/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef AINEWVIDEORUNNER_H
#define AINEWVIDEORUNNER_H

// T331 P11 (T319 rule 4): New video's first cut built on disk by the session runner (bridge/new_video_runner.py,
// bridge/letitedit/studio/first_cut.py), with no window, and opened in the person's window at the end. Off by default.
//
// With the switch on, New video's request (not Turbo, not a connector, not Learn, not the AI's own screen, Claude)
// goes to the runner instead of the chat's AI:
// - **Getting ready** (a few seconds, in the background: the window never waits): the runner's checks, the project made
//   in the video's folder, the runner's own preflight. Nothing else is sent meanwhile.
// - **A fallback** (the runner can't take this video, or it never answered): the request goes to the AI in this window
//   exactly as before (aiStageStartBegin or aiChatDispatch), and the chat says why in one plain line. Nothing was
//   launched, and the project the runner made is taken back.
// - **Started:** the chat shows the request as New video's own (the same block, so Home's card and Try again work as
//   ever), Busy and Stop as for any run, and one line before and after each of the three parts. The runner's tool
//   servers carry this chat's progress run (aiChatProgressRun), so the card follows them.
// - **Done:** the request ends answered. Home then opens the finished project in this window as it does when the
//   window's AI opened nothing: only an empty, unchanged window, without taking the keyboard (useFinishedVideo,
//   MAIN.openWithoutFocus); otherwise it offers Open. The window's Undo starts at the opened project; the build's own
//   steps are in the project's journal (letitedit_timeline_undo).
// - **Stop** (the chat's or the card's): the runner is told to stop (a line on its stdin) and the request ends as any
//   stopped New video does, with Continue the edit. Continue (or Home's Try again) starts the runner again on the same
//   video: it carries the same sessions on from its record (<project>.letitedit/session-runner.json).
// - A typed message while the runner works is refused with plain words (there is no conversation in this window to
//   steer); once the video is done and open, the chat edits it in the window as ever.
//
// The switch, on by default (T365): LETITEDIT_NEW_VIDEO_RUNNER (1 or 0) wins, else settings.json new_video_runner
// (false turns it off); the bridge also needs
// session_runner on (first_cut.enabled) and says so in its fallback line otherwise. QA: under LETITEDIT_QA,
// LETITEDIT_QA_NEW_VIDEO_RUNNER_SCRIPT names the script the chat starts instead of bridge/new_video_runner.py.

static bool aiNewVideoRunnerOn()
{
    const QString forced = qEnvironmentVariable("LETITEDIT_NEW_VIDEO_RUNNER").trimmed().toLower();
    if (forced == QLatin1String("1") || forced == QLatin1String("true") || forced == QLatin1String("on")
        || forced == QLatin1String("yes"))
        return true;
    if (forced == QLatin1String("0") || forced == QLatin1String("false") || forced == QLatin1String("off")
        || forced == QLatin1String("no"))
        return false;
    const QString path = qEnvironmentVariableIsSet("LETITEDIT_SETTINGS") ? qEnvironmentVariable("LETITEDIT_SETTINGS")
                                                                        : QDir(aiRoot()).filePath(QStringLiteral("settings.json"));
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return true;
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    return QJsonDocument::fromJson(data).object().value(QStringLiteral("new_video_runner")).toBool(true);
}

// The one run of this window's chat (one chat per window).
struct AiRunnerRun
{
    QPointer<QProcess> proc;
    QString chat;        // the chat it belongs to (c->chatId when it started)
    QString message;     // the request as the chat sends it (its stage-sessions line included): the fallback's text
    QString original;    // the request as New video wrote it: what the runner builds from
    QString summary;
    QString fallback;    // a carry-on's own words, sent to the window's AI on a fallback ("" for New video's request)
    bool spoken = false;
    bool preparing = false; // started, not yet "started" or "fallback"
    bool started = false;
    int request = 0;        // the chat's request this run answers (0 before "started")
    QString project;
    QByteArray buffer;
    int token = 0;
};

static AiRunnerRun &aiRunnerRun()
{
    static AiRunnerRun run;
    return run;
}

static bool aiRunnerWorking()
{
    const AiRunnerRun &r = aiRunnerRun();
    return r.proc && r.proc->state() != QProcess::NotRunning;
}

static bool aiRunnerWanted(AiChat *c, const QString &message)
{
    return aiNewVideoRunnerOn() && c->autonomousNewVideo && c->newVideoMakes && c->stageSessions && !c->liveReviewHold
           && !c->busy && !c->carrySending && c->carryEngine == QLatin1String("claude") && !aiTerminalMode()
           && message.contains(QStringLiteral("\nSave video in: "));
}

// The request goes to the window's AI, as before New video had a runner.
static int aiRunnerFallback(AiChat *c, MainWindow *window, const QString &reason)
{
    AiRunnerRun &r = aiRunnerRun();
    const QString message = r.fallback.isEmpty() ? r.message : r.fallback;
    const QString summary = r.summary;
    const bool spoken = r.spoken;
    const bool carry = !r.fallback.isEmpty();
    // from here this is the window's run: its carry-ons are the window's own
    r = AiRunnerRun{r.proc};
    c->carryAllowed = true;
    c->refusal.clear(); // from here only the send's own reason (not a message refused while getting ready)
    const int id = c->nextRequest; // the id the runner's start answered with
    const int sent = !carry && aiStageStartWanted(c, message) ? aiStageStartBegin(c, window, message, summary, spoken)
                                                              : aiChatDispatch(c, window, message, summary, spoken, !carry);
    if (sent) {
        aiChatAdd(c, QStringLiteral("note"),
                  QStringLiteral("letitedit is making this video with your AI in this window instead: %1").arg(reason));
    } else {
        c->status->setText(QStringLiteral("Your video did not start: %1").arg(c->refusal.isEmpty() ? reason : c->refusal));
        aiChatStartRefused(c, id, message, summary, c->refusal, carry);
    }
    aiChatSaveCurrent(c);
    return sent;
}

static void aiRunnerSay(AiChat *c, const QString &kind, const QString &text)
{
    if (text.trimmed().isEmpty())
        return;
    aiChatAdd(c, kind, text.trimmed());
    aiChatSaveCurrent(c);
}

// The request ends: answered (done), cancelled (a stop the runner confirms after the chat's Stop already ended it) or
// failed.
static void aiRunnerEnd(AiChat *c, const QString &outcome, const QString &error = QString())
{
    AiRunnerRun &r = aiRunnerRun();
    const int request = r.request;
    r.started = r.preparing = false;
    r.request = 0;
    if (!request || c->request != request)
        return;
    aiChatEndRequest(c, outcome, error);
    c->busy = true; // so the watchers (Home's card, its open at the end) hear that it is no longer busy
    aiChatSetBusy(c, false);
    if (outcome != QLatin1String("answered") && c->newVideoChat && c->newVideoMakes) {
        c->carryStopped = true;
        if (c->carryBar) {
            c->carryLabel->setText(QStringLiteral("letitedit stopped making this video. Everything done so far stays in "
                                                  "your project; you can carry on."));
            c->carryContinue->show();
            c->carryBar->show();
        }
    }
    aiChatSaveCurrent(c);
}

static void aiRunnerEvent(AiChat *c, MainWindow *window, const QJsonObject &e)
{
    AiRunnerRun &r = aiRunnerRun();
    const QString kind = e.value(QStringLiteral("event")).toString();
    if (kind == QLatin1String("fallback")) {
        if (r.preparing)
            aiRunnerFallback(c, window, e.value(QStringLiteral("reason")).toString(QStringLiteral("it couldn't start")));
        return;
    }
    if (kind == QLatin1String("started")) {
        if (!r.preparing)
            return;
        r.preparing = false;
        r.started = true;
        r.project = e.value(QStringLiteral("project")).toString();
        c->carryAllowed = false; // the runner carries its own phases on; the window's carry-on never runs for it
        r.request = aiChatBeginRequest(c, r.message, r.summary, r.spoken);
        aiChatSetBusy(c, true, QStringLiteral("letitedit is making your video, with no window..."));
        aiChatRevealDock(c);
        aiRunnerSay(c, QStringLiteral("note"),
                    QStringLiteral("letitedit is making this video on its own, on the project file (%1), with no "
                                   "window. Your window stays yours: it opens the video here when it is done.")
                        .arg(QDir::toNativeSeparators(r.project)));
        return;
    }
    if (!r.started)
        return;
    if (kind == QLatin1String("progress")) {
        const QString line = e.value(QStringLiteral("message")).toString();
        aiRunnerSay(c, QStringLiteral("note"), line);
        if (!e.value(QStringLiteral("phase")).toString().isEmpty())
            c->status->setText(line.section(QLatin1Char('.'), 0, 0) + QStringLiteral("..."));
    } else if (kind == QLatin1String("done")) {
        const QString exported = e.value(QStringLiteral("export")).toString();
        aiRunnerSay(c, QStringLiteral("note"),
                    exported.isEmpty()
                        ? QStringLiteral("Your video is made. letitedit opens it in your window.")
                        : QStringLiteral("Your video is made and saved as %1. letitedit opens it in your window.")
                              .arg(QDir::toNativeSeparators(exported)));
        aiRunnerEnd(c, QStringLiteral("answered"));
    } else if (kind == QLatin1String("stopped")) {
        const QString code = e.value(QStringLiteral("code")).toString();
        const QString why = e.value(QStringLiteral("message")).toString();
        if (code == QLatin1String("cancelled")) {
            aiRunnerEnd(c, QStringLiteral("cancelled"), QStringLiteral("You pressed Stop."));
        } else {
            aiRunnerSay(c, QStringLiteral("error"), QStringLiteral("letitedit stopped making your video: %1").arg(why));
            aiRunnerEnd(c, QStringLiteral("failed"), why);
        }
    }
}

// New video's request goes to the runner. Returns the id the request takes (as the first stage's start does).
static int aiRunnerBegin(AiChat *c, MainWindow *window, const QString &original, const QString &message,
                         const QString &summary, bool spoken, const QString &fallback = QString())
{
    static int runs = 0;
    AiRunnerRun &r = aiRunnerRun();
    if (aiRunnerWorking()) {
        c->refusal = QStringLiteral("letitedit is still stopping your last video. Try again in a moment.");
        c->status->setText(c->refusal);
        return 0;
    }
    const QJsonObject s = aiChatSettings();
    QString script = QDir(aiRoot()).filePath(QStringLiteral("bridge/new_video_runner.py"));
    if (qEnvironmentVariableIsSet("LETITEDIT_QA") && qEnvironmentVariableIsSet("LETITEDIT_QA_NEW_VIDEO_RUNNER_SCRIPT"))
        script = qEnvironmentVariable("LETITEDIT_QA_NEW_VIDEO_RUNNER_SCRIPT");
    r = AiRunnerRun{};
    r.token = ++runs;
    r.chat = c->chatId;
    r.message = message;
    r.original = original;
    r.summary = summary;
    r.fallback = fallback;
    r.spoken = spoken;
    r.preparing = true;
    const int id = c->nextRequest;
    auto *process = new QProcess(c->dock);
    r.proc = process;
    process->setProgram(s.value(QStringLiteral("python")).toString());
    process->setArguments({script});
    process->setProcessChannelMode(QProcess::SeparateChannels);
    process->setStandardErrorFile(QProcess::nullDevice());
    const int token = r.token;
    const auto mine = [c, token]() { return aiRunnerRun().token == token; };
    QObject::connect(process, &QProcess::readyReadStandardOutput, c->dock, [c, window, process, mine]() {
        if (!mine())
            return;
        AiRunnerRun &run = aiRunnerRun();
        run.buffer += process->readAllStandardOutput();
        int end;
        while ((end = run.buffer.indexOf('\n')) >= 0) {
            const QByteArray line = run.buffer.left(end).trimmed();
            run.buffer.remove(0, end + 1);
            const QJsonObject e = QJsonDocument::fromJson(line).object();
            if (e.isEmpty())
                continue;
            if (c->chatId != run.chat) { // the person started another chat: this run ends quietly
                if (process->state() != QProcess::NotRunning)
                    process->write("stop\n");
                run.preparing = run.started = false;
                return;
            }
            aiRunnerEvent(c, window, e);
            if (!mine())
                return;
        }
    });
    QObject::connect(process, &QProcess::finished, c->dock, [c, window, process, mine]() {
        process->deleteLater();
        if (!mine())
            return;
        AiRunnerRun &run = aiRunnerRun();
        if (run.preparing && c->chatId == run.chat)
            aiRunnerFallback(c, window, QStringLiteral("letitedit's video maker ended before it started."));
        else if (run.started && c->chatId == run.chat) {
            aiRunnerSay(c, QStringLiteral("error"),
                        QStringLiteral("letitedit stopped making your video: its video maker ended without saying how. "
                                       "Everything done so far stays in your project."));
            aiRunnerEnd(c, QStringLiteral("failed"), QStringLiteral("the video maker ended"));
        }
    });
    QObject::connect(process, &QProcess::errorOccurred, c->dock, [c, window, mine](QProcess::ProcessError error) {
        if (error != QProcess::FailedToStart || !mine())
            return;
        AiRunnerRun &run = aiRunnerRun();
        if (run.preparing && c->chatId == run.chat)
            aiRunnerFallback(c, window, QStringLiteral("letitedit's video maker couldn't start."));
    });
    // getting ready takes seconds; past this the window's AI takes the video (nothing has been launched yet)
    QTimer::singleShot(120000, c->dock, [c, window, mine]() {
        AiRunnerRun &run = aiRunnerRun();
        if (!mine() || !run.preparing)
            return;
        if (run.proc && run.proc->state() != QProcess::NotRunning)
            run.proc->write("stop\n");
        if (c->chatId == run.chat)
            aiRunnerFallback(c, window, QStringLiteral("letitedit's video maker took too long to get ready."));
    });
    c->status->setText(QStringLiteral("letitedit is getting your video ready..."));
    process->start();
    const QJsonObject input{{"folder", c->autonomousWriteDir}, {"request", original}, {"engine", c->carryEngine},
                            {"progress_run", aiChatProgressRun()}};
    process->write(QJsonDocument(input).toJson(QJsonDocument::Compact) + '\n');
    return id;
}

// While the runner gets ready nothing else is sent; while it works a typed message has no conversation to go into.
// Returns true (and the refusal) when this request can't go now.
static bool aiRunnerRefuses(AiChat *c)
{
    const AiRunnerRun &r = aiRunnerRun();
    if (r.chat != c->chatId || (!r.preparing && !r.started))
        return false;
    c->refusal = r.preparing ? QStringLiteral("letitedit is getting your video ready. Send this again in a moment.")
                             : QStringLiteral("letitedit is making this video on its own, with no window, so there is no "
                                              "conversation here to send this to. Send it once the video is open, or "
                                              "press Stop.");
    c->status->setText(c->refusal);
    return true;
}

// The chat's Stop (and the card's): the runner stops its sessions; the chat ends the request as for any stop.
static void aiRunnerStop(AiChat *c)
{
    AiRunnerRun &r = aiRunnerRun();
    if (r.chat != c->chatId || !aiRunnerWorking())
        return;
    r.proc->write("stop\n");
    r.started = r.preparing = false;
    r.request = 0;
}

// Continue the edit (the chat's or the card's) on a video the runner was making: the runner again, on the same video.
// Returns the request's id, 0 when it couldn't start, -1 when this isn't a runner video.
static int aiRunnerCarryOn(AiChat *c, MainWindow *window, const QString &message)
{
    AiRunnerRun &r = aiRunnerRun();
    if (r.chat.isEmpty() || r.chat != c->chatId || r.original.isEmpty() || message != aiNewVideoCarryWords())
        return -1;
    if (!aiNewVideoRunnerOn())
        return -1;
    const QString original = r.original;
    const QString sent = r.message.isEmpty() ? original : r.message;
    c->autonomousNewVideo = true;
    return aiRunnerBegin(c, window, original, sent, QStringLiteral("Continue the edit"), false, message);
}

// What the chat's state says about it (aiChatState, for checks)
static QJsonObject aiRunnerStateJson(AiChat *c)
{
    const AiRunnerRun &r = aiRunnerRun();
    const bool mine = !r.chat.isEmpty() && r.chat == c->chatId;
    return QJsonObject{{"on", aiNewVideoRunnerOn()}, {"owns_chat", mine}, {"preparing", mine && r.preparing},
                       {"started", mine && r.started}, {"working", aiRunnerWorking()}, {"request", mine ? r.request : 0},
                       {"project", mine ? r.project : QString()}};
}

#endif // AINEWVIDEORUNNER_H
