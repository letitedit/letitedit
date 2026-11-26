/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef AINEWVIDEOSTART_H
#define AINEWVIDEOSTART_H

// T300: New video's first stage starts complete (T299's starter, bridge/letitedit/app/stage_start.py; the editor's
// call is bridge/new_video_first_stage.py). Before the first conversation of a run that takes one conversation per
// stage (stageSessions: not Turbo, not a connector, not Learn), with the switch on:
// - the bridge builds the first message (log, or story with no footage): the request as New video wrote it, then every
//   skill, the Look, the brief's inputs, the journal tail and the timeline attached in full and checksummed, to the
//   receiving AI's own one-message limit (aiStageStartMaxBytes), in the background (the window never waits on it);
// - a Studio job's prepared project is adopted: the run's folder, carry checks and seed use the bridge's project
//   folder, and the request the run keeps is the bridge's original_request;
// - the exact outgoing text is verified twice: by the bridge (stage_start_verify on the text, its UTF-8 bytes and
//   SHA-256), then at the transport itself (aiVerbatimTake: the very string written must hash the same). A failed
//   verification starts nothing and says so in the chat;
// - the message goes out word for word, with no context line: Claude Code's stdin (stream-json), Codex's app-server
//   (turn/start over stdin), never a command line (Windows caps one at 32,767 characters);
// - a refused start (too big for the AI, an input missing, the bridge slow or failing) starts the run with its own
//   request in one conversation, as before, with the reason in the chat.
// Later stages (T294's next_stage) carry the same startup checksums; their send is checked the same way at the
// transport.
//
// The switch, on by default (T365): LETITEDIT_COMPLETE_STAGE_START (1 or 0) wins, else settings.json
// new_video_complete_stage_start (false turns it off); a lean
// run (T294's switch) always starts complete. Off, New video sends its request exactly as before.

static int aiChatDispatch(AiChat *c, MainWindow *window, const QString &message, const QString &summary, bool spoken,
                          bool autonomousNewVideo);

static bool aiCompleteStageStartOn()
{
    const QString forced = qEnvironmentVariable("LETITEDIT_COMPLETE_STAGE_START").trimmed().toLower();
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
    return QJsonDocument::fromJson(data).object().value(QStringLiteral("new_video_complete_stage_start")).toBool(true);
}

// The most one first message may carry on the transport this run's AI receives it by, in UTF-8 bytes; 0 when it isn't
// measured (the run then starts as before). Measured on this PC, 20 Nov 2026 (tests/t300/REPORT.md): Claude Code's
// stdin carried a 6 MB message whole, and Claude Code itself refuses one past the model's context (Opus 5.5: 1,000,000
// tokens); Codex's app-server refuses a turn past 1,048,576 characters (input_too_large) and GPT-6.1-Sol's context is
// 475,000 tokens. A 378,130-byte start arrived whole on both (about 197k and 123k input tokens). 512,000 bytes, about
// 150k tokens of message, sits well inside each and leaves the stage its room to work.
static const qint64 kClaudeStreamJsonStartBytes = 512000; // Claude Code, stream-json on stdin
static const qint64 kCodexAppServerStartBytes = 512000;   // Codex app-server, turn/start on stdin

static qint64 aiStageStartMaxBytes(AiChat *c)
{
    // QA: LETITEDIT_STAGE_START_MAX_BYTES sets the limit (a journey proves a too-big start keeps the run going)
    const qint64 forced = qEnvironmentVariable("LETITEDIT_STAGE_START_MAX_BYTES").toLongLong();
    if (forced > 0)
        return forced;
    if (aiTerminalMode())
        return 0; // the AI's own screen takes the message as a paste: not measured, so the run starts as before
    return c->carryEngine == QLatin1String("codex") ? kCodexAppServerStartBytes : kClaudeStreamJsonStartBytes;
}

// The next send goes out word for word; the transport takes it only if its UTF-8 bytes are the startup's.
static void aiVerbatimExpect(AiChat *c, const QJsonObject &startup, const QString &detail = QString())
{
    c->verbatimBytes = qint64(startup.value(QStringLiteral("bytes")).toDouble(-1));
    c->verbatimSha = startup.value(QStringLiteral("sha256")).toString();
    c->verbatimDetail = detail;
}

static void aiVerbatimClear(AiChat *c)
{
    c->verbatimBytes = -1;
    c->verbatimSha.clear();
    c->verbatimDetail.clear();
}

// At the transport: 0 = an ordinary send (the context line goes first), 1 = word for word and verified (content is the
// exact text to write), -1 = it doesn't match its checksums: send nothing.
static int aiVerbatimTake(AiChat *c, const QString &message, QString *content)
{
    if (c->verbatimBytes < 0)
        return 0;
    const QByteArray bytes = message.toUtf8();
    const bool ok = bytes.size() == c->verbatimBytes && aiLeanSha256(bytes) == c->verbatimSha
                    && message.endsWith(QStringLiteral("\n--- END COMPLETE STAGE START ---\n"));
    if (ok) {
        *content = message;
        return 1;
    }
    aiChatAdd(c, QStringLiteral("error"),
              QStringLiteral("letitedit did not start the AI: the stage's first message was not exactly what was "
                             "prepared (%1 bytes, expected %2).").arg(bytes.size()).arg(c->verbatimBytes));
    aiVerbatimClear(c);
    return -1;
}

static bool aiStageStartWanted(AiChat *c, const QString &message)
{
    return c->autonomousNewVideo && c->stageSessions && c->newVideoMakes && !c->liveReviewHold && !c->busy
           && !c->carrySending && (c->leanStages || aiCompleteStageStartOn())
           && message.contains(QStringLiteral("\nSave video in: "));
}

// The run starts with its own request, as before: the reason is kept and said in the chat.
static int aiStageStartRefused(AiChat *c, MainWindow *window, const QString &message, const QString &summary,
                               bool spoken, const QString &reason)
{
    c->stageStart = QJsonObject{{"state", QStringLiteral("refused")}, {"reason", reason},
                                {"max_bytes", double(aiStageStartMaxBytes(c))}};
    aiChatSaveCurrent(c);
    const int sent = aiChatDispatch(c, window, message, summary, spoken, true);
    if (sent)
        aiChatAdd(c, QStringLiteral("note"),
                  QStringLiteral("letitedit started this video with its request alone: the first stage's skills could "
                                 "not be attached in full (%1). The AI reads them itself.").arg(reason));
    return sent;
}

// The first stage's message: built by the bridge in the background; then verified and sent word for word.
static int aiStageStartBegin(AiChat *c, MainWindow *window, const QString &message, const QString &summary, bool spoken)
{
    const qint64 limit = aiStageStartMaxBytes(c);
    if (limit <= 0)
        return aiStageStartRefused(c, window, message, summary, spoken,
                                   QStringLiteral("the AI's own screen takes it as a paste, whose limit isn't measured"));
    c->stageStartPending = true;
    const int token = ++c->stageStartToken;
    const QString chat = c->chatId;
    c->stageStart = QJsonObject{{"state", QStringLiteral("preparing")}, {"max_bytes", double(limit)}};
    c->status->setText(QStringLiteral("letitedit is attaching the first stage's skills and inputs..."));
    QJsonObject input{{"action", "start"}, {"folder", c->autonomousWriteDir}, {"request", message},
                      {"ai", aiLeanAi(c)}, {"max_bytes", double(limit)}};
    const QString open = window->fileName();
    if (!open.isEmpty())
        input["project"] = open;
    const int id = c->nextRequest; // the id this request takes when it goes out
    const auto live = [c, token, chat]() { return c->stageStartPending && c->stageStartToken == token && c->chatId == chat; };
    aiLeanPython(c, QStringLiteral("bridge/new_video_first_stage.py"), input, 90000,
                 [c, window, message, summary, spoken, live, id](const QJsonObject &r) {
        if (!live())
            return;
        if (r.value(QStringLiteral("decision")).toString() != QLatin1String("stage_ready")
            || r.value(QStringLiteral("request")).toString().isEmpty()) {
            c->stageStartPending = false;
            c->refusal.clear(); // from here only the send's own reason (not a message refused while preparing)
            if (!aiStageStartRefused(c, window, message, summary, spoken,
                                     r.value(QStringLiteral("reason")).toString(
                                         QStringLiteral("letitedit could not prepare it")))) {
                c->status->setText(QStringLiteral("Your video did not start."));
                aiChatSaveCurrent(c);
                aiChatStartRefused(c, id, message, summary, c->refusal);
            }
            return;
        }
        const QString text = r.value(QStringLiteral("request")).toString();
        QJsonObject startup = r;
        startup.remove(QStringLiteral("request"));
        startup.remove(QStringLiteral("decision"));
        // a Studio job's prepared project: the run's folder, carry checks and seed are the bridge's from here on
        const QString folder = r.value(QStringLiteral("folder")).toString();
        if (!folder.isEmpty()
            && QDir::cleanPath(QDir::fromNativeSeparators(folder)).compare(
                   QDir::cleanPath(QDir::fromNativeSeparators(c->autonomousWriteDir)), Qt::CaseInsensitive) != 0) {
            c->autonomousWriteDir = folder;
            window->setProperty("letitedit:newVideoFolder", folder);
        }
        const QString original = r.value(QStringLiteral("original_request")).toString();
        if (!original.isEmpty())
            c->newVideoRequest = original;
        aiChatSaveCurrent(c);
        aiLeanPython(c, QStringLiteral("bridge/new_video_first_stage.py"),
                     QJsonObject{{"action", "verify"}, {"startup", startup}, {"delivered", text}}, 90000,
                     [c, window, text, startup, message, summary, spoken, original, live, id](const QJsonObject &v) {
            if (!live())
                return;
            c->stageStartPending = false;
            // what the chat would show as this request, for Try again if it is refused below
            const QString asked = original.isEmpty() ? message : original;
            QJsonObject state{{"stage", startup.value(QStringLiteral("stage"))},
                              {"bytes", startup.value(QStringLiteral("bytes"))},
                              {"sha256", startup.value(QStringLiteral("sha256"))},
                              {"project", startup.value(QStringLiteral("project"))},
                              {"folder", startup.value(QStringLiteral("folder"))},
                              {"skills", startup.value(QStringLiteral("skills"))},
                              {"max_bytes", c->stageStart.value(QStringLiteral("max_bytes"))}};
            if (v.value(QStringLiteral("decision")).toString() != QLatin1String("stage_verified")) {
                state["state"] = QStringLiteral("not_verified");
                state["reason"] = v.value(QStringLiteral("reason")).toString(QStringLiteral("no answer from the check"));
                c->stageStart = state;
                c->carryAllowed = false;
                const QString why = QStringLiteral(
                    "letitedit did not start your video: it could not confirm the first stage's message would reach the "
                    "AI whole (%1). Nothing was sent. Try again from Home.")
                    .arg(state.value(QStringLiteral("reason")).toString());
                aiChatAdd(c, QStringLiteral("error"), why);
                c->status->setText(QStringLiteral("Your video did not start."));
                aiChatSaveCurrent(c);
                aiChatStartRefused(c, id, asked, summary, why);
                return;
            }
            state["state"] = QStringLiteral("verified");
            c->stageStart = state;
            aiChatSaveCurrent(c);
            aiVerbatimExpect(c, startup, original.isEmpty() ? QString() : original);
            c->refusal.clear();
            if (!aiChatDispatch(c, window, text, summary, spoken, true)) {
                c->stageStart["state"] = QStringLiteral("not_sent");
                c->status->setText(QStringLiteral("Your video did not start."));
                aiChatSaveCurrent(c);
                aiChatStartRefused(c, id, asked, summary, c->refusal);
            }
        });
    });
    return id;
}

#endif // AINEWVIDEOSTART_H
