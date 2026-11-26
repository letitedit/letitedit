/*
 * Copyright (c) 2026 Meltytech, LLC
 *
 * This program is free software: you can redistribute it and/or modify
 * it under the terms of the GNU General Public License as published by
 * the Free Software Foundation, either version 3 of the License, or
 * (at your option) any later version.
 *
 * This program is distributed in the hope that it will be useful,
 * but WITHOUT ANY WARRANTY; without even the implied warranty of
 * MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
 * GNU General Public License for more details.
 *
 * You should have received a copy of the GNU General Public License
 * along with this program.  If not, see <http://www.gnu.org/licenses/>.
 */

// Review: sending the notes to the AI.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"

#include <QPointer>
#include "letitedit/chat/connectai.h"
#include <QStatusBar>
#include <QCollator>

namespace ReviewMode {

// The notes as they are become a batch: every picture and recording checked and copied to review/<time>/, then the
// draft is cleared and the batch joins the queue (NoteQueue), which sends it now or as soon as the AI is free (T221).
// A failed copy leaves the notes as they were.
bool ReviewWindow::sendNotes()
{
    const QStringList missing = draftComplete();
    if (!missing.isEmpty()) {
        m_status->setText(tr("A picture of your notes is missing (%1), so nothing was sent. Delete that note and add "
                             "it again, then send.")
                              .arg(missing.join(QStringLiteral(", "))));
        return false;
    }
    // the copy that goes with the request: every file checked, or nothing is sent
    const QString stampName = QDateTime::currentDateTime().toString(QStringLiteral("yyyyMMdd-HHmmss"));
    QString sent = QDir(m_dir).filePath(stampName);
    for (int n = 2; QFileInfo::exists(sent); ++n)
        sent = QDir(m_dir).filePath(stampName + QStringLiteral("-%1").arg(n));
    QStringList copyFiles{QStringLiteral("notes.json")};
    for (const auto &n : std::as_const(m_notes))
        copyFiles << files(n);
    if (!QDir().mkpath(sent)) {
        m_status->setText(tr("Could not make the folder for your notes (%1); nothing was sent.")
                              .arg(QDir::toNativeSeparators(sent)));
        return false;
    }
    for (const QString &file : std::as_const(copyFiles)) {
        const QString from = QDir(m_dir).filePath(file), to = QDir(sent).filePath(file);
        if (!QFile::copy(from, to) || QFileInfo(to).size() != QFileInfo(from).size()) {
            QDir(sent).removeRecursively();
            m_status->setText(tr("Could not copy %1 for your AI; nothing was sent. Your notes are as they were.")
                                  .arg(file));
            return false;
        }
    }
    NoteBatch batch;
    batch.sent = sent;
    bool anyTake = false;
    for (const auto &n : std::as_const(m_notes)) {
        anyTake = anyTake || n.take;
        batch.lines << noteLine(n, batch.lines.size() + 1);
    }
    batch.takes = anyTake ? takesExplained() : QString();
    batch.count = m_notes.size();
    if (!NoteQueue::of(m_window).add(batch)) {
        m_status->setText(tr("Could not save your waiting notes. Your draft is unchanged; try Send again."));
        QDir(sent).removeRecursively();
        return false;
    }
    // queued: the draft's own files go (the copy in review/<time>/ is what the AI reads)
    for (const QString &file : std::as_const(copyFiles)) {
        if (auto process = m_pictureRefinements.value(QDir(m_dir).filePath(file)))
            process->setProperty("destination", sent);
        if (!QFile::remove(QDir(m_dir).filePath(file)))
            LOG_WARNING() << "review: could not remove the sent draft file" << file;
    }
    m_notes.clear();
    m_unwritten.clear();
    m_written.clear();
    m_writtenMarks.clear();
    refreshQueueLine();
    return true;
}

void ReviewWindow::refreshQueueLine()
{
    if (!m_queueLine)
        return;
    const NoteQueue &queue = NoteQueue::of(m_window);
    const QString text = queue.problem().isEmpty() ? queue.line() : queue.problem();
    if (m_queueLine->text() != text)
        m_queueLine->setText(text);
    m_queueLine->setVisible(!text.isEmpty());
}

NoteQueue &NoteQueue::of(MainWindow *window)
{
    static QPointer<NoteQueue> queue;
    if (!queue)
        queue = new NoteQueue(window);
    return *queue;
}

NoteQueue::NoteQueue(MainWindow *window)
    : QObject(window)
    , m_window(window)
{
    m_timer.setInterval(700);
    connect(&m_timer, &QTimer::timeout, this, [this]() { pump(); });
    connect(window, &MainWindow::producerOpened, this, [this]() { recover(); });
    m_recoveryLine = new QLabel(window->statusBar());
    m_recoveryLine->setObjectName(QStringLiteral("reviewRecoveredNotes"));
    window->statusBar()->addWidget(m_recoveryLine);
    m_recoveryLine->hide();
}

void initializeQueue(MainWindow *window)
{
    NoteQueue::of(window);
}

bool NoteQueue::persist(const NoteBatch &batch, const QString &state)
{
    QSaveFile file(QDir(batch.sent).filePath(QStringLiteral("delivery.json")));
    if (!file.open(QIODevice::WriteOnly))
        return false;
    const QByteArray bytes = QJsonDocument(QJsonObject{{"state", state}, {"project", m_project},
        {"lines", QJsonArray::fromStringList(batch.lines)}, {"takes", batch.takes}, {"count", batch.count}}).toJson();
    return file.write(bytes) == bytes.size() && file.commit();
}

void NoteQueue::recover()
{
    const QString project = m_window->fileName();
    if (project.isEmpty() || project == m_project || !MLT.isMultitrack())
        return;
    m_timer.stop();
    m_waiting.clear();
    m_problem.clear();
    m_done = 0;
    m_recovered = 0;
    m_project = project;
    const QDir review(leSideFolder(project) + QStringLiteral("/review"));
    auto directories = review.entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot, QDir::Name);
    QCollator order;
    order.setNumericMode(true);
    std::sort(directories.begin(), directories.end(), [&order](const QFileInfo &first, const QFileInfo &second) {
        return order.compare(first.fileName(), second.fileName()) < 0;
    });
    for (const auto &directory : directories) {
        const QDir folder(directory.absoluteFilePath());
        QFile delivery(folder.filePath(QStringLiteral("delivery.json")));
        QJsonObject saved;
        const bool tracked = delivery.exists();
        if (tracked) {
            if (!delivery.open(QIODevice::ReadOnly))
                continue;
            saved = QJsonDocument::fromJson(delivery.readAll()).object();
            if (saved.value("state").toString() != QLatin1String("waiting"))
                continue;
        } else {
            if (aiChatReviewBatchSent(directory.absoluteFilePath()) != 0)
                continue;
        }
        QFile notes(folder.filePath(QStringLiteral("notes.json")));
        if (!notes.open(QIODevice::ReadOnly))
            continue;
        const auto document = QJsonDocument::fromJson(notes.readAll()).object();
        const auto rows = document.value("notes").toArray();
        if (rows.isEmpty())
            continue;
        NoteBatch batch;
        batch.sent = directory.absoluteFilePath();
        batch.count = rows.size();
        batch.takes = saved.value("takes").toString();
        for (const auto &line : saved.value("lines").toArray())
            batch.lines << line.toString();
        if (batch.lines.isEmpty())
            for (const auto &note : rows)
                batch.lines << QString::fromUtf8(QJsonDocument(note.toObject()).toJson(QJsonDocument::Compact));
        if (!tracked && !persist(batch, QStringLiteral("waiting")))
            continue;
        m_waiting << batch;
        m_recovered += batch.count;
    }
    if (m_recovered) {
        const QString text = m_recovered == 1 ? QObject::tr("1 note from last time is waiting")
                                              : QObject::tr("%1 notes from last time are waiting").arg(m_recovered);
        m_recoveryLine->setText(text);
        m_recoveryLine->show();
        m_window->showStatusMessage(text);
        m_timer.start();
    } else {
        m_recoveryLine->hide();
    }
}

int NoteQueue::waiting() const
{
    int count = 0;
    for (const auto &batch : m_waiting)
        count += batch.count;
    return count;
}

QString NoteQueue::line() const
{
    const auto notes = [](int n) {
        return n == 1 ? QObject::tr("1 note") : QObject::tr("%1 notes").arg(n);
    };
    if (m_onCount && waiting())
        return QObject::tr("Your AI is on %1. %2 waiting: they go by themselves, in order.")
            .arg(notes(m_onCount), notes(waiting()));
    if (m_onCount)
        return QObject::tr("Your AI is on %1. Keep adding notes: they wait their turn.").arg(notes(m_onCount));
    if (waiting())
        return QObject::tr("%1 waiting for your AI: they go by themselves when it's free.").arg(notes(waiting()));
    if (m_done)
        return QObject::tr("Your AI has done %1. Each is one Undo step.").arg(notes(m_done));
    return {};
}

bool NoteQueue::add(const NoteBatch &batch)
{
    if (m_project != m_window->fileName())
        recover();
    if (!persist(batch, QStringLiteral("waiting")))
        return false;
    for (auto &waiting : m_waiting)
        if (waiting.sent == batch.sent) {
            waiting = batch;
            return true;
        }
    if (!m_onRequest && m_waiting.isEmpty())
        m_done = 0;
    m_waiting << batch;
    m_problem.clear();
    m_timer.start();
    return true;
}

void NoteQueue::pump()
{
    if (m_window->fileName() != m_project) {
        recover();
        return;
    }
    if (m_recovered && !m_waiting.isEmpty()) {
        QString text = waiting() == 1 ? QObject::tr("1 note from last time is waiting")
                                      : QObject::tr("%1 notes from last time are waiting").arg(waiting());
        if (!ConnectAi::anyAi())
            text += waiting() == 1 ? QObject::tr(". Connect your AI to send it.")
                                   : QObject::tr(". Connect your AI to send them.");
        m_recoveryLine->setText(text);
    } else if (m_waiting.isEmpty()) {
        m_recoveryLine->hide();
    }
    if (m_onRequest || m_waiting.isEmpty()) {
        if (m_waiting.isEmpty())
            m_timer.stop();
        return;
    }
    if (aiChatState().value(QStringLiteral("busy")).toBool())
        return; // the AI is answering something else: this batch goes when it's free
    if (!ConnectAi::anyAi())
        return;
    if (go(m_waiting.first()))
        m_waiting.removeFirst();
    else if (!m_problem.isEmpty()) {
        m_recoveryLine->setText(m_problem);
        m_recoveryLine->show();
        m_window->showStatusMessage(m_problem);
        m_timer.stop();
    }
}

// One batch to the AI: the video as it is now is kept as "<name> vN.mlt" (an earlier version in Versions of This Video)
// and the request goes to the chat panel's AI, which makes each note one Undo step.
bool NoteQueue::go(const NoteBatch &batch)
{
    QFile notes(QDir(batch.sent).filePath(QStringLiteral("notes.json")));
    bool complete = notes.open(QIODevice::ReadOnly);
    const auto rows = QJsonDocument::fromJson(notes.readAll()).object().value("notes").toArray();
    complete = complete && rows.size() == batch.count;
    const auto checkFiles = [&complete, &batch](const QJsonObject &entry) {
        for (const QString &key : {QStringLiteral("frame_png"), QStringLiteral("marked_png"), QStringLiteral("audio")}) {
            const QString name = entry.value(key).toString();
            if (!name.isEmpty()) {
                const QFileInfo file(QDir(batch.sent).filePath(name));
                complete = complete && file.exists() && file.isFile() && file.size() > 0;
            }
        }
    };
    for (const auto &row : rows) {
        const auto note = row.toObject();
        checkFiles(note);
        for (const auto &stroke : note.value("strokes").toArray())
            checkFiles(stroke.toObject());
    }
    if (!complete) {
        m_problem = QObject::tr("A saved Review file is missing. Your notes are waiting in the project's review folder.");
        return false;
    }
    if (m_window->fileName().isEmpty()) {
        m_problem = QObject::tr("Open the project again to send your notes; they're kept in its review folder.");
        return false;
    }
    if (m_window->isWindowModified() && !m_window->on_actionSave_triggered()) {
        m_problem = QObject::tr("Save the project, so your AI can read it; your notes are waiting.");
        return false;
    }
    const QFileInfo project(m_window->fileName());
    static const QRegularExpression version(QStringLiteral(R"( v(\d+)$)"));
    const QString base = project.completeBaseName().remove(version);
    int next = 1;
    for (const auto &f : project.dir().entryInfoList({base + QStringLiteral(" v*.mlt")}, QDir::Files)) {
        const auto m = version.match(f.completeBaseName());
        if (m.hasMatch() && f.completeBaseName().size() == base.size() + m.capturedLength())
            next = qMax(next, m.captured(1).toInt() + 1);
    }
    const QString before = project.dir().filePath(QStringLiteral("%1 v%2.mlt").arg(base).arg(next));
    if (!QFile::copy(project.absoluteFilePath(), before)) {
        m_problem = QObject::tr("Could not keep the current version as %1; your notes are waiting.")
                        .arg(QFileInfo(before).fileName());
        return false;
    }
    const QString request
        = QStringLiteral(
              "Re-edit from my review of the open letitedit project \"%1\". The video as it was is kept as \"%2\" "
              "(leave that file alone). My notes, the frames I drew on and the recordings are in \"%3\" (notes.json "
              "has the times, the words and the drawn marks as points 0-1 across the picture). Look at each marked "
              "frame to see what I pointed at (arrows and circles mark the thing to change, an arrow's direction "
              "is a direction of movement); check the moment with letitedit_check_frames when you need the full "
              "picture.%4 Make each note's change in the open project with letitedit_timeline_apply as one Undo "
              "step labelled \"Review: <the note in a few words>\", and keep everything I did not mention as it is. "
              "Then answer with one line per note: what you changed, or why you could not.\n\n%5")
              .arg(QDir::toNativeSeparators(project.absoluteFilePath()), QDir::toNativeSeparators(before),
                   QDir::toNativeSeparators(batch.sent), batch.takes, batch.lines.join(QLatin1Char('\n')));
    const QString summary = batch.count == 1 ? QObject::tr("Apply my review note")
                                             : QObject::tr("Apply my %1 review notes").arg(batch.count);
    if (!persist(batch, QStringLiteral("dispatched"))) {
        QFile::remove(before);
        m_problem = QObject::tr("Could not save the delivery record. Your notes are waiting; try Send again.");
        return false;
    }
    const int requestId = aiChatRequest(m_window, request, summary);
    if (!requestId) {
        if (!persist(batch, QStringLiteral("waiting"))) {
            m_problem = QObject::tr("Your AI did not take these notes, and their delivery record could not be updated. The saved batch needs checking before retrying.");
            return false;
        }
        QFile::remove(before);
        if (aiChatState().value(QStringLiteral("busy")).toBool())
            return false; // it became busy meanwhile: this batch goes when it's free
        m_problem = QObject::tr("Your AI could not take your notes. They're waiting: press Send again when your AI is "
                                "ready (Menu > AI > Connect Your AI checks it).");
        return false;
    }
    m_onRequest = requestId;
    m_onCount = batch.count;
    m_window->showStatusMessage(QObject::tr("Review sent to your AI. The video before its changes is \"%1\" in "
                                            "Versions of This Video.")
                                    .arg(QFileInfo(before).completeBaseName()));
    if (auto chat = m_window->findChild<QDockWidget *>(QStringLiteral("aiChatDock")))
        chat->show();
    showSentBanner(m_window, batch.count, QFileInfo(before).completeBaseName(), requestId, request, summary);
    // this request's own end (answered, stopped or failed): the next batch goes when the AI is free
    const QString sentProject = m_project;
    aiChatWatchRequest(this, requestId, [this, requestId, sentProject](const QJsonObject &) {
        if (m_onRequest != requestId)
            return;
        if (m_project == sentProject)
            m_done += m_onCount;
        m_onRequest = 0;
        m_onCount = 0;
        if (!m_waiting.isEmpty())
            m_timer.start();
    });
    return true;
}

} // namespace ReviewMode
