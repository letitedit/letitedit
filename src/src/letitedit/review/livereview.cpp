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

#include "letitedit/review/livereview.h"

#include "letitedit/bridge/jsonprocess.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/workspace/leside.h"
#include "mainwindow.h"
#include "mltcontroller.h"

#include <QCoreApplication>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QProcess>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QSaveFile>
#include <QUndoStack>

namespace LiveReview {

namespace {

const char *stateName(State s)
{
    switch (s) {
    case State::Waiting: return "waiting";
    case State::Working: return "working";
    case State::Done: return "done";
    case State::NotAnEdit: return "not_an_edit";
    case State::CouldNot: return "could_not";
    case State::Cancelled: return "cancelled";
    case State::Undone: return "undone";
    }
    return "";
}

State stateFrom(const QString &name)
{
    for (State s : {State::Waiting, State::Working, State::Done, State::NotAnEdit, State::CouldNot, State::Cancelled, State::Undone})
        if (name == QLatin1String(stateName(s)))
            return s;
    return State::CouldNot;
}

QByteArray fileHash(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return QByteArray();
    QCryptographicHash hash(QCryptographicHash::Md5);
    hash.addData(&f);
    return hash.result();
}

bool copyOver(const QString &from, const QString &to)
{
    if (from == to)
        return true;
    QFile::remove(to);
    return QFile::copy(from, to);
}

QString clock(double seconds)
{
    const int tenths = qMax(0, int(std::lround(seconds * 10)));
    return QStringLiteral("%1:%2.%3")
        .arg(tenths / 600)
        .arg((tenths / 10) % 60, 2, 10, QLatin1Char('0'))
        .arg(tenths % 10);
}

QString firstLine(QString text)
{
    text = text.trimmed();
    const int at = text.indexOf(QLatin1Char('\n'));
    if (at > 0)
        text = text.left(at).trimmed();
    return text.size() > 160 ? text.left(157) + QStringLiteral("...") : text;
}

// One line of why a helper failed: the last line of what it printed.
QString reason(const QString &err)
{
    QStringList lines = err.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
    while (!lines.isEmpty() && lines.last().trimmed().isEmpty())
        lines.removeLast();
    return lines.isEmpty() ? QString() : lines.last().trimmed().left(240);
}

QProcessEnvironment toolEnvironment()
{
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.remove(QStringLiteral("LETITEDIT_OWNER"));
    env.insert(QStringLiteral("LETITEDIT_INSTANCE"), qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main")));
    return env;
}

QString instanceId()
{
    return qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main"));
}

} // namespace

Session::Session(MainWindow *window, const QString &project, QObject *parent)
    : QObject(parent)
    , m_window(window)
    , m_project(project)
{
    setObjectName(QStringLiteral("liveReviewSession"));
    m_folder = leSideFolder(project) + QStringLiteral("/review/live");
    m_tick.setInterval(700);
    connect(&m_tick, &QTimer::timeout, this, [this]() { pump(); });
    // nothing more for a while: the AI's unattended session for this round ends
    m_endRound.setSingleShot(true);
    m_endRound.setInterval(qEnvironmentVariableIsSet("LETITEDIT_QA_LIVE_ROUND_MS") ? qEnvironmentVariableIntValue("LETITEDIT_QA_LIVE_ROUND_MS") : 120000);
    connect(&m_endRound, &QTimer::timeout, this, []() { aiChatLiveEnd(aiChatInstance()); });
    restore();
}

Session *Session::of(MainWindow *window)
{
    const QString project = window->fileName();
    for (Session *s : window->findChildren<Session *>(QStringLiteral("liveReviewSession"), Qt::FindDirectChildrenOnly)) {
        if (s->m_project == project)
            return s;
        if (!s->working() && !s->waiting() && !s->m_loading) {
            aiChatLiveEnd(aiChatInstance());
            delete s; // another video's, with nothing going on: it stays on disk
        }
    }
    return new Session(window, project, window);
}

Session *Session::existing(MainWindow *window)
{
    for (Session *s : window->findChildren<Session *>(QStringLiteral("liveReviewSession"), Qt::FindDirectChildrenOnly))
        if (s->m_project == window->fileName())
            return s->empty() ? nullptr : s;
    return nullptr;
}

const Item *Session::item(int id) const
{
    for (const Item &it : m_items)
        if (it.id == id)
            return &it;
    return nullptr;
}

Item *Session::find(int id)
{
    for (Item &it : m_items)
        if (it.id == id)
            return &it;
    return nullptr;
}

int Session::waiting() const
{
    int n = 0;
    for (const Item &it : m_items)
        n += it.state == State::Waiting;
    return n;
}

int Session::working() const
{
    int n = 0;
    for (const Item &it : m_items)
        n += it.state == State::Working;
    return n;
}

int Session::ready() const
{
    int n = 0;
    for (const Item &it : m_items)
        n += it.state == State::Done && !it.landed;
    return n;
}

int Session::reserve(QString *folder)
{
    const int id = m_nextId++;
    *folder = QDir(m_folder).filePath(QStringLiteral("note-%1").arg(id));
    QDir().mkpath(*folder);
    return id;
}

void Session::add(Item item)
{
    item.state = State::Waiting;
    item.watched = m_watched;
    m_items.append(item);
    touch();
    pump();
}

void Session::touch()
{
    save();
    emit changed();
}

QProcess *Session::helper(const QStringList &args, const std::function<void(int, const QJsonObject &, const QString &)> &done)
{
    auto process = new QProcess(this);
    process->setProgram(aiChatSettings().value("python").toString());
    process->setArguments(QStringList{QStringLiteral("-u"), aiRootPath(QStringLiteral("bridge/live_review.py"))} + args);
    process->setWorkingDirectory(aiRootPath(QStringLiteral("bridge")));
    process->setProcessEnvironment(toolEnvironment());
    return startJsonProcess(process, this,
        [process, done](int code, const QJsonObject &result, const QString &err) {
            done(code, result, process->error() == QProcess::FailedToStart
                ? tr("letitedit's helper tools could not start") : reason(err));
        });
}

// ---- sending, one at a time ----

void Session::pump()
{
    if (!m_window)
        return;
    const auto stopTicking = [this]() { m_tick.stop(); };
    // a note the AI has while the request has already ended (a turn that ended without a word from the chat)
    for (Item &it : m_items) {
        if (it.state != State::Working)
            continue;
        const QJsonObject outcome = aiChatOutcome(it.request);
        if (!outcome.isEmpty()) {
            finish(it.id, outcome);
            return;
        }
        if (const qint64 minutes = (QDateTime::currentMSecsSinceEpoch() - it.sentMs) / 60000; minutes != m_shownMinutes) {
            m_shownMinutes = minutes;
            emit changed(); // the list says how long, from a few minutes on
        }
        if (aiChatState().value(QStringLiteral("busy")).toBool()) {
            m_idleTicks = 0;
        } else if (it.cancelAsked || ++m_idleTicks > 8) { // about 5 s with the AI idle and no outcome: it never hangs on "working"
            m_idleTicks = 0;
            finish(it.id, QJsonObject{{"outcome", it.cancelAsked ? "cancelled" : "failed"},
                                      {"error", tr("it stopped without answering")}});
        }
        return;
    }
    if (m_preparing || m_loading) {
        m_tick.start();
        return;
    }
    int next = 0;
    for (const Item &it : m_items)
        if (it.state == State::Waiting) {
            next = it.id;
            break;
        }
    if (!next) {
        if (!m_aiBusyNote.isEmpty()) {
            m_aiBusyNote.clear();
            emit changed();
        }
        stopTicking();
        if (AiChat *c = aiChatInstance(); c && c->liveReviewHold)
            m_endRound.start();
        return;
    }
    m_tick.start();
    if (aiChatState().value(QStringLiteral("busy")).toBool()) {
        const QString note = tr("Your AI is finishing something else. Your notes go next.");
        if (m_aiBusyNote != note) {
            m_aiBusyNote = note;
            emit changed();
        }
        return;
    }
    if (!m_aiBusyNote.isEmpty()) {
        m_aiBusyNote.clear();
        emit changed();
    }
    sendNext(next);
}

// A round starts from what the window shows now, hand edits and undos included, whenever nothing unfinished rests on the copy.
void Session::beginRound(const std::function<void(bool)> &then)
{
    if (ready() > 0 && !m_tip.isEmpty()) {
        then(true);
        return;
    }
    helper({QStringLiteral("begin"), QStringLiteral("--instance"), instanceId(), QStringLiteral("--folder"), m_folder},
           [this, then](int code, const QJsonObject &, const QString &err) {
               if (code != 0) {
                   failRest(tr("The working copy couldn't be made (%1).").arg(err));
                   then(false);
                   return;
               }
               const QDir dir(m_folder);
               m_tip = m_base = dir.filePath(QStringLiteral("base.mlt"));
               m_watched = dir.filePath(QStringLiteral("watched-%1.mlt").arg(++m_watchedNumber));
               copyOver(dir.filePath(QStringLiteral("watched.mlt")), m_watched);
               m_keptVersion = false;
               then(true);
           });
}

void Session::sendNext(int id)
{
    m_preparing = true;
    beginRound([this, id](bool ok) {
        if (!ok) {
            m_preparing = false;
            return;
        }
        Item *it = find(id);
        if (!it || it->state != State::Waiting) { // cancelled meanwhile
            m_preparing = false;
            QTimer::singleShot(0, this, [this]() { pump(); });
            return;
        }
        // the copy is exactly the last finished note, whatever a stopped AI may have left in it
        copyOver(m_tip, QDir(m_folder).filePath(QStringLiteral("work.mlt")));
        if (it->watched.isEmpty())
            it->watched = m_watched;
        if (it->frame < 0) {
            compose(id, QJsonObject());
            return;
        }
        helper({QStringLiteral("moment"), QStringLiteral("--watched"), it->watched, QStringLiteral("--work"),
                QDir(m_folder).filePath(QStringLiteral("work.mlt")), QStringLiteral("--frame"), QString::number(it->frame),
                QStringLiteral("--fps"), QString::number(MLT.profile().fps())},
               [this, id](int code, const QJsonObject &moment, const QString &) { compose(id, code == 0 ? moment : QJsonObject()); });
    });
}

void Session::compose(int id, const QJsonObject &moment)
{
    m_preparing = false;
    Item *it = find(id);
    if (!it || it->state != State::Waiting || !m_window) {
        QTimer::singleShot(0, this, [this]() { pump(); });
        return;
    }
    const QString work = QDir::toNativeSeparators(QDir(m_folder).filePath(QStringLiteral("work.mlt")));
    QString where;
    if (it->takesBack) {
        where = QStringLiteral("This one takes back an earlier note: put that part of the working copy back as it was, "
                               "and leave every other change as it is.");
    } else if (!moment.isEmpty()) {
        where = QStringLiteral("The moment: %1 in the version they are watching").arg(clock(moment.value("watched_s").toDouble()));
        if (!moment.value("clip").toString().isEmpty())
            where += QStringLiteral(" (clip %1, %2 s into its source)").arg(moment.value("clip").toString()).arg(moment.value("source_s").toDouble());
        where += QStringLiteral(". ");
        where += moment.value("now_s").isNull()
                     ? QStringLiteral("An earlier note took that moment out of the working copy, so go by the words and the picture.")
                     : QStringLiteral("In the working copy, after the earlier notes, that is at %1 s.").arg(moment.value("now_s").toDouble());
    } else {
        where = QStringLiteral("Earlier notes may have moved things in the working copy, so go by the words and the picture.");
    }
    QStringList earlier, later;
    for (const Item &other : std::as_const(m_items)) {
        if (other.id == id || other.takesBack)
            continue;
        const QString line = QStringLiteral("note %1 (%2): \"%3\"").arg(other.id).arg(other.when, other.words.left(160));
        if (other.state == State::Waiting)
            later << line;
        else if (other.state == State::Done && other.id < id)
            earlier << line;
    }
    QString context;
    if (!earlier.isEmpty())
        context += QStringLiteral("\n\nAlready done in this copy: %1.").arg(earlier.join(QStringLiteral("; ")));
    if (!later.isEmpty())
        context += QStringLiteral("\n\nWaiting after this one, each coming to you on its own turn: %1. A pause can split one "
                                  "thought into two notes, so read them together; if a later one finishes this thought, "
                                  "do what it means now.").arg(later.join(QStringLiteral("; ")));
    const QString text = QStringLiteral(
        "Live Review note %1. The person is watching the video right now and talking to you, so they can't answer questions: "
        "make your own calls, and keep to this one note. The words below are their voice as they watch, picked up by "
        "their microphone: they are never words in the video, so never look for them in the footage or cut them.\n\n"
        "Work only on the working copy, not on the open project: every letitedit tool gets project=\"%2\". The open project "
        "\"%3\" refuses edits while you work on this; what they are watching changes only when they load your changes.\n\n"
        "%4\n\n"
        "%5%6\n\n"
        "\"This\", \"here\" and \"this part\" mean this moment of the video, not the whole of it. A drawing with no words asks "
        "for something too: look at the marked frame; if what it points at doesn't make plain what they want, change nothing "
        "and say so with could_not. If this isn't asking for a change to the video (they are talking to someone else, or "
        "thinking aloud), change nothing. Keep everything they did not mention as it is. Don't export or review the whole "
        "video, don't change the order of tracks and don't hide or mute a whole track (those can't come in while the video "
        "is open).\n\n"
        "End by calling letitedit_review_note(project=\"%2\", note=%1, state=...): state=\"done\" with what= one plain line "
        "saying what you changed, state=\"could_not\" with why= what stopped you, or state=\"not_an_edit\". Then answer in one line.")
        .arg(id)
        .arg(work, QDir::toNativeSeparators(m_project), where, it->body, context);
    const QString summary = tr("Live Review note %1").arg(id);
    writeActive(true);
    m_endRound.stop();
    AiChat *c = aiChatInstance();
    int request = 0;
    if (c && !c->liveReviewHold) {
        // The person is watching and can't answer a permission prompt: the AI runs as in a New video (it never stops to ask),
        // in one session for the round, with the project's folder open to it.
        const QVariant folderBefore = m_window->property("letitedit:newVideoFolder");
        m_window->setProperty("letitedit:newVideoFolder", QFileInfo(m_project).absolutePath());
        c->liveReviewHold = true;
        request = aiChatRequest(m_window, text, summary, false, true);
        m_window->setProperty("letitedit:newVideoFolder", folderBefore);
        if (!request)
            c->liveReviewHold = false;
    } else {
        request = aiChatRequest(m_window, text, summary);
    }
    if (!request) {
        writeActive(false);
        const QString refusal = c ? c->refusal : QString();
        failRest(refusal.isEmpty() ? tr("Your AI could not take this. Send it again when your AI is ready "
                                        "(Menu > AI > Connect Your AI checks it).")
                                   : refusal);
        return;
    }
    it->state = State::Working;
    it->request = request;
    it->sentMs = QDateTime::currentMSecsSinceEpoch();
    aiChatWatchRequest(this, request, [this, id](const QJsonObject &o) { finish(id, o); });
    touch();
}

// The AI stopped, or can't be reached: what was waiting says so, and nothing hangs on "working".
void Session::failRest(const QString &why)
{
    for (Item &it : m_items)
        if (it.state == State::Waiting) {
            it.state = State::CouldNot;
            it.why = why;
        }
    touch();
}

void Session::writeActive(bool on)
{
    const QString path = QDir(m_folder).filePath(QStringLiteral("active.json"));
    if (!on) {
        QFile::remove(path);
        return;
    }
    QSaveFile f(path);
    if (f.open(QIODevice::WriteOnly)) {
        f.write(QJsonDocument(QJsonObject{{"pid", QCoreApplication::applicationPid()},
                                          {"since", double(QDateTime::currentSecsSinceEpoch())},
                                          {"work", QDir::toNativeSeparators(QDir(m_folder).filePath(QStringLiteral("work.mlt")))}})
                    .toJson());
        f.commit();
    }
}

// The turn ended. What the AI said decides; if it said nothing, whether the copy changed does.
void Session::finish(int id, const QJsonObject &o)
{
    Item *it = find(id);
    if (!it || it->state != State::Working)
        return;
    writeActive(false);
    it->tookS = (QDateTime::currentMSecsSinceEpoch() - it->sentMs) / 1000.0;
    const QString work = QDir(m_folder).filePath(QStringLiteral("work.mlt"));
    const bool copyChanged = fileHash(work) != fileHash(m_tip);
    const QString outcome = o.value("outcome").toString();
    QJsonObject said;
    QFile report(QDir(m_folder).filePath(QStringLiteral("reports/note-%1.json").arg(id)));
    if (report.open(QIODevice::ReadOnly))
        said = QJsonDocument::fromJson(report.readAll()).object();
    const QString state = said.value("state").toString();
    const QString answer = firstLine(o.value("answer").toString());
    bool keep = false;
    if (it->cancelAsked) {
        it->state = State::Cancelled;
        it->why = tr("Stopped. Nothing from it was kept.");
    } else if (outcome != QLatin1String("answered") && state.isEmpty()) {
        it->state = State::CouldNot;
        it->why = outcome == QLatin1String("cancelled")
                      ? tr("Your AI was stopped before it finished.")
                      : tr("Your AI stopped: %1").arg(o.value("error").toString().left(200));
        failRest(tr("Not started: your AI stopped before it got to this one."));
    } else if (state == QLatin1String("not_an_edit")) {
        it->state = State::NotAnEdit;
        it->why = tr("Not an edit, so it was ignored.");
    } else if (state == QLatin1String("could_not")) {
        it->state = State::CouldNot;
        it->why = said.value("why").toString();
    } else if (copyChanged) {
        it->state = State::Done;
        it->what = said.value("what").toString();
        if (it->what.isEmpty())
            it->what = answer.isEmpty() ? tr("Changed") : answer;
        keep = true;
    } else {
        // no change on the copy: the AI's own words say why
        it->state = State::CouldNot;
        it->why = state == QLatin1String("done") ? tr("Your AI said it was done, but the video didn't change.")
                  : answer.isEmpty()             ? tr("Your AI finished without changing anything.")
                                                 : tr("Your AI made no change: %1").arg(answer);
    }
    if (keep) {
        it->after = QDir(m_folder).filePath(QStringLiteral("after-%1.mlt").arg(id));
        copyOver(work, it->after);
        it->label = tr("Review: %1").arg(it->what.left(80));
        m_tip = it->after;
        if (it->takesBack)
            if (Item *target = find(it->takesBack)) {
                target->state = State::Undone;
                target->why = tr("Taken back.");
            }
    } else if (!m_tip.isEmpty()) {
        copyOver(m_tip, work); // nothing half-done stays on the copy
    }
    touch();
    QTimer::singleShot(0, this, [this]() { pump(); });
}

void Session::cancel(int id)
{
    Item *it = find(id);
    if (!it)
        return;
    if (it->state == State::Waiting) {
        it->state = State::Cancelled;
        it->why = tr("Canceled before your AI saw it.");
        touch();
        return;
    }
    if (it->state != State::Working || it->cancelAsked)
        return;
    it->cancelAsked = true;
    touch();
    if (AiChat *c = aiChatInstance())
        if (c->stop && c->stop->isEnabled()) {
            c->stop->click();
            return;
        }
    QTimer::singleShot(0, this, [this]() { pump(); });
}

// The timeline before this note's change.
QString Session::tipBefore(int id) const
{
    QString before = m_base;
    for (const Item &it : m_items) {
        if (it.id == id)
            break;
        if (it.state == State::Done && !it.after.isEmpty())
            before = it.after;
    }
    return before;
}

void Session::undo(int id)
{
    Item *it = find(id);
    if (!it || it->state != State::Done)
        return;
    bool newest = true;
    for (const Item &other : std::as_const(m_items))
        if (other.id != id && other.id > id
            && (other.state == State::Done || other.state == State::Working || other.state == State::Waiting))
            newest = false;
    if (m_loading)
        return;
    if (newest && it->landed) {
        // its own Undo step, if that is still the top one; anything else on top goes through the AI
        QUndoStack *stack = m_window ? m_window->undoStack() : nullptr;
        newest = stack && stack->canUndo() && stack->undoText() == it->label;
        if (newest)
            stack->undo();
    }
    if (newest) {
        m_tip = tipBefore(id);
        copyOver(m_tip, QDir(m_folder).filePath(QStringLiteral("work.mlt")));
        it->state = State::Undone;
        it->landed = false;
        it->why = tr("Taken back.");
        touch();
        return;
    }
    QString folder;
    Item back;
    back.id = reserve(&folder);
    back.takesBack = id;
    back.frame = -1;
    back.when = it->when;
    back.words = tr("Take back: %1").arg(it->what);
    back.body = QStringLiteral("Take back note %1 (%2). What it changed: \"%3\". What they had said: \"%4\".")
                    .arg(id)
                    .arg(it->when, it->what, it->words);
    back.folder = folder;
    add(back);
}

void Session::again(int id)
{
    Item *it = find(id);
    if (!it || (it->state != State::CouldNot && it->state != State::Cancelled && it->state != State::NotAnEdit))
        return;
    QFile::remove(QDir(m_folder).filePath(QStringLiteral("reports/note-%1.json").arg(id)));
    if (it->state == State::NotAnEdit)
        it->body += QStringLiteral(" (They looked at this and it is meant as a change to the video.)");
    it->state = State::Waiting;
    it->why.clear();
    it->cancelAsked = false;
    touch();
    pump();
}

void Session::clear(int id)
{
    for (int i = 0; i < m_items.size(); ++i)
        if (m_items[i].id == id && m_items[i].state != State::Working && m_items[i].state != State::Waiting
            && !(m_items[i].state == State::Done && !m_items[i].landed)) {
            m_items.removeAt(i);
            touch();
            return;
        }
}

// ---- loading ----

void Session::load(const std::function<void(double, const QString &)> &done)
{
    if (m_loading)
        return;
    if (!m_window || m_window->fileName() != m_project) {
        done(0, tr("Another video is open now."));
        return;
    }
    QJsonArray notes;
    for (const Item &it : std::as_const(m_items))
        if (it.state == State::Done && !it.landed)
            notes.append(QJsonObject{{"id", it.id}, {"after", it.after}, {"label", it.label}});
    if (notes.isEmpty()) {
        done(0, QString());
        return;
    }
    m_loading = true;
    m_loadProblem.clear();
    emit changed();
    QJsonObject plan{{"project", m_project}, {"folder", m_folder}, {"notes", notes}};
    if (!m_keptVersion && !m_base.isEmpty())
        plan["base"] = m_base;
    const QString planFile = QDir(m_folder).filePath(QStringLiteral("load-plan.json"));
    QFile f(planFile);
    if (f.open(QIODevice::WriteOnly)) {
        f.write(QJsonDocument(plan).toJson());
        f.close();
    }
    helper({QStringLiteral("land"), QStringLiteral("--instance"), instanceId(), QStringLiteral("--plan"), planFile},
           [this, done](int code, const QJsonObject &r, const QString &err) {
               m_loading = false;
               if (!r.value("kept").toString().isEmpty())
                   m_keptVersion = true;
               QString problem = code == 0 ? QString() : err;
               for (const auto &v : r.value("steps").toArray()) {
                   const QJsonObject step = v.toObject();
                   Item *it = find(step.value("id").toInt());
                   if (!it)
                       continue;
                   if (step.value("ok").toBool()) {
                       it->landed = true;
                       it->changeAt = step.value("final_s").toDouble();
                   } else {
                       problem = step.value("error").toString();
                       it->why = tr("It couldn't come in: %1").arg(problem);
                   }
               }
               if (code != 0 && problem.isEmpty())
                   problem = tr("the tools stopped without saying why");
               m_loadProblem = problem;
               if (problem.isEmpty()) {
                   const QDir dir(m_folder);
                   m_watched = dir.filePath(QStringLiteral("watched-%1.mlt").arg(++m_watchedNumber));
                   copyOver(dir.filePath(QStringLiteral("watched.mlt")), m_watched);
               }
               touch();
               done(r.value("first_change_s").toDouble(), problem);
               pump();
           });
}

// ---- kept on disk ----

void Session::save()
{
    QJsonArray items;
    for (const Item &it : std::as_const(m_items))
        items.append(QJsonObject{{"id", it.id}, {"frame", it.frame}, {"takes_back", it.takesBack}, {"when", it.when},
                                 {"words", it.words}, {"body", it.body}, {"folder", it.folder}, {"picture", it.picture},
                                 {"watched", it.watched}, {"strokes", it.strokes}, {"state", stateName(it.state)},
                                 {"what", it.what}, {"why", it.why}, {"after", it.after}, {"label", it.label},
                                 {"landed", it.landed}, {"change_at", it.changeAt}, {"took_s", it.tookS}});
    QDir().mkpath(m_folder);
    QSaveFile f(QDir(m_folder).filePath(QStringLiteral("session.json")));
    if (f.open(QIODevice::WriteOnly)) {
        f.write(QJsonDocument(QJsonObject{{"project", m_project}, {"next_id", m_nextId}, {"tip", m_tip}, {"base", m_base},
                                          {"watched", m_watched}, {"watched_number", m_watchedNumber},
                                          {"kept_version", m_keptVersion}, {"items", items}})
                    .toJson());
        f.commit();
    }
}

// What was left from last time: changes not loaded yet stay; anything the AI had or was waiting for says it stopped.
void Session::restore()
{
    QFile f(QDir(m_folder).filePath(QStringLiteral("session.json")));
    if (!f.open(QIODevice::ReadOnly))
        return;
    const QJsonObject root = QJsonDocument::fromJson(f.readAll()).object();
    m_nextId = qMax(1, root.value("next_id").toInt(1));
    m_tip = root.value("tip").toString();
    m_base = root.value("base").toString();
    m_watched = root.value("watched").toString();
    m_watchedNumber = root.value("watched_number").toInt();
    m_keptVersion = root.value("kept_version").toBool();
    for (const auto &v : root.value("items").toArray()) {
        const QJsonObject o = v.toObject();
        Item it;
        it.id = o.value("id").toInt();
        it.frame = o.value("frame").toInt(-1);
        it.takesBack = o.value("takes_back").toInt();
        it.when = o.value("when").toString();
        it.words = o.value("words").toString();
        it.body = o.value("body").toString();
        it.folder = o.value("folder").toString();
        it.picture = o.value("picture").toString();
        it.watched = o.value("watched").toString();
        it.strokes = o.value("strokes").toArray();
        it.state = stateFrom(o.value("state").toString());
        it.what = o.value("what").toString();
        it.why = o.value("why").toString();
        it.after = o.value("after").toString();
        it.label = o.value("label").toString();
        it.landed = o.value("landed").toBool();
        it.changeAt = o.value("change_at").toDouble(-1);
        it.tookS = o.value("took_s").toDouble();
        if (it.state == State::Done && it.landed)
            continue; // finished and in the video: last time's list
        if (it.state == State::Cancelled || it.state == State::Undone || it.state == State::NotAnEdit)
            continue;
        if (it.state == State::Working || it.state == State::Waiting) {
            it.state = State::CouldNot;
            it.why = tr("letitedit closed before this was finished. Send it again if you still want it.");
        }
        m_items.append(it);
    }
    QFile::remove(QDir(m_folder).filePath(QStringLiteral("active.json")));
}

QJsonObject Session::state() const
{
    QJsonArray items;
    for (const Item &it : m_items)
        items.append(QJsonObject{{"id", it.id}, {"state", stateName(it.state)}, {"words", it.words}, {"when", it.when},
                                 {"frame", it.frame}, {"what", it.what}, {"why", it.why}, {"landed", it.landed},
                                 {"label", it.label}, {"change_at", it.changeAt}, {"took_s", it.tookS},
                                 {"takes_back", it.takesBack}, {"cancel_asked", it.cancelAsked}});
    return QJsonObject{{"items", items}, {"waiting", waiting()}, {"working", working()}, {"ready", ready()},
                       {"loading", m_loading}, {"load_problem", m_loadProblem}, {"folder", m_folder}, {"tip", m_tip}, {"ai_busy_note", m_aiBusyNote}};
}

} // namespace LiveReview
