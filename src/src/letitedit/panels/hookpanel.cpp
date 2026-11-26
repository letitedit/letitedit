/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit "Opening" panel (hookpanel.h). The contract with the tools is STYLES.md 5.2: the app reads
 * <project stem>.letitedit/hooks.json itself and shows the next candidate at once; hooks.py next | more | mark |
 * request | preview | apply run in the background, one at a time (preview on its own), and apply lands in the open
 * window as one native undo step.
 */
#include "letitedit/panels/hookpanel.h"

#include "letitedit/bridge/jsonprocess.h"
#include "letitedit/chat/aichatpanel.h"
#include "docks/timelinedock.h"
#include "models/multitrackmodel.h"
#include <MltPlaylist.h>
#include <MltTractor.h>
#include "letitedit/airoot.h"
#include "letitedit/workspace/leside.h"
#include "letitedit/workspace/focusworkspace.h"
#include "mainwindow.h"
#include "player.h"

#include <QAudioOutput>
#include <QDir>
#include <QDockWidget>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QFrame>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QMediaPlayer>
#include <QPointer>
#include <QProcess>
#include <QProcessEnvironment>
#include <QPushButton>
#include <QRegularExpression>
#include <QScrollArea>
#include <QCoreApplication>
#include <QTimer>
#include <QUndoStack>
#include <QVBoxLayout>
#include <QVideoFrame>
#include <QVideoSink>

#include <algorithm>
#include <functional>
#include <memory>

namespace HookPanel {

namespace {

// The environment for the hook tools: this window's instance, and no AI session's owner token (one inherited from
// whoever started the editor would make the helpers part of that session). Apply is the person's own edit, so it
// passes --from-app: the tools check that this window started the helper, then neither check nor take the window's AI
// ownership (an AI that edited the window keeps it; another AI is still refused).
QProcessEnvironment toolEnvironment()
{
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.remove(QStringLiteral("LETITEDIT_OWNER"));
    env.insert(QStringLiteral("LETITEDIT_INSTANCE"), qEnvironmentVariable("LETITEDIT_INSTANCE", QStringLiteral("main")));
    return env;
}

// A low-res preview of the opening (hooks.py preview: an MP4 and a strip of frames), played in the panel with sound.
class PreviewView : public QLabel
{
public:
    explicit PreviewView(QWidget *parent)
        : QLabel(parent)
    {
        setObjectName(QStringLiteral("hookPreview"));
        setAlignment(Qt::AlignCenter);
        setMinimumHeight(170);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Preferred);
        setWordWrap(true);
        setStyleSheet(QStringLiteral("background: %1; border-radius: 8px; color: %2;")
                          .arg(LetItEditColors::deep, LetItEditColors::muted));
        m_sink = new QVideoSink(this);
        m_audio = new QAudioOutput(this);
        m_player = new QMediaPlayer(this);
        m_player->setVideoSink(m_sink);
        m_player->setAudioOutput(m_audio);
        connect(m_sink, &QVideoSink::videoFrameChanged, this, [this](const QVideoFrame &frame) {
            const QImage image = frame.toImage();
            if (!image.isNull())
                setPixmap(QPixmap::fromImage(image.scaled(size() - QSize(8, 8), Qt::KeepAspectRatio, Qt::SmoothTransformation)));
        });
        connect(m_player, &QMediaPlayer::errorOccurred, this, [this](QMediaPlayer::Error, const QString &) {
            showStill(); // no player for this file here: the strip of frames instead
        });
    }

    void showClip(const QString &clip, const QString &strip)
    {
        if (clip == m_clip && playing())
            return;
        m_clip = clip;
        m_strip = strip;
        m_player->stop();
        if (!clip.isEmpty() && QFileInfo::exists(clip)) {
            m_player->setSource(QUrl::fromLocalFile(clip));
            m_player->play();
        } else {
            m_player->setSource(QUrl());
            showStill();
        }
    }

    void showText(const QString &text)
    {
        m_player->stop();
        m_player->setSource(QUrl());
        m_clip.clear();
        m_strip.clear();
        setPixmap(QPixmap());
        setText(text);
    }

    void stop() { m_player->stop(); }
    bool playing() const { return m_player->playbackState() == QMediaPlayer::PlayingState; }
    QString clip() const { return m_clip; }

private:
    void showStill()
    {
        if (!m_strip.isEmpty() && QFileInfo::exists(m_strip)) {
            setPixmap(QPixmap(m_strip).scaled(size() - QSize(8, 8), Qt::KeepAspectRatio, Qt::SmoothTransformation));
        } else {
            setPixmap(QPixmap());
            setText(tr("Preview coming..."));
        }
    }

    QVideoSink *m_sink = nullptr;
    QAudioOutput *m_audio = nullptr;
    QMediaPlayer *m_player = nullptr;
    QString m_clip;
    QString m_strip;
};

class Panel : public QWidget
{
public:
    explicit Panel(MainWindow *window, QWidget *parent)
        : QWidget(parent)
        , m_window(window)
    {
        using namespace LetItEditColors;
        setObjectName(QStringLiteral("hookPanel"));
        setStyleSheet(QStringLiteral(
                          "QFrame#hookCard { background: %1; border: 1px solid %2; border-radius: 12px; }"
                          "QLabel#hookApproach { color: %3; font-size: 11px; font-weight: 700; letter-spacing: 1px; }"
                          "QLabel#hookSaid { color: %4; font-size: 16px; font-weight: 600; }"
                          "QLabel#hookWords { color: %4; font-size: 12px; }"
                          "QLabel#hookWhy { color: %5; font-size: 12px; }"
                          "QLabel#hookStatus { color: %3; }"
                          "QPushButton#hookNew { font-size: 16px; min-height: 30px; }"
                          "QPushButton#hookOriginal { background: transparent; border: none; color: %5; text-align: left; "
                          "padding: 2px 0; } QPushButton#hookOriginal:hover { color: %4; }")
                          .arg(panel, line, tealLight, cream, muted));
        auto column = new QVBoxLayout(this);
        column->setContentsMargins(14, 10, 14, 12);
        column->setSpacing(8);
        auto contentScroll = new QScrollArea(this);
        contentScroll->setObjectName(QStringLiteral("openingCardScroll"));
        contentScroll->setWidgetResizable(true);
        contentScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        contentScroll->setMinimumSize(0, 0);
        auto content = new QWidget(contentScroll);
        auto contentColumn = new QVBoxLayout(content);
        contentColumn->setContentsMargins(0, 0, 0, 0);
        contentColumn->setSpacing(8);
        auto lead = new QLabel(tr("The first seconds decide whether people keep watching. Try openings (also called hooks) until one "
                                  "grabs you: each one goes straight into your video."),
                               content);
        lead->setWordWrap(true);
        lead->setProperty("studioMuted", true);
        contentColumn->addWidget(lead);

        auto card = new QFrame(content);
        card->setObjectName(QStringLiteral("hookCard"));
        auto inside = new QVBoxLayout(card);
        inside->setContentsMargins(12, 10, 12, 12);
        inside->setSpacing(6);
        m_approach = new QLabel(card);
        m_approach->setObjectName(QStringLiteral("hookApproach"));
        inside->addWidget(m_approach);
        m_said = new QLabel(card);
        m_said->setObjectName(QStringLiteral("hookSaid"));
        m_said->setWordWrap(true);
        inside->addWidget(m_said);
        m_words = new QLabel(card);
        m_words->setObjectName(QStringLiteral("hookWords"));
        m_words->setWordWrap(true);
        inside->addWidget(m_words);
        m_preview = new PreviewView(card);
        inside->addWidget(m_preview);
        m_why = new QLabel(card);
        m_why->setObjectName(QStringLiteral("hookWhy"));
        m_why->setWordWrap(true);
        inside->addWidget(m_why);
        contentColumn->addWidget(card);
        contentScroll->setWidget(content);
        column->addWidget(contentScroll, 1);

        m_new = new QPushButton(tr("New hook"), this);
        m_new->setObjectName(QStringLiteral("hookNew"));
        m_new->setProperty("studioPrimary", true);
        m_new->setToolTip(tr("Show the next opening and put it in your video (one Undo step)"));
        connect(m_new, &QPushButton::clicked, this, [this]() { newHook(); });
        column->addWidget(m_new);
        auto row = new QHBoxLayout;
        row->setSpacing(6);
        m_previous = new QPushButton(tr("Previous"), this);
        m_previous->setObjectName(QStringLiteral("hookPrevious"));
        m_previous->setToolTip(tr("The opening you saw before this one"));
        connect(m_previous, &QPushButton::clicked, this, [this]() { previous(); });
        row->addWidget(m_previous);
        m_otherWords = new QPushButton(tr("Other words"), this);
        m_otherWords->setObjectName(QStringLiteral("hookOtherWords"));
        m_otherWords->setToolTip(tr("Other words on screen for this opening, or none"));
        connect(m_otherWords, &QPushButton::clicked, this, [this]() { otherWords(); });
        row->addWidget(m_otherWords);
        m_play = new QPushButton(tr("Play in my video"), this);
        m_play->setObjectName(QStringLiteral("hookPlay"));
        m_play->setToolTip(tr("Play your video from the start, with this opening"));
        connect(m_play, &QPushButton::clicked, this, [this]() { playVideo(); });
        row->addWidget(m_play);
        column->addLayout(row);
        m_original = new QPushButton(tr("Back to my original opening"), this);
        m_original->setObjectName(QStringLiteral("hookOriginal"));
        m_original->setCursor(Qt::PointingHandCursor);
        connect(m_original, &QPushButton::clicked, this, [this]() { original(); });
        column->addWidget(m_original);
        m_status = new QLabel(this);
        m_status->setObjectName(QStringLiteral("hookStatus"));
        m_status->setWordWrap(true);
        column->addWidget(m_status);
        m_ask = new QPushButton(tr("Ask my AI for hook ideas"), this);
        m_ask->setObjectName(QStringLiteral("hookAsk"));
        m_ask->hide();
        connect(m_ask, &QPushButton::clicked, this, [this]() { askAi(); });
        column->addWidget(m_ask);
        // Only a panel that shows follows the open video: opening a project starts nothing here. Showing the panel follows it.
        connect(m_window, &MainWindow::producerOpened, this, [this]() {
            QTimer::singleShot(300, this, [this]() {
                if (isVisible())
                    follow();
            });
        });
        // Undo, Redo or an edit that swapped the opening: the panel shows the one the timeline really has
        connect(m_window->undoStack(), &QUndoStack::indexChanged, this, [this]() {
            QTimer::singleShot(0, this, [this]() { followUndo(); });
        });
        // the AI may add hook candidates (a request answered, or asked in the chat): read the file when it is done
        aiChatWatchBusy(this, [this](bool busy) {
            if (!busy && !m_project.isEmpty() && isVisible() && readFile())
                showOnScreen();
        });
        showOnScreen();
    }

    // The project the panel works on follows the open video.
    void follow()
    {
        const QString file = m_window->fileName();
        if (file == m_project)
            return;
        m_project = file;
        m_ready.clear();
        m_history.clear();
        m_index = -1;
        m_textIndex = 0;
        m_current = QJsonObject();
        m_applied.clear();
        m_appliedText = 0;
        m_all.clear();
        m_wanted.clear();
        m_previews.clear();
        m_jobs.clear();
        m_noMore = false;
        m_refillExhausted = false;
        m_asked = false;
        m_ask->hide();
        if (m_project.isEmpty()) {
            setStatus(tr("Save your video first, then try other openings."));
            showOnScreen();
            return;
        }
        // what the file already holds shows at once; next --count 0 brings it up to date with the cut (marks kept,
        // nothing marked shown)
        readFile();
        if (!m_applied.isEmpty() && m_applied != QLatin1String("h0"))
            setStatus(tr("This is the opening in your video now."));
        followUndo(); // the timeline's own word on it wins over the file's
        showOnScreen();
        refresh();
    }

    QJsonObject state() const
    {
        QJsonArray history;
        for (const auto &c : m_history)
            history.append(c.value("id"));
        QJsonArray ready;
        for (const auto &c : m_ready)
            ready.append(c.value("id"));
        QJsonArray jobs;
        for (const auto &j : m_jobs)
            jobs.append(j.args.value(0));
        const QJsonObject shown = onScreen();
        return QJsonObject{{"open", isVisible()},
                           {"project", m_project},
                           {"file", hooksFile()},
                           {"on_screen", QJsonObject{{"id", shown.value("id")},
                                                     {"approach", shown.value("approach")},
                                                     {"label", m_approach->text()},
                                                     {"said", m_said->text()},
                                                     {"words", m_words->text()},
                                                     {"why", m_why->text()},
                                                     {"text_index", m_textIndex},
                                                     {"preview", m_preview->clip()}}},
                           {"applied", m_applied},
                           {"applied_text", m_appliedText},
                           {"timeline_hook", timelineHook()},
                           {"wanted", m_wanted},
                           {"applying", m_applying},
                           {"running", m_running.isEmpty() ? QJsonValue() : QJsonValue(m_running)},
                           {"queued", jobs},
                           {"previewing", m_previewProc != nullptr},
                           {"ready", ready},
                           {"history", history},
                           {"index", m_index},
                           {"previews", m_previews.size()},
                           {"status", m_status->text()},
                           {"last_show_ms", m_lastShowMs},
                           {"last_apply_ms", m_lastApplyMs},
                           {"last_live", m_lastLive},
                           {"new_enabled", m_new->isEnabled()},
                           {"new_text", m_new->text()},
                           {"no_more", m_noMore},
                           {"preview_playing", m_preview->playing()}};
    }

    void stopPreview() { m_preview->stop(); }

protected:
    void hideEvent(QHideEvent *e) override
    {
        m_preview->stop();
        QWidget::hideEvent(e);
    }

private:
    using Done = std::function<void(int, const QJsonObject &, const QString &)>;
    struct Job
    {
        QStringList args;
        Done done;
    };

    QString hooksFile() const
    {
        if (m_project.isEmpty())
            return QString();
        return leSideFolder(m_project) + QStringLiteral("/hooks.json"); // <stem>.letitedit (an old .shotcut moves)
    }

    // hooks.json as the tools wrote it: the cut's own opening, the hook in the video now, and the candidates not
    // shown yet in showing order. False when there is no file (yet).
    bool readFile()
    {
        QFile f(hooksFile());
        if (!f.open(QIODevice::ReadOnly))
            return false;
        const QJsonObject data = QJsonDocument::fromJson(f.readAll()).object();
        if (data.value("format").toString() != QLatin1String("letitedit-hooks/1"))
            return false;
        QList<QJsonObject> fresh;
        for (const auto &v : data.value("candidates").toArray()) {
            const QJsonObject c = v.toObject();
            const QString id = c.value("id").toString();
            m_all.insert(id, c);
            if (c.value("approach").toString() == QLatin1String("current") || id == QLatin1String("h0")) {
                m_current = c;
                continue;
            }
            // a preview the tools made (here or by an earlier session) plays at once
            const QString clip = c.value("preview").toString();
            if (!clip.isEmpty() && QFileInfo::exists(clip) && !m_previews.contains(id))
                m_previews.insert(id, QJsonObject{{"clip", clip}, {"sheet", c.value("preview_sheet").toString()}});
            if (c.value("status").toString() == QLatin1String("new") && !inHistory(id))
                fresh << c;
            // keep what is known about candidates already queued up to date (the AI may rewrite their text)
            for (auto &r : m_ready)
                if (r.value("id").toString() == id) {
                    const QString status = r.value("status").toString();
                    r = c;
                    r.insert("status", status);
                }
            for (auto &h : m_history)
                if (h.value("id").toString() == id && c.value("text") != h.value("text"))
                    h.insert("text", c.value("text"));
        }
        if (m_applied.isEmpty())
            m_applied = data.value("applied").toString();
        for (const auto &c : fresh)
            if (!inReady(c.value("id").toString()))
                m_ready << c;
        std::stable_sort(m_ready.begin(), m_ready.end(), [](const QJsonObject &a, const QJsonObject &b) {
            return a.value("order").toInt() < b.value("order").toInt();
        });
        m_missing = data.value("no_transcript").toArray().size();
        if (!m_ready.isEmpty()) {
            m_noMore = false;
            m_ask->hide();
        }
        if (m_ready.size() > 8)
            m_refillExhausted = false;
        if (m_ready.size() <= 8 && !m_moreQueued)
            refillAhead();
        previewAhead();
        return true;
    }

    // The candidates a 'next' or 'more' printed are the next to show (listing marks nothing in hooks.json: they stay
    // 'new' there until the person passes over one, which this panel marks).
    void takePrinted(const QJsonObject &r)
    {
        if (r.value("current").isObject())
            m_current = r.value("current").toObject();
        for (const auto &v : r.value("candidates").toArray()) {
            const QJsonObject c = v.toObject();
            const QString id = c.value("id").toString();
            if (!id.isEmpty() && !inHistory(id) && !inReady(id))
                m_ready << c;
        }
        std::stable_sort(m_ready.begin(), m_ready.end(), [](const QJsonObject &a, const QJsonObject &b) {
            return a.value("order").toInt() < b.value("order").toInt();
        });
    }

    bool inReady(const QString &id) const
    {
        return std::any_of(m_ready.begin(), m_ready.end(), [&id](const QJsonObject &c) { return c.value("id").toString() == id; });
    }

    bool inHistory(const QString &id) const
    {
        return std::any_of(m_history.begin(), m_history.end(), [&id](const QJsonObject &c) { return c.value("id").toString() == id; });
    }

    // python bridge/hooks.py <args>: one JSON object on stdout, the reason on stderr when it fails. The calls that
    // write hooks.json run one at a time, in order; previews run on their own.
    void enqueue(const QStringList &args, const Done &done, bool front = false)
    {
        if (front)
            m_jobs.prepend(Job{args, done});
        else
            m_jobs.append(Job{args, done});
        runNext();
    }

    void runNext()
    {
        if (!m_running.isEmpty() || m_jobs.isEmpty())
            return;
        const Job job = m_jobs.takeFirst();
        m_running = job.args.value(0);
        const QString project = m_project;
        start(job.args, [this, job, project](int code, const QJsonObject &r, const QString &err) {
            m_running.clear();
            if (project == m_project && job.done)
                job.done(code, r, err);
            runNext();
        });
    }

    QProcess *start(const QStringList &args, const Done &done)
    {
        const QString python = aiChatSettings().value("python").toString();
        auto process = new QProcess(this);
        process->setProgram(python);
        process->setArguments(QStringList{QStringLiteral("-u"), aiRootPath(QStringLiteral("bridge/hooks.py"))} + args
                              + QStringList{QStringLiteral("--window-pid"),
                                            QString::number(QCoreApplication::applicationPid())}); // ends with this window
        process->setWorkingDirectory(aiRootPath(QStringLiteral("bridge")));
        process->setProcessEnvironment(toolEnvironment());
        return startJsonProcess(process, this,
            [process, done](int code, const QJsonObject &result, const QString &err) {
                if (done)
                    done(code, result, process->error() == QProcess::FailedToStart
                        ? QObject::tr("letitedit's helper tools could not start.") : err);
            });
    }

    // The last line of a Python error, without the traceback.
    static QString reason(const QString &err)
    {
        QStringList lines = err.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
        while (!lines.isEmpty() && lines.last().trimmed().isEmpty())
            lines.removeLast();
        QString last = lines.isEmpty() ? QString() : lines.last().trimmed();
        last.remove(QRegularExpression(QStringLiteral("^[A-Za-z_.]*(Error|Exception):\\s*")));
        return last.isEmpty() ? QObject::tr("the hook tools did not answer") : last.left(240);
    }

    // Brings hooks.json up to date with the cut (made when missing; re-scored when the cut changed; marks kept).
    void refresh()
    {
        if (m_project.isEmpty())
            return;
        if (m_ready.isEmpty() && m_index < 0)
            setStatus(tr("Getting openings ready..."));
        showOnScreen();
        enqueue({QStringLiteral("next"), m_project, QStringLiteral("--count"), QStringLiteral("0")},
                [this](int code, const QJsonObject &r, const QString &err) {
                    if (code != 0) {
                        setStatus(tr("Couldn't get openings: %1").arg(reason(err)));
                        showOnScreen();
                        return;
                    }
                    takePrinted(r);
                    readFile();
                    if (m_ready.size() < 3)
                        more();
                    else
                        readyStatus();
                    showOnScreen();
                });
    }

    // Fewer than three left: the tools search deeper and append.
    void more()
    {
        if (m_moreQueued || m_noMore)
            return;
        m_moreQueued = true;
        enqueue({QStringLiteral("more"), m_project, QStringLiteral("--count"), QStringLiteral("8")},
                [this](int code, const QJsonObject &r, const QString &err) {
                    m_moreQueued = false;
                    if (code != 0) {
                        setStatus(tr("Couldn't get more openings: %1").arg(reason(err)));
                        showOnScreen();
                        return;
                    }
                    const int before = m_ready.size();
                    takePrinted(r);
                    readFile();
                    m_noMore = m_ready.size() == before && r.value("left").toInt() == 0;
                    if (m_noMore && m_ready.isEmpty()) {
                        setStatus(tr("Finding more openings from your video..."));
                        refillAhead();
                    } else if (!m_applying) {
                        readyStatus();
                    }
                    showOnScreen();
                });
    }

    // A separate process keeps AI generation out of the chat and off the ordered apply queue.
    void refillAhead()
    {
        if (m_project.isEmpty() || m_refillProc || m_refillExhausted || m_ready.size() > 8 || !isVisible())
            return;
        const QString project = m_project;
        m_refillProc = start({QStringLiteral("refill"), project, QStringLiteral("--count"), QStringLiteral("8")},
                             [this, project](int code, const QJsonObject &r, const QString &err) {
                                 m_refillProc = nullptr;
                                 if (project != m_project)
                                     return;
                                 if (code == 0) {
                                     m_refillExhausted = r.value("added").toInt() == 0;
                                     readFile();
                                     if (m_ready.isEmpty() && r.value("added").toInt() == 0) {
                                         setStatus(tr("No more distinct openings are ready yet. Ask your AI for ideas."));
                                         m_ask->setVisible(!m_asked);
                                     } else if (!m_applying) {
                                         readyStatus();
                                     }
                                 } else if (m_ready.isEmpty()) {
                                     m_refillExhausted = true;
                                     setStatus(tr("Couldn't get more openings: %1").arg(reason(err)));
                                     m_ask->setVisible(!m_asked);
                                 }
                                 showOnScreen();
                             });
    }

    void readyStatus()
    {
        if (m_applying)
            return;
        setStatus(m_ready.isEmpty()        ? QString()
                  : m_ready.size() == 1    ? tr("1 more opening ready.")
                                           : tr("%1 more openings ready.").arg(m_ready.size()));
    }

    // Previews of the next two openings, one render at a time in the background (each waits its turn for the PC's
    // render lock; about 20 s, then cached).
    void previewAhead()
    {
        if (m_previewProc || m_project.isEmpty() || !isVisible())
            return;
        QString id;
        const QJsonObject on = onScreen();
        if (m_index >= 0 && !m_previews.contains(on.value("id").toString()))
            id = on.value("id").toString();
        for (int i = 0; id.isEmpty() && i < qMin(2, int(m_ready.size())); ++i)
            if (!m_previews.contains(m_ready[i].value("id").toString())
                && !m_previewFailed.contains(m_ready[i].value("id").toString()))
                id = m_ready[i].value("id").toString();
        if (id.isEmpty() || m_previewFailed.contains(id))
            return;
        const QString project = m_project;
        m_previewProc = start({QStringLiteral("preview"), m_project, id, QStringLiteral("--text"), QStringLiteral("0")},
                              [this, id, project](int code, const QJsonObject &r, const QString &) {
                                  m_previewProc = nullptr;
                                  if (project != m_project)
                                      return;
                                  if (code == 0 && r.contains("clip")) {
                                      m_previews.insert(id, r);
                                      if (onScreen().value("id").toString() == id && m_textIndex == 0)
                                          m_preview->showClip(r.value("clip").toString(), r.value("sheet").toString());
                                  } else {
                                      m_previewFailed.insert(id);
                                  }
                                  previewAhead();
                              });
    }

    // The opening the timeline holds, as the swap wrote it on the project in the same Undo step: "<id>|<text>"
    // (text: the index of the words on screen, "none" or "custom"); empty: the cut's own opening, or nothing known.
    QString timelineHook() const
    {
        auto *tractor = m_window->multitrack();
        return tractor && tractor->is_valid() ? QString::fromUtf8(tractor->get("letitedit_ai:hook")) : QString();
    }

    // After Undo or Redo (or the AI swapping the opening), the card, its words, its preview and the status say what is
    // in the video now, from the timeline itself.
    void followUndo()
    {
        if (m_project.isEmpty() || m_applying || m_project != m_window->fileName())
            return;
        const QString prop = timelineHook();
        const QString id = openingInVideo(m_window);
        if (id.isEmpty())
            return; // an opening swapped in without a record on the timeline: hooks.json's word stands
        const QString words = prop.section(QLatin1Char('|'), 1, 1);
        QJsonObject candidate = id == QLatin1String("h0") ? m_current : m_all.value(id);
        for (const auto &c : std::as_const(m_history))
            if (c.value("id").toString() == id)
                candidate = c;
        bool isNumber = false;
        const int number = words.toInt(&isNumber);
        const int text = isNumber ? number : textOptions(candidate).size(); // none or custom: no option of the list
        const QString now = m_applied.isEmpty() ? QStringLiteral("h0") : m_applied;
        if (id == now && (id == QLatin1String("h0") || text == m_appliedText))
            return;
        m_applied = id;
        m_appliedText = text;
        m_wanted = id;
        m_wantedText = text;
        if (id == QLatin1String("h0")) {
            m_index = -1;
            m_textIndex = 0;
        } else {
            int at = -1;
            for (int i = 0; i < m_history.size(); ++i)
                if (m_history[i].value("id").toString() == id)
                    at = i;
            if (at < 0 && !candidate.isEmpty()) { // put back from outside this session's list (the AI, or the file)
                for (int i = 0; i < m_ready.size(); ++i)
                    if (m_ready[i].value("id").toString() == id) {
                        m_ready.removeAt(i);
                        break;
                    }
                m_history << candidate;
                at = m_history.size() - 1;
            }
            m_index = at;
            m_textIndex = text;
        }
        setStatus(id == QLatin1String("h0") ? tr("Your original opening is in your video now.")
                                           : tr("This opening is in your video now."));
        showOnScreen();
    }

    QJsonObject onScreen() const
    {
        if (m_index >= 0 && m_index < m_history.size())
            return m_history[m_index];
        return m_current;
    }

    void setStatus(const QString &text) { m_status->setText(text); }

    // The card shows the opening on screen: what it is, what is said, the words on screen, why, and its preview.
    void showOnScreen()
    {
        const QJsonObject c = onScreen();
        const bool original = m_index < 0;
        if (c.isEmpty()) {
            m_approach->setText(tr("YOUR OPENING"));
            m_said->setText(m_project.isEmpty() ? tr("Save your video to try other openings.") : tr("Looking at your video..."));
            m_words->clear();
            m_why->clear();
            m_preview->showText(QString());
        } else {
            const QString approach = c.value("label").toString();
            m_approach->setText(original ? tr("YOUR ORIGINAL OPENING") : approach.toUpper());
            const QString said = c.value("said").toString().trimmed();
            m_said->setText(said.isEmpty() ? (original ? tr("The video as it starts now.") : tr("(a moment without words)"))
                                           : QStringLiteral("“%1”").arg(said));
            const QStringList options = textOptions(c);
            if (!options.isEmpty() && m_textIndex < options.size())
                m_words->setText(tr("On screen: %1").arg(options[m_textIndex]));
            else
                m_words->setText(original ? QString() : tr("No words on screen"));
            QString why = c.value("why").toString();
            // Older queued candidates included their position in the original cut. That claim becomes false
            // after this opening is put at the start, so describe only the creative reason here.
            why.remove(QRegularExpression(QStringLiteral("; (?:it plays at .*|it is not in the cut yet)\\.?$")));
            if (!why.isEmpty() && !why.endsWith(QLatin1Char('.')))
                why += QLatin1Char('.');
            m_why->setText(original ? QString() : why);
            const QJsonObject p = m_previews.value(c.value("id").toString());
            if (!p.isEmpty() && (m_textIndex == 0 || original))
                m_preview->showClip(p.value("clip").toString(), p.value("sheet").toString());
            else if (original)
                m_preview->showText(tr("Press Play in my video to watch it"));
            else if (m_textIndex > 0)
                m_preview->showText(m_textIndex >= options.size()
                                        ? tr("Press Play in my video to watch without words on screen")
                                        : tr("Press Play in my video to see it with these words"));
            else
                m_preview->showText(m_applying ? tr("Applying opening... The preview may take longer.")
                                               : tr("Preview coming... Press Play in my video to watch it."));
        }
        const bool saved = !m_project.isEmpty();
        const bool waiting = m_ready.isEmpty() && m_index + 1 >= m_history.size() && (m_running == QLatin1String("next")
                                                                                      || m_moreQueued);
        m_new->setEnabled(saved && !waiting);
        m_new->setText(waiting ? tr("Getting openings...") : tr("New hook"));
        m_previous->setEnabled(saved && m_index >= 0);
        m_original->setEnabled(saved && (m_index >= 0 || (!m_applied.isEmpty() && m_applied != QLatin1String("h0"))));
        m_otherWords->setVisible(!original && !textOptions(c).isEmpty());
        m_play->setEnabled(saved);
    }

    static QStringList textOptions(const QJsonObject &c)
    {
        QStringList out;
        for (const auto &v : c.value("text").toArray())
            if (!v.toString().trimmed().isEmpty())
                out << v.toString().trimmed();
        return out;
    }

    void newHook()
    {
        QElapsedTimer clock;
        clock.start();
        if (m_index + 1 < m_history.size()) {
            ++m_index;
        } else {
            if (m_ready.isEmpty())
                readFile(); // the AI may have added some
            if (m_ready.isEmpty()) {
                if (!m_noMore) {
                    setStatus(tr("Getting more openings ready..."));
                    more();
                } else {
                    setStatus(tr("Finding more openings from your video..."));
                    refillAhead();
                }
                showOnScreen();
                return;
            }
            m_history << m_ready.takeFirst();
            m_index = m_history.size() - 1;
        }
        m_window->player()->pause();
        m_textIndex = 0;
        showOnScreen();
        m_lastShowMs = clock.elapsed();
        apply(onScreen().value("id").toString(), 0);
        if (m_ready.size() < 3)
            more(); // top up while the person watches this one
        previewAhead();
    }

    void previous()
    {
        if (m_index < 0)
            return;
        --m_index;
        m_textIndex = 0;
        m_window->player()->pause();
        showOnScreen();
        apply(m_index >= 0 ? onScreen().value("id").toString() : QStringLiteral("h0"), 0);
    }

    void original()
    {
        m_index = -1;
        m_textIndex = 0;
        showOnScreen();
        apply(QStringLiteral("h0"), 0);
    }

    void otherWords()
    {
        const QStringList options = textOptions(onScreen());
        if (options.isEmpty())
            return;
        m_textIndex = (m_textIndex + 1) % (options.size() + 1); // the last turn: no words on screen
        showOnScreen();
        apply(onScreen().value("id").toString(), m_textIndex);
    }

    void playVideo()
    {
        m_preview->stop();
        m_window->seekTimeline(0);
        m_window->player()->play();
    }

    void askAi()
    {
        m_asked = true;
        m_ask->hide();
        enqueue({QStringLiteral("request"), m_project, QStringLiteral("--count"), QStringLiteral("8")}, nullptr);
        if (aiChatRequest(m_window,
                          QStringLiteral("The person wants more openings for the open video: answer the hook request in "
                                         "its hooks.json (letitedit_hooks) by adding strong candidates of different "
                                         "approaches, in the speaker's own words. Don't change the video; they try them "
                                         "with the New hook button."),
                          tr("Find more openings for this video")))
            setStatus(tr("Asked your AI for more openings. Press New hook when it has answered."));
        else
            setStatus(tr("Your AI is busy. Ask again when it has answered."));
    }

    // The swap goes into the open video as one Undo step; a newer choice made meanwhile follows when it is done.
    void apply(const QString &id, int textIndex)
    {
        if (id.isEmpty() || m_project.isEmpty())
            return;
        m_wanted = id;
        m_wantedText = textIndex;
        // a swap not started yet gives way to the newest choice
        m_jobs.erase(std::remove_if(m_jobs.begin(), m_jobs.end(),
                                    [](const Job &j) { return j.args.value(0) == QLatin1String("apply"); }),
                     m_jobs.end());
        QJsonObject candidate;
        for (const auto &c : std::as_const(m_history))
            if (c.value("id").toString() == id)
                candidate = c;
        // --from-app: the person's own swap from this window, not an AI session (STYLES.md 5.2)
        QStringList args{QStringLiteral("apply"), m_project, id, QStringLiteral("--from-app")};
        if (id == QLatin1String("h0") || textIndex >= textOptions(candidate).size())
            args << QStringLiteral("--no-text");
        else
            args << QStringLiteral("--text") << QString::number(textIndex);
        m_applying = true;
        setStatus(id == QLatin1String("h0") ? tr("Putting your original opening back...") : tr("Putting it in your video..."));
        showOnScreen();
        auto clock = std::make_shared<QElapsedTimer>();
        clock->start();
        // ahead of top-ups and marks: the person is waiting for this one
        enqueue(args, [this, id, textIndex, clock](int code, const QJsonObject &r, const QString &err) {
            m_lastApplyMs = clock->elapsed();
            m_lastLive = r.value("live").toBool();
            const bool latest = m_wanted == id && m_wantedText == textIndex;
            if (latest)
                m_applying = false;
            if (code != 0) {
                const QString why = reason(err);
                if (latest)
                    setStatus(why.contains(QLatin1String("unsaved"), Qt::CaseInsensitive)
                                  ? tr("Save your video (Ctrl+S), then press New hook again.")
                                  : tr("Couldn't put this opening in: %1").arg(why));
            } else {
                const QString before = m_applied;
                m_applied = id;
                m_appliedText = textIndex;
                // the one the person moved on from: passed over (the AI reads that in hooks.json), or just seen when
                // New hook can still bring it back in this session
                if (!before.isEmpty() && before != id && before != QLatin1String("h0"))
                    enqueue({QStringLiteral("mark"), m_project, before,
                             inHistoryAfter(before) ? QStringLiteral("shown") : QStringLiteral("rejected")},
                            nullptr);
                if (latest) {
                    if (!m_lastLive)
                        setStatus(tr("Saved into the video file; open it again to see the new opening."));
                    else
                        setStatus(id == QLatin1String("h0") ? tr("Your original opening is back. Undo (Ctrl+Z) puts the hook back.")
                                                            : tr("In your video now. Undo (Ctrl+Z) puts the last opening back."));
                    // no preview to watch here: the real thing from the start
                    if (m_lastLive && id != QLatin1String("h0") && isVisible()
                        && (!m_previews.contains(id) || textIndex > 0))
                        playVideo();
                }
            }
            showOnScreen();
        }, true);
    }

    // A candidate the person may come back to with Previous / New hook in this session is not marked rejected.
    bool inHistoryAfter(const QString &id) const
    {
        for (int i = m_index; i < m_history.size(); ++i)
            if (i >= 0 && m_history[i].value("id").toString() == id)
                return true;
        return false;
    }

    MainWindow *m_window;
    QLabel *m_approach = nullptr;
    QLabel *m_said = nullptr;
    QLabel *m_words = nullptr;
    QLabel *m_why = nullptr;
    QLabel *m_status = nullptr;
    PreviewView *m_preview = nullptr;
    QPushButton *m_new = nullptr;
    QPushButton *m_previous = nullptr;
    QPushButton *m_otherWords = nullptr;
    QPushButton *m_play = nullptr;
    QPushButton *m_original = nullptr;
    QPushButton *m_ask = nullptr;
    QString m_project;
    QList<QJsonObject> m_ready;   // not shown yet, in showing order
    QList<QJsonObject> m_history; // shown, in order
    int m_index = -1;             // the one on screen; -1: the original opening
    QJsonObject m_current;        // h0, the cut's own opening
    QString m_applied;            // in the video now
    int m_appliedText = 0;        // its words on screen (an index into its text options; past the end: none)
    QHash<QString, QJsonObject> m_all; // every candidate in hooks.json, by id
    QString m_wanted;             // the person's latest choice
    int m_wantedText = 0;
    int m_textIndex = 0;
    int m_missing = 0;            // source files without a transcript (left out)
    bool m_applying = false;
    bool m_noMore = false;
    bool m_moreQueued = false;
    bool m_refillExhausted = false;
    bool m_asked = false;
    bool m_lastLive = false;
    QHash<QString, QJsonObject> m_previews;
    QSet<QString> m_previewFailed;
    QList<Job> m_jobs;
    QString m_running; // the hooks.py command running now
    QProcess *m_previewProc = nullptr;
    QProcess *m_refillProc = nullptr;
    qint64 m_lastShowMs = -1;
    qint64 m_lastApplyMs = -1;
};

QPointer<QDockWidget> &dockRef()
{
    static QPointer<QDockWidget> dock;
    return dock;
}

Panel *panel()
{
    return dockRef() ? static_cast<Panel *>(dockRef()->findChild<QWidget *>(QStringLiteral("hookPanel"))) : nullptr;
}

} // namespace

QDockWidget *install(MainWindow *window)
{
    if (dockRef())
        return dockRef();
    auto dock = new QDockWidget(QObject::tr("Opening"), window);
    dock->setObjectName(QStringLiteral("focusHookDock"));
    auto p = new Panel(window, dock);
    dock->setWidget(p);
    dock->setMinimumWidth(320);
    window->addDockWidget(Qt::RightDockWidgetArea, dock);
    dock->hide();
    dockRef() = dock;
    QObject::connect(dock, &QDockWidget::visibilityChanged, p, [p](bool visible) {
        if (visible)
            p->follow();
        else
            p->stopPreview();
    });
    // After a New video request: when the AI is done and a saved video is open, the Opening panel shows itself.
    aiChatWatchBusy(p, [window](bool busy) {
        if (busy)
            return;
        const QDateTime sent = window->property("letitedit:firstCutSent").toDateTime();
        if (!sent.isValid() || sent.secsTo(QDateTime::currentDateTime()) > 6 * 3600 || window->fileName().isEmpty())
            return;
        window->setProperty("letitedit:firstCutSent", QVariant());
        QTimer::singleShot(800, window, [window]() { show(window); });
    });
    return dock;
}

void show(MainWindow *window)
{
    auto dock = install(window);
    auto chat = window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"));
    if (window->dockWidgetArea(dock) != Qt::RightDockWidgetArea)
        window->addDockWidget(Qt::RightDockWidgetArea, dock);
    dock->setFloating(false);
    dock->show();
    dock->raise();
    // above the AI chat in the same column when the chat is showing, so both stay in reach
    if (chat && chat->isVisible() && window->dockWidgetArea(chat) == Qt::RightDockWidgetArea && !chat->isFloating()) {
        window->splitDockWidget(dock, chat, Qt::Vertical);
        window->resizeDocks({dock}, {qMax(420, window->height() / 2)}, Qt::Vertical);
    }
    window->resizeDocks({dock}, {qMin(460, qMax(360, window->width() / 3))}, Qt::Horizontal);
    if (auto p = panel())
        p->follow();
}

QJsonObject state()
{
    auto p = panel();
    return p ? p->state() : QJsonObject{{"open", false}, {"installed", false}};
}

QString openingInVideo(MainWindow *window)
{
    auto *multitrack = window->multitrack();
    if (!multitrack || !multitrack->is_valid())
        return QString();
    const QString prop = QString::fromUtf8(multitrack->get("letitedit_ai:hook"));
    if (!prop.isEmpty())
        return prop.section(QLatin1Char('|'), 0, 0);
    // no swap recorded: is a swapped-in opening (a hook-* item) on the timeline at all?
    Mlt::Tractor tractor(*multitrack);
    if (!tractor.is_valid())
        return QString();
    auto *model = window->timelineDock()->model();
    for (const auto &track : model->trackList()) {
        std::unique_ptr<Mlt::Producer> producer(tractor.track(track.mlt_index));
        if (!producer || !producer->is_valid())
            continue;
        Mlt::Playlist playlist(*producer);
        for (int i = 0; i < playlist.count(); ++i) {
            std::unique_ptr<Mlt::ClipInfo> info(playlist.clip_info(i));
            if (!info || !info->producer || !info->producer->is_valid())
                continue;
            Mlt::Producer parent(info->producer->parent());
            if (QString::fromUtf8(parent.get("letitedit_ai:id")).startsWith(QLatin1String("hook-")))
                return QString();
        }
    }
    return QStringLiteral("h0");
}

} // namespace HookPanel
