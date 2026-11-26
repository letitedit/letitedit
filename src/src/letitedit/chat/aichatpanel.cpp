/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * "Chat with Claude/Codex": a dock where the user talks to an AI while editing. It runs the user's own Claude Code (or Codex CLI, panel.json "engine": "codex")
 * (headless, streaming JSON) with the person's tools; letitedit edits land in this window as Undo steps.
 * Every message carries what the user is looking at (project, unsaved changes, playhead, selected clips).
 * Settings: <root>/chat/panel.json (engine, claude, model, effort, codex, codex_model, codex_reasoning, python,
 * mcp_server), or the file LETITEDIT_CHAT_SETTINGS names (a test window's own copy); the panel's top row chooses the
 * AI, its model and its effort. Prompt: <root>/chat/panel-prompt.md. <root> = aiRoot() (airoot.h): the install
 * folder, C:/LetItEdit on the build PC.
 */

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/chat/aichatsettings.h"
#include "letitedit/chat/newvideotools.h"
#include "letitedit/chat/aicodexprobe.h"
#include "letitedit/chat/stagesessionsline.h"

static void aiVoiceTurnDone(AiChat *c);
static void aiChatShowActiveModel(AiChat *c);
static int aiChatBeginRequest(AiChat *c, const QString &message, const QString &summary, bool spoken);
static void aiChatAdd(AiChat *c, const QString &kind, const QString &text);
static void aiChatSetBusy(AiChat *c, bool busy, const QString &status = QString());
static void aiChatEndRequest(AiChat *c, const QString &outcome, const QString &error = QString());
static void aiTerminalStop(AiChat *c);
static void aiChatRevealDock(AiChat *c);
static void aiChatStopClaude(AiChat *c);
static void aiChatSyncMode(AiChat *c);
static bool aiChatStart(AiChat *c);
static void aiChatRefreshChoices(AiChat *c);
static QJsonObject aiLeanRecord(AiChat *c);
static void aiLeanLoad(AiChat *c, const QJsonObject &lean);

AiChat *&aiChatInstance()
{
    static AiChat *chat = nullptr;
    return chat;
}

static void aiChatDiscoverCodexModels(AiChat *chat)
{
    const QJsonObject settings = aiChatSettings();
    if (aiChatEngineId(settings) != QLatin1String("codex"))
        return;
    const QString program = settings.value("codex").toString();
    const QString identity = program + QLatin1Char('|') + aiCodexHome();
    const qint64 now = QDateTime::currentSecsSinceEpoch();
    if (chat->dock->property("codexModelsPending").toBool()
        || (chat->dock->property("codexModelsIdentity").toString() == identity
            && now - chat->dock->property("codexModelsAt").toLongLong() < 60)
        || program.isEmpty() || !QFileInfo::exists(program))
        return;
    chat->dock->setProperty("codexModelsPending", true);
    chat->dock->setProperty("codexModelsIdentity", identity);
    chat->dock->setProperty("codexModelsAt", now);
    auto *probe = aiCodexModelsProbe(program, settings.value("work_dir").toString(), chat->dock);
    QObject::connect(probe, &QProcess::started, probe, [probe]() {
        probe->write("{\"id\":1,\"method\":\"initialize\",\"params\":{\"clientInfo\":{\"name\":\"letitedit-models\",\"version\":\"1.0\"},\"capabilities\":{\"experimentalApi\":true}}}\n");
    });
    QObject::connect(probe, &QProcess::readyReadStandardOutput, probe, [chat, probe, home = aiCodexHome(), buffer = QByteArray(), models = QJsonArray()]() mutable {
        buffer += probe->readAllStandardOutput();
        if (buffer.size() > 1024 * 1024) {
            probe->kill();
            return;
        }
        int newline;
        while ((newline = buffer.indexOf('\n')) >= 0) {
            const QJsonObject message = QJsonDocument::fromJson(buffer.left(newline)).object();
            buffer.remove(0, newline + 1);
            if (!message.contains("id"))
                continue;
            if (message.contains("error")) {
                probe->kill();
                return;
            }
            if (message.value("id").toInt() == 1) {
                probe->write("{\"method\":\"initialized\"}\n{\"id\":2,\"method\":\"model/list\",\"params\":{\"limit\":100}}\n");
                continue;
            }
            const QJsonObject result = message.value("result").toObject();
            if (!result.value("data").isArray()) {
                probe->kill();
                return;
            }
            for (const auto &model : result.value("data").toArray())
                models.append(model);
            const QString cursor = result.value("nextCursor").toString();
            if (!cursor.isEmpty()) {
                const QJsonObject request{{"id", 2}, {"method", QStringLiteral("model/list")},
                                          {"params", QJsonObject{{"limit", 100}, {"cursor", cursor}}}};
                probe->write(QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n');
                continue;
            }
            const QJsonObject snapshot{{"home", QDir(home).absolutePath()},
                                        {"fetched_at", QDateTime::currentMSecsSinceEpoch() / 1000.0}, {"data", models}};
            QDir().mkpath(QFileInfo(aiCodexModelsPath()).absolutePath());
            QSaveFile output(aiCodexModelsPath());
            if (output.open(QIODevice::WriteOnly)) {
                output.write(QJsonDocument(snapshot).toJson(QJsonDocument::Compact));
                if (output.commit())
                    QTimer::singleShot(0, chat->dock, [chat]() { aiChatRefreshChoices(chat); });
            }
            probe->kill();
            return;
        }
    });
    QObject::connect(probe, &QProcess::readyReadStandardError, probe, [probe]() { probe->readAllStandardError(); });
    QObject::connect(probe, &QProcess::errorOccurred, chat->dock, [chat, probe](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            chat->dock->setProperty("codexModelsPending", false);
            probe->deleteLater();
        }
    });
    QObject::connect(probe, &QProcess::finished, chat->dock, [chat, probe]() {
        chat->dock->setProperty("codexModelsPending", false);
        probe->deleteLater();
    });
    QTimer::singleShot(8000, probe, [probe]() { probe->kill(); });
    probe->start();
}

static QJsonObject aiRunSettings(AiChat *chat)
{
    QJsonObject settings = aiChatSettings();
    if (chat->speedNormal)
        settings[aiSpeedKey(aiChatEngineId(settings))] = QStringLiteral("normal");
    return settings;
}

static bool aiSpeedRefused(const QString &text)
{
    return text.contains(QRegularExpression(QStringLiteral("fast.?mode|service[ _-]?tier|priority.?tier|fast (?:speed|mode)|ultrafast"),
                                            QRegularExpression::CaseInsensitiveOption))
        && text.contains(QRegularExpression(QStringLiteral("not (?:available|supported|allowed|enabled|eligible)|unavailable|unsupported|ineligible|invalid|denied|disabled|requires|not included|extra usage|credits|overloaded|capacity"),
                                             QRegularExpression::CaseInsensitiveOption));
}

static bool aiSpeedFallback(AiChat *chat, const QString &error)
{
    if (chat->procSpeed.isEmpty() || chat->procSpeed == QLatin1String("normal") || chat->speedRetried
        || chat->speedProduced || chat->retryContent.isEmpty() || !aiSpeedRefused(error))
        return false;
    chat->speedRetried = chat->speedNormal = true;
    chat->procSpeed = QStringLiteral("normal");
    aiChatAdd(chat, QStringLiteral("note"), QStringLiteral("%1 could not use the selected speed; continuing at Normal. Your saved choice is unchanged.")
                                                .arg(ConnectAi::programName(chat->engine)));
    aiChatRefreshChoices(chat);
    return true;
}

static QByteArray aiClaudeEnvelope(const QString &content)
{
    return QJsonDocument(QJsonObject{{"type", "user"},
                                    {"message", QJsonObject{{"role", "user"}, {"content", QJsonArray{
                                        QJsonObject{{"type", "text"}, {"text", content}}}}}}}).toJson(QJsonDocument::Compact) + '\n';
}

static bool aiClaudeRetrySpeed(AiChat *chat, const QString &error)
{
    if (!aiSpeedFallback(chat, error))
        return false;
    if (chat->proc) {
        QProcess *previous = chat->proc;
        QObject::disconnect(previous, nullptr, nullptr, nullptr);
        if (previous->state() == QProcess::NotRunning)
            previous->deleteLater();
        else {
            QObject::connect(previous, &QProcess::finished, previous, &QObject::deleteLater);
            previous->kill();
        }
        chat->proc = nullptr;
        chat->buffer.clear();
    }
    const int request = chat->request;
    const QString chatId = chat->chatId;
    QTimer::singleShot(0, chat->dock, [chat, request, chatId]() {
        if (chat->request != request || chat->chatId != chatId || !chat->busy)
            return;
        if (aiChatStart(chat)) {
            chat->proc->write(aiClaudeEnvelope(chat->retryContent));
            aiChatSetBusy(chat, true);
        } else {
            aiChatEndRequest(chat, QStringLiteral("failed"), QStringLiteral("The AI could not restart at Normal speed."));
            aiChatSetBusy(chat, false);
        }
    });
    return true;
}

QJsonObject aiClaudeInstructionSettings(const QJsonObject &settings)
{
    const QString configuredHome = qEnvironmentVariable("CLAUDE_CONFIG_DIR");
    const QString home = QDir::fromNativeSeparators(QDir(configuredHome.isEmpty()
                                                           ? QDir::home().filePath(QStringLiteral(".claude"))
                                                           : configuredHome).absolutePath());
    return {{"claudeMdExcludes", QJsonArray{home + QStringLiteral("/**")}}, {"autoMemoryEnabled", false},
            {"fastMode", aiSpeedValue(settings, QStringLiteral("claude")) == QLatin1String("fast")}};
}

QStringList aiClaudeInstructionArgs(const QJsonObject &settings)
{
    return {QStringLiteral("--settings"),
            QString::fromUtf8(QJsonDocument(aiClaudeInstructionSettings(settings)).toJson(QJsonDocument::Compact))};
}

// T221: what the chat never lets Claude do, whatever the automatic check would allow: delete files from a shell,
// push with git, or write a footage or sound file with its file tools (a person's originals are media files). The
// automatic safety check (auto mode) refuses other risky actions; a refusal goes back to the AI, never to a box.
QJsonArray aiClaudeChatDenyRules()
{
    QJsonArray deny;
    for (const char *command : {"rm", "rmdir", "del", "rd", "erase", "shred"})
        deny.append(QStringLiteral("Bash(%1 *)").arg(QLatin1String(command)));
    deny.append(QStringLiteral("Bash(git push*)"));
    for (const char *command : {"Remove-Item", "rm", "del", "rmdir", "ri", "rd", "erase"})
        deny.append(QStringLiteral("PowerShell(%1 *)").arg(QLatin1String(command)));
    deny.append(QStringLiteral("PowerShell(git push*)"));
    static const char *media[] = {"mov", "mp4", "m4v", "mkv", "avi", "mts", "m2ts", "mxf", "wav", "mp3", "m4a",
                                  "aac", "flac", "heic", "dng", "cr2", "arw", "nef", "braw", "r3d", "insv", "lrv"};
    for (const char *tool : {"Edit", "Write", "NotebookEdit"})
        for (const char *ext : media)
            deny.append(QStringLiteral("%1(//**/*.%2)").arg(QLatin1String(tool), QLatin1String(ext)));
    return deny;
}

// The chat's settings for Claude: the instruction settings above plus aiClaudeChatDenyRules.
QStringList aiClaudeChatSettingsArgs(const QJsonObject &selected)
{
    QJsonObject settings = aiClaudeInstructionSettings(selected);
    settings[QStringLiteral("permissions")] = QJsonObject{{QStringLiteral("deny"), aiClaudeChatDenyRules()}};
    return {QStringLiteral("--settings"), QString::fromUtf8(QJsonDocument(settings).toJson(QJsonDocument::Compact))};
}

// --model / --effort for Claude Code from panel.json "model" and "effort"; nothing for the person's own setting.
// A saved "auto" is the planning role's model (aiResolvedChoice): a conversation, a review and the window's New video
// all make the calls the planning model makes.
QStringList aiClaudeChoiceArgs(const QJsonObject &settings)
{
    const QJsonObject s = aiResolvedChoice(settings);
    QStringList args;
    const QString model = s.value(QStringLiteral("model")).toString().trimmed();
    const QString effort = s.value(QStringLiteral("effort")).toString().trimmed();
    if (!model.isEmpty())
        args << QStringLiteral("--model") << model;
    if (!effort.isEmpty())
        args << QStringLiteral("--effort") << effort;
    return args;
}

// Model and effort for Codex. The nearest effort the model takes is used when it lacks the chosen effort.
QStringList aiCodexChoiceArgs(const QJsonObject &settings, QString *model)
{
    const QJsonObject s = aiResolvedChoice(settings);
    QString m = s.value(QStringLiteral("codex_model")).toString().trimmed();
    QString effort = s.value(QStringLiteral("codex_reasoning")).toString().trimmed();
    const QList<AiChatChoice> takes = aiCodexEffortChoicesFor(m);
    if (!aiChatHasChoice(takes, effort) && !takes.isEmpty()) {
        effort = aiNearestEffort(takes, effort);
    }
    QStringList args;
    if (!m.isEmpty())
        args << QStringLiteral("-m") << m;
    if (!effort.isEmpty())
        args << QStringLiteral("-c") << QStringLiteral("model_reasoning_effort=") + aiTomlString(effort);
    args << QStringLiteral("-c") << QStringLiteral("service_tier=") + aiTomlString(aiCodexSpeedTier(s));
    args << aiCodexSpeedConfigArgs();
    if (model)
        *model = m;
    return args;
}

static QString aiChatClock(double seconds)
{
    const int m = int(seconds / 60);
    return QStringLiteral("%1:%2").arg(m).arg(seconds - m * 60, 4, 'f', 1, QLatin1Char('0'));
}

// What the user is looking at, sent with every message.
static QString aiChatContext(MainWindow *window)
{
    QStringList parts;
    const QString file = window->fileName();
    parts << (file.isEmpty() ? QStringLiteral("project: (not saved yet)")
                             : QStringLiteral("project: %1%2").arg(QDir::toNativeSeparators(file),
                                   window->isWindowModified() ? QStringLiteral(" (unsaved changes)") : QString()));
    auto *timeline = window->timelineDock();
    const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
    if (timeline) {
        parts << QStringLiteral("playhead %1").arg(aiChatClock(timeline->position() / fps));
        QStringList sel;
        auto *model = timeline->model();
        for (const QPoint &p : timeline->selection()) {
            const QString track = model->index(p.y()).data(MultitrackModel::NameRole).toString();
            QString id, name;
            if (auto info = model->getClipInfo(p.y(), p.x())) {
                if (info->producer && info->producer->is_valid()) {
                    Mlt::Producer parent(info->producer->parent());
                    id = QString::fromUtf8(parent.get("letitedit_ai:id"));
                    name = QString::fromUtf8(parent.get("shotcut:caption"));
                }
                if (name.isEmpty() && info->resource)
                    name = QFileInfo(QString::fromUtf8(info->resource)).fileName();
                sel << QStringLiteral("%1 clip %2%3 at %4%5")
                           .arg(track)
                           .arg(p.x() + 1)
                           .arg(id.isEmpty() ? QString() : QStringLiteral(" = ") + id)
                           .arg(aiChatClock(info->start / fps))
                           .arg(name.isEmpty() ? QString() : QStringLiteral(" (") + name + QStringLiteral(")"));
            }
        }
        if (!sel.isEmpty())
            parts << QStringLiteral("selected: ") + sel.join(QStringLiteral("; "));
    }
    // the style the person chose for this video (My style's "Use on This Video", or the AI's {op: style})
    if (auto *tractor = window->multitrack()) {
        const QString style = MyStyle::projectStyle(window);
        if (!style.isEmpty())
            parts << QStringLiteral("look: %1").arg(style);
    }
    QString context = QStringLiteral("[letitedit] ") + parts.join(QStringLiteral(" | "));
    if (AiChat *c = aiChatInstance(); c && !c->typedTarget.isEmpty())
        context += QStringLiteral("\n[letitedit] ") + c->typedTarget;
    return context;
}

static QString aiChatProjectKey(MainWindow *window)
{
    return window && !window->fileName().isEmpty()
               ? QFileInfo(window->fileName()).absoluteFilePath().toLower()
               : QString();
}

static void aiChatSaveCurrent(AiChat *c)
{
    if (c->chatId.isEmpty())
        return;
    QDir().mkpath(QFileInfo(aiChatHistoryPath()).absolutePath());
    QLockFile lock(aiChatHistoryPath() + QStringLiteral(".lock"));
    if (!lock.tryLock(500))
        return;
    // Other open editor windows may have added chats since this window loaded its list.
    QFile existing(aiChatHistoryPath());
    if (existing.open(QIODevice::ReadOnly))
        for (const QJsonValue &v : QJsonDocument::fromJson(existing.readAll()).object().value("chats").toArray()) {
            const QJsonObject disk = v.toObject();
            bool found = false;
            for (int i = 0; i < c->history.size(); ++i)
                if (c->history[i].toObject().value("id") == disk.value("id")) {
                    found = true;
                    if (disk.value("id").toString() != c->chatId
                        && disk.value("updated").toString() > c->history[i].toObject().value("updated").toString())
                        c->history[i] = disk;
                    break;
                }
            if (!found)
                c->history.append(disk);
        }
    existing.close(); // Windows cannot replace an open history file when QSaveFile commits.
    QJsonArray messages;
    QString title;
    for (const AiChatBlock &b : c->blocks) {
        messages.append(QJsonObject{{"kind", b.kind}, {"text", b.text}, {"detail", b.detail},
                                    {"repeats", b.repeats}});
        if (title.isEmpty() && b.kind == QLatin1String("user"))
            title = b.text.left(70);
    }
    if (title.isEmpty())
        title = QStringLiteral("New chat");
    QJsonObject record{{"id", c->chatId}, {"project", c->projectKey}, {"engine", c->engine},
                       {"terminal_work", c->terminalWork},
                       {"session", c->sessionId}, {"started", c->sessionStarted},
                       {"title", title}, {"updated", QDateTime::currentDateTimeUtc().toString(Qt::ISODateWithMs)},
                       {"allowed_actions", QJsonArray::fromStringList(c->claudeChatAllowed.values())},
                       {"messages", messages}};
    if (c->newVideoChat) {
        // New video's (or Learn's) own chat: reopened later, its turns still run unattended, with the same folder
        record["new_video"] = true;
        record["new_video_folder"] = c->autonomousWriteDir;
        record["new_video_makes"] = c->newVideoMakes;
        record["stage_sessions"] = c->stageSessions;
        record["new_video_request"] = c->newVideoRequest;
        record["run_sessions"] = QJsonArray::fromStringList(c->runSessions);
        if (c->leanStages) // T294 (chat/ainewvideolean.h): only a lean run's record has it
            record["lean_stage_handoffs"] = aiLeanRecord(c);
    }
    bool replaced = false;
    for (int i = 0; i < c->history.size(); ++i) {
        if (c->history[i].toObject().value("id").toString() == c->chatId) {
            c->history[i] = record;
            replaced = true;
            break;
        }
    }
    if (!replaced)
        c->history.append(record);
    QSaveFile f(aiChatHistoryPath());
    if (f.open(QIODevice::WriteOnly)) {
        f.write(QJsonDocument(QJsonObject{{"current", c->chatId}, {"chats", c->history}}).toJson());
        f.commit();
    }
}

// A usage-limit wait (T193) ends: Stop, a new chat, another chat loaded, or the carry-on it waited for.
static void aiChatLimitClear(AiChat *c)
{
    c->limitCarryAt = 0;
    c->limitWords.clear();
    if (c->limitTimer)
        c->limitTimer->stop();
}

static void aiChatLoadRecord(AiChat *c, const QJsonObject &record)
{
    c->carryAllowed = c->carryPending = c->carryStopped = c->carryHumanInput = false;
    if (c->carryBar)
        c->carryBar->hide();
    c->chatId = record.value("id").toString();
    c->projectKey = record.value("project").toString();
    c->terminalWork = record.value("terminal_work").toString();
    c->engine = record.value("engine").toString();
    c->sessionId = record.value("session").toString();
    c->sessionStarted = record.value("started").toBool();
    c->newVideoChat = record.value("new_video").toBool();
    c->newVideoMakes = c->newVideoChat && record.value("new_video_makes").toBool(true);
    c->autonomousWriteDir = c->newVideoChat ? record.value("new_video_folder").toString() : QString();
    c->stageSessions = c->newVideoChat && record.value("stage_sessions").toBool();
    c->newVideoRequest = c->newVideoChat ? record.value("new_video_request").toString() : QString();
    c->runSessions.clear();
    for (const QJsonValue &v : record.value("run_sessions").toArray())
        c->runSessions << v.toString();
    aiLeanLoad(c, c->newVideoChat ? record.value("lean_stage_handoffs").toObject() : QJsonObject());
    c->stageStartPending = false; // T300: a first stage being prepared belongs to the chat it was prepared for
    c->stageStart = QJsonObject();
    c->verbatimBytes = -1;
    aiChatLimitClear(c);
    c->blocks.clear();
    for (const QJsonValue &v : record.value("messages").toArray()) {
        const QJsonObject b = v.toObject();
        AiChatBlock block{b.value("kind").toString(), b.value("text").toString(), b.value("detail").toString()};
        block.repeats = qMax(1, b.value("repeats").toInt(1));
        c->blocks.append(block);
    }
    c->live = -1;
    c->followBottom = true;
    c->queued.clear();
    c->codexSteers.clear();
    c->codexRpc.clear();
    c->codexReady = false;
    c->codexTurnId.clear();
    c->codexPending.clear();
    c->claudeChatAllowed.clear();
    for (const QJsonValue &action : record.value("allowed_actions").toArray())
        if (action.isString())
            c->claudeChatAllowed.insert(action.toString());
    c->lastPermission.clear();
}

static void aiChatNewRecord(AiChat *c, const QString &project)
{
    c->carryAllowed = c->carryPending = c->carryStopped = c->carryHumanInput = false;
    if (c->carryBar)
        c->carryBar->hide();
    c->chatId = QUuid::createUuid().toString(QUuid::WithoutBraces);
    c->projectKey = project;
    c->terminalWork.clear();
    c->engine = aiChatEngineId(aiChatSettings());
    c->sessionId = QUuid::createUuid().toString(QUuid::WithoutBraces);
    c->sessionStarted = false;
    c->newVideoChat = false; // a chat the person starts keeps their own rules
    c->newVideoMakes = false;
    c->stageSessions = false;
    c->newVideoRequest.clear();
    c->runSessions.clear();
    aiLeanLoad(c, QJsonObject());
    c->stageStartPending = false; // T300
    c->stageStart = QJsonObject();
    c->verbatimBytes = -1;
    c->autonomousWriteDir.clear();
    aiChatLimitClear(c);
    c->blocks.clear();
    c->live = -1;
    c->followBottom = true;
    c->queued.clear();
    c->codexSteers.clear();
    c->codexRpc.clear();
    c->codexReady = false;
    c->codexTurnId.clear();
    c->codexPending.clear();
    c->claudeChatAllowed.clear();
    c->lastPermission.clear();
    aiChatSaveCurrent(c);
}

static void aiChatLoadHistory(AiChat *c)
{
    QFile f(aiChatHistoryPath());
    const QJsonObject data = f.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(f.readAll()).object() : QJsonObject();
    c->history = data.value("chats").toArray();
    const QString project = aiChatProjectKey(c->window);
    QJsonObject selected;
    for (const QJsonValue &v : c->history) {
        const QJsonObject record = v.toObject();
        if (record.value("project").toString() != project)
            continue;
        if (record.value("id").toString() == data.value("current").toString()) {
            selected = record;
            break;
        }
        if (selected.isEmpty() || record.value("updated").toString() > selected.value("updated").toString())
            selected = record;
    }
    if (selected.isEmpty())
        aiChatNewRecord(c, project);
    else // reading a chat never changes the person's saved AI (T97); a chat on another AI starts anew at the next message
        aiChatLoadRecord(c, selected);
}

// Which stage of making a video a tool belongs to, in words a person follows. Empty for the engine's own steps
// and housekeeping (loading tools, reading a guide, looking at open windows): those keep the stage it is in.
static QString aiChatStage(const QString &tool)
{
    if (!tool.contains(QLatin1String("letitedit_")))
        return QString();
    const QString t = QString(tool).remove(QStringLiteral("mcp__letitedit__")).remove(QStringLiteral("letitedit_"));
    static const QStringList housekeeping{"guide", "instances", "editor", "hardware", "platforms", "status", "jobs",
                                          "show", "command_help"};
    static const QStringList footage{"footage", "search", "stills", "look", "log_frames", "log_write", "transcript",
                                     "words", "speakers", "places", "ask_frames", "segments", "hear", "find_takes",
                                     "measure", "overview", "archive", "sync", "annotate", "find_ranges"};
    static const QStringList story{"journal", "note", "bin", "hooks", "learn"};
    static const QStringList sound{"fit_music", "music_make", "soundtrack", "separate", "voice", "check_audio",
                                   "library", "dub_lines", "dub", "dub_voices"};
    static const QStringList checking{"export", "export_job", "export_edit", "review_bundle", "quality_gate",
                                      "critic", "check_frames", "check_range", "qc", "timing"};
    static const QStringList graphics{"motion", "assets", "graphic", "fonts", "effects", "vfx_effects", "style"};
    if (housekeeping.contains(t))
        return QString();
    if (t == QLatin1String("timeline_read"))
        return QStringLiteral("Looking at the edit");
    if (footage.contains(t))
        return QStringLiteral("Reviewing the footage");
    if (story.contains(t))
        return QStringLiteral("Planning the story");
    if (sound.contains(t))
        return QStringLiteral("Working on the sound");
    if (checking.contains(t))
        return QStringLiteral("Checking the video");
    if (graphics.contains(t))
        return QStringLiteral("Adding graphics and effects");
    return QStringLiteral("Editing"); // timeline edits, reframe and the rest
}

// "Editing · Tighten the talk · 3:12": the stage, what it is doing now, and how long the request has taken.
static QString aiChatProgress(AiChat *c, const QString &tool, const QString &phrase)
{
    const QString stage = aiChatStage(tool);
    // Notes, markers and the journal are written all through an edit: once it is past planning they don't send the
    // line back to "Planning the story" (a run fixing its review read as if it had started over).
    const bool bookkeeping = stage == QLatin1String("Planning the story") && !c->stage.isEmpty()
                             && c->stage != QLatin1String("Getting ready")
                             && c->stage != QLatin1String("Reviewing the footage");
    if (!stage.isEmpty() && !bookkeeping)
        c->stage = stage;
    QString line = (c->stage.isEmpty() ? QStringLiteral("Getting ready") : c->stage) + QStringLiteral(" \u00b7 ")
                   + phrase;
    if (c->turnClock.isValid()) {
        const qint64 s = c->turnClock.elapsed() / 1000;
        line += QStringLiteral(" \u00b7 %1:%2").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0'));
    }
    return line;
}

static QString aiChatToolPhrase(const QString &tool, const QJsonObject &input)
{
    const QString t = QString(tool).remove(QStringLiteral("mcp__letitedit__"));
    if (t == QStringLiteral("letitedit_timeline_apply")) {
        const QString label = input.value("label").toString();
        return label.isEmpty() ? QStringLiteral("Editing the timeline") : label;
    }
    if (t == QStringLiteral("letitedit_image")) { // only 'make' draws anything
        const QString action = input.value("action").toString();
        if (action == QStringLiteral("show"))
            return QStringLiteral("Showing a picture");
        if (action == QStringLiteral("history"))
            return QStringLiteral("Looking at the pictures made");
        if (action == QStringLiteral("status"))
            return QStringLiteral("Checking who can draw");
        if (action == QStringLiteral("file"))
            return QStringLiteral("Saving a picture");
    }
    static const QMap<QString, QString> phrases{
        {"letitedit_timeline_read", "Reading the timeline"}, {"letitedit_timeline_undo", "Undoing"},
        {"letitedit_wait", "Waiting for a long step"},
        {"letitedit_footage", "Looking at footage"}, {"letitedit_words", "Listening to what's said"},
        {"letitedit_transcript", "Reading what's said"}, {"letitedit_note", "Taking a note"},
        {"letitedit_check_frames", "Checking frames"}, {"letitedit_check_range", "Watching a stretch"},
        {"letitedit_check_audio", "Checking the sound"}, {"letitedit_qc", "Running checks"},
        {"letitedit_quality_gate", "Running the quality checks"}, {"letitedit_review_bundle", "Reviewing the whole video"},
        {"letitedit_critic", "Getting a second opinion"}, {"letitedit_export", "Starting an export"},
        {"letitedit_export_job", "Checking the export"}, {"letitedit_export_edit", "Exporting the edit"},
        {"letitedit_fonts", "Looking at fonts"}, {"letitedit_looks", "Looking at Looks"},
        {"letitedit_graphic", "Designing a graphic"}, {"letitedit_effects", "Adding an effect"},
        {"letitedit_vfx_effects", "Adding a visual effect"}, {"letitedit_library", "Searching the music and sound library"},
        {"letitedit_guide", "Reading the guide"}, {"letitedit_project_new", "Making a project"},
        {"letitedit_show", "Opening the project"}, {"letitedit_instances", "Looking at open windows"},
        {"letitedit_editor", "Looking at the editor"}, {"letitedit_3d", "Making a 3D shot"},
        {"letitedit_archive", "Looking at earlier videos"}, {"letitedit_ask_frames", "Looking closely at frames"},
        {"letitedit_bin", "Sorting clips"}, {"letitedit_fit_music", "Fitting the music"},
        {"letitedit_fix", "Fixing a problem"}, {"letitedit_hardware", "Checking this computer"},
        {"letitedit_hear", "Listening"}, {"letitedit_import", "Building the edit"},
        {"letitedit_import_srt", "Adding captions"}, {"letitedit_jobs", "Checking background work"},
        {"letitedit_journal", "Reading the project notes"}, {"letitedit_log_frames", "Logging shots"},
        {"letitedit_log_write", "Writing the shot log"}, {"letitedit_look", "Looking at a shot"},
        {"letitedit_map", "Making a map"}, {"letitedit_measure", "Measuring"},
        {"letitedit_music_make", "Making music"}, {"letitedit_overview", "Getting an overview of the footage"},
        {"letitedit_places", "Finding places"}, {"letitedit_platforms", "Checking platform sizes"},
        {"letitedit_search", "Searching the footage"}, {"letitedit_segments", "Finding the parts of a clip"},
        {"letitedit_separate", "Separating the voice from the background"},
        {"letitedit_speakers", "Working out who is speaking"}, {"letitedit_status", "Checking progress"},
        {"letitedit_stills", "Looking at stills"}, {"letitedit_sync", "Lining up cameras"},
        {"letitedit_track", "Tracking a subject"}, {"letitedit_try", "Trying an edit"},
        {"letitedit_versions", "Making another version"}, {"letitedit_voice", "Making a voiceover"},
        {"letitedit_find_takes", "Comparing takes"}, {"letitedit_annotate", "Taking notes on the footage"},
        {"letitedit_match_shots", "Matching colors between shots"}, {"letitedit_soundtrack", "Building the soundtrack"},
        {"letitedit_caption_fit", "Placing the captions"}, {"letitedit_find_ranges", "Finding the moments"},
        {"letitedit_reframe", "Reframing for another shape"}, {"letitedit_timing", "Checking the timing"},
        {"letitedit_motion", "Making an animated title"}, {"letitedit_hooks", "Finding openings"},
        {"letitedit_assets", "Looking for stickers and sounds"}, {"letitedit_command_help", "Looking up how to do it"},
        {"letitedit_dub_lines", "Getting the lines to dub"}, {"letitedit_dub", "Dubbing the voice"},
        {"letitedit_dub_voices", "Choosing a voice"},
        {"letitedit_code_scene", "Drawing a scene"}, {"letitedit_image", "Making a picture"},
        {"letitedit_song", "Working with the song to cut to"}, {"letitedit_my_assets", "Looking at your own files"}, {"letitedit_object", "Lifting an object out of the shot"},
        {"letitedit_review_note", "Taking a review note"},
        // the engine's own steps
        {"ToolSearch", "Getting the tools ready"}, {"Skill", "Reading the editing guide"}, {"Read", "Reading a file"},
        {"Glob", "Looking through files"}, {"Grep", "Looking through files"}, {"Bash", "Running a step"},
        {"PowerShell", "Running a step"}, {"Write", "Writing notes"}, {"Edit", "Writing notes"},
        {"TodoWrite", "Planning the steps"}, {"WebSearch", "Looking something up online"},
        {"WebFetch", "Looking something up online"}, {"Agent", "Asking a helper"}, {"Task", "Asking a helper"},
        {"fileChange", "Writing files"}};
    if (phrases.contains(t))
        return phrases.value(t);
    if (!t.startsWith(QLatin1String("letitedit_")))
        return QStringLiteral("Working");
    QString words = t.mid(QStringLiteral("letitedit_").size()).replace(QLatin1Char('_'), QLatin1Char(' '));
    if (!words.isEmpty())
        words[0] = words[0].toUpper();
    return words;
}

static QString aiChatCommandPhrase(const QString &command)
{
    const QString lower = command.toLower();
    if (lower.contains(QLatin1String("get-content")) || lower.contains(QLatin1String("type "))
        || lower.contains(QLatin1String("cat ")))
        return QStringLiteral("Reading a file");
    if (lower.contains(QLatin1String("get-childitem")) || lower.contains(QLatin1String("rg "))
        || lower.contains(QLatin1String("dir ")))
        return QStringLiteral("Looking through files");
    return QStringLiteral("Running a step");
}

static void aiChatRender(AiChat *c)
{
    c->rendering = true;
    const int oldPosition = c->view->verticalScrollBar()->value();
    const bool atEnd = c->followBottom;
    QString html = QStringLiteral(
        "<style>p{margin:0 0 8px 0;} .u{color:#5b9cf0;font-weight:600;} .t{color:#8c8c8c;font-style:italic;}"
        ".e{color:#e05a5a;} .n{color:#8c8c8c;} .d{color:#8c8c8c;font-size:small;} a{color:#9ED6E2;}</style>");
    if (c->blocks.isEmpty())
        html += QStringLiteral("<h3>What can I do here?</h3><p>Ask your AI to edit the open video, explain a step, "
                               "or help with your files. It sees the playhead and selection, and video edits "
                               "land as Undo steps.</p><p>Try: ‘Tighten this opening’, ‘Find the best hook’, "
                               "or ‘What can you do with this video?’</p><p>Past chats keeps your earlier conversations, "
                               "and you can send a follow-up while the AI is working.</p>");
    for (int i = 0; i < c->blocks.size(); ++i) {
        const AiChatBlock &b = c->blocks[i];
        QString body = b.text.toHtmlEscaped();
        body.replace(QLatin1Char('\n'), QStringLiteral("<br>"));
        if ((b.kind == QLatin1String("user") || b.kind == QLatin1String("letitedit")) && !b.detail.isEmpty()) {
            // a request the app wrote: its summary, and the full text it sent behind a link
            html += QStringLiteral("<p class='u'>%4: %1 &nbsp;<a href='letitedit-detail:%2'>%3</a></p>")
                        .arg(body)
                        .arg(i)
                        .arg(b.expanded ? QStringLiteral("Hide the details") : QStringLiteral("Show the details"))
                        .arg(b.kind == QLatin1String("letitedit") ? QStringLiteral("letitedit") : QStringLiteral("You"));
            if (b.expanded) {
                QString detail = b.detail.toHtmlEscaped();
                detail.replace(QLatin1Char('\n'), QStringLiteral("<br>"));
                html += QStringLiteral("<p class='d'>%1</p>").arg(detail);
            }
        } else if (b.kind == QLatin1String("user"))
            html += QStringLiteral("<p class='u'>You: %1</p>").arg(body);
        else if (b.kind == QLatin1String("tool"))
            html += QStringLiteral("<p class='t'>&#8226; %1%2</p>")
                        .arg(body, b.repeats > 1 ? QStringLiteral(" (%1 times)").arg(b.repeats) : QString());
        else if (b.kind == QLatin1String("error"))
            html += QStringLiteral("<p class='e'>%1</p>").arg(body);
        else if (b.kind == QLatin1String("note"))
            html += QStringLiteral("<p class='n'>%1</p>").arg(body);
        else
            html += QStringLiteral("<p>%1</p>").arg(body);
    }
    c->view->setHtml(html);
    c->view->verticalScrollBar()->setValue(atEnd ? c->view->verticalScrollBar()->maximum() : oldPosition);
    c->rendering = false;
    // QTextBrowser can finish its layout on the next event loop pass. Keep the reading position then too.
    QTimer::singleShot(0, c->view, [c, atEnd, oldPosition]() {
        c->rendering = true;
        c->view->verticalScrollBar()->setValue(atEnd ? c->view->verticalScrollBar()->maximum() : oldPosition);
        c->rendering = false;
    });
    if (atEnd)
        QTimer::singleShot(60, c->view, [c]() {
            if (!c->followBottom)
                return; // the person scrolled up after this render
            c->rendering = true;
            c->view->verticalScrollBar()->setValue(c->view->verticalScrollBar()->maximum());
            c->rendering = false;
        });
    aiChatSaveCurrent(c);
}

// Who wants to know when the AI starts or finishes a request (Review's "the changes are in", the first cut's Opening
// panel). The context object ends the watch when it is deleted.
static QList<QPair<QPointer<QObject>, std::function<void(bool)>>> &aiChatBusyWatchers()
{
    static QList<QPair<QPointer<QObject>, std::function<void(bool)>>> watchers;
    return watchers;
}

void aiChatWatchBusy(QObject *context, const std::function<void(bool)> &watcher)
{
    aiChatBusyWatchers().append({QPointer<QObject>(context), watcher});
}

static void aiChatSetBusy(AiChat *c, bool busy, const QString &status)
{
    busy = busy || c->carryPending;
    const bool changed = c->busy != busy;
    c->busy = busy;
    c->send->setEnabled(true);
    c->send->setText(QStringLiteral("Send")); // while the AI works too: it reads the message as a follow-up
    c->stop->setEnabled(busy);
    c->status->setText(status.isEmpty() ? (busy ? aiChatEngineName() + QStringLiteral(" is working...") : QString()) : status);
    if (!changed)
        return;
    auto &watchers = aiChatBusyWatchers();
    watchers.erase(std::remove_if(watchers.begin(), watchers.end(), [](const auto &w) { return w.first.isNull(); }),
                   watchers.end());
    const auto now = watchers; // a watcher may add or end watches
    for (const auto &w : now)
        if (w.first)
            w.second(busy);
}

static void aiChatAdd(AiChat *c, const QString &kind, const QString &text)
{
    if (kind == QLatin1String("tool") && !c->blocks.isEmpty()
        && c->blocks.last().kind == kind && c->blocks.last().text == text)
        ++c->blocks.last().repeats;
    else
        c->blocks.append({kind, text});
    c->repaint->start();
}

// Who sent a request and wants its outcome: called once, when that request's answer ends, then forgotten. The context
// object ends the watch when it is deleted first.
static QList<std::tuple<int, QPointer<QObject>, std::function<void(const QJsonObject &)>>> &aiChatRequestWatchers()
{
    static QList<std::tuple<int, QPointer<QObject>, std::function<void(const QJsonObject &)>>> watchers;
    return watchers;
}

void aiChatWatchRequest(QObject *context, int request, const std::function<void(const QJsonObject &)> &watcher)
{
    if (request > 0)
        aiChatRequestWatchers().append({request, QPointer<QObject>(context), watcher});
}

// The outcome of a request that ended (empty while it runs or when it is not known).
QJsonObject aiChatOutcome(int request)
{
    AiChat *c = aiChatInstance();
    return c ? c->outcomes.value(request) : QJsonObject();
}

// A request has ended: its outcome is kept (the last 40) and whoever watched that request hears it, once.
static void aiChatRecordOutcome(AiChat *c, int id, const QJsonObject &o)
{
    c->outcomes.insert(id, o);
    if (c->outcomes.size() > 40)
        c->outcomes.remove(*std::min_element(c->outcomes.keyBegin(), c->outcomes.keyEnd()));
    auto &watchers = aiChatRequestWatchers();
    QList<std::function<void(const QJsonObject &)>> due;
    for (int i = watchers.size() - 1; i >= 0; --i) {
        const auto &[request, context, watcher] = watchers[i];
        if (!context) {
            watchers.removeAt(i);
        } else if (request == id) {
            due.prepend(watcher);
            watchers.removeAt(i); // once: a later request never reaches this watcher
        }
    }
    for (const auto &watcher : due)
        watcher(o);
}

static QList<QPair<QPointer<QObject>, AiChatStartRefusedWatcher>> &aiChatStartRefusedWatchers()
{
    static QList<QPair<QPointer<QObject>, AiChatStartRefusedWatcher>> watchers;
    return watchers;
}

void aiChatWatchStartRefused(QObject *context, const AiChatStartRefusedWatcher &watcher)
{
    aiChatStartRefusedWatchers().append({QPointer<QObject>(context), watcher});
}

// A start that answered with an id (T300's first message, prepared in the background; T331's runner) was refused
// afterwards. No busy turn ever began, so the request ends "failed" here under that id, and Home hears it. The chat
// has already said what went wrong. Told on the next turn of the event loop: a start can be refused before the call
// that answered with the id has returned.
static void aiChatStartRefused(AiChat *c, int id, const QString &request, const QString &summary, const QString &why,
                               bool carryOn = false)
{
    c->nextRequest = qMax(c->nextRequest, id + 1); // the id is spent: no later request takes it
    const QString chat = c->chatId;
    QTimer::singleShot(0, c->dock, [c, chat, id, request, summary, why, carryOn]() {
        if (c->chatId != chat)
            return; // the person went to another chat meanwhile
        if (carryOn) {
            // as when the AI can't take Continue the edit at once: the stopped video keeps its way back
            c->carryAllowed = false;
            c->carryStopped = true;
            if (c->carryBar) {
                c->carryContinue->show();
                c->carryBar->show();
            }
        }
        if (!c->outcomes.contains(id)) // a transport that began the request recorded its own
            aiChatRecordOutcome(c, id, QJsonObject{{"id", id},
                                                   {"outcome", QStringLiteral("failed")},
                                                   {"summary", summary},
                                                   {"answer", QString()},
                                                   {"changes", QJsonArray()},
                                                   {"seconds", 0.0},
                                                   {"error", why.isEmpty() ? QStringLiteral("Your AI couldn't take the request.")
                                                                           : why}});
        auto &watchers = aiChatStartRefusedWatchers();
        watchers.erase(std::remove_if(watchers.begin(), watchers.end(), [](const auto &w) { return w.first.isNull(); }),
                       watchers.end());
        const auto now = watchers; // a watcher may add or end watches
        for (const auto &w : now)
            if (w.first)
                w.second(request, summary, why, carryOn);
    });
}

// Per launch of Claude Code (never the person's configuration). A long tool call stays a plain call: by default Claude
// Code 2.1.x answers the AI after 120 s that the call moved to the background, and cuts off a stdio tool that's silent
// for 30 min. Versions that don't know these names ignore them. QA can force the move, to test what happens if a
// version stops honouring this.
static QStringList aiClaudeLongToolEnvironment()
{
    const QString forced = qEnvironmentVariableIsSet("LETITEDIT_QA") ? qEnvironmentVariable("LETITEDIT_QA_CLAUDE_BACKGROUND_MS")
                                                                     : QString();
    return {QStringLiteral("CLAUDE_CODE_MCP_AUTO_BACKGROUND_MS=") + (forced.isEmpty() ? QStringLiteral("0") : forced),
            QStringLiteral("CLAUDE_CODE_MCP_TOOL_IDLE_TIMEOUT=0")};
}

// Whether a background task of this type keeps the request open. Claude Code's own housekeeping tasks and monitors
// (which may never end) don't; a shell command the AI left running only does in a New video, where nobody is there to
// send the next message. type: the stream's name or the Stop hook's name for it.
static bool aiChatTaskHolds(const AiChat *c, const QString &type)
{
    if (type == QLatin1String("local_bash") || type == QLatin1String("shell"))
        return c->autonomousNewVideo;
    return type == QLatin1String("mcp_task") || type == QLatin1String("MCP task") || type == QLatin1String("local_agent")
           || type == QLatin1String("subagent") || type == QLatin1String("local_workflow")
           || type == QLatin1String("workflow");
}

static bool aiChatHeldWorkRunning(const AiChat *c)
{
    if (c->heldOnUnseenWork || !c->toolCallsRunning.isEmpty())
        return true;
    for (const QString &type : c->backgroundTasks)
        if (aiChatTaskHolds(c, type))
            return true;
    return false;
}


// The AI's turn ended with work still running: the request stays open.
static void aiChatHoldTurn(AiChat *c)
{
    c->turnHeld = true;
    aiChatSetBusy(c, true, QStringLiteral("A long step is still running. %1 carries on when it finishes.").arg(aiChatEngineName()));
}

static void aiChatTurnResumed(AiChat *c)
{
    if (!c->turnHeld)
        return;
    c->turnHeld = false;
    aiChatSetBusy(c, true);
}

// The work a held turn waited on has ended, so the AI gets told and starts its next turn within seconds. If it never
// does, say so rather than stay Busy for ever.
static void aiChatWatchHeldTurn(AiChat *c)
{
    const int request = c->request;
    const int ms = qEnvironmentVariableIsSet("LETITEDIT_QA_HELD_TURN_MS") ? qEnvironmentVariableIntValue("LETITEDIT_QA_HELD_TURN_MS")
                                                                          : 120000;
    QTimer::singleShot(ms, c->dock, [c, request]() {
        if (c->request != request || !c->turnHeld || aiChatHeldWorkRunning(c))
            return;
        const QString error = QStringLiteral("A long step finished but %1 didn't carry on. Send a message to continue.")
                                  .arg(aiChatEngineName());
        aiChatAdd(c, QStringLiteral("error"), error);
        aiChatEndRequest(c, QStringLiteral("failed"), error);
        aiChatSetBusy(c, false);
    });
}

// The request being answered ends: "answered" (the AI finished its turn), "failed" (it stopped with an error, or its
// program stopped) or "cancelled" (the person pressed Stop, New chat or Sign in). The outcome holds the AI's answer and
// the edits its tools applied in this window while it ran ("changes": their Undo labels).
#include "letitedit/chat/ainewvideolean.h"
#include "letitedit/chat/ainewvideocarry.h"
#include "letitedit/chat/ainewvideostart.h"
#include "letitedit/chat/ainewvideorunner.h"

static void aiChatEndRequest(AiChat *c, const QString &outcome, const QString &error)
{
    if (!c->request)
        return;
    QStringList answer;
    for (int i = qMax(0, c->turnStart); i < c->blocks.size(); ++i)
        if (c->blocks[i].kind == QLatin1String("claude") && !c->blocks[i].text.trimmed().isEmpty())
            answer << c->blocks[i].text.trimmed();
    QStringList said; // what this turn printed, for a usage limit (T193)
    for (int i = qMax(0, c->turnStart); i < c->blocks.size(); ++i)
        if (c->blocks[i].kind == QLatin1String("error") || c->blocks[i].kind == QLatin1String("claude"))
            said << c->blocks[i].text;
    if (aiNewVideoCarry(c, outcome, answer.isEmpty() ? QString() : answer.constLast(),
                        error + QLatin1Char('\n') + said.mid(qMax(0, int(said.size()) - 6)).join(QLatin1Char('\n'))))
        return;
    const int id = c->request;
    c->turnHeld = false;
    c->heldOnUnseenWork = false;
    c->permissionWaiting = false;
    c->request = 0;
    QJsonObject o{{"id", id},
                  {"outcome", outcome},
                  {"summary", c->requestSummary},
                  {"answer", answer.join(QStringLiteral("\n\n"))},
                  {"changes", QJsonArray::fromStringList(aiBridgeEditsSince(c->requestEdits))},
                  {"seconds", c->turnClock.isValid() ? c->turnClock.elapsed() / 1000.0 : 0.0}};
    if (!error.isEmpty())
        o["error"] = error;
    aiChatRecordOutcome(c, id, o);
    if (c->autonomousNewVideo && !c->liveReviewHold) {
        // The unattended policy belongs to this chat, not to the panel: close
        // this run's CLI session. The next turn of this same chat runs
        // unattended again (newVideoChat, aiChatRequest); any other chat the
        // person starts or switches to resumes under ordinary permissions.
        c->autonomousNewVideo = false;
        QTimer::singleShot(0, c->dock, [c]() {
            if (aiTerminalMode())
                aiTerminalStop(c);
            else if (c->proc)
                aiChatStopClaude(c);
        });
    }
}

// Live Review's round is over: the next thing the person types goes under ordinary permissions, as after New video.
void aiChatLiveEnd(AiChat *c)
{
    if (!c || !c->liveReviewHold)
        return;
    c->liveReviewHold = false;
    if (c->request)
        return; // something is running: aiChatEndRequest closes it when it ends
    c->autonomousNewVideo = false;
    if (aiTerminalMode())
        aiTerminalStop(c);
    else if (c->proc)
        aiChatStopClaude(c);
}

// Interactive sessions use an isolated working directory for each video. The user's own
// Claude and Codex configuration is still loaded by the programs; only letitedit's MCP
// entry, instructions and progress hooks live here.
static QString aiTerminalWork(AiChat *c)
{
    if (!c->terminalWork.isEmpty()) return c->terminalWork;
    const QString root = aiChatSettings().value("work_dir").toString();
    const QString key = c->projectKey.isEmpty() ? QStringLiteral("no-project")
        : QString::fromLatin1(QCryptographicHash::hash(c->projectKey.toUtf8(), QCryptographicHash::Sha256).toHex().left(20));
    return QDir(root).filePath(QStringLiteral("projects/") + key);
}

static bool aiTerminalWrite(const QString &path, const QByteArray &data)
{
    QSaveFile file(path);
    return file.open(QIODevice::WriteOnly) && file.write(data) == data.size() && file.commit();
}

static void aiTerminalPrepare(AiChat *c)
{
    const QJsonObject s = aiChatSettings();
    c->terminalWork = aiTerminalWork(c);
    QDir().mkpath(c->terminalWork);
    c->terminalEvents = QDir(c->terminalWork).filePath(QStringLiteral("events.jsonl"));
    const QString python = s.value("python").toString();
    const QString proxy = aiRootPath(QStringLiteral("chat/mcp_proxy.py"));
    const QString server = s.value("mcp_server").toString();
    const QJsonObject tool{{"command", python},
                           {"args", QJsonArray{proxy, server, c->terminalEvents}},
                           {"env", QJsonObject{{"PYTHONUTF8", "1"}, {"PYTHONIOENCODING", "utf-8"}}}};
    aiTerminalWrite(QDir(c->terminalWork).filePath(QStringLiteral("mcp.json")),
                    QJsonDocument(QJsonObject{{"mcpServers", QJsonObject{{"letitedit", tool}}}}).toJson());
    const QString hook = QStringLiteral("\"%1\" \"%2\" \"%3\"")
        .arg(QDir::toNativeSeparators(python),
             QDir::toNativeSeparators(aiRootPath(QStringLiteral("chat/session_event.py"))),
             QDir::toNativeSeparators(c->terminalEvents));
    QJsonObject hooks;
    for (const QString &name : {QStringLiteral("PreToolUse"), QStringLiteral("Stop")}) {
        const QString event = name == QLatin1String("Stop") ? QStringLiteral("stop") : QStringLiteral("pre");
        hooks[name] = QJsonArray{QJsonObject{{"hooks", QJsonArray{QJsonObject{{"type", "command"},
                                                    {"command", hook + QLatin1Char(' ') + event}}}}}};
    }
    QJsonObject terminalSettings = aiClaudeInstructionSettings(aiRunSettings(c));
    terminalSettings.insert(QStringLiteral("hooks"), hooks);
    terminalSettings.insert(QStringLiteral("permissions"), QJsonObject{{"defaultMode", c->autonomousNewVideo
                                                                                         ? QStringLiteral("auto")
                                                                                         : QStringLiteral("default")}});
    aiTerminalWrite(QDir(c->terminalWork).filePath(QStringLiteral("settings.json")),
                    QJsonDocument(terminalSettings).toJson());
    QFile prompt(s.value("prompt").toString());
    const QByteArray instructions = prompt.open(QIODevice::ReadOnly) ? prompt.readAll() : QByteArray();
    aiTerminalWrite(QDir(c->terminalWork).filePath(QStringLiteral("AGENTS.md")), instructions);
    c->terminalEventOffset = QFileInfo(c->terminalEvents).size();
    c->terminalEventBuffer.clear();
    c->terminalSessionFile.clear(); c->terminalSessionOffset = 0; c->terminalSessionBuffer.clear();
    c->terminalSeenMessages.clear();
    c->toolCallsRunning.clear();
}

static void aiTerminalStop(AiChat *c)
{
    if (!c->terminal) return;
    c->terminalStopping = true;
    c->terminal->stop();
    c->terminalStopping = false;
    if (c->terminalPoll) c->terminalPoll->stop();
    c->terminalWork.clear();
}

static QString aiTerminalFindSession(AiChat *c)
{
    QString root;
    if (c->engine == QLatin1String("claude")) {
        root = QDir::homePath() + QStringLiteral("/.claude/projects");
        if (c->sessionId.isEmpty()) return QString();
        QDirIterator files(root, QStringList{c->sessionId + QStringLiteral(".jsonl")}, QDir::Files, QDirIterator::Subdirectories);
        if (!files.hasNext()) return QString();
        c->sessionStarted = true;
        return files.next();
    }
    // Codex creates its own session ID. Find today's new record by cwd, then remember its ID.
    const QDate utc = QDateTime::currentDateTimeUtc().date();
    QString newest;
    QDateTime newestTime;
    for (int delta = 0; delta <= 1; ++delta) {
        const QString dir = QDir::homePath() + QStringLiteral("/.codex/sessions/")
                            + utc.addDays(-delta).toString(QStringLiteral("yyyy/MM/dd"));
        QDirIterator files(dir, QStringList{QStringLiteral("*.jsonl")}, QDir::Files);
        while (files.hasNext()) {
            const QString path = files.next();
            const QFileInfo info(path);
            if (!c->sessionId.isEmpty() && !path.contains(c->sessionId)) continue;
            if (c->sessionId.isEmpty() && info.lastModified().toUTC() < c->terminalLaunchedUtc.addSecs(-10)) continue;
            QFile file(path);
            if (!file.open(QIODevice::ReadOnly)) continue;
            const QJsonObject first = QJsonDocument::fromJson(file.readLine()).object();
            const QJsonObject meta = first.value("payload").toObject();
            const QString recordedWork = QDir::cleanPath(QDir::fromNativeSeparators(meta.value("cwd").toString()));
            const QString currentWork = QDir::cleanPath(QDir::fromNativeSeparators(c->terminalWork));
            if (recordedWork.compare(currentWork, Qt::CaseInsensitive) == 0) {
                if (newest.isEmpty() || info.lastModified() > newestTime) {
                    newest = path; newestTime = info.lastModified();
                }
            }
        }
    }
    if (!newest.isEmpty() && c->sessionId.isEmpty()) {
        QFile chosen(newest);
        if (chosen.open(QIODevice::ReadOnly)) {
            const QJsonObject meta = QJsonDocument::fromJson(chosen.readLine()).object().value("payload").toObject();
            c->sessionId = meta.value("id").toString(meta.value("session_id").toString());
            c->sessionStarted = !c->sessionId.isEmpty();
            aiChatSaveCurrent(c);
        }
    }
    return newest;
}

static void aiTerminalPoll(AiChat *c);
static bool aiTerminalStart(AiChat *c);

static bool aiTerminalRetrySpeed(AiChat *c, const QString &error)
{
    if (!aiSpeedFallback(c, error))
        return false;
    c->speedRestartPending = true;
    const int request = c->request;
    const QString chatId = c->chatId;
    QTimer::singleShot(0, c->dock, [c, request, chatId]() {
        if (c->request != request || c->chatId != chatId || !c->busy)
            return;
        aiTerminalStop(c);
        c->speedRestartPending = false;
        if (!aiTerminalStart(c)) {
            aiChatEndRequest(c, QStringLiteral("failed"), QStringLiteral("The AI could not restart at Normal speed."));
            aiChatSetBusy(c, false);
            return;
        }
        auto waiting = new QTimer(c->dock);
        auto since = std::make_shared<QElapsedTimer>();
        since->start();
        waiting->setInterval(500);
        QObject::connect(waiting, &QTimer::timeout, c->dock, [c, request, chatId, waiting, since]() {
            if (c->request != request || c->chatId != chatId || !c->terminal->running()) {
                waiting->stop();
                waiting->deleteLater();
            } else if ((since->elapsed() >= 5000 && c->terminal->receivedBytes() > 0) || since->elapsed() >= 30000) {
                waiting->stop();
                waiting->deleteLater();
                c->terminal->submit(c->retryContent);
            }
        });
        waiting->start();
    });
    return true;
}

static void aiSpeedAutoNormal(AiChat *c, const QString &text)
{
    if (c->procSpeed == QLatin1String("fast") && !c->speedNormal
        && text.contains(QStringLiteral("Fast mode disabled"), Qt::CaseInsensitive)) {
        c->speedNormal = c->speedRetried = true;
        c->procSpeed = QStringLiteral("normal");
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("Claude Code switched to Normal speed. Your saved choice is unchanged."));
        aiChatRefreshChoices(c);
    }
}

static void aiTerminalEvent(AiChat *c, const QJsonObject &event)
{
    const QString type = event.value("type").toString();
    if (c->speedRestartPending) return;
    if (type == QLatin1String("tool") || type == QLatin1String("pre")) {
        c->speedProduced = true;
        const QString tool = event.value("tool_name").toString();
        if (tool.startsWith(QLatin1String("letitedit_")) || tool.startsWith(QLatin1String("mcp__letitedit__"))) {
            const QString phrase = aiChatToolPhrase(tool, event.value("tool_input").toObject());
            aiChatSetBusy(c, true, aiChatProgress(c, tool, phrase));
        }
        if (type == QLatin1String("tool") && !event.value("call").toString().isEmpty())
            c->toolCallsRunning.insert(event.value("call").toString());
    } else if (type == QLatin1String("tool_end")) {
        c->toolCallsRunning.remove(event.value("call").toString());
        if (c->turnHeld && !aiChatHeldWorkRunning(c))
            aiChatWatchHeldTurn(c);
    } else if (type == QLatin1String("stop") && c->request) {
        const QString id = event.value("session_id").toString();
        if (!id.isEmpty()) c->sessionId = id;
        c->sessionStarted = true;
        const int request = c->request;
        const QString chatId = c->chatId;
        // Is anything still running? Claude Code's list where it gives one; letitedit's own calls are also known to
        // the tool proxy, on any version.
        bool hold = !c->toolCallsRunning.isEmpty();
        bool unseen = false;
        for (const QJsonValue &value : event.value("background_tasks").toArray()) {
            const QJsonObject task = value.toObject();
            if (!aiChatTaskHolds(c, task.value("type").toString()))
                continue;
            hold = true;
            if (task.value("server").toString() != QLatin1String("letitedit"))
                unseen = true;
        }
        // Claude writes the final assistant entry and its Stop hook near each
        // other. Give the session-file poll a turn to capture the answer.
        QTimer::singleShot(700, c->dock, [c, request, chatId, hold, unseen]() {
            if (c->request != request || c->chatId != chatId) return;
            aiTerminalPoll(c);
            if (hold) {
                c->heldOnUnseenWork = unseen;
                aiChatHoldTurn(c);
                if (!aiChatHeldWorkRunning(c))
                    aiChatWatchHeldTurn(c); // it ended in these moments
                return;
            }
            aiChatEndRequest(c, QStringLiteral("answered"));
            ConnectAi::record(QStringLiteral("claude"), true, QStringLiteral("answered in the terminal"));
            aiChatSetBusy(c, false);
            aiChatSaveCurrent(c);
        });
    }
}

static void aiTerminalPoll(AiChat *c)
{
    if (!c->terminal || !c->terminal->running()) return;
    aiSpeedAutoNormal(c, c->terminal->visibleText());
    if (!c->terminalSessionFile.isEmpty() && !QFileInfo::exists(c->terminalSessionFile)) c->terminalSessionFile.clear();
    if (c->terminalSessionFile.isEmpty()) c->terminalSessionFile = aiTerminalFindSession(c);
    const auto readNew = [](const QString &path, qint64 &offset, QByteArray &partial,
                            const std::function<void(const QJsonObject &)> &handle) {
        QFile file(path);
        if (!file.open(QIODevice::ReadOnly)) return;
        if (file.size() < offset) { offset = 0; partial.clear(); }
        if (!file.seek(offset)) return;
        partial += file.readAll(); offset = file.pos();
        int end;
        while ((end = partial.indexOf('\n')) >= 0) {
            const QByteArray line = partial.left(end); partial.remove(0, end + 1);
            const QJsonDocument doc = QJsonDocument::fromJson(line);
            if (doc.isObject()) handle(doc.object());
        }
    };
    if (!c->terminalSessionFile.isEmpty()) readNew(c->terminalSessionFile, c->terminalSessionOffset, c->terminalSessionBuffer,
            [c](const QJsonObject &entry) {
        if (c->speedRestartPending) return;
        const QDateTime when = QDateTime::fromString(entry.value("timestamp").toString(), Qt::ISODateWithMs);
        if (when.isValid() && when.toUTC() < c->terminalLaunchedUtc.addSecs(-2)) return;
        if (c->engine == QLatin1String("codex")) {
            const QString type = entry.value("type").toString();
            const QJsonObject p = entry.value("payload").toObject();
            if (type == QLatin1String("event_msg") && p.value("type") == QLatin1String("user_message"))
                c->retryContent = p.value("message").toString();
            if (type == QLatin1String("event_msg") && p.value("type") == QLatin1String("task_started") && !c->request) {
                aiChatBeginRequest(c, QStringLiteral("Message typed in Codex"), QString(), false);
                aiChatSetBusy(c, true);
            } else if (type == QLatin1String("event_msg") && p.value("type") == QLatin1String("task_complete") && c->request) {
                aiChatEndRequest(c, QStringLiteral("answered")); aiChatSetBusy(c, false);
                ConnectAi::record(QStringLiteral("codex"), true, QStringLiteral("answered in the terminal"));
                aiChatSaveCurrent(c);
            } else if (type == QLatin1String("event_msg") && p.value("type") == QLatin1String("error") && c->request
                       && !p.value("message").toString().isEmpty()) {
                // Codex's own words for a failed turn (a usage limit's reset time among them, T193)
                if (!aiTerminalRetrySpeed(c, p.value("message").toString()))
                    aiChatAdd(c, QStringLiteral("error"), p.value("message").toString());
            } else if (type == QLatin1String("event_msg") && p.value("type") == QLatin1String("task_failed") && c->request) {
                aiChatEndRequest(c, QStringLiteral("failed"), QStringLiteral("Codex reported a failed turn."));
                aiChatSetBusy(c, false);
            } else if (type == QLatin1String("event_msg") && p.value("type") == QLatin1String("item_completed")
                       && p.value("item").toObject().value("type") == QLatin1String("AgentMessage")) {
                const QJsonObject item = p.value("item").toObject();
                QStringList parts;
                for (const QJsonValue &part : item.value("content").toArray()) {
                    const QString text = part.toObject().value("text").toString();
                    if (!text.isEmpty()) parts << text;
                }
                if (!parts.isEmpty()) aiChatAdd(c, QStringLiteral("claude"), parts.join(QStringLiteral("\n")));
            } else if (type == QLatin1String("response_item") && p.value("type") == QLatin1String("custom_tool_call")) {
                const QString name = p.value("name").toString();
                if (name.startsWith(QLatin1String("mcp__letitedit__"))) aiTerminalEvent(c, QJsonObject{{"type", "tool"}, {"tool_name", name}});
            }
        } else if (c->turnHeld && (entry.value("type") == QLatin1String("user") || entry.value("type") == QLatin1String("queue-operation")
                                   || entry.value("type") == QLatin1String("api-request"))) {
            // The AI's next turn has begun (a task's notification, or a message): it reports again when that ends.
            c->heldOnUnseenWork = false;
            aiChatTurnResumed(c);
        } else if (entry.value("type") == QLatin1String("user") && !c->request) {
            const QJsonValue content = entry.value("message").toObject().value("content");
            QString message = content.toString();
            if (content.isArray())
                for (const QJsonValue &part : content.toArray())
                    if (part.toObject().value("type") == QLatin1String("text")) message += part.toObject().value("text").toString();
            if (!message.trimmed().isEmpty()) {
                c->retryContent = message;
                aiChatBeginRequest(c, message, QString(), false);
                aiChatSetBusy(c, true);
            }
        } else if (entry.value("type") == QLatin1String("assistant") && c->request) {
            if (c->turnHeld) {
                c->heldOnUnseenWork = false;
                aiChatTurnResumed(c);
            }
            const QString uuid = entry.value("uuid").toString();
            if (c->terminalSeenMessages.contains(uuid)) return;
            c->terminalSeenMessages.insert(uuid);
            for (const QJsonValue &part : entry.value("message").toObject().value("content").toArray()) {
                const QJsonObject block = part.toObject();
                if (block.value("type") == QLatin1String("text") && !block.value("text").toString().isEmpty())
                    aiChatAdd(c, QStringLiteral("claude"), block.value("text").toString());
            }
        }
    });
    readNew(c->terminalEvents, c->terminalEventOffset, c->terminalEventBuffer,
            [c](const QJsonObject &event) { aiTerminalEvent(c, event); });
}

static bool aiTerminalStart(AiChat *c)
{
    if (qEnvironmentVariableIsSet("LETITEDIT_QA")
        && qEnvironmentVariableIsSet("LETITEDIT_QA_MOCK_AI"))
        return false; // QA can show the terminal layout without starting a real AI program.
    if (!c->terminal) return false;
    const QJsonObject s = aiRunSettings(c);
    if (c->terminal->running()) {
        if (c->procSpeed == aiSpeedValue(s, aiChatEngineId(s)))
            return true;
        aiTerminalStop(c);
    }
    if (!c->engine.isEmpty() && c->engine != s.value("engine").toString()) {
        // An old chat on an AI that's no longer on this PC: its session can't go on, so this is a new chat.
        aiChatSaveCurrent(c);
        aiChatNewRecord(c, c->projectKey);
    }
    c->engine = aiChatEngineId(s);
    // The screen starts with this chat's own policy: unattended for New video's or Learn's chat, whoever types next into
    // it, and the person's own rules for any other chat (a request already set it; Live Review keeps its round's).
    if (!c->request && !c->liveReviewHold)
        c->autonomousNewVideo = c->newVideoChat;
    aiTerminalPrepare(c);
    const bool codex = c->engine == QLatin1String("codex");
    const QString exe = codex ? s.value("codex").toString() : s.value("claude").toString();
    if (!QFileInfo::exists(exe)) {
        c->status->setText(QStringLiteral("%1 was not found. Use Menu > AI > Connect Your AI.").arg(ConnectAi::programName(c->engine)));
        return false;
    }
    QStringList args;
    if (codex) {
        const QString python = s.value("python").toString();
        const QStringList proxyArgs{aiRootPath(QStringLiteral("chat/mcp_proxy.py")),
                                    s.value("mcp_server").toString(), c->terminalEvents};
        QStringList quotedArgs;
        for (const QString &arg : proxyArgs) quotedArgs << aiTomlString(arg);
        args << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.command=") + aiTomlString(python)
             << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.args=[") + quotedArgs.join(QLatin1Char(',')) + QLatin1Char(']')
             << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.enabled=true")
             // Codex's own default gives a tool call 60 s, then tells the AI it failed. The chat view has this too.
             << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.startup_timeout_sec=120")
             << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.tool_timeout_sec=3600");
        args << aiCodexWindowArgs();
        args << aiCodexChoiceArgs(s);
        if (c->autonomousNewVideo) {
            // --approve-for-me already means workspace-write; Codex refuses --sandbox with it.
            args << QStringLiteral("--approve-for-me");
            if (!c->autonomousWriteDir.isEmpty())
                args << QStringLiteral("--add-dir") << c->autonomousWriteDir;
        }
        if (c->sessionStarted && !c->sessionId.isEmpty()) args << QStringLiteral("resume") << c->sessionId;
        else c->sessionId.clear();
    } else {
        args << QStringLiteral("--mcp-config") << QDir(c->terminalWork).filePath(QStringLiteral("mcp.json"))
             << QStringLiteral("--settings") << QDir(c->terminalWork).filePath(QStringLiteral("settings.json"))
             << QStringLiteral("--allowedTools") << QStringLiteral("mcp__letitedit__*");
        args << aiClaudeNewVideoToolArgs(c->autonomousNewVideo, c->newVideoChat);
        const QString prompt = s.value("prompt").toString();
        if (QFileInfo::exists(prompt)) args << QStringLiteral("--append-system-prompt-file") << prompt;
        args << aiClaudeChoiceArgs(s);
        if (c->autonomousNewVideo)
            args << QStringLiteral("--permission-mode") << QStringLiteral("auto")
                 // If this plan or model cannot use auto mode, Claude denies a
                 // disallowed action and tells the agent instead of waiting for
                 // somebody to answer a dialog.
                 << QStringLiteral("--permission-prompts") << QStringLiteral("none");
        if (c->sessionStarted && !c->sessionId.isEmpty()) args << QStringLiteral("--resume") << c->sessionId;
        else args << QStringLiteral("--session-id") << c->sessionId;
    }
    QString error;
    c->terminalLaunchedUtc = QDateTime::currentDateTimeUtc();
    QStringList environment = codex ? QStringList() : aiClaudeLongToolEnvironment();
    const QString path = aiChatPythonPath(s);
    if (!path.isEmpty())
        environment << QStringLiteral("PATH=") + path;
    if (!c->terminal->start(exe, args, c->terminalWork, &error, environment)) {
        c->status->setText(error);
        if (c->terminalNotice) { c->terminalNotice->setText(error); c->terminalNotice->show(); }
        return false;
    }
    if (c->terminalNotice) { c->terminalNotice->clear(); c->terminalNotice->hide(); }
    const QJsonObject resolved = aiResolvedChoice(s); // Auto as the model and effort it runs on
    c->procModel = resolved.value(codex ? "codex_model" : "model").toString();
    c->procEffort = resolved.value(codex ? "codex_reasoning" : "effort").toString();
    c->procSpeed = aiSpeedValue(s, c->engine);
    aiChatSaveCurrent(c);
    if (c->terminalPoll) c->terminalPoll->start();
    c->terminal->setFocus();
    return true;
}

static QString aiChatPermissionAction(const QString &tool, const QJsonObject &request)
{
    const QJsonObject input = request.value("input").toObject();
    const QString command = input.value("command").toString();
    if (!command.isEmpty())
        return QStringLiteral("%1 wants to run this command:\n%2").arg(aiChatEngineName(), command.left(700));
    const QString path = input.value("file_path").toString(input.value("path").toString());
    if (!path.isEmpty())
        return QStringLiteral("%1 wants to use %2 on this file:\n%3").arg(aiChatEngineName(), tool, path.left(700));
    if (tool.startsWith(QLatin1String("mcp__"))) {
        const QString service = tool.section(QLatin1String("__"), 1, 1);
        const QString description = request.value("description").toString();
        return QStringLiteral("%1 wants to use %2%3")
            .arg(aiChatEngineName(), service, description.isEmpty() ? QStringLiteral(" to continue.")
                                                 : QStringLiteral(":\n%1").arg(description.left(700)));
    }
    const QString description = request.value("description").toString();
    return QStringLiteral("%1 wants to %2%3")
        .arg(aiChatEngineName(), aiChatToolPhrase(tool, input).toLower(),
             description.isEmpty() ? QStringLiteral(".") : QStringLiteral(":\n%1").arg(description.left(700)));
}

static QString aiChatPermissionKey(AiChat *c, const QString &tool, const QJsonObject &input)
{
    // T221: "Allow for this chat" covers that kind of action (the tool: every command, every file write), not only
    // the exact command asked about. The history keeps chat-scoped grants across a restart; the key is a hash, so no
    // tool input (which may hold a secret) is stored.
    Q_UNUSED(input)
    const QByteArray action = c->chatId.toUtf8() + '\0' + tool.toUtf8() + '\0';
    return QString::fromLatin1(QCryptographicHash::hash(action, QCryptographicHash::Sha256).toHex());
}

// The person's answer to an action the AI asks about: Allow once, Allow for this chat (kept as a grant), or Deny.
static bool aiChatAskPermission(AiChat *c, const QString &signature, const QString &action)
{
    aiChatAdd(c, QStringLiteral("note"), action);
    QMessageBox box(QMessageBox::Question, QStringLiteral("%1 asks permission").arg(aiChatEngineName()),
                    action, QMessageBox::NoButton,
                    c->dock);
    QPushButton *once = box.addButton(QStringLiteral("Allow once"), QMessageBox::AcceptRole);
    QPushButton *chat = box.addButton(QStringLiteral("Allow for this chat"), QMessageBox::AcceptRole);
    box.addButton(QStringLiteral("Deny"), QMessageBox::RejectRole);
    c->permissionWaiting = true;
    box.exec();
    c->permissionWaiting = false;
    const bool allow = box.clickedButton() == once || box.clickedButton() == chat;
    if (box.clickedButton() == chat)
        c->claudeChatAllowed.insert(signature);
    aiChatAdd(c, QStringLiteral("note"), allow
        ? box.clickedButton() == chat ? QStringLiteral("Allowed for this chat: %1").arg(action)
                                      : QStringLiteral("Allowed once: %1").arg(action)
        : QStringLiteral("Denied: %1. Ask %2 to try again if you change your mind.").arg(action, aiChatEngineName()));
    return allow;
}

// A control request from Claude Code: whether a tool may run (can_use_tool), answered on its input.
static void aiChatAnswerControl(AiChat *c, const QJsonObject &msg)
{
    const QJsonObject request = msg.value("request").toObject();
    if (request.value("subtype").toString() == QLatin1String("can_use_tool")) {
        const QString tool = request.value("tool_name").toString();
        const QJsonObject input = request.value("input").toObject();
        const QString signature = aiChatPermissionKey(c, tool, input);
        const QString action = aiChatPermissionAction(tool, request);
        // The person's editor tools were installed for this chat. This also protects older
        // Claude versions that do not honor the --allowedTools server wildcard.
        bool allow = tool.startsWith(QLatin1String("mcp__letitedit__"))
                     || c->claudeChatAllowed.contains(signature);
        if (!allow)
            allow = aiChatAskPermission(c, signature, action);
        c->lastPermission = allow ? QStringLiteral("allow") : QStringLiteral("deny");
        const QJsonObject decision = allow ? QJsonObject{{"behavior", "allow"}, {"updatedInput", input}}
                                           : QJsonObject{{"behavior", "deny"}, {"message", "The person denied this action."}};
        const QJsonObject response{{"type", "control_response"},
                                   {"response", QJsonObject{{"subtype", "success"},
                                                             {"request_id", msg.value("request_id")},
                                                             {"response", decision}}}};
        if (c->proc)
            c->proc->write(QJsonDocument(response).toJson(QJsonDocument::Compact) + '\n');
    } else {
        aiChatAdd(c, QStringLiteral("error"), QStringLiteral("%1 asked for an action this chat cannot answer. "
            "Update %2 or use Menu > AI > Connect Your AI, then try again.").arg(aiChatEngineName(), ConnectAi::programName(aiChatEngineId(aiChatSettings()))));
    }
}

// The AI's session has started: its id, model, tools and permission mode.
static void aiChatSessionStarted(AiChat *c, const QJsonObject &msg)
{
    c->sessionId = msg.value("session_id").toString(c->sessionId);
    c->sessionStarted = true;
    c->activeModel = msg.value("model").toString(c->activeModel);
    c->tools = msg.value("tools").toArray();
    c->permissionMode = msg.value("permissionMode").toString();
    aiChatShowActiveModel(c);
    if (aiEngineIsConnector(c->engine))   // the host has just saved what this account is offered
        QTimer::singleShot(0, c->dock, [c]() { aiChatRefreshChoices(c); });
}

// The reply as it is written: each piece of text goes on the reply being shown.
static void aiChatStreamed(AiChat *c, const QJsonObject &msg)
{
    const QJsonObject ev = msg.value("event").toObject();
    const QString et = ev.value("type").toString();
    if (et == QLatin1String("message_start")) {
        c->live = -1;
    } else if (et == QLatin1String("content_block_delta")) {
        const QJsonObject d = ev.value("delta").toObject();
        if (d.value("type").toString() == QLatin1String("text_delta")) {
            if (c->live < 0 || c->live >= c->blocks.size() || c->blocks[c->live].kind != QLatin1String("claude")) {
                c->blocks.append({QStringLiteral("claude"), QString()});
                c->live = c->blocks.size() - 1;
            }
            c->blocks[c->live].text += d.value("text").toString();
            c->repaint->start();
        }
    }
}

// A finished message from the AI: each tool it uses is a line, and its text replaces the streamed pieces.
static void aiChatAssistantMessage(AiChat *c, const QJsonObject &msg)
{
    QString text;
    for (const auto &v : msg.value("message").toObject().value("content").toArray()) {
        const QJsonObject b = v.toObject();
        if (b.value("type").toString() == QLatin1String("text")) {
            text += b.value("text").toString();
        } else if (b.value("type").toString() == QLatin1String("tool_use")) {
            c->speedProduced = true;
            c->live = -1;
            const QString phrase = aiChatToolPhrase(b.value("name").toString(), b.value("input").toObject());
            aiChatAdd(c, QStringLiteral("tool"), phrase);
            aiChatSetBusy(c, true, aiChatProgress(c, b.value("name").toString(), phrase));
        }
    }
    if (!aiEngineIsConnector(c->engine) && (text.contains(QLatin1String("Not logged in")) || text.contains(QLatin1String("/login")))) {
        c->live = -1;
        aiChatAdd(c, QStringLiteral("error"),
                  QStringLiteral("Claude Code on this PC isn't signed in yet. Click \"Sign in\": a window opens with "
                                 "Claude Code; type /login there and finish in the browser. Then send your message again."));
        c->signIn->show();
        text.clear();
    }
    if (!text.isEmpty()) {
        if (c->live >= 0 && c->live < c->blocks.size() && c->blocks[c->live].kind == QLatin1String("claude"))
            c->blocks[c->live].text = text; // the finished message replaces the streamed pieces
        else
            aiChatAdd(c, QStringLiteral("claude"), text);
        c->repaint->start();
    }
}

// The tools' answers: a step that failed is a line, and a blocked one says what to do.
static void aiChatToolResults(AiChat *c, const QJsonObject &msg)
{
    for (const auto &v : msg.value("message").toObject().value("content").toArray()) {
        const QJsonObject b = v.toObject();
        if (b.value("type").toString() == QLatin1String("tool_result") && b.value("is_error").toBool()) {
            QString err;
            const QJsonValue content = b.value("content");
            if (content.isString())
                err = content.toString();
            else
                for (const auto &part : content.toArray())
                    err += part.toObject().value("text").toString();
            const bool blocked = err.contains(QLatin1String("permission"), Qt::CaseInsensitive)
                || err.contains(QLatin1String("denied"), Qt::CaseInsensitive)
                || err.contains(QLatin1String("blocked"), Qt::CaseInsensitive)
                || err.contains(QLatin1String("haven't granted"), Qt::CaseInsensitive);
            aiChatAdd(c, blocked ? QStringLiteral("error") : QStringLiteral("note"), blocked
                ? QStringLiteral("%2 could not do that step because it was blocked: %1\n"
                                 "Ask %2 to try again; the permission request will appear here. "
                                 "If it does not, use Menu > AI > Connect Your AI.").arg(err.left(300), aiChatEngineName())
                : QStringLiteral("That step failed: %1").arg(err.left(300)));
        }
    }
}

// The work the AI runs in the background now; a held turn ends once none of it is left.
static void aiChatBackgroundTasks(AiChat *c, const QJsonObject &msg)
{
    c->backgroundTasks.clear();
    for (const QJsonValue &value : msg.value("tasks").toArray()) {
        const QJsonObject task = value.toObject();
        c->backgroundTasks.insert(task.value("task_id").toString(), task.value("task_type").toString());
    }
    if (c->turnHeld && !aiChatHeldWorkRunning(c))
        aiChatWatchHeldTurn(c);
}

// The turn's end: answered or failed (held while background work runs). A connector takes one message at a time, so
// one sent meanwhile goes next.
static void aiChatTurnResult(AiChat *c, const QJsonObject &msg)
{
    c->live = -1;
    if (msg.value("subtype").toString() == QLatin1String("cancelled"))
        return; // the connector host after Stop, which has already ended the request; another may have begun since
    const bool failed = msg.value("is_error").toBool() && msg.value("subtype").toString() != QLatin1String("success");
    if (!failed && aiChatHeldWorkRunning(c)) {
        aiChatHoldTurn(c);
        return;
    }
    const QString error = msg.value("result").toString(QStringLiteral("%1 stopped with an error.").arg(aiChatEngineName()));
    if (failed)
        aiChatAdd(c, QStringLiteral("error"), error);
    aiChatEndRequest(c, failed ? QStringLiteral("failed") : QStringLiteral("answered"), failed ? error : QString());
    if (!failed) // a real answer: the connection works (Connect Your AI and the welcome screen say so)
        ConnectAi::record(c->engine.isEmpty() ? QStringLiteral("claude") : c->engine, true, QStringLiteral("answered in the chat"));
    aiChatSetBusy(c, false);
    aiVoiceTurnDone(c);
    if (aiEngineIsConnector(c->engine) && !c->queued.isEmpty()) {
        // A connector takes one message at a time: what was sent meanwhile goes next.
        const QString next = c->queued.takeFirst();
        const QString nextTarget = c->queuedTargets.take(next);
        for (int i = c->blocks.size() - 1; i >= 0; --i) {
            if (c->blocks[i].kind == QLatin1String("user") && c->blocks[i].text == next) {
                c->blocks.removeAt(i);
                break;
            }
        }
        QTimer::singleShot(0, c->dock, [c, next, nextTarget]() {
            c->typedTarget = nextTarget;
            aiChatRequest(c->window, next, QString(), false, false);
            c->typedTarget.clear();
        });
    }
}

void aiChatHandleLine(AiChat *c, const QJsonObject &msg)
{
    const QString type = msg.value("type").toString();
    if (type == QLatin1String("result") && msg.value("is_error").toBool()
        && aiClaudeRetrySpeed(c, QString::fromUtf8(QJsonDocument(msg).toJson(QJsonDocument::Compact))))
        return;
    // After a held turn: the AI's next turn has begun (its stream opens with "init"), so its next result counts.
    if (c->turnHeld && (type == QLatin1String("assistant") || type == QLatin1String("stream_event")
                        || (type == QLatin1String("system") && msg.value("subtype") == QLatin1String("init"))))
        aiChatTurnResumed(c);
    if (type == QLatin1String("control_request")) {
        aiChatAnswerControl(c, msg);
    } else if (type == QLatin1String("system") && msg.value("subtype").toString() == QLatin1String("notification")) {
        aiSpeedAutoNormal(c, msg.value("text").toString());
    } else if (type == QLatin1String("system") && msg.value("subtype").toString() == QLatin1String("letitedit_note")) {
        aiChatAdd(c, QStringLiteral("note"), msg.value("text").toString()); // the connector host: a line in the chat
    } else if (type == QLatin1String("system") && msg.value("subtype").toString() == QLatin1String("letitedit_signin")) {
        c->signIn->show(); // the connector host: its result says why
    } else if (type == QLatin1String("system") && msg.value("subtype").toString() == QLatin1String("init")) {
        aiChatSessionStarted(c, msg);
    } else if (type == QLatin1String("stream_event")) {
        aiChatStreamed(c, msg);
    } else if (type == QLatin1String("assistant")) {
        aiChatAssistantMessage(c, msg);
    } else if (type == QLatin1String("user")) {
        aiChatToolResults(c, msg);
    } else if (type == QLatin1String("system") && msg.value("subtype") == QLatin1String("background_tasks_changed")) {
        aiChatBackgroundTasks(c, msg);
    } else if (type == QLatin1String("result")) {
        aiChatTurnResult(c, msg);
    }
}

// The letitedit tools for Claude Code: work/mcp.json, written for every start. Its path.
static QString aiChatWriteMcpConfig(const QJsonObject &s, const QString &work)
{
    QJsonObject server{{"command", s.value("python").toString()},
                       {"args", QJsonArray{s.value("mcp_server").toString()}},
                       {"env", QJsonObject{{"PYTHONUTF8", "1"}, {"PYTHONIOENCODING", "utf-8"}}}};
    QFile cfg(work + QStringLiteral("/mcp.json"));
    if (cfg.open(QIODevice::WriteOnly | QIODevice::Truncate))
        cfg.write(QJsonDocument(QJsonObject{{"mcpServers", QJsonObject{{"letitedit", server}}}}).toJson());
    cfg.close();
    return cfg.fileName();
}

// Claude Code's command line for the chat: streaming JSON both ways, the letitedit tools, its settings and this chat's
// session.
static QStringList aiClaudeChatArgs(AiChat *c, const QJsonObject &s, const QString &mcpConfig)
{
    QStringList args{QStringLiteral("-p"), QStringLiteral("--input-format"), QStringLiteral("stream-json"),
                     QStringLiteral("--output-format"), QStringLiteral("stream-json"), QStringLiteral("--include-partial-messages"),
                     QStringLiteral("--verbose"), QStringLiteral("--mcp-config"), mcpConfig,
                     // T221: every chat approves as New video does. The automatic safety check refuses a risky
                     // action and tells the AI; nothing waits on a box ("By using the software I'm 'allowing' it").
                     QStringLiteral("--permission-mode"), QStringLiteral("auto"),
                     QStringLiteral("--permission-prompts"), QStringLiteral("none"),
                     // In Claude Code 2.1.304, host alone silently denies prompts in print mode.
                     // The SDK's stdio permission tool delivers can_use_tool control requests.
                     QStringLiteral("--permission-prompt-tool"), QStringLiteral("stdio"),
                     QStringLiteral("--allowedTools"), QStringLiteral("mcp__letitedit__*")};
    args << aiClaudeLockdownArgs() << (c->autonomousNewVideo ? aiClaudeInstructionArgs(s) : aiClaudeChatSettingsArgs(s));
    args << aiClaudeNewVideoToolArgs(c->autonomousNewVideo, c->newVideoChat);
    const QString prompt = s.value("prompt").toString();
    if (QFileInfo::exists(prompt))
        args << QStringLiteral("--append-system-prompt-file") << prompt;
    args << aiClaudeChoiceArgs(s);
    return args;
}

// The connector host speaks the protocol to the AI and these same lines to this chat (bridge/acp_host.py).
static QStringList aiConnectorChatArgs(AiChat *c, const QString &engine, const QString &work)
{
    QStringList args{aiRootPath(QStringLiteral("bridge/acp_host.py")), QStringLiteral("chat"), QStringLiteral("--ai"), engine,
                     QStringLiteral("--work"), work};
    if (!c->procModel.isEmpty())
        args << QStringLiteral("--model") << c->procModel;
    if (!c->procEffort.isEmpty())
        args << QStringLiteral("--effort") << c->procEffort;
    if (c->sessionStarted)
        args << QStringLiteral("--resume") << c->sessionId;
    if (c->autonomousNewVideo)
        args << QStringLiteral("--autonomous");
    const QString project = c->window ? QFileInfo(c->window->fileName()).absolutePath() : QString();
    const QString writeDir = !c->autonomousWriteDir.isEmpty() ? c->autonomousWriteDir
                             : c->window && !c->window->fileName().isEmpty() ? project : QString();
    if (!writeDir.isEmpty())
        args << QStringLiteral("--write-dir") << writeDir;
    return args;
}

// The program's lines go to aiChatHandleLine; its end, while a request is running, fails the request.
static void aiChatListen(AiChat *c)
{
    QObject::connect(c->proc, &QProcess::readyReadStandardOutput, c->dock, [c]() {
        c->buffer += c->proc->readAllStandardOutput();
        int nl;
        while ((nl = c->buffer.indexOf('\n')) >= 0) {
            const QByteArray line = c->buffer.left(nl).trimmed();
            c->buffer.remove(0, nl + 1);
            if (line.isEmpty())
                continue;
            const QJsonDocument doc = QJsonDocument::fromJson(line);
            if (doc.isObject())
                aiChatHandleLine(c, doc.object());
        }
    });
    QObject::connect(c->proc, &QProcess::finished, c->dock, [c](int code, QProcess::ExitStatus) {
        const QString err = QString::fromUtf8(c->proc->readAllStandardError()).trimmed();
        if (c->busy && aiClaudeRetrySpeed(c, err))
            return;
        if (c->busy) {
            const QString e = err.isEmpty() ? QStringLiteral("%1 stopped (exit %2).").arg(aiChatEngineName()).arg(code) : err.right(400);
            aiChatAdd(c, QStringLiteral("error"), e);
            aiChatEndRequest(c, QStringLiteral("failed"), e);
        }
        c->proc->deleteLater();
        c->proc = nullptr;
        aiChatSetBusy(c, false);
    });
}

static bool aiChatStart(AiChat *c)
{
    const QJsonObject s = aiRunSettings(c);
    const QString engine = aiChatEngineId(s);
    const bool connector = aiEngineIsConnector(engine);
    const QString claude = s.value("claude").toString();
    if (!connector && !QFileInfo::exists(claude)) {
        aiChatAdd(c, QStringLiteral("error"), QStringLiteral("Claude Code wasn't found (%1). Use Menu > AI > Connect Your AI "
                                                             "to find it or to switch to ChatGPT (Codex).").arg(claude));
        return false;
    }
    const QString work = s.value("work_dir").toString();
    QDir().mkpath(work);
    if (connector && !c->sessionStarted && s.value("view_mode").toString() != QLatin1String("bubbles"))
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("%1 shows here as chat bubbles: it has no terminal screen.").arg(aiEngineShortName(engine)));
    const QString mcpConfig = aiChatWriteMcpConfig(s, work);
    const QJsonObject resolved = aiResolvedChoice(s); // Auto as the model and effort it runs on (T331 P10)
    c->procModel = resolved.value(aiChatModelKeyOf(engine)).toString().trimmed();
    c->procEffort = resolved.value(aiChatEffortKeyOf(engine)).toString().trimmed();
    c->procSpeed = aiSpeedValue(s, engine);
    QStringList args;
    if (connector) {
        args = aiConnectorChatArgs(c, engine, work);
    } else {
        args = aiClaudeChatArgs(c, s, mcpConfig);
        if (c->sessionStarted)
            args << QStringLiteral("--resume") << c->sessionId;
        else
            args << QStringLiteral("--session-id") << c->sessionId;
    }
    c->proc = new QProcess(c->dock);
    c->proc->setProgram(connector ? s.value("python").toString() : claude);
    c->proc->setArguments(args);
    c->proc->setWorkingDirectory(work);
    auto env = QProcessEnvironment::systemEnvironment();
    env.remove(QStringLiteral("LETITEDIT_OWNER"));
    const QString path = aiChatPythonPath(s);
    if (!path.isEmpty())
        env.insert(QStringLiteral("PATH"), path);
    if (!connector) {
        for (const QString &extra : aiClaudeLongToolEnvironment())
            env.insert(extra.section(QLatin1Char('='), 0, 0), extra.section(QLatin1Char('='), 1));
    }
    c->proc->setProcessEnvironment(env);
    c->backgroundTasks.clear();
    aiChatListen(c);
    c->proc->start();
    if (!c->proc->waitForStarted(15000)) {
        aiChatAdd(c, QStringLiteral("error"), QStringLiteral("Could not start %1: ").arg(ConnectAi::programName(engine)) + c->proc->errorString());
        c->proc->deleteLater();
        c->proc = nullptr;
        return false;
    }
    return true;
}

// ------------------------------------------------------------------ Codex CLI (panel.json "engine": "codex")
// The Codex app-server stays open across turns. It uses the person's configuration and other MCP servers.

static void aiCodexTurnEnded(AiChat *c, const QString &outcome = QStringLiteral("answered"),
                             const QString &error = QString())
{
    c->turnOpen = false;
    c->live = -1;
    aiChatEndRequest(c, outcome, error);
    if (outcome == QLatin1String("answered"))
        ConnectAi::record(QStringLiteral("codex"), true, QStringLiteral("answered in the chat"));
    aiChatSetBusy(c, false);
    aiVoiceTurnDone(c);
}

#include "letitedit/chat/aicodexserver.h"

static void aiChatRefreshHistory(AiChat *c);

// Ends the running Claude Code between two turns. The conversation is saved on disk; the next start resumes it.
static void aiChatStopClaude(AiChat *c)
{
    if (!c->proc)
        return;
    c->busy = false; // finished() then reports nothing as an error
    QObject::disconnect(c->proc, &QProcess::readyReadStandardOutput, nullptr, nullptr); // what it says on the way out
    c->buffer.clear();
    c->proc->closeWriteChannel(); // the end of its input: it exits
    if (!c->proc->waitForFinished(8000) && c->proc) {
        c->proc->kill();
        c->proc->waitForFinished(5000); // its finished() handler clears c->proc
    }
    if (c->proc) { // never reported finishing: let it go
        QObject::disconnect(c->proc, nullptr, nullptr, nullptr);
        c->proc->deleteLater();
        c->proc = nullptr;
    }
    c->codexReady = false;
    c->codexTurnId.clear();
}

static void aiChatSwitchRecord(AiChat *c, const QJsonObject &record)
{
    if (c->busy) {
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("Finish or stop this reply before switching chats."));
        return;
    }
    aiTerminalStop(c);
    if (c->proc)
        aiChatStopClaude(c);
    aiChatSaveCurrent(c);
    const QString engine = record.value("engine").toString();
    const QJsonObject settings = aiChatSettings();
    if (!engine.isEmpty() && settings.value("engine").toString() != engine && aiEngineHere(settings, engine))
        aiChatSaveSettings(QJsonObject{{"engine", engine}});
    aiChatLoadRecord(c, record);
    aiChatRender(c);
    aiChatRefreshChoices(c);
    aiChatRefreshHistory(c);
    aiChatSyncMode(c);
    if (aiTerminalMode()) aiTerminalStart(c);
}

static void aiChatRefreshHistory(AiChat *c)
{
    if (!c->historyButton)
        return;
    QMenu *menu = c->historyButton->menu();
    menu->clear();
    QList<QJsonObject> current, noProject;
    for (const QJsonValue &v : c->history) {
        const QJsonObject record = v.toObject();
        if (record.value("project").toString() == c->projectKey)
            current.append(record);
        else if (record.value("project").toString().isEmpty())
            noProject.append(record);
    }
    const auto byRecent = [](const QJsonObject &a, const QJsonObject &b) {
        return a.value("updated").toString() > b.value("updated").toString();
    };
    std::sort(current.begin(), current.end(), byRecent);
    std::sort(noProject.begin(), noProject.end(), byRecent);
    const auto addGroup = [c, menu](const QString &name, const QList<QJsonObject> &records) {
        if (records.isEmpty())
            return;
        QAction *heading = menu->addAction(name);
        heading->setEnabled(false);
        for (const QJsonObject &record : records) {
            QString label = record.value("title").toString(QStringLiteral("New chat"));
            label += QStringLiteral(" · ") + aiEngineShortName(record.value("engine").toString(QStringLiteral("claude")));
            QAction *action = menu->addAction(label);
            action->setObjectName(QStringLiteral("aiChatHistory:") + record.value("id").toString());
            action->setCheckable(true);
            action->setChecked(record.value("id").toString() == c->chatId);
            QObject::connect(action, &QAction::triggered, c->dock, [c, record]() { aiChatSwitchRecord(c, record); });
        }
    };
    addGroup(c->projectKey.isEmpty() ? QStringLiteral("Chats without a project") : QStringLiteral("This project"), current);
    if (!c->projectKey.isEmpty()) {
        menu->addSeparator();
        addGroup(QStringLiteral("Chats without a project"), noProject);
    }
    if (c->sessionStarted && !c->sessionId.isEmpty() && !aiEngineIsConnector(c->engine)) {
        menu->addSeparator();
        QAction *external = menu->addAction(c->engine == QLatin1String("codex")
            ? QStringLiteral("Continue in Codex") : QStringLiteral("Continue in Claude Code"));
        QObject::connect(external, &QAction::triggered, c->dock, [c]() {
            const QJsonObject s = aiChatSettings();
            const QString exe = s.value(c->engine == QLatin1String("codex") ? "codex" : "claude").toString();
            if (exe.isEmpty())
                return;
            if (c->proc && !c->busy)
                aiChatStopClaude(c);
            QStringList args{QStringLiteral("/c"), QStringLiteral("start"), QString(), QStringLiteral("cmd.exe"),
                             QStringLiteral("/k"), exe};
            if (c->engine == QLatin1String("codex"))
                args << aiCodexChoiceArgs(s) << QStringLiteral("resume") << c->sessionId;
            else
                args << QStringLiteral("--resume") << c->sessionId << aiClaudeInstructionArgs(s) << aiClaudeChoiceArgs(s);
            QProcess::startDetached(QStringLiteral("cmd.exe"), args);
        });
    }
}

// What Claude Code or Codex gets for a turn: what the person is looking at, then the message. A spoken message says so,
// and that the reply is read aloud.
static QString aiChatTurnText(MainWindow *window, const QString &message, bool spoken)
{
    return aiChatContext(window)
           + (spoken ? QStringLiteral(" | spoken (push-to-talk, transcribed on this PC; the reply is read aloud)") : QString())
           + QStringLiteral("\n\n") + message;
}

// The request just sent gets its id and is shown: a request the app wrote shows its short summary, with the full text
// it sent behind "Show the details"; what the person typed shows as typed.
static int aiChatBeginRequest(AiChat *c, const QString &message, const QString &summary, bool spoken)
{
    c->turnStart = c->blocks.size();
    ++c->turnNumber;
    if (!c->carrySending)
        c->turnClock.start();
    c->stage.clear();
    AiChatBlock block{QStringLiteral("user"), spoken ? QStringLiteral("(spoken) ") + message : message};
    if (c->carrySending)
        block.kind = QStringLiteral("letitedit");
    if (!summary.trimmed().isEmpty() && summary.trimmed() != message) {
        block.text = summary.trimmed();
        // T300: a first stage sent with its skills attached shows the person's own request (Try again resends it)
        block.detail = c->verbatimBytes >= 0 && !c->verbatimDetail.isEmpty() ? c->verbatimDetail : message;
    }
    c->blocks.append(block);
    c->repaint->start();
    if (!c->carrySending) {
        c->request = c->nextRequest++;
        c->requestEdits = aiBridgeEditCount();
        c->requestSummary = block.text;
        c->speedRetried = c->speedProduced = false;
        c->speedError.clear();
    }
    return c->request;
}

// Why the last request was refused, in words for the person, or "" when an ordinary "try again" fits.
QString aiChatRefusal()
{
    AiChat *c = aiChatInstance();
    return c ? c->refusal : QString();
}

// Whether any AI can take a request now (and, for New video, one new enough for it). False: the reason is the chat's
// refusal and its status line.
static bool aiChatCanTake(AiChat *c, MainWindow *window, bool autonomousNewVideo)
{
    if (!ConnectAi::anyAi()) {
        // Nothing can take this: the one next step is to set up an AI, and it can go on if they do. (A test window shows no
        // dialog here, since the request waits on it.)
        if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
            ConnectAi::show(window);
        if (!ConnectAi::anyAi()) {
            const QString broken = ConnectAi::anyMissingWords();
            c->refusal = broken.isEmpty() ? QStringLiteral("No AI is set up yet. Use Menu > AI > Connect Your AI.") : broken;
            c->status->setText(c->refusal);
            return false;
        }
    }
    if (autonomousNewVideo) {
        c->refusal = ConnectAi::newVideoTooOldWords(aiChatSettings().value("engine").toString());
        if (!c->refusal.isEmpty()) {
            c->status->setText(c->refusal);
            return false;
        }
    }
    return true;
}

// New video's or Learn's first request: a chat of its own with the run's unattended settings. The message as it is sent
// (with its stage-sessions line).
static QString aiChatStartNewVideoRun(AiChat *c, MainWindow *window, QString message)
{
    // A pre-existing normal chat may have Manual/on-request permissions.
    // New video must not resume it, and normal chat must not inherit this
    // run's unattended policy afterwards.
    if (aiTerminalMode())
        aiTerminalStop(c);
    else if (c->proc)
        aiChatStopClaude(c);
    aiChatSaveCurrent(c);
    aiChatNewRecord(c, c->projectKey);
    c->autonomousNewVideo = true;
    const QString learnJob = window->property("letitedit:learnJob").toString();
    c->autonomousWriteDir = learnJob.isEmpty()
        ? window->property("letitedit:newVideoFolder").toString()
        : QFileInfo(learnJob).absolutePath();
    // New video's and Learn's chats keep this on every later turn; Live Review's round ends it (aiChatLiveEnd)
    c->newVideoChat = !c->liveReviewHold;
    c->carryAllowed = learnJob.isEmpty();
    c->newVideoMakes = learnJob.isEmpty();
    c->carryPending = c->carrySending = c->carryStopped = c->carryHumanInput = false;
    c->carryCount = 0;
    c->limitWaits = 0;
    aiChatLimitClear(c);
    c->carryStarted = QDateTime::currentMSecsSinceEpoch();
    c->carryEngine = aiChatEngineId(aiChatSettings());
    c->carryModel = aiChatSettings().value(aiChatModelKeyOf(c->carryEngine)).toString();
    c->carryEffort = aiChatSettings().value(aiChatEffortKeyOf(c->carryEngine)).toString();
    // T194: one conversation per stage when letitedit starts the AI itself (not a connector) for a video that isn't
    // Turbo: the request asks for a hand-over after each big stage (letitedit-firstcut FIRST-1s), and the carry-on
    // check starts the next stage in a fresh session (aiNewVideoFreshSession). A long conversation re-reads all of
    // itself on every step; a fresh one reads the files and the hand-over.
    c->stageSessions = learnJob.isEmpty() && !aiEngineIsConnector(c->carryEngine)
        && !message.contains(QStringLiteral("turbo: on"));
    // T294: lean stage hand-offs (chat/ainewvideolean.h), off by default: a run that takes one conversation per stage
    // also hands each stage over through a checked hand-off file when the switch is on
    c->leanStages = c->stageSessions && aiLeanStageHandoffsOn();
    // Home's Try again sends the request back as it was sent, line and all: one line, never two (stagesessionsline.h)
    message = aiNewVideoWithSessionsLine(message, c->stageSessions, c->leanStages);
    c->newVideoRequest = c->newVideoMakes ? message : QString();
    c->runSessions = QStringList{c->sessionId};
    aiLeanStart(c);
    if (c->carryBar)
        c->carryBar->hide();
    aiChatSaveCurrent(c);
    return message;
}

// A message while the AI is still on the last one: it goes into that turn (a steer), or next in line for an AI that
// takes one message at a time.
static int aiChatSteer(AiChat *c, MainWindow *window, const QString &message)
{
    if (c->autonomousNewVideo)
        c->carryHumanInput = true;
    c->blocks.append({QStringLiteral("user"), message});
    c->repaint->start();
    if (aiTerminalMode() && c->terminal && c->terminal->running()) {
        c->terminal->submit(aiChatContext(window) + QStringLiteral("\n\n") + message);
    } else if (!qEnvironmentVariable("LETITEDIT_QA_MOCK_AI").isEmpty()) {
        QFile log(qEnvironmentVariable("LETITEDIT_QA_MOCK_AI"));
        if (log.open(QIODevice::Append))
            log.write(QJsonDocument(QJsonObject{{"steer", true}, {"text", message}, {"unattended", c->autonomousNewVideo}})
                          .toJson(QJsonDocument::Compact) + '\n');
    } else if (c->engine == QLatin1String("codex")) {
        const QString content = aiChatContext(window) + QStringLiteral("\n\n") + message;
        if (c->codexTurnId.isEmpty())
            c->queued.append(message);
        else {
            const int rpc = aiCodexRpc(c, QStringLiteral("turn/steer"),
                                        QJsonObject{{"threadId", c->sessionId},
                                                    {"expectedTurnId", c->codexTurnId},
                                                    {"input", aiCodexInput(content)}}, QStringLiteral("steer"));
            c->codexSteers.insert(rpc, message);
        }
    } else if (aiEngineIsConnector(c->engine)) {
        c->queued.append(message);
        if (!c->typedTarget.isEmpty())
            c->queuedTargets.insert(message, c->typedTarget);
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("%1 takes one message at a time: this one goes next, when it finishes.").arg(aiEngineShortName(c->engine)));
    } else if (c->proc) {
        c->proc->write(aiClaudeEnvelope(aiChatContext(window) + QStringLiteral("\n\n") + message));
    }
    return c->request;
}

// The mocked AI's answer to request id, unless it was stopped meanwhile (aiChatMockRequest).
static void aiChatMockAnswer(AiChat *c, int id)
{
    if (c->request != id)
        return; // stopped meanwhile
    QString outcome = qEnvironmentVariable("LETITEDIT_QA_MOCK_AI_OUTCOME", QStringLiteral("answered"));
    QString reply = qEnvironmentVariable("LETITEDIT_QA_MOCK_AI_REPLY");
    // QA: LETITEDIT_QA_MOCK_AI_NEXT=<file>: {"outcome", "reply"} for this one answer, then the file is gone (a
    // journey makes one turn end with a usage limit and the next one answer, T193)
    QFile next(qEnvironmentVariable("LETITEDIT_QA_MOCK_AI_NEXT"));
    if (!next.fileName().isEmpty() && next.open(QIODevice::ReadOnly)) {
        const QJsonObject once = QJsonDocument::fromJson(next.readAll()).object();
        next.close();
        next.remove();
        outcome = once.value(QStringLiteral("outcome")).toString(outcome);
        reply = once.value(QStringLiteral("reply")).toString(reply);
    }
    if (outcome == QLatin1String("failed")) {
        const QString error = reply.isEmpty() ? QStringLiteral("(test failure: the AI is mocked)") : reply;
        aiChatAdd(c, QStringLiteral("error"), error);
        aiChatEndRequest(c, outcome, error);
    } else {
        aiChatAdd(c, QStringLiteral("claude"), reply.isEmpty() ? QStringLiteral("(test answer: the AI is mocked)") : reply);
        aiChatEndRequest(c, outcome == QLatin1String("cancelled") ? outcome : QStringLiteral("answered"));
    }
    aiChatSetBusy(c, false);
}

// QA hook: LETITEDIT_QA_MOCK_AI=<file> stands in for the AI. The request is appended to that file (one JSON line),
// the chat shows it, stays busy for LETITEDIT_QA_MOCK_AI_MS (1500) and answers LETITEDIT_QA_MOCK_AI_REPLY, so a
// journey check never spends the person's subscription. LETITEDIT_QA_MOCK_AI_OUTCOME=failed|cancelled ends the
// request that way instead of with an answer.
static int aiChatMockRequest(AiChat *c, MainWindow *window, const QString &mock, const QString &message,
                             const QString &summary, bool spoken)
{
    // QA: LETITEDIT_QA_MOCK_AI_REFUSE=<file>: while that file exists the AI can't take a request (as when its
    // program is missing), so a check can see what a failed send leaves behind and then send again
    const QString refuse = qEnvironmentVariable("LETITEDIT_QA_MOCK_AI_REFUSE");
    if (!refuse.isEmpty() && QFileInfo::exists(refuse)) {
        aiChatAdd(c, QStringLiteral("error"), QStringLiteral("(test: the AI could not take the request)"));
        return 0;
    }
    // T294: a lean run's fresh Codex thread is named by Codex when it starts; the mock names one as Codex would
    const bool leanCodex = c->leanStages && c->engine == QLatin1String("codex")
                           && c->leanTransition.value(QStringLiteral("state")).toString() == QLatin1String("launching");
    // T300: a stage's first message is checked as a real transport checks it, and logged as it would be written
    QString verbatim;
    const int exact = aiVerbatimTake(c, message, &verbatim);
    if (exact < 0)
        return 0;
    if (leanCodex)
        c->sessionId = QStringLiteral("mock-codex-thread-") + QUuid::createUuid().toString(QUuid::WithoutBraces);
    QFile log(mock);
    if (log.open(QIODevice::Append)) {
        log.write(QJsonDocument(QJsonObject{{"time", QDateTime::currentDateTime().toString(Qt::ISODateWithMs)},
                                            {"context", exact ? QString() : aiChatContext(window)},
                                            {"verbatim", exact == 1},
                                            {"engine", aiChatEngineId(aiChatSettings())},
                                            {"summary", summary},
                                            {"text", message},
                                            // what a real AI would have been started with this turn (T181)
                                            {"unattended", c->autonomousNewVideo},
                                            {"new_video_chat", c->newVideoChat},
                                            {"write_dir", c->autonomousWriteDir},
                                            {"chat", c->chatId},
                                            // T194: which conversation a real AI would have taken this turn in
                                            {"session", c->sessionId},
                                            {"session_started", c->sessionStarted}})
                      .toJson(QJsonDocument::Compact)
                  + '\n');
    }
    if (leanCodex) {
        c->sessionStarted = true;
        aiLeanSessionCreated(c);
    }
    const int id = aiChatBeginRequest(c, message, summary, spoken);
    aiVerbatimClear(c);
    aiChatSetBusy(c, true);
    aiChatRevealDock(c);
    const int ms = qEnvironmentVariableIsSet("LETITEDIT_QA_MOCK_AI_MS") ? qEnvironmentVariableIntValue("LETITEDIT_QA_MOCK_AI_MS")
                                                                        : 1500;
    QTimer::singleShot(ms, c->dock, [c, id]() { aiChatMockAnswer(c, id); });
    return id;
}

// ConPTY accepts input during startup, but the TUI may not be ready for it (a slow PC, many MCP servers).
// Wait at least 5 s and for the screen to settle before sending a New video or Review request. A spinner
// never goes quiet, so stop waiting after 30 s.
static void aiTerminalSubmitWhenSettled(AiChat *c, int id, const QString &content)
{
    auto waiting = new QTimer(c->dock);
    waiting->setInterval(500);
    auto since = std::make_shared<QElapsedTimer>();
    since->start();
    auto lastBytes = std::make_shared<qint64>(-1);
    auto quietTicks = std::make_shared<int>(0);
    const bool automaticCarry = c->carrySending;
    const QString sendingSpeed = c->procSpeed;
    QObject::connect(waiting, &QTimer::timeout, c->dock, [c, id, content, waiting, since, lastBytes, quietTicks, automaticCarry, sendingSpeed]() {
        if (c->request != id || !c->terminal || !c->terminal->running() || c->procSpeed != sendingSpeed) {
            waiting->stop();
            waiting->deleteLater();
            return;
        }
        if (automaticCarry && (!c->carryAllowed || c->carryHumanInput || c->recording || aiNewVideoChoiceChanged(c))) {
            waiting->stop();
            waiting->deleteLater();
            aiNewVideoStopped(c, QStringLiteral("letitedit did not send anything because you started typing, stopped, or changed your AI choice."));
            aiChatEndRequest(c, QStringLiteral("answered"), QString());
            aiChatSetBusy(c, false);
            return;
        }
        const qint64 bytes = c->terminal->receivedBytes();
        *quietTicks = bytes == *lastBytes ? *quietTicks + 1 : 0;
        *lastBytes = bytes;
        if ((since->elapsed() >= 5000 && bytes > 0 && *quietTicks >= 2) || since->elapsed() >= 30000) {
            waiting->stop();
            waiting->deleteLater();
            c->terminal->submit(content);
        }
    });
    waiting->start();
}

// A request in the AI's real program screen (aiTerminalMode).
static int aiTerminalRequest(AiChat *c, MainWindow *window, const QJsonObject &s, const QString &message,
                             const QString &summary, bool spoken, bool autonomousNewVideo)
{
    const QString engine = aiChatEngineId(s);
    if (!c->engine.isEmpty() && c->engine != engine) {
        aiTerminalStop(c);
        aiChatSaveCurrent(c);
        aiChatNewRecord(c, c->projectKey);
        if (!autonomousNewVideo)
            c->autonomousNewVideo = false; // the person changed AI: a new chat, under their own rules
    }
    c->engine = engine;
    QString verbatim;
    const int exact = aiVerbatimTake(c, message, &verbatim); // T300: a stage's first message, word for word
    if (exact < 0)
        return 0;
    if (!aiTerminalStart(c)) return 0;
    const int id = aiChatBeginRequest(c, message, summary, spoken);
    aiVerbatimClear(c);
    const QString content = exact ? verbatim : aiChatContext(window)
        + (spoken ? QStringLiteral(" | spoken (push-to-talk, transcribed on this PC)") : QString())
        + QStringLiteral("\n\n") + message;
    c->retryContent = content;
    aiChatRevealDock(c);
    aiChatSetBusy(c, true);
    aiTerminalSubmitWhenSettled(c, id, content);
    return id;
}

// Another AI chosen since the last request (chat bubbles): its own chat, kept apart in the history.
static void aiChatFollowEngine(AiChat *c, const QString &engine, bool autonomousNewVideo)
{
    if (c->engine.isEmpty() || c->engine == engine)
        return;
    // Keep the previous engine's chat in history and start a separate CLI session.
    if (c->proc) {
        aiChatStopClaude(c);
    }
    aiChatSaveCurrent(c);
    aiChatNewRecord(c, c->projectKey);
    if (!autonomousNewVideo)
        c->autonomousNewVideo = false; // the person changed AI: a new chat, under their own rules
    c->activeModel.clear();
    c->tools = QJsonArray();
    c->permissionMode.clear();
    aiChatRefreshChoices(c);
    aiChatRender(c);
}

// A request to Codex (its app-server, aicodexserver.h).
static int aiCodexRequest(AiChat *c, MainWindow *window, const QString &engine, const QString &message,
                          const QString &summary, bool spoken)
{
    c->engine = engine;
    QString verbatim;
    const int exact = aiVerbatimTake(c, message, &verbatim); // T300: a stage's first message, word for word
    if (exact < 0)
        return 0;
    const QString content = exact ? verbatim : aiChatTurnText(window, message, spoken);
    c->spokenTurn = spoken;
    const int id = aiChatBeginRequest(c, message, summary, spoken);
    aiVerbatimClear(c);
    if (!aiCodexAppSend(c, content)) {
        aiChatEndRequest(c, QStringLiteral("failed"), QStringLiteral("Codex could not start."));
        return 0;
    }
    c->live = -1;
    aiChatSetBusy(c, true);
    aiChatRevealDock(c);
    return id;
}

// A request to Claude Code, or to an AI through a connector (the same lines).
static int aiClaudeRequest(AiChat *c, MainWindow *window, const QJsonObject &s, const QString &engine,
                           const QString &message, const QString &summary, bool spoken)
{
    c->engine = engine;
    const QJsonObject resolved = aiResolvedChoice(s); // Auto's Max on every stage changes what it runs on too
    if (c->proc && (resolved.value(aiChatModelKeyOf(engine)).toString().trimmed() != c->procModel
                    || resolved.value(aiChatEffortKeyOf(engine)).toString().trimmed() != c->procEffort
                    || aiSpeedValue(s, engine) != c->procSpeed))
        aiChatStopClaude(c); // another model or effort: the same conversation goes on in a new Claude Code
    QString verbatim;
    const int exact = aiVerbatimTake(c, message, &verbatim); // T300: a stage's first message, word for word
    if (exact < 0)
        return 0;
    if (!c->proc && !aiChatStart(c))
        return 0;
    c->spokenTurn = spoken;
    const int id = aiChatBeginRequest(c, message, summary, spoken);
    aiVerbatimClear(c);
    const QString content = exact ? verbatim : aiChatTurnText(window, message, spoken);
    c->retryContent = content;
    c->proc->write(aiClaudeEnvelope(content));
    c->live = -1;
    aiChatSetBusy(c, true);
    aiChatRevealDock(c);
    return id;
}

// Send a message: the request's id (0 when the AI could not take it). summary: a short line the chat shows for a
// request the app wrote ("Make my first cut with Word pop"); the AI gets the whole text. Also used by the bridge's
// chat_send for automation and tests.
int aiChatRequest(MainWindow *window, const QString &text, const QString &summary, bool spoken,
                         bool autonomousNewVideo)
{
    AiChat *c = aiChatInstance();
    // T300: a stage's first message goes word for word (its closing line ends with a newline, which trimming would cut)
    QString message = c && c->verbatimBytes >= 0 ? text : text.trimmed();
    if (!c || message.trimmed().isEmpty())
        return 0;
    if (c->stageStartPending) {
        // T300: the first stage's message is being prepared; nothing else goes until it has
        c->refusal = QStringLiteral("letitedit is still preparing your video's first stage. Send this again in a moment.");
        c->status->setText(c->refusal);
        return 0;
    }
    if (aiRunnerRefuses(c)) // T331 P11: the runner is getting ready or making the video (chat/ainewvideorunner.h)
        return 0;
    if (!c->carrySending && c->carryPending) {
        c->carryHumanInput = true;
        return 0;
    }
    if (c->busy && !summary.isEmpty())
        return 0; // an app button needs its own outcome; it cannot become a typed steer
    c->refusal.clear();
    if (c->liveReviewHold && !c->busy && summary.isEmpty())
        aiChatLiveEnd(c); // the person typing: ordinary permissions again
    if (!aiChatCanTake(c, window, autonomousNewVideo))
        return 0;
    if (!autonomousNewVideo && !c->busy) {
        // T331 P11: Continue the edit on a video the runner was making goes to the runner again
        const int carried = aiRunnerCarryOn(c, window, message);
        if (carried >= 0)
            return carried;
    }
    if (autonomousNewVideo) {
        const QString asWritten = message;
        message = aiChatStartNewVideoRun(c, window, message);
        // T331 P11: built on disk by the session runner and opened at the end (chat/ainewvideorunner.h; off by default)
        if (aiRunnerWanted(c, message))
            return aiRunnerBegin(c, window, asWritten, message, summary, spoken);
        // T300: the first stage starts complete (chat/ainewvideostart.h), prepared in the background
        if (aiStageStartWanted(c, message))
            return aiStageStartBegin(c, window, message, summary, spoken);
    } else if (c->newVideoChat && !c->busy && !c->liveReviewHold) {
        // Another turn of New video's or Learn's own chat: the app's carry-on, Continue the edit, a message the person
        // typed, or the chat reopened after a restart. It runs with the same unattended settings as the first turn
        // (T181: a plain message to a resumed New video chat went back to ordinary permissions and asked 76 times).
        c->autonomousNewVideo = true;
    }
    return aiChatDispatch(c, window, message, summary, spoken, autonomousNewVideo);
}

static int aiChatDispatchTo(AiChat *c, MainWindow *window, const QString &message, const QString &summary, bool spoken,
                            bool autonomousNewVideo);

// The request goes to the AI: as a steer into the turn it is on, to the mocked AI, or to the AI's program.
static int aiChatDispatch(AiChat *c, MainWindow *window, const QString &message, const QString &summary, bool spoken,
                          bool autonomousNewVideo)
{
    const int id = aiChatDispatchTo(c, window, message, summary, spoken, autonomousNewVideo);
    aiVerbatimClear(c); // a word-for-word send is for this one message only
    return id;
}

static int aiChatDispatchTo(AiChat *c, MainWindow *window, const QString &message, const QString &summary, bool spoken,
                            bool autonomousNewVideo)
{
    // T193: the AI's programs started for this turn carry the run's name, so their tool calls show on this window's
    // card and nobody else's (bridge/progress_feed.py). A chat that isn't New video's names no run.
    if (!c->busy) {
        const QString run = aiChatProgressRun();
        if (run.isEmpty())
            qunsetenv("LETITEDIT_PROGRESS_RUN");
        else
            qputenv("LETITEDIT_PROGRESS_RUN", run.toUtf8());
    }
    if (c->busy)
        return aiChatSteer(c, window, message);
    const QString mock = qEnvironmentVariable("LETITEDIT_QA_MOCK_AI");
    if (!mock.isEmpty())
        return aiChatMockRequest(c, window, mock, message, summary, spoken);
    c->speedNormal = c->speedRetried = c->speedProduced = false;
    c->speedRestartPending = false;
    c->speedError.clear();
    const QJsonObject s = aiChatSettings();
    if (aiTerminalMode())
        return aiTerminalRequest(c, window, s, message, summary, spoken, autonomousNewVideo);
    const bool codex = aiChatIsCodex(s);
    const QString engine = aiChatEngineId(s);
    aiChatFollowEngine(c, engine, autonomousNewVideo);
    if (codex)
        return aiCodexRequest(c, window, engine, message, summary, spoken);
    return aiClaudeRequest(c, window, s, engine, message, summary, spoken);
}

// What the person typed or said (never an app button's request). With something selected in the video the request carries
// it; if it has gone, nothing is sent and they're asked to select it again.
static bool aiChatSend(MainWindow *window, const QString &text, bool spoken = false)
{
    AiChat *c = aiChatInstance();
    auto *preview = window->findChild<PreviewObjects *>();
    if (!c || !preview || !preview->hasTarget() || text.trimmed().isEmpty())
        return aiChatRequest(window, text, QString(), spoken) > 0;
    QString problem;
    c->typedTarget = preview->requestLine(&problem);
    if (!problem.isEmpty()) {
        c->status->setText(problem);
        return false;
    }
    const QString about = preview->chipText();
    const bool sent = aiChatRequest(window, text, QString(), spoken) > 0;
    c->typedTarget.clear();
    if (sent && !about.isEmpty())
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("About: ") + about);
    return sent;
}

// The chip: on the request while typing, in both views. Its Clear makes the request about the whole video.
static void aiChatUpdateTarget(AiChat *c)
{
    auto *preview = c && c->window ? c->window->findChild<PreviewObjects *>() : nullptr;
    if (!c || !c->targetBar || !preview)
        return;
    c->targetBar->setVisible(preview->hasTarget());
    const QString words = preview->chipText();
    c->targetLabel->setText(c->targetLabel->fontMetrics().elidedText(words, Qt::ElideMiddle, 400));
}

// In the real Claude or Codex screen the person presses Enter in the AI's own box. This adds the same line to the end of
// what they typed, just before it's sent. False: the item has gone, so nothing is sent.
static bool aiTerminalAddTarget(AiChat *c, QString *extra)
{
    auto *preview = c && c->window ? c->window->findChild<PreviewObjects *>() : nullptr;
    if (!preview || !preview->hasTarget())
        return true;
    QString problem;
    const QString line = preview->requestLine(&problem);
    if (!problem.isEmpty()) {
        aiChatUpdateTarget(c);
        c->status->setText(problem);
        return false;
    }
    c->typedTarget = line;
    *extra = aiChatContext(c->window);
    c->typedTarget.clear();
    return true;
}

int aiChatReviewBatchSent(const QString &folder)
{
    QFile file(aiChatHistoryPath());
    if (!file.open(QIODevice::ReadOnly))
        return -1;
    const auto history = QJsonDocument::fromJson(file.readAll());
    if (!history.isObject() || !history.object().contains(QStringLiteral("chats")))
        return -1;
    const QString path = QLatin1Char('"') + QDir::fromNativeSeparators(folder) + QLatin1Char('"');
    for (const auto &chat : history.object().value(QStringLiteral("chats")).toArray())
        for (const auto &message : chat.toObject().value(QStringLiteral("messages")).toArray()) {
            const auto entry = message.toObject();
            if (entry.value(QStringLiteral("kind")).toString() == QLatin1String("user")
                && (QDir::fromNativeSeparators(entry.value(QStringLiteral("text")).toString()).contains(path)
                    || QDir::fromNativeSeparators(entry.value(QStringLiteral("detail")).toString()).contains(path)))
                return 1;
        }
    return 0;
}

QJsonObject aiChatState()
{
    AiChat *c = aiChatInstance();
    if (!c)
        return QJsonObject{{"installed", false}};
    QJsonArray tail;
    for (int i = qMax(0, int(c->blocks.size()) - 30); i < c->blocks.size(); ++i) {
        QJsonObject m{{"kind", c->blocks[i].kind}, {"text", c->blocks[i].text},
                      {"repeats", c->blocks[i].repeats}};
        if (!c->blocks[i].detail.isEmpty()) {
            m["detail"] = c->blocks[i].detail;
            m["expanded"] = c->blocks[i].expanded;
        }
        tail.append(m);
    }
    QJsonArray outcomes;
    QList<int> ids = c->outcomes.keys();
    std::sort(ids.begin(), ids.end());
    for (int i = qMax(0, int(ids.size()) - 10); i < ids.size(); ++i)
        outcomes.append(c->outcomes.value(ids[i]));
    const QJsonObject s = aiChatSettings();
    const bool codex = aiChatIsCodex(s);
    const QString engine = !c->engine.isEmpty() ? c->engine : aiChatEngineId(s);
    // choice: what the top row holds now (applies from the next message); active_model: what answered last
    const QJsonObject choice{{"engine", aiChatEngineId(s)},
                             {"model", s.value(aiChatModelKeyOf(aiChatEngineId(s))).toString()},
                             {"effort", s.value(aiChatEffortKeyOf(aiChatEngineId(s))).toString()}};
    // the top row as shown: each button's text and its menu (item names for trigger, texts, the ticked one)
    QJsonObject top;
    for (const auto &b : {qMakePair(QStringLiteral("engine"), c->engineButton), qMakePair(QStringLiteral("model"), c->modelButton),
                          qMakePair(QStringLiteral("effort"), c->effortButton)}) {
        if (!b.second)
            continue;
        QJsonArray items;
        for (QAction *a : b.second->menu()->actions())
            items.append(QJsonObject{{"name", a->objectName()}, {"text", a->text()}, {"checked", a->isChecked()},
                                     {"enabled", a->isEnabled()}, {"tip", a->toolTip()}});
        top[b.first] = QJsonObject{{"button", b.second->text()}, {"tip", b.second->toolTip()}, {"items", items}};
    }
    QJsonArray chats;
    for (const QJsonValue &v : c->history) {
        const QJsonObject record = v.toObject();
        if (record.value("project").toString() == c->projectKey)
            chats.append(QJsonObject{{"id", record.value("id")}, {"title", record.value("title")},
                                     {"engine", record.value("engine")}});
    }
    const QString terminalText = c->terminal ? c->terminal->visibleText() : QString();
    const bool terminalWaiting = aiTerminalMode() && c->busy
        && terminalText.contains(QStringLiteral("Do you want to proceed?"))
        && terminalText.contains(QStringLiteral("Esc to cancel"));
    return QJsonObject{{"installed", true}, {"busy", c->busy},
                       {"waiting", c->busy && (c->permissionWaiting || terminalWaiting)},
                       {"running", c->proc != nullptr || (c->terminal && c->terminal->running())},
                       {"review_conversation", c->reviewWatch && c->reviewWatch->isActive()},
                       {"refusal", c->refusal},
                       {"view_mode", aiTerminalMode() ? QStringLiteral("terminal") : QStringLiteral("bubbles")},
                       {"terminal_text", terminalText}, {"engine", engine},
                       {"terminal_received_bytes", c->terminal ? c->terminal->receivedBytes() : 0},
                       {"terminal_sent_bytes", c->terminal ? c->terminal->sentBytes() : 0},
                       {"session", c->sessionId}, {"chat_id", c->chatId}, {"project", c->projectKey},
                       {"chats", chats}, {"history_file", aiChatHistoryPath()},
                       {"scroll_position", c->view->verticalScrollBar()->value()},
                       {"scroll_maximum", c->view->verticalScrollBar()->maximum()},
                       {"follow_bottom", c->followBottom},
                       {"status", c->status->text()}, {"messages", tail},
                       {"choice", choice}, {"active_model", c->activeModel}, {"top_row", top},
                       {"title", c->dock->windowTitle()}, {"menu_text", c->dock->toggleViewAction()->text()},
                       {"placeholder", c->input->placeholderText()}, {"tools", c->tools},
                       {"permission_mode", c->permissionMode}, {"request", c->request}, {"outcomes", outcomes},
                       {"last_permission", c->lastPermission},
                       {"new_video_carries", c->carryCount}, {"new_video_carry_pending", c->carryPending},
                       {"new_video_stopped", c->carryStopped},
                       {"progress_run", aiChatProgressRun()},
                       // T331 P11: New video on the session runner (chat/ainewvideorunner.h)
                       {"new_video_runner", aiRunnerStateJson(c)},
                       {"new_video_limit", c->limitCarryAt ? QJsonObject{{"words", c->limitWords},
                                                                         {"carry_at", double(c->limitCarryAt)}}
                                                           : QJsonObject()},
                       {"new_video_autonomous", c->autonomousNewVideo},
                       // T294: the lean hand-offs' state (only a lean run has more than on: false)
                       {"new_video_lean", c->leanStages ? QJsonObject{{"on", true}, {"run_id", c->leanRunId},
                                                                      {"project", c->leanProject},
                                                                      {"seed_refused", c->leanSeedRefused},
                                                                      {"transition", c->leanTransition},
                                                                      {"repairs", c->leanRepairs},
                                                                      {"acks", c->leanAcks}}
                                                        : QJsonObject{{"on", false}}},
                       {"new_video_chat", c->newVideoChat},
                       // T300: how this run's first stage started (empty: not through the bridge)
                       {"new_video_start", c->stageStart},
                       {"new_video_start_pending", c->stageStartPending},
                       {"talk_button", c->talk ? c->talk->text() : QString()},
                       {"settings_file", QDir::toNativeSeparators(aiChatSettingsPath())}};
}

QString aiChatProgressRun()
{
    AiChat *c = aiChatInstance();
    return c && c->newVideoChat && c->newVideoMakes && !c->chatId.isEmpty() ? QStringLiteral("nv-") + c->chatId : QString();
}

void aiChatStopRun()
{
    AiChat *c = aiChatInstance();
    if (c && c->stop && (c->busy || c->request))
        c->stop->click();
}

bool aiChatCarryOn(MainWindow *window)
{
    AiChat *c = aiChatInstance();
    if (!c || c->busy || !c->newVideoChat || !c->newVideoMakes)
        return false;
    if (!aiChatRequest(window, aiNewVideoCarryWords(), QStringLiteral("Continue the edit"), false, false))
        return false;
    // the person said go on: the run carries on by itself again (its own carry-on, a usage limit's wait)
    c->carryAllowed = true;
    c->carryHumanInput = false;
    c->carryCount = 0;
    c->carryStopped = false;
    if (c->carryBar)
        c->carryBar->hide();
    return true;
}

// ------------------------------------------------------------------ push-to-talk
// The microphone is open only between press and release (or until max_record_s). The recording goes to a temporary
// WAV that bridge/voice_chat.py transcribes on this PC and deletes; the text is sent like a typed message, and the
// reply is read aloud by a Windows voice. Defaults here match voice_chat.DEFAULTS.

QJsonObject aiVoiceSettings()
{
    QJsonObject v = aiChatSettings().value("voice").toObject();
    // F12: no editor command uses it (F8 is the 540p preview); "Hold to talk" in Actions and Shortcuts changes it
    const QJsonObject defaults{{"enabled", true},       {"ptt_key", "F12"},         {"mic_device", ""},
                               {"sample_rate_hz", 16000}, {"max_record_s", 60.0},   {"speak_replies", "spoken"},
                               {"helper", aiRootPath(QStringLiteral("bridge/voice_chat.py"))}};
    for (auto it = defaults.begin(); it != defaults.end(); ++it)
        if (!v.contains(it.key()))
            v[it.key()] = it.value();
    return v;
}

static void aiVoiceSetStatus(AiChat *c, const QString &text)
{
    c->voiceStatus = text;
    if (!c->busy)
        c->status->setText(text);
}

static void aiVoiceHandleReply(AiChat *c, const QJsonObject &r);

static bool aiVoiceHelper(AiChat *c)
{
    if (c->voiceHelper)
        return true;
    const QString python = aiChatSettings().value("python").toString();
    const QString script = aiVoiceSettings().value("helper").toString();
    if (!QFileInfo::exists(python) || !QFileInfo::exists(script)) {
        aiVoiceSetStatus(c, QStringLiteral("Voice helper not found (%1, %2)").arg(python, script));
        return false;
    }
    c->voiceHelper = new QProcess(c->dock);
    c->voiceHelper->setProgram(python);
    c->voiceHelper->setArguments({QStringLiteral("-u"), script, QStringLiteral("serve")});
    c->voiceHelper->setWorkingDirectory(QFileInfo(script).absolutePath());
    QObject::connect(c->voiceHelper, &QProcess::readyReadStandardOutput, c->dock, [c]() {
        if (!c->voiceHelper)
            return;
        c->voiceBuffer += c->voiceHelper->readAllStandardOutput();
        int nl;
        while ((nl = c->voiceBuffer.indexOf('\n')) >= 0) {
            const QByteArray line = c->voiceBuffer.left(nl).trimmed();
            c->voiceBuffer.remove(0, nl + 1);
            const QJsonDocument doc = QJsonDocument::fromJson(line);
            if (doc.isObject())
                aiVoiceHandleReply(c, doc.object());
        }
    });
    QObject::connect(c->voiceHelper, &QProcess::finished, c->dock, [c](int code, QProcess::ExitStatus) {
        if (!c->voiceHelper)
            return;
        const QString err = QString::fromUtf8(c->voiceHelper->readAllStandardError()).trimmed();
        if (code != 0)
            aiVoiceSetStatus(c, QStringLiteral("Voice helper stopped (exit %1) %2").arg(code).arg(err.right(200)));
        c->voiceHelper->deleteLater();
        c->voiceHelper = nullptr;
        c->speaking = false;
    });
    c->voiceHelper->start();
    if (!c->voiceHelper->waitForStarted(15000)) {
        aiVoiceSetStatus(c, QStringLiteral("Could not start the voice helper: ") + c->voiceHelper->errorString());
        c->voiceHelper->deleteLater();
        c->voiceHelper = nullptr;
        return false;
    }
    return true;
}

static void aiVoiceSend(AiChat *c, QJsonObject request)
{
    if (!aiVoiceHelper(c))
        return;
    request["id"] = c->voiceNextId++;
    c->voiceHelper->write(QJsonDocument(request).toJson(QJsonDocument::Compact) + "\n");
}

QAudioDevice aiVoiceDevice(const QString &want)
{
    if (!want.isEmpty())
        for (const QAudioDevice &d : QMediaDevices::audioInputs())
            if (d.description().contains(want, Qt::CaseInsensitive))
                return d;
    return QMediaDevices::defaultAudioInput();
}

bool aiVoiceWriteWav(const QByteArray &pcm, const QAudioFormat &f, const QString &path)
{
    const quint16 channels = quint16(f.channelCount());
    const quint32 rate = quint32(f.sampleRate());
    const quint16 bytes = quint16(f.bytesPerSample());
    const quint16 tag = f.sampleFormat() == QAudioFormat::Float ? 3 : 1;
    QByteArray h;
    auto u32 = [&h](quint32 v) { for (int i = 0; i < 4; ++i) h.append(char((v >> (8 * i)) & 0xff)); };
    auto u16 = [&h](quint16 v) { h.append(char(v & 0xff)); h.append(char((v >> 8) & 0xff)); };
    h.append("RIFF");
    u32(36 + quint32(pcm.size()));
    h.append("WAVEfmt ");
    u32(16);
    u16(tag);
    u16(channels);
    u32(rate);
    u32(rate * channels * bytes);
    u16(quint16(channels * bytes));
    u16(quint16(bytes * 8));
    h.append("data");
    u32(quint32(pcm.size()));
    QSaveFile file(path);
    if (!file.open(QIODevice::WriteOnly))
        return false;
    file.write(h);
    file.write(pcm);
    return file.commit();
}

static void aiVoiceTranscribe(AiChat *c, const QString &wav, bool remove)
{
    aiVoiceSetStatus(c, QStringLiteral("Transcribing on this PC..."));
    aiVoiceSend(c, QJsonObject{{"cmd", "transcribe"}, {"wav", QDir::toNativeSeparators(wav)}, {"delete", remove}});
}

// The push-to-talk key: the "Hold to talk" action's shortcut (Actions and Shortcuts can change it). Key_unknown: none.
static QKeyCombination aiVoiceKey(AiChat *c)
{
    if (!c->talkAction || c->talkAction->shortcut().isEmpty())
        return QKeyCombination(Qt::Key_unknown);
    return c->talkAction->shortcut()[0];
}

// The talk button names the key it listens for.
static void aiVoiceShowKey(AiChat *c)
{
    if (!c->talk)
        return;
    const QString key = c->talkAction ? c->talkAction->shortcut().toString(QKeySequence::NativeText) : QString();
    c->talk->setText(key.isEmpty() ? QStringLiteral("Hold to talk") : QStringLiteral("Hold to talk (%1)").arg(key));
}

static void aiVoiceStart(AiChat *c)
{
    if (c->recording)
        return;
    const QJsonObject v = aiVoiceSettings();
    if (!v.value("enabled").toBool(true))
        return;
    if (c->speaking)
        aiVoiceSend(c, QJsonObject{{"cmd", "stop_speaking"}});
    // QA hook: LETITEDIT_QA_PTT_WAV stands in for the microphone: nothing is recorded, that file is the take
    const bool qaTake = !qEnvironmentVariableIsEmpty("LETITEDIT_QA_PTT_WAV");
    const QAudioDevice device = qaTake ? QAudioDevice() : aiVoiceDevice(v.value("mic_device").toString());
    if (device.isNull() && !qaTake) {
        aiVoiceSetStatus(c, QStringLiteral("No microphone found."));
        return;
    }
    QAudioFormat format;
    format.setSampleRate(v.value("sample_rate_hz").toInt(16000));
    format.setChannelCount(1);
    format.setSampleFormat(QAudioFormat::Int16);
    if (!qaTake && !device.isFormatSupported(format))
        format = device.preferredFormat();
    c->recordFormat = format;
    c->micName = qaTake ? QStringLiteral("the QA recording") : device.description();
    c->recorded = new QBuffer(c->dock);
    c->recorded->open(QIODevice::WriteOnly);
    c->mic = nullptr;
    if (!qaTake) {
        c->mic = new QAudioSource(device, format, c->dock);
        c->mic->start(c->recorded);
    }
    c->recording = true;
    c->recordClock.start();
    c->recordLimit->start(int(v.value("max_record_s").toDouble(60.0) * 1000));
    c->talk->setText(QStringLiteral("Listening... (release to send)"));
    aiVoiceSetStatus(c, QStringLiteral("Listening (%1)").arg(c->micName));
    aiVoiceSend(c, QJsonObject{{"cmd", "warm"}}); // loads the speech model while the person talks
}

static void aiVoiceStop(AiChat *c, bool send = true)
{
    if (!c->recording)
        return;
    c->recording = false;
    c->keyTalking = false;
    c->recordLimit->stop();
    if (c->mic) {
        c->mic->stop();
        c->mic->deleteLater();
        c->mic = nullptr;
    }
    const QByteArray pcm = c->recorded->data();
    c->recorded->deleteLater();
    c->recorded = nullptr;
    aiVoiceShowKey(c);
    if (!send) {
        aiVoiceSetStatus(c, QString());
        return;
    }
    const QString qaWav = qEnvironmentVariable("LETITEDIT_QA_PTT_WAV");
    if (pcm.isEmpty() && qaWav.isEmpty()) {
        aiVoiceSetStatus(c, QStringLiteral("Nothing was recorded from %1.").arg(c->micName));
        return;
    }
    const QString dir = QDir::tempPath() + QStringLiteral("/letitedit-voice");
    QDir().mkpath(dir);
    const QString path = dir + QStringLiteral("/ptt-") + QUuid::createUuid().toString(QUuid::Id128) + QStringLiteral(".wav");
    if (!qaWav.isEmpty() ? !QFile::copy(qaWav, path) : !aiVoiceWriteWav(pcm, c->recordFormat, path)) {
        aiVoiceSetStatus(c, QStringLiteral("Could not write the recording to ") + path);
        return;
    }
    aiVoiceTranscribe(c, path, true);
}

static void aiVoiceHandleReply(AiChat *c, const QJsonObject &r)
{
    const QString cmd = r.value("cmd").toString();
    if (cmd == QLatin1String("transcribe")) {
        c->lastTranscription = r;
        if (!r.value("ok").toBool()) {
            aiVoiceSetStatus(c, QStringLiteral("Couldn't transcribe: ") + r.value("error").toString());
            return;
        }
        const QString text = r.value("text").toString().trimmed();
        if (text.isEmpty()) {
            aiVoiceSetStatus(c, QStringLiteral("Didn't hear anything (%1 s of sound above %2 dB).")
                                    .arg(r.value("speech_s").toDouble())
                                    .arg(r.value("silence_threshold_db").toDouble()));
            return;
        }
        c->lastTranscript = text;
        ++c->voiceTurns;
        aiVoiceSetStatus(c, QString());
        if (c->busy || !aiChatSend(c->window, text, true)) {
            c->input->setPlainText(text);
            aiVoiceSetStatus(c, aiChatEngineName() + QStringLiteral(" is still working; what you said is in the box."));
        }
    } else if (cmd == QLatin1String("speak")) {
        if (r.value("started").toBool()) {
            c->speaking = true;
            c->lastSpoken = r.value("text").toString();
        }
        if (r.value("done").toBool())
            c->speaking = false;
        if (!r.value("ok").toBool() && r.contains("error"))
            aiVoiceSetStatus(c, QStringLiteral("Couldn't speak: ") + r.value("error").toString());
    } else if (!r.value("ok").toBool(true) && r.contains("error")) {
        aiVoiceSetStatus(c, QStringLiteral("Voice: ") + r.value("error").toString());
    }
}

static void aiVoiceTurnDone(AiChat *c)
{
    const QString mode = aiVoiceSettings().value("speak_replies").toString();
    const bool say = mode == QLatin1String("always") || (mode == QLatin1String("spoken") && c->spokenTurn);
    c->spokenTurn = false;
    if (!say)
        return;
    QStringList parts;
    for (int i = qMax(0, c->turnStart); i < c->blocks.size(); ++i)
        if (c->blocks[i].kind == QLatin1String("claude") && !c->blocks[i].text.trimmed().isEmpty())
            parts << c->blocks[i].text.trimmed();
    if (!parts.isEmpty())
        aiVoiceSend(c, QJsonObject{{"cmd", "speak"}, {"text", parts.join(QStringLiteral("\n"))}});
}

// Bridge methods voice_state, voice_turn (a WAV file in place of the microphone), voice_press, voice_release,
// voice_speak, voice_stop_speaking.
QJsonObject aiVoiceCommand(MainWindow *window, const QString &method, const QJsonObject &params, QString *error)
{
    Q_UNUSED(window)
    AiChat *c = aiChatInstance();
    if (!c) {
        *error = QStringLiteral("the chat panel is not installed");
        return {};
    }
    if (method == QLatin1String("voice_state")) {
        QJsonArray inputs;
        for (const QAudioDevice &d : QMediaDevices::audioInputs())
            inputs.append(d.description());
        return QJsonObject{{"recording", c->recording},
                           {"recording_ms", c->recording ? double(c->recordClock.elapsed()) : 0.0},
                           {"helper_running", c->voiceHelper != nullptr},
                           {"speaking", c->speaking},
                           {"last_transcript", c->lastTranscript},
                           {"last_spoken", c->lastSpoken},
                           {"transcription", c->lastTranscription},
                           {"voice_turns", c->voiceTurns},
                           {"status", c->voiceStatus},
                           {"chat_busy", c->busy},
                           {"settings", aiVoiceSettings()},
                           {"default_microphone", QMediaDevices::defaultAudioInput().description()},
                           {"microphones", inputs}};
    }
    if (method == QLatin1String("voice_turn")) {
        const QString wav = params.value("wav").toString();
        if (wav.isEmpty() || !QFileInfo::exists(wav)) {
            *error = QStringLiteral("voice_turn needs 'wav': an existing WAV file");
            return {};
        }
        aiVoiceTranscribe(c, wav, params.value("delete").toBool(false));
        return QJsonObject{{"queued", wav}};
    }
    if (method == QLatin1String("voice_press")) {
        aiVoiceStart(c);
        return QJsonObject{{"recording", c->recording}, {"microphone", c->micName}};
    }
    if (method == QLatin1String("voice_release")) {
        aiVoiceStop(c, params.value("send").toBool(true));
        return QJsonObject{{"recording", c->recording}};
    }
    if (method == QLatin1String("voice_speak")) {
        aiVoiceSend(c, QJsonObject{{"cmd", "speak"}, {"text", params.value("text").toString()}});
        return QJsonObject{{"queued", true}};
    }
    if (method == QLatin1String("voice_stop_speaking")) {
        aiVoiceSend(c, QJsonObject{{"cmd", "stop_speaking"}});
        return QJsonObject{{"queued", true}};
    }
    *error = QStringLiteral("unknown method '%1'").arg(method);
    return {};
}

// Hold the push-to-talk key (the "Hold to talk" action's shortcut) while the editor window is active. The key is
// claimed at Qt's shortcut-override stage, so no other command's shortcut fires instead, and the press and the
// release both reach this filter wherever the keyboard focus is. Key repeat is ignored; losing the window (another
// window comes up, the app loses focus) ends the take as a release would.
class AiVoiceKeyFilter : public QObject
{
public:
    AiVoiceKeyFilter(QObject *parent, AiChat *chat)
        : QObject(parent)
        , m_chat(chat)
    {}

protected:
    bool eventFilter(QObject *obj, QEvent *event) override
    {
        const QEvent::Type type = event->type();
        if (type == QEvent::ShortcutOverride || type == QEvent::KeyPress || type == QEvent::KeyRelease) {
            const QKeyCombination want = aiVoiceKey(m_chat);
            if (want.key() == Qt::Key_unknown)
                return QObject::eventFilter(obj, event);
            auto *k = static_cast<QKeyEvent *>(event);
            if (k->key() != want.key())
                return QObject::eventFilter(obj, event);
            // a press needs the key's own modifiers; a release counts however the modifiers were let go
            const Qt::KeyboardModifiers mods = k->modifiers() & ~Qt::KeypadModifier;
            if (type != QEvent::KeyRelease && mods != want.keyboardModifiers())
                return QObject::eventFilter(obj, event);
            if (type == QEvent::KeyRelease && !m_chat->keyTalking)
                return QObject::eventFilter(obj, event);
            QWidget *active = QApplication::activeWindow();
            const bool ours = qApp->property("letitedit:qaKey").toBool() // QA: a key event the bridge injected
                              || (active && (active == m_chat->window || m_chat->window->isAncestorOf(active)));
            if (!ours)
                return QObject::eventFilter(obj, event);
            if (type == QEvent::ShortcutOverride) {
                event->accept(); // ours: delivered as a key press, never as another command's shortcut
                return true;
            }
            if (!k->isAutoRepeat()) {
                if (type == QEvent::KeyPress) {
                    aiVoiceStart(m_chat);
                    m_chat->keyTalking = m_chat->recording;
                } else {
                    aiVoiceStop(m_chat);
                }
            }
            return true;
        }
        if (m_chat->keyTalking && m_chat->recording
            && (type == QEvent::ApplicationDeactivate
                || (type == QEvent::ApplicationStateChange && qApp->applicationState() != Qt::ApplicationActive)
                || (type == QEvent::WindowDeactivate && obj == m_chat->window))) {
            // the key's release would go to another window: what was said so far is sent, as on a release
            aiVoiceStop(m_chat);
        }
        return QObject::eventFilter(obj, event);
    }

private:
    AiChat *m_chat;
};

class AiChatInputFilter : public QObject
{
public:
    AiChatInputFilter(QObject *parent, std::function<void()> onEnter)
        : QObject(parent)
        , m_onEnter(std::move(onEnter))
    {}

protected:
    bool eventFilter(QObject *obj, QEvent *event) override
    {
        if (event->type() == QEvent::KeyPress) {
            auto *k = static_cast<QKeyEvent *>(event);
            if ((k->key() == Qt::Key_Return || k->key() == Qt::Key_Enter) && !(k->modifiers() & Qt::ShiftModifier)) {
                m_onEnter();
                return true;
            }
        }
        return QObject::eventFilter(obj, event);
    }

private:
    std::function<void()> m_onEnter;
};

// ------------------------------------------------------------------ the top row: the AI, its model, its effort

// The AI's name wherever the chat shows it: the panel's title, its menu item and the typing hint (after a switch too).
static void aiChatShowEngine(AiChat *c)
{
    const QString name = aiChatEngineName();
    c->dock->setWindowTitle(QStringLiteral("Chat with ") + name);
    c->dock->toggleViewAction()->setText(QStringLiteral("Chat with ") + name);
    c->input->setPlaceholderText(QStringLiteral("Ask %1 to edit... (Enter to send, Shift+Enter for a new line)").arg(name));
}

// The model button's tooltip names the model that answered last, as the CLI reports it.
static void aiChatShowActiveModel(AiChat *c)
{
    if (!c->modelButton)
        return;
    QString tip = QStringLiteral("Which model answers. Star your default in this menu. A change applies from your next "
                                 "message and keeps the conversation.");
    if (!c->activeModel.isEmpty())
        tip += QStringLiteral("\nAnswering now: %1").arg(c->activeModel);
    const QJsonObject settings = aiChatSettings();
    const QString engine = aiChatEngineId(settings);
    if (!aiSpeedKey(engine).isEmpty()) {
        const QString effective = c->busy && c->engine == engine ? c->procSpeed : aiSpeedValue(settings, engine);
        QString label = effective;
        for (const auto &value : aiSpeedChoices(settings, engine)) {
            const QJsonObject choice = value.toObject();
            if (choice.value("value").toString() == effective)
                label = choice.value("label").toString();
        }
        tip += QStringLiteral("\nSpeed: %1").arg(label);
        const QString saved = settings.value(aiSpeedKey(engine)).toString(QStringLiteral("normal"));
        if (saved != effective)
            tip += QStringLiteral(" (saved: %1; not in effect)").arg(saved);
    }
    c->modelButton->setToolTip(tip);
}

// A top-row button's menu: one item per choice, the current one ticked and shown on the button. The items are named
// for automation (the bridge's trigger): aiChatEngine:codex, aiChatModel:haiku, aiChatEffort:default, ...
static void aiChatFillChoices(QToolButton *button, const QString &kind, const QList<AiChatChoice> &choices,
                              const QString &current, const std::function<void(const QString &)> &pick,
                              const QString &starred = QString(),
                              const std::function<void(const QString &)> &starPick = {})
{
    QMenu *menu = button->menu();
    qDeleteAll(menu->findChildren<QActionGroup *>(QString(), Qt::FindDirectChildrenOnly));
    menu->clear();
    auto *group = new QActionGroup(menu);
    QString shown = choices.isEmpty() ? QString() : choices.first().button;
    for (const auto &choice : choices) {
        QAction *a = menu->addAction((!starred.isEmpty() && choice.value == starred ? QStringLiteral("★ ") : QString())
                                     + choice.label);
        a->setObjectName(QStringLiteral("aiChat%1:%2").arg(kind, choice.value.isEmpty() ? QStringLiteral("default")
                                                                                          : choice.value));
        a->setToolTip(choice.tip);
        a->setCheckable(true);
        a->setChecked(choice.value == current);
        group->addAction(a);
        if (choice.value == current)
            shown = choice.button;
        QObject::connect(a, &QAction::triggered, button, [pick, value = choice.value]() { pick(value); });
    }
    if (starPick) {
        menu->addSeparator();
        QMenu *starMenu = menu->addMenu(QStringLiteral("Star my default model"));
        for (const auto &choice : choices) {
            QAction *a = starMenu->addAction(choice.label);
            a->setObjectName(QStringLiteral("aiChatStar:") + choice.value);
            QObject::connect(a, &QAction::triggered, button,
                             [starPick, value = choice.value]() { starPick(value); });
        }
    }
    button->setText(shown + QStringLiteral(" ▾"));
    button->setAccessibleName(
        QStringLiteral("%1: %2").arg(kind == QLatin1String("Engine") ? QStringLiteral("AI") : kind, shown));
}

// Picking an AI: the next message goes to it, in a new conversation (aiChatSend starts it).
static void aiChatApplyMode(AiChat *c);

// Picking an AI with no terminal view, or leaving one, changes which view shows.
static void aiChatSyncMode(AiChat *c)
{
    if (c->terminal && c->terminal->isVisibleTo(c->terminal->parentWidget()) != aiTerminalMode())
        aiChatApplyMode(c);
}

void aiChatPickEngine(AiChat *c, const QString &engine)
{
    if (engine == aiChatEngineId(aiChatSettings()))
        return;
    if (!c->busy) aiTerminalStop(c);
    QJsonObject changes{{"engine", engine}};
    if (engine == QLatin1String("claude")) { // as choosing Claude in Connect Your AI does: where Claude Code is on this PC
        const QString found = ConnectAi::claudeExe();
        if (!found.isEmpty() && aiChatRawSettings().value("claude").toString() != found)
            changes.insert("claude", found);
    }
    aiChatSaveSettings(changes);
    if (c->busy) {
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("The AI choice will apply after this reply."));
    } else if (c->engine != engine) {
        if (c->proc)
            aiChatStopClaude(c);
        aiChatSaveCurrent(c);
        aiChatNewRecord(c, c->projectKey);
        aiChatRender(c);
    }
    const QString name = aiEntry(engine).value("picker").toObject().value("label").toString(engine);
    if (!aiEngineHere(aiChatSettings(), engine))
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("(%1 isn't on this PC yet: Menu > AI > Connect Your AI shows "
                                                            "how to get it)").arg(ConnectAi::programName(engine)));
    else if (c->busy)
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("Your next message goes to %1 in a new chat.").arg(name));
    QTimer::singleShot(0, c->dock, [c]() { aiChatRefreshChoices(c); }); // not inside the menu item's own signal
    if (!c->busy)
        QTimer::singleShot(0, c->dock, [c]() { aiChatSyncMode(c); });
    if (aiTerminalMode() && !c->busy) QTimer::singleShot(0, c->dock, [c]() { aiTerminalStart(c); });
}

// Picking a model or an effort: saved, used from the next message, same conversation. A Codex model that doesn't
// take the chosen effort puts the effort back to Default.
void aiChatPickSetting(AiChat *c, bool effort, const QString &value)
{
    const QJsonObject s = aiChatSettings();
    const bool codex = aiChatIsCodex(s);
    const QString key = effort ? aiChatEffortKeyOf(aiChatEngineId(s)) : aiChatModelKeyOf(aiChatEngineId(s));
    if (s.value(key).toString().trimmed() == value)
        return;
    QJsonObject changes{{key, value}};
    QString extra;
    if (codex && !effort) {
        const QString chosen = s.value(QStringLiteral("codex_reasoning")).toString().trimmed();
        const QString model = value.isEmpty() ? aiCodexConfigValue(QStringLiteral("model")) : value;
        if (!chosen.isEmpty() && !aiChatHasChoice(aiCodexEffortChoicesFor(model), chosen)) {
            const QList<AiChatChoice> takes = aiCodexEffortChoicesFor(model);
            const QString closest = takes.isEmpty() ? QStringLiteral("medium") : aiNearestEffort(takes, chosen);
            changes.insert(QStringLiteral("codex_reasoning"), closest);
            extra = QStringLiteral(" This model uses %1 effort.").arg(aiChatEffortWord(closest));
        }
    }
    aiChatSaveSettings(changes);
    if (aiTerminalMode() && c->terminal && c->terminal->running() && !c->busy) {
        aiTerminalStop(c);
        aiTerminalStart(c);
    }
    QString name = value;
    if (!value.isEmpty()) {
        name = value;
        const QList<AiChatChoice> list = effort ? aiChatEffortChoices(aiChatSettings()) : aiChatModelChoices(aiChatSettings());
        for (const auto &choice : list) {
            if (choice.value == value)
                name = effort ? choice.label : choice.button;
        }
    }
    // a conversation with this AI goes on; after a switch to the other AI, the next message starts a new one
    const bool goesOn = c->sessionStarted && c->engine == aiChatEngineId(s);
    aiChatAdd(c, QStringLiteral("note"), QStringLiteral("(%1: %2. It applies from your next message%3.%4)")
                                             .arg(effort ? QStringLiteral("Effort") : QStringLiteral("Model"), name,
                                                  goesOn ? QStringLiteral(" and keeps this conversation") : QString(),
                                                  extra));
    QTimer::singleShot(0, c->dock, [c]() { aiChatRefreshChoices(c); }); // not inside the menu item's own signal
}

// The top row shows what panel.json holds now (also after Connect Your AI or a hand edit changed it).
static void aiChatRefreshChoices(AiChat *c)
{
    if (!c->engineButton)
        return;
    aiChatDiscoverCodexModels(c);
    const QJsonObject s = aiChatSettings();
    const QString engineNow = aiChatEngineId(s);
    const QString starKey = QStringLiteral("default_%1_model").arg(engineNow);
    // The AI in use stays in use: a second one installed later doesn't take over.
    if (aiChatRawSettings().value("engine").toString().isEmpty() && aiEngineHere(s, s.value("engine").toString()))
        aiChatSaveSettings(QJsonObject{{"engine", s.value("engine").toString()}});
    aiChatFillChoices(c->engineButton, QStringLiteral("Engine"), aiChatEngineChoicesHere(s),
                      aiChatEngineId(s),
                      [c](const QString &value) {
                          if (value == QLatin1String("connect"))
                              ConnectAi::show(c->window);
                          else
                              aiChatPickEngine(c, value);
                      });
    aiChatFillChoices(c->modelButton, QStringLiteral("Model"), aiChatModelChoices(s),
                      s.value(aiChatModelKeyOf(engineNow)).toString().trimmed(),
                      [c](const QString &value) { aiChatPickSetting(c, false, value); },
                      s.value(starKey).toString(),
                      [c, starKey](const QString &value) {
                          aiChatPickSetting(c, false, value);
                          aiChatSaveSettings(QJsonObject{{starKey, value}});
                          aiChatRefreshChoices(c);
                      });
    aiChatFillChoices(c->effortButton, QStringLiteral("Effort"), aiChatEffortChoices(s),
                      s.value(aiChatEffortKeyOf(engineNow)).toString().trimmed(),
                      [c](const QString &value) { aiChatPickSetting(c, true, value); });
    const QJsonArray speeds = aiSpeedChoices(s, engineNow);
    if (!speeds.isEmpty()) {
        QMenu *menu = c->modelButton->menu();
        menu->addSection(QStringLiteral("Reply speed"));
        auto *group = new QActionGroup(menu);
        const QString effective = c->busy && c->engine == engineNow ? c->procSpeed : aiSpeedValue(s, engineNow);
        for (const auto &value : speeds) {
            const QJsonObject speed = value.toObject();
            const QString id = speed.value("value").toString();
            QAction *action = menu->addAction(speed.value("label").toString());
            action->setObjectName(QStringLiteral("aiChatSpeed:") + id);
            action->setToolTip(speed.value("tip").toString());
            action->setCheckable(true);
            action->setChecked(id == effective);
            action->setEnabled(speed.value("enabled").toBool());
            group->addAction(action);
            QObject::connect(action, &QAction::triggered, c->dock, [c, engineNow, id]() {
                aiChatSaveSettings(QJsonObject{{aiSpeedKey(engineNow), id}});
                aiChatAdd(c, QStringLiteral("note"), QStringLiteral("Reply speed applies from your next message. This does not change New video Turbo."));
                if (aiTerminalMode() && !c->busy) {
                    c->speedNormal = false;
                    aiTerminalStop(c);
                    aiTerminalStart(c);
                }
                QTimer::singleShot(0, c->dock, [c]() { aiChatRefreshChoices(c); });
            });
        }
    }
    aiChatShowActiveModel(c);
    aiChatShowEngine(c);
}

// Shows the AI panel. Beside another panel on the right it goes in as a tab: stacked, the two ask for more height than a
// laptop has and the window grows off the screen (T82: 1366x925). The Opening panel sits above the chat on purpose.
static void aiChatRevealDock(AiChat *c)
{
    if (!c->dock->isVisible() && c->window && !c->dock->isFloating()) {
        for (auto *other : c->window->findChildren<QDockWidget *>()) {
            if (other != c->dock && other->isVisible() && !other->isFloating()
                && other->objectName() != QLatin1String("focusHookDock")
                && c->window->dockWidgetArea(other) == Qt::RightDockWidgetArea) {
                c->window->tabifyDockWidget(other, c->dock);
                break;
            }
        }
    }
    c->dock->show();
    c->dock->raise();
}

// The line a project opened for the person to edit with the AI waits for (aiChatShowReady): shown in that project's own
// chat once the panel has switched to it, then saved with it.
static void aiChatPostReady(AiChat *c)
{
    if (c->readyNote.isEmpty() || c->projectKey.isEmpty() || c->projectKey != c->readyProject)
        return;
    aiChatAdd(c, QStringLiteral("note"), c->readyNote);
    c->readyNote.clear();
    c->readyProject.clear();
    aiChatSaveCurrent(c);
    aiChatRender(c);
}

void aiChatShowReady(const QString &project, const QString &note)
{
    AiChat *c = aiChatInstance();
    if (!c)
        return;
    c->readyProject = QFileInfo(project).absoluteFilePath().toLower();
    c->readyNote = note;
    // the opened project starts its own chat: a chat with no project yet (a New video that stopped before its project
    // opened) keeps its record instead of taking this project over
    if (!c->busy && c->projectKey.isEmpty() && !c->blocks.isEmpty()) {
        aiTerminalStop(c);
        if (c->proc)
            aiChatStopClaude(c);
        aiChatSaveCurrent(c);
        aiChatNewRecord(c, c->readyProject);
        aiChatRender(c);
        aiChatRefreshHistory(c);
        if (aiTerminalMode())
            aiTerminalStart(c);
    }
    aiChatRevealDock(c);
    aiChatPostReady(c);
}

static void aiChatApplyMode(AiChat *c)
{
    if (!c->terminal || !c->view || !c->modeButton) return;
    const bool terminal = aiTerminalMode();
    // What goes away first: with both views up for a moment the panel asks for more height than a laptop has, and the
    // window grows and stays grown (T82: 1366x913).
    if (terminal) {
        c->view->setVisible(false);
        c->input->setVisible(false);
        c->send->setVisible(false);
    } else {
        c->terminal->setVisible(false);
    }
    c->terminal->setVisible(terminal);
    if (c->terminalNotice)
        c->terminalNotice->setVisible(terminal && !c->terminalNotice->text().isEmpty());
    c->view->setVisible(!terminal);
    c->input->setVisible(!terminal);
    c->send->setVisible(!terminal);
    c->signIn->setVisible(false);
    if (auto *menu = c->modeButton->menu())
        for (QAction *a : menu->actions())
            if (a->isCheckable())
                a->setChecked(a->objectName() == (terminal ? QLatin1String("aiChatView:terminal") : QLatin1String("aiChatView:bubbles")));
    if (terminal && c->dock->isVisible()) aiTerminalStart(c);
}

// After Connect Your AI (or anything else) changed panel.json: the chat shows it.
// The first-use notice, once, at the top of the panel: not a dialog, so nothing waits on it and nothing takes the keyboard.
static void aiChatShowFirstUse(AiChat *c)
{
    if (!c->firstUseBar)
        return;
    const QJsonObject s = aiChatSettings();
    const QString engine = aiChatEngineId(s);
    const bool connector = aiEngineIsConnector(engine) && aiEngineHere(s, engine);
    const bool here = connector || !ConnectAi::claudeExe().isEmpty() || !ConnectAi::codexExe().isEmpty();
    const bool shown = here && !ConnectAi::firstUseNoticeSeen(connector ? engine : QString())
                       && (!qEnvironmentVariableIsSet("LETITEDIT_QA") || qEnvironmentVariableIsSet("LETITEDIT_QA_FIRST_USE"));
    c->firstUseText->setText(connector ? ConnectAi::connectorNotice(engine) : ConnectAi::firstUseNotice());
    c->firstUseBar->setVisible(shown);
}

// Is the chosen AI's program signed in? Asked in the background; only a clear no changes anything.
static void aiChatCheckSignIn(AiChat *c)
{
    const QString engine = aiChatSettings().value("engine").toString();
    ConnectAi::checkSignedIn(engine, c->dock, [c, engine](int answer) {
        if (aiChatSettings().value("engine").toString() != engine || !c->terminalNotice)
            return;
        const QString saved = aiChatRawSettings().value("engine").toString();
        const QString broken = saved.isEmpty() || saved == engine ? QString() : ConnectAi::missingWords(saved);
        if (!broken.isEmpty() && answer != 0) {
            // The AI they chose has gone and the other is standing in: say so, once, rather than switch quietly.
            c->signedOutShown = true;
            c->terminalNotice->setText(broken + QStringLiteral(" Using %1 for now.").arg(ConnectAi::programName(engine)));
            c->terminalNotice->show();
        } else if (answer == 0) {
            c->signedOutShown = true;
            c->terminalNotice->setText(QStringLiteral("%1 on this PC isn't signed in. Click \"Sign in\" and finish there.")
                                           .arg(ConnectAi::programName(engine)));
            c->terminalNotice->show();
            c->signIn->show();
        } else if (c->signedOutShown) {
            c->signedOutShown = false;
            c->terminalNotice->clear();
            c->terminalNotice->hide();
            c->signIn->hide();
        }
    });
}

// Ends the bubble view's program: the end of its input first, which it treats as the time to exit, then by force if it's still
// there in a few seconds. Its finished() handler does the rest. Never blocks the window.
static void aiChatEndGently(QProcess *process)
{
    process->closeWriteChannel();
    QTimer::singleShot(3000, process, [process]() { process->kill(); });
}

static void aiChatEndVisibleReview(AiChat *c)
{
    ++c->reviewGeneration;
    c->reviewWatch->stop();
    if (c->reviewTerminal->running())
        c->reviewTerminal->stop();
    c->reviewTerminal->hide();
    c->reviewBar->hide();
}

// The review's screen and bar in the panel, watched for its answer.
static void aiChatShowReview(AiChat *c)
{
    aiChatRevealDock(c);
    c->reviewBar->show();
    c->reviewTerminal->show();
    c->reviewWatch->start();
}

// A test window: no program. It says what it was asked and answers with LETITEDIT_QA_MOCK_REVIEW after a moment.
static QJsonObject aiChatMockReview(AiChat *c, const QString &mock, const QString &requestFile, const QString &engine)
{
    QFile log(mock);
    if (log.open(QIODevice::Append))
        log.write(QJsonDocument(QJsonObject{{"review_request", requestFile}}).toJson(QJsonDocument::Compact) + '\n');
    const QString answer = qEnvironmentVariable("LETITEDIT_QA_MOCK_REVIEW");
    aiChatRevealDock(c);
    c->reviewBar->show();
    c->reviewWatch->start();
    if (!answer.isEmpty()) {
        QTimer::singleShot(1500, c->dock, [c, answer]() {
            QFile f(c->reviewAnswer);
            if (f.open(QIODevice::WriteOnly))
                f.write(answer.toUtf8());
        });
    }
    return QJsonObject{{"started", true}, {"engine", engine}};
}

// The connector host prints the conversation here as plain words. No terminal view of the AI: this is our own record of it.
static bool aiChatConnectorReview(AiChat *c, const QJsonObject &s, const QString &engine, const QString &requestFile,
                                  const QString &out, const QString &label, const QJsonObject &more, const QString &work)
{
    QStringList args;
    args << aiRootPath(QStringLiteral("bridge/acp_host.py")) << QStringLiteral("once") << QStringLiteral("--ai") << engine
         << QStringLiteral("--request") << requestFile << QStringLiteral("--out") << out << QStringLiteral("--label") << label
         << QStringLiteral("--mode") << more.value("mode").toString(QStringLiteral("review"));
    if (!s.value(aiChatModelKeyOf(engine)).toString().isEmpty())
        args << QStringLiteral("--model") << s.value(aiChatModelKeyOf(engine)).toString();
    if (!s.value(aiChatEffortKeyOf(engine)).toString().isEmpty())
        args << QStringLiteral("--effort") << s.value(aiChatEffortKeyOf(engine)).toString();
    QString error;
    if (!c->reviewTerminal->start(s.value("python").toString(), args, work, &error, QStringList())) {
        LOG_WARNING() << "visible conversation:" << error;
        return false;
    }
    aiChatShowReview(c);
    return true;
}

// As with a request in the main terminal: the review's request is typed once its program has started and its screen
// has settled.
static void aiReviewSubmitWhenSettled(AiChat *c, const QString &requestFile, int generation)
{
    const QString ask = QStringLiteral("Read this file and do what it says: %1").arg(QDir::toNativeSeparators(requestFile));
    auto *waiting = new QTimer(c->dock);
    waiting->setInterval(500);
    auto since = std::make_shared<QElapsedTimer>();
    since->start();
    auto lastBytes = std::make_shared<qint64>(-1);
    auto quietTicks = std::make_shared<int>(0);
    const bool normalSpeed = c->reviewNormalSpeed;
    QObject::connect(waiting, &QTimer::timeout, c->dock, [c, ask, waiting, since, lastBytes, quietTicks, normalSpeed, generation]() {
        if (!c->reviewTerminal->running() || c->reviewNormalSpeed != normalSpeed || c->reviewGeneration != generation) {
            waiting->stop();
            waiting->deleteLater();
            return;
        }
        const qint64 bytes = c->reviewTerminal->receivedBytes();
        *quietTicks = bytes == *lastBytes ? *quietTicks + 1 : 0;
        *lastBytes = bytes;
        if ((since->elapsed() >= 5000 && bytes > 0 && *quietTicks >= 2) || since->elapsed() >= 30000) {
            waiting->stop();
            waiting->deleteLater();
            c->reviewTerminal->submit(ask);
        }
    });
    waiting->start();
}

// Background runs are off (Connect Your AI), so a review doesn't run unseen: it is a second conversation in the panel,
// the person's own program started the ordinary way, with the critic's request and nothing of this conversation. The
// program saves review.json itself, and that ends it. critic.py waits for that file.
QJsonObject aiChatVisibleReview(const QString &requestFile, const QString &out, const QJsonObject &more)
{
    AiChat *c = aiChatInstance();
    const QJsonObject no{{"started", false}};
    if (!c || !c->reviewTerminal || c->reviewTerminal->running() || c->reviewWatch->isActive())
        return no;
    const int generation = ++c->reviewGeneration;
    QJsonObject s = aiChatSettings();
    // more: for a picture another AI asked for, the AI that draws, the words on the bar and the file that says it finished
    const QString engine = more.value("engine").toString(s.value("engine").toString());
    c->reviewNormalSpeed = more.value("_normal_speed").toBool();
    if (c->reviewNormalSpeed)
        s[aiSpeedKey(engine)] = QStringLiteral("normal");
    c->reviewRequestFile = requestFile;
    c->reviewOut = out;
    c->reviewOptions = more;
    c->reviewSpeed = aiSpeedValue(s, engine);
    const QString label = more.value("label").toString(QStringLiteral("A second conversation is reviewing your video:"));
    if (c->reviewLabel)
        c->reviewLabel->setText(label);
    if (c->reviewStopButton)
        c->reviewStopButton->setText(more.contains("label") ? QStringLiteral("Stop") : QStringLiteral("Stop the review"));
    c->reviewAnswer = QDir(out).filePath(more.value("answer").toString(QStringLiteral("review.json")));
    const QString mock = qEnvironmentVariable("LETITEDIT_QA_MOCK_AI");
    if (!mock.isEmpty())
        return aiChatMockReview(c, mock, requestFile, engine);
    if (!aiEngineHere(s, engine))
        return no;
    const QString work = QDir(aiTerminalWork(c)).filePath(QStringLiteral("review"));
    QDir().mkpath(work);
    if (aiEngineIsConnector(engine)) {
        if (!aiChatConnectorReview(c, s, engine, requestFile, out, label, more, work))
            return no;
        return QJsonObject{{"started", true}, {"engine", engine}};
    }
    QStringList args;
    if (engine == QLatin1String("codex"))
        args << aiCodexChoiceArgs(s) << QStringLiteral("--approve-for-me")
             << QStringLiteral("--add-dir") << out;
    else
        args << QStringLiteral("--allowedTools") << QStringLiteral("Read,Write") << QStringLiteral("--setting-sources")
             << QStringLiteral("local") << QStringLiteral("--strict-mcp-config") << QStringLiteral("--permission-mode")
             << QStringLiteral("acceptEdits") << aiClaudeChoiceArgs(s) << QStringLiteral("--add-dir") << out;
    if (engine == QLatin1String("claude"))
        args << aiClaudeInstructionArgs(s);
    QString error;
    if (!c->reviewTerminal->start(s.value(engine).toString(), args, work, &error, QStringList())) {
        LOG_WARNING() << "visible review:" << error;
        return no;
    }
    aiChatShowReview(c);
    aiReviewSubmitWhenSettled(c, requestFile, generation);
    return QJsonObject{{"started", true}, {"engine", engine}};
}

static bool aiReviewRetrySpeed(AiChat *c)
{
    if (c->reviewNormalSpeed || c->reviewSpeed == QLatin1String("normal")
        || QFileInfo::exists(c->reviewAnswer) || !aiSpeedRefused(c->reviewTerminal->visibleText()))
        return false;
    const QString error = c->reviewTerminal->visibleText();
    c->reviewNormalSpeed = true;
    aiChatAdd(c, QStringLiteral("note"), QStringLiteral("The review is continuing at Normal speed. Your saved choice is unchanged."));
    if (error.contains(QStringLiteral("Fast mode disabled"), Qt::CaseInsensitive))
        return false;
    c->reviewWatch->stop();
    c->reviewTerminal->stop();
    const QString requestFile = c->reviewRequestFile;
    const QString out = c->reviewOut;
    QJsonObject options = c->reviewOptions;
    options["_normal_speed"] = true;
    const int generation = ++c->reviewGeneration;
    QTimer::singleShot(0, c->dock, [c, requestFile, out, options, generation]() {
        if (c->reviewGeneration != generation) return;
        if (!aiChatVisibleReview(requestFile, out, options).value("started").toBool()) {
            QFile answer(c->reviewAnswer);
            if (answer.open(QIODevice::WriteOnly))
                answer.write(QJsonDocument(QJsonObject{{"error", "The review could not restart at Normal speed."}}).toJson());
        }
    });
    return true;
}

void aiChatSettingsChanged()
{
    if (AiChat *c = aiChatInstance()) {
        aiChatRefreshChoices(c);
        aiChatApplyMode(c);
        aiChatShowFirstUse(c);
        aiChatCheckSignIn(c);
    }
}

// The AI settings button at the end of the top row, and its menu.
static void aiChatBuildSettingsMenu(AiChat *c, QWidget *panel)
{
    c->modeButton = new QToolButton(panel);
    c->modeButton->setObjectName(QStringLiteral("aiChatViewMode"));
    c->modeButton->setPopupMode(QToolButton::InstantPopup);
    // AI settings: how the chat shows (bubbles, or the AI's real program), and connecting an AI.
    c->modeButton->setText(QStringLiteral("AI settings ▾"));
    c->modeButton->setToolTip(QStringLiteral("How this chat shows your AI, and Connect Your AI"));
    auto *modeMenu = new QMenu(c->modeButton);
    modeMenu->setToolTipsVisible(true);
    c->modeButton->setMenu(modeMenu);
    for (const auto &mode : {QStringLiteral("terminal"), QStringLiteral("bubbles")}) {
        QAction *action = modeMenu->addAction(mode == QLatin1String("terminal") ? QStringLiteral("Real program screen")
                                                                          : QStringLiteral("Chat bubbles"));
        action->setObjectName(QStringLiteral("aiChatView:") + mode);
        action->setCheckable(true);
        QObject::connect(action, &QAction::triggered, c->dock, [c, mode]() {
            if (aiTerminalMode() == (mode == QLatin1String("terminal"))) {
                aiChatApplyMode(c); // already showing: a running request carries on
                return;
            }
            if (c->busy) {
                aiChatEndRequest(c, QStringLiteral("cancelled"), QStringLiteral("View changed."));
                aiChatSetBusy(c, false);
            }
            aiTerminalStop(c);
            if (c->proc) aiChatStopClaude(c);
            aiChatSaveSettings(QJsonObject{{"view_mode", mode}});
            aiChatApplyMode(c);
        });
    }
    // Behind the gear (the owner, 13 Nov: options most people don't need): Auto's every step on the max row (T331 P10).
    modeMenu->addSeparator();
    auto *routingMax = modeMenu->addAction(QStringLiteral("Max on every stage"));
    routingMax->setObjectName(QStringLiteral("aiChatRoutingMax"));
    routingMax->setCheckable(true);
    QObject::connect(routingMax, &QAction::triggered, c->dock, [c](bool on) {
        aiChatSaveSettings(QJsonObject{{"routing_max", on}});
        if (aiTerminalMode() && c->terminal && c->terminal->running() && !c->busy) {
            aiTerminalStop(c);
            aiTerminalStart(c);
        }
        aiChatAdd(c, QStringLiteral("note"),
                  on ? QStringLiteral("(Max on every stage: with Auto, every step uses the most capable model at its "
                                      "deepest thinking. Slower, and uses the most of your plan. From your next message.)")
                     : QStringLiteral("(Max on every stage is off: Auto picks the model for each step again. From your "
                                      "next message.)"));
    });
    modeMenu->addSeparator();
    auto *connectAi = modeMenu->addAction(QStringLiteral("Connect Your AI..."));
    connectAi->setObjectName(QStringLiteral("aiChatSettingsConnect"));
    QObject::connect(connectAi, &QAction::triggered, c->dock, [c]() { ConnectAi::show(c->window); });
    // An AI reached through a connector has chat bubbles only.
    QObject::connect(modeMenu, &QMenu::aboutToShow, c->dock, [c, modeMenu]() {
        const QJsonObject s = aiChatSettings();
        const bool can = aiEngineCan(s.value("engine").toString(), QStringLiteral("terminal"));
        const QString engine = aiChatEngineId(s);
        const bool saved = s.value(QStringLiteral("routing_max")).toBool(false);
        const bool routed = !aiRouting(engine).value(QStringLiteral("max")).toObject().isEmpty();
        const bool onAuto = aiModelIsAuto(s.value(aiChatModelKeyOf(engine)).toString());
        for (QAction *a : modeMenu->actions()) {
            if (a->objectName() == QLatin1String("aiChatView:terminal")) {
                a->setEnabled(can);
                a->setToolTip(can ? QString() : QStringLiteral("This AI has chat bubbles only."));
            } else if (a->objectName() == QLatin1String("aiChatRoutingMax")) {
                // shown while Auto is offered (its switch) or this was turned on before; it acts only with Auto
                a->setVisible(routed && (aiAutoRouting() || saved));
                a->setChecked(saved);
                a->setEnabled(onAuto);
                a->setToolTip(onAuto ? QStringLiteral("With Auto, every step uses the most capable model at its "
                                                      "deepest thinking. Slower, and uses the most of your plan.")
                                     : QStringLiteral("Acts when the model is Auto. A model you chose is always used "
                                                      "as it is."));
            }
        }
    });
}

// The top row: which AI, which model, how much effort (aiChatRefreshChoices fills the menus), then AI settings.
static QHBoxLayout *aiChatBuildChoiceRow(AiChat *c, QWidget *panel)
{
    auto *choices = new QHBoxLayout;
    choices->setSpacing(4);
    const QList<QPair<QToolButton **, QString>> tops{{&c->engineButton, QStringLiteral("aiChatEngine")},
                                                     {&c->modelButton, QStringLiteral("aiChatModel")},
                                                     {&c->effortButton, QStringLiteral("aiChatEffort")}};
    for (const auto &top : tops) {
        auto *b = new QToolButton(panel);
        b->setObjectName(top.second);
        b->setProperty("aiChatChoice", true);
        b->setPopupMode(QToolButton::InstantPopup);
        b->setToolButtonStyle(Qt::ToolButtonTextOnly);
        b->setStyleSheet(QStringLiteral("QToolButton::menu-indicator { image: none; width: 0px; }")); // arrow in the text
        auto *menu = new QMenu(b);
        menu->setToolTipsVisible(true);
        b->setMenu(menu);
        choices->addWidget(b);
        *top.first = b;
    }
    // A second AI installed since the last look shows up when the menu opens, with no restart.
    QObject::connect(c->engineButton->menu(), &QMenu::aboutToShow, c->dock, [c]() { aiChatRefreshChoices(c); });
    QObject::connect(c->modelButton->menu(), &QMenu::aboutToShow, c->dock, [c]() { aiChatRefreshChoices(c); });
    choices->addStretch(1);
    aiChatBuildSettingsMenu(c, panel);
    choices->addWidget(c->modeButton);
    c->engineButton->setToolTip(QStringLiteral("Which AI you talk to: letitedit runs your own program on this PC, on your "
                                               "own plan. Switching starts a new conversation."));
    c->effortButton->setToolTip(QStringLiteral("How hard the AI thinks before it answers. Higher effort is smarter but "
                                               "slower and uses more of your plan. A change applies from your next "
                                               "message and keeps the conversation."));
    return choices;
}

// The conversation: chat bubbles, or the AI's own program screen with a notice when the program ends.
static void aiChatBuildConversation(AiChat *c, QWidget *panel)
{
    c->view = new QTextBrowser(panel);
    c->view->setObjectName(QStringLiteral("aiChatView"));
    c->view->setOpenLinks(false);
    c->view->setMinimumHeight(80); // room for Send on a laptop, whatever else the panel shows
    c->terminal = new AiTerminal(panel);
    c->terminal->setMinimumHeight(120);
    c->terminalNotice = new QLabel(panel);
    c->terminalNotice->setWordWrap(true);
    c->terminalNotice->setStyleSheet(QStringLiteral("QLabel { color: #F4EFE6; background: #7A392B; padding: 9px; }"));
    c->terminalNotice->hide();
    c->terminal->exited = [c](int code) {
        if (c->terminalStopping) return;
        if (c->request && aiTerminalRetrySpeed(c, c->terminal->visibleText())) return;
        if (c->terminalPoll) c->terminalPoll->stop();
        const QString error = QStringLiteral("%1 exited (code %2). Send again to reopen it.")
                                  .arg(c->engine == QLatin1String("codex") ? "Codex" : "Claude Code").arg(code);
        aiChatAdd(c, QStringLiteral("error"), error);
        c->terminalNotice->setText(error);
        c->terminalNotice->show();
        c->window->showStatusMessage(error, 10);
        if (c->request)
            aiChatEndRequest(c, QStringLiteral("failed"), error);
        aiChatSetBusy(c, false, error);
    };
    c->terminalPoll = new QTimer(c->dock);
    c->terminalPoll->setInterval(350);
    QObject::connect(c->terminalPoll, &QTimer::timeout, c->dock, [c]() { aiTerminalPoll(c); });
    QObject::connect(c->view->verticalScrollBar(), &QScrollBar::valueChanged, c->dock, [c](int value) {
        if (!c->rendering)
            c->followBottom = value >= c->view->verticalScrollBar()->maximum() - 4;
    });
    // "Show the details" under a request the app wrote opens (and closes) the full text it sent
    QObject::connect(c->view, &QTextBrowser::anchorClicked, c->dock, [c](const QUrl &url) {
        if (url.scheme() == QLatin1String("letitedit-detail")) {
            const int i = url.path().toInt();
            if (i >= 0 && i < c->blocks.size()) {
                c->blocks[i].expanded = !c->blocks[i].expanded;
                aiChatRender(c);
            }
            return;
        }
        QDesktopServices::openUrl(url);
    });
}

// The message box, the status line and the buttons. Returns New chat, which the panel connects once it is built.
static QPushButton *aiChatBuildInput(AiChat *c, QWidget *panel, const QString &engineName)
{
    c->input = new QPlainTextEdit(panel);
    c->input->setObjectName(QStringLiteral("aiChatInput"));
    QObject::connect(c->input, &QPlainTextEdit::textChanged, c->dock, [c]() {
        if (c->autonomousNewVideo && !c->input->toPlainText().isEmpty())
            c->carryHumanInput = true;
    });
    c->input->setPlaceholderText(QStringLiteral("Ask %1 to edit... (Enter to send, Shift+Enter for a new line)").arg(engineName));
    c->input->setMinimumHeight(48);
    c->input->setMaximumHeight(90);
    c->status = new QLabel(panel);
    c->status->setObjectName(QStringLiteral("aiChatStatus"));
    c->status->setWordWrap(true);
    c->send = new QPushButton(QStringLiteral("Send"), panel);
    c->send->setObjectName(QStringLiteral("aiChatSend"));
    c->stop = new QPushButton(QStringLiteral("Stop"), panel);
    c->stop->setObjectName(QStringLiteral("aiChatStop"));
    c->historyButton = new QToolButton(panel);
    c->historyButton->setObjectName(QStringLiteral("aiChatHistory"));
    c->historyButton->setText(QStringLiteral("Past chats ▾"));
    c->historyButton->setPopupMode(QToolButton::InstantPopup);
    c->historyButton->setMenu(new QMenu(c->historyButton));
    QObject::connect(c->historyButton->menu(), &QMenu::aboutToShow, c->dock, [c]() { aiChatRefreshHistory(c); });
    auto *fresh = new QPushButton(QStringLiteral("New chat"), panel);
    fresh->setObjectName(QStringLiteral("aiChatNew"));
    c->signIn = new QPushButton(QStringLiteral("Sign in"), panel);
    c->signIn->setObjectName(QStringLiteral("aiChatSignIn"));
    c->signIn->hide();
    c->stop->setEnabled(false);
    return fresh;
}

// The key is a registered command, "Hold to talk": it shows in Actions and Shortcuts (which refuses a key
// another command has), and a key from panel.json that another command already uses gives way to F12.
static void aiChatAddTalkKey(AiChat *c, MainWindow *window, const QJsonObject &voice)
{
    c->talkAction = new QAction(QStringLiteral("Hold to talk"), window);
    c->talkAction->setObjectName(QStringLiteral("aiChatHoldToTalkAction"));
    c->talkAction->setToolTip(QStringLiteral("Hold the key to talk to your AI; let go to send"));
    QKeySequence key = QKeySequence::fromString(voice.value("ptt_key").toString());
    const auto taken = [](const QKeySequence &seq) {
        if (seq.isEmpty())
            return QString();
        for (const QString &name : Actions.keys())
            if (QAction *a = Actions[name])
                for (const QKeySequence &s : a->shortcuts())
                    if (s.matches(seq) == QKeySequence::ExactMatch)
                        return name;
        return QString();
    };
    const QString clash = taken(key);
    if (!clash.isEmpty()) {
        LOG_WARNING() << "push-to-talk key" << key.toString() << "is" << clash << "'s shortcut: using F12";
        key = QKeySequence(Qt::Key_F12);
        if (!taken(key).isEmpty())
            key = QKeySequence();
    }
    c->talkAction->setShortcut(key);
    c->talkAction->setShortcutContext(Qt::WindowShortcut);
    window->addAction(c->talkAction);
    Actions.add(QStringLiteral("aiChatHoldToTalkAction"), c->talkAction, QStringLiteral("AI"));
    // the key the person chose in Actions and Shortcuts, which loaded the others before this panel existed
    const QList<QKeySequence> chosen = Settings.shortcuts(c->talkAction->objectName());
    if (!chosen.isEmpty())
        c->talkAction->setShortcuts(chosen);
    if (!c->talkAction->shortcut().isEmpty())
        c->talkAction->setToolTip(QStringLiteral("Hold the key to talk to your AI; let go to send (%1)")
                                      .arg(c->talkAction->shortcut().toString(QKeySequence::NativeText)));
    // clicked rather than held (no key): a take starts, and the next click sends it
    QObject::connect(c->talkAction, &QAction::triggered, c->dock, [c]() {
        if (c->recording)
            aiVoiceStop(c);
        else
            aiVoiceStart(c);
    });
    QObject::connect(c->talkAction, &QAction::changed, c->dock, [c]() { aiVoiceShowKey(c); });
    qApp->installEventFilter(new AiVoiceKeyFilter(c->dock, c));
}

// Hold to talk: the button, the recording's time limit and, when talking is on, the key.
static void aiChatBuildTalk(AiChat *c, MainWindow *window, QWidget *panel)
{
    const QJsonObject voice = aiVoiceSettings();
    c->talk = new QPushButton(QStringLiteral("Hold to talk"), panel);
    c->talk->setObjectName(QStringLiteral("aiChatTalk"));
    c->talk->setToolTip(QStringLiteral("The microphone records only while this (or its key) is held; the recording is "
                                       "transcribed on this PC and deleted, then sent like a typed message. The reply "
                                       "is read aloud. Menu > Help > Actions and Shortcuts changes the key."));
    c->talk->setVisible(voice.value("enabled").toBool(true));
    c->recordLimit = new QTimer(c->dock);
    c->recordLimit->setSingleShot(true);
    QObject::connect(c->recordLimit, &QTimer::timeout, c->dock, [c]() { aiVoiceStop(c); });
    QObject::connect(c->talk, &QPushButton::pressed, c->dock, [c]() { aiVoiceStart(c); });
    QObject::connect(c->talk, &QPushButton::released, c->dock, [c]() { aiVoiceStop(c); });
    if (voice.value("enabled").toBool(true))
        aiChatAddTalkKey(c, window, voice);
    aiVoiceShowKey(c);
}

// The row under the message box: the status line, then the buttons.
static QHBoxLayout *aiChatButtonRow(AiChat *c, QPushButton *fresh)
{
    auto *buttons = new QHBoxLayout;
    buttons->addWidget(c->status, 1);
    buttons->addWidget(c->talk);
    buttons->addWidget(c->signIn);
    buttons->addWidget(c->historyButton);
    buttons->addWidget(fresh);
    buttons->addWidget(c->stop);
    buttons->addWidget(c->send);
    return buttons;
}

// The first-use notice (aiChatShowFirstUse) and its Got it.
static void aiChatBuildFirstUseBar(AiChat *c, QWidget *panel, QVBoxLayout *layout)
{
    c->firstUseBar = new QWidget(panel);
    c->firstUseBar->setObjectName(QStringLiteral("aiFirstUseNotice"));
    auto *firstUseRow = new QHBoxLayout(c->firstUseBar);
    firstUseRow->setContentsMargins(6, 4, 6, 4);
    c->firstUseText = new QLabel(c->firstUseBar);
    c->firstUseText->setObjectName(QStringLiteral("aiFirstUseText"));
    c->firstUseText->setWordWrap(true);
    firstUseRow->addWidget(c->firstUseText, 1);
    auto *firstUseOk = new QPushButton(QStringLiteral("Got it"), c->firstUseBar);
    firstUseOk->setObjectName(QStringLiteral("aiFirstUseOk"));
    QObject::connect(firstUseOk, &QPushButton::clicked, c->dock, [c]() {
        const QJsonObject s = aiChatSettings();
        ConnectAi::setFirstUseNoticeSeen(aiEngineIsConnector(aiChatEngineId(s)) ? aiChatEngineId(s) : QString());
        c->firstUseBar->hide();
    });
    firstUseRow->addWidget(firstUseOk);
    c->firstUseBar->hide();
    layout->addWidget(c->firstUseBar);
}

// The review as a second conversation the person can watch (aiChatVisibleReview): its screen, and a bar with Stop the
// review. The panel lays them out.
static void aiChatBuildReviewBar(AiChat *c, QWidget *panel)
{
    c->reviewTerminal = new AiTerminal(panel);
    c->reviewTerminal->setObjectName(QStringLiteral("aiReviewTerminal"));
    c->reviewTerminal->setMinimumHeight(100);
    c->reviewTerminal->hide();
    c->reviewBar = new QWidget(panel);
    c->reviewBar->setObjectName(QStringLiteral("aiReviewBar"));
    auto *reviewRow = new QHBoxLayout(c->reviewBar);
    reviewRow->setContentsMargins(6, 4, 6, 4);
    auto *reviewText = new QLabel(QStringLiteral("A second conversation is reviewing your video:"), c->reviewBar);
    reviewText->setWordWrap(true);
    reviewRow->addWidget(reviewText, 1);
    c->reviewLabel = reviewText;
    auto *reviewStop = new QPushButton(QStringLiteral("Stop the review"), c->reviewBar);
    reviewStop->setObjectName(QStringLiteral("aiReviewStop"));
    c->reviewStopButton = reviewStop;
    reviewRow->addWidget(reviewStop);
    c->reviewBar->hide();
    c->reviewWatch = new QTimer(c->dock);
    c->reviewWatch->setInterval(1000);
    QObject::connect(c->reviewWatch, &QTimer::timeout, c->dock, [c]() {
        QFile f(c->reviewAnswer);
        if (f.open(QIODevice::ReadOnly) && QJsonDocument::fromJson(f.readAll()).isObject())
            aiChatEndVisibleReview(c);
        else
            aiReviewRetrySpeed(c);
    });
    const auto reviewClosed = [c]() {
        // Closed before it answered: say so, so nothing waits on it.
        if (!QFileInfo::exists(c->reviewAnswer)) {
            QFile f(c->reviewAnswer);
            if (f.open(QIODevice::WriteOnly))
                f.write(QJsonDocument(QJsonObject{{"error", "The review conversation was closed before it finished. Run the review again."},
                                                  {"error_kind", "no_answer"}}).toJson());
        }
    };
    QObject::connect(reviewStop, &QPushButton::clicked, c->dock, [c, reviewClosed]() {
        reviewClosed();
        aiChatEndVisibleReview(c);
    });
    c->reviewTerminal->exited = [c, reviewClosed](int) {
        if (!c->reviewWatch->isActive())
            return;
        if (aiReviewRetrySpeed(c)) return;
        reviewClosed();
        aiChatEndVisibleReview(c);
    };
}

// Continue the edit: New video's run, stopped early or by the person, carries on from here.
static void aiChatBuildCarryBar(AiChat *c, QWidget *panel, QVBoxLayout *layout)
{
    c->carryBar = new QWidget(panel);
    c->carryBar->setObjectName(QStringLiteral("aiNewVideoCarryBar"));
    auto *carryLayout = new QHBoxLayout(c->carryBar);
    c->carryLabel = new QLabel(c->carryBar);
    c->carryLabel->setWordWrap(true);
    c->carryContinue = new QPushButton(QStringLiteral("Continue the edit"), c->carryBar);
    c->carryContinue->setObjectName(QStringLiteral("aiNewVideoContinue"));
    carryLayout->addWidget(c->carryLabel, 1);
    carryLayout->addWidget(c->carryContinue);
    c->carryBar->hide();
    layout->addWidget(c->carryBar);
    QObject::connect(c->carryContinue, &QPushButton::clicked, c->dock, [c]() {
        if (c->busy || !c->carryStopped)
            return;
        if (aiChatRequest(c->window, aiNewVideoCarryWords(), QStringLiteral("Continue the edit"), false, false)) {
            c->carryStopped = false;
            c->carryBar->hide();
        }
    });
}

// T99's chip: what is selected in the video, which a typed request is about, and Clear.
static void aiChatBuildTargetBar(AiChat *c, MainWindow *window, QWidget *panel)
{
    c->targetBar = new QWidget(panel);
    c->targetBar->setObjectName(QStringLiteral("aiChatTargetBar"));
    c->targetBar->setStyleSheet(QStringLiteral("#aiChatTargetBar { background: palette(alternate-base); border: 1px solid #2A8597; border-radius: 5px; }"));
    auto *row = new QHBoxLayout(c->targetBar);
    row->setContentsMargins(8, 3, 3, 3);
    row->setSpacing(6);
    c->targetLabel = new QLabel(c->targetBar);
    c->targetLabel->setObjectName(QStringLiteral("aiChatTarget"));
    c->targetLabel->setToolTip(QStringLiteral("Your request is about this. Clear it to ask about the whole video."));
    row->addWidget(c->targetLabel, 1);
    auto *clear = new QToolButton(c->targetBar);
    clear->setObjectName(QStringLiteral("aiChatTargetClear"));
    clear->setText(QStringLiteral("Clear"));
    clear->setToolTip(c->targetLabel->toolTip());
    clear->setAutoRaise(true);
    row->addWidget(clear);
    if (auto *preview = window->findChild<PreviewObjects *>()) {
        QObject::connect(clear, &QToolButton::clicked, preview, &PreviewObjects::clearTarget);
        QObject::connect(preview, &PreviewObjects::targetChanged, c->dock, [c]() { aiChatUpdateTarget(c); });
        QObject::connect(preview, &PreviewObjects::askAiRequested, c->dock, [c]() {
            aiChatRevealDock(c);
            if (c->terminal && c->terminal->isVisible())
                c->terminal->setFocus();
            else if (c->input->isVisible())
                c->input->setFocus();
        });
    }
    c->targetBar->hide();
}

// Send, and Enter in the message box: what the person typed.
static void aiChatConnectSend(AiChat *c, MainWindow *window)
{
    auto sendNow = [window, c]() {
        const QString typed = c->input->toPlainText();
        if (aiChatSend(window, typed)) {
            c->input->clear();
            // T202: the person's own words to the AI go in the open project's journal (actor person, kind said), so a
            // Look made from this video can keep their "always ..." and "never ..." about style (bridge/project_look.py)
            const QString project = window->fileName();
            if (!typed.trimmed().isEmpty() && !project.isEmpty() && project != window->untitledFileName()
                && QFileInfo(project).suffix().compare(QLatin1String("mlt"), Qt::CaseInsensitive) == 0)
                QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(),
                                        {aiRootPath(QStringLiteral("bridge/project_look.py")), QStringLiteral("said"),
                                         QStringLiteral("--where"), QStringLiteral("chat"), QStringLiteral("--"),
                                         QDir::toNativeSeparators(project), typed.left(4000)});
        }
    };
    c->input->installEventFilter(new AiChatInputFilter(c->input, sendNow));
    QObject::connect(c->send, &QPushButton::clicked, c->dock, sendNow);
}

// Stop: the AI's turn ends, what was done stays, and New video's run can carry on later.
static void aiChatStopPressed(AiChat *c)
{
    aiRunnerStop(c); // T331 P11: a video the runner is making stops its sessions; the request ends below as any stop
    c->carryAllowed = c->carryPending = false;
    const bool waitingOnLimit = c->limitCarryAt != 0;
    aiChatLimitClear(c);
    if (c->carryBar)
        c->carryBar->hide();
    if (aiTerminalMode() && c->terminal && c->terminal->running()) {
        // Ctrl+C only interrupts the turn: work running in the background would go on and start a new turn later.
        // Closing the program ends it; the next message resumes the conversation.
        if (c->turnHeld || aiChatHeldWorkRunning(c))
            aiTerminalStop(c);
        else
            c->terminal->interrupt();
    }
    if (c->proc && aiEngineIsConnector(c->engine)) {
        // It takes 15 s to start, so it stays: the host cancels the turn, and closes it itself if that fails.
        c->busy = false;
        c->queued.clear();
        c->proc->write("{\"type\":\"interrupt\"}\n");
    } else if (c->proc) {
        c->busy = false; // finished() then reports nothing as an error
        aiChatEndGently(c->proc);
    }
    if (c->request) {
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("(stopped)"));
        aiChatEndRequest(c, QStringLiteral("cancelled"), QStringLiteral("You pressed Stop."));
        c->busy = true; // so the watchers hear that it is no longer busy
        aiChatSetBusy(c, false);
        if (c->newVideoChat && c->newVideoMakes) {
            // T193: what was kept, and the way back (the card offers the same Carry on)
            c->carryStopped = true;
            if (c->carryBar) {
                c->carryLabel->setText(waitingOnLimit
                    ? QStringLiteral("You stopped the wait for the usage limit. Everything done so far stays in your project.")
                    : QStringLiteral("You stopped this video. Everything done so far stays in your project; you can carry on later."));
                c->carryContinue->show();
                c->carryBar->show();
            }
        }
    }
}

// Sign in: the CLI's own sign-in (Claude Code, or codex login) in its own console window; the user completes it.
static void aiChatSignInPressed(AiChat *c)
{
    const QJsonObject s = aiChatSettings();
    if (aiEngineIsConnector(aiChatEngineId(s))) { // on Google's own page, from Connect Your AI
        ConnectAi::show(c->window);
        return;
    }
    const bool codex = aiChatIsCodex(s);
    const QString exe = QDir::toNativeSeparators(s.value(codex ? "codex" : "claude").toString());
    QStringList cmd{QStringLiteral("/c"), QStringLiteral("start"),
                    codex ? QStringLiteral("Codex sign-in") : QStringLiteral("Claude Code sign-in"),
                    QStringLiteral("cmd.exe"), QStringLiteral("/k"), exe};
    if (codex)
        cmd << QStringLiteral("login");
    QProcess::startDetached(QStringLiteral("cmd.exe"), cmd);
    if (c->proc) {
        c->busy = false;
        aiChatEndGently(c->proc);
    }
    if (c->request) {
        aiChatEndRequest(c, QStringLiteral("cancelled"), QStringLiteral("Stopped to sign in."));
        c->busy = true;
        aiChatSetBusy(c, false);
    }
    c->signIn->hide();
    aiChatAdd(c, QStringLiteral("note"), QStringLiteral("After signing in, send your message again."));
}

// New chat: the running one is saved and a new one starts for the same project.
static void aiChatNewChatPressed(AiChat *c)
{
    aiTerminalStop(c);
    if (c->proc) {
        c->busy = false;
        aiChatEndGently(c->proc);
    }
    if (c->request) {
        aiChatEndRequest(c, QStringLiteral("cancelled"), QStringLiteral("A new chat was started."));
        c->busy = true; // aiChatSetBusy below tells the watchers
    }
    aiChatSaveCurrent(c);
    aiChatNewRecord(c, aiChatProjectKey(c->window));
    aiChatSetBusy(c, false);
    aiChatRender(c);
    aiChatRefreshHistory(c);
    if (aiTerminalMode()) aiTerminalStart(c);
}

// Put it in the AI menu (created by installAiAssistPanel), with a shortcut.
static void aiChatAddToAiMenu(AiChat *c, MainWindow *window, const QString &engineName)
{
    for (QAction *a : window->menuBar()->actions()) {
        if (a->menu() && a->text() == QLatin1String("AI")) {
            QAction *toggle = c->dock->toggleViewAction();
            toggle->setText(QStringLiteral("Chat with ") + engineName);
            toggle->setShortcut(QKeySequence(QStringLiteral("Ctrl+Shift+Space")));
            a->menu()->insertAction(a->menu()->actions().value(0), toggle);
            break;
        }
    }
}

// The window's project, looked at every 600 ms: another project shows its latest chat, or a new one.
static void aiChatFollowProject(AiChat *c)
{
    const QString project = aiChatProjectKey(c->window);
    if (project == c->projectKey || c->busy) {
        aiChatPostReady(c);
        return;
    }
    if (c->projectKey.isEmpty() && !project.isEmpty()) {
        // A first cut started in an unsaved chat belongs to the video once it opens.
        c->projectKey = project;
        aiChatSaveCurrent(c);
        aiChatPostReady(c);
        return;
    }
    QJsonObject latest;
    for (const QJsonValue &v : c->history) {
        const QJsonObject record = v.toObject();
        if (record.value("project").toString() == project
            && (latest.isEmpty() || record.value("updated").toString() > latest.value("updated").toString()))
            latest = record;
    }
    if (latest.isEmpty()) {
        aiTerminalStop(c);
        if (c->proc)
            aiChatStopClaude(c);
        aiChatSaveCurrent(c);
        aiChatNewRecord(c, project);
        aiChatRender(c);
        if (aiTerminalMode()) aiTerminalStart(c);
    } else {
        aiChatSwitchRecord(c, latest);
    }
    aiChatPostReady(c);
}

void installAiChatPanel(MainWindow *window)
{
    auto *c = new AiChat;
    aiChatInstance() = c;
    c->sessionId = QUuid::createUuid().toString(QUuid::WithoutBraces);
    const QString engineName = aiChatEngineName();
    c->dock = new QDockWidget(QStringLiteral("Chat with ") + engineName, window);
    c->dock->setMinimumWidth(500);
    c->dock->setObjectName(QStringLiteral("aiChatDock"));
    c->dock->toggleViewAction()->setObjectName(QStringLiteral("aiChatAction"));
    auto *panel = new QWidget(c->dock);
    auto *layout = new QVBoxLayout(panel);
    layout->setContentsMargins(6, 6, 6, 6);
    QHBoxLayout *choices = aiChatBuildChoiceRow(c, panel);
    aiChatBuildConversation(c, panel);
    QPushButton *fresh = aiChatBuildInput(c, panel, engineName);
    c->window = window;
    aiChatBuildTalk(c, window, panel);
    QHBoxLayout *buttons = aiChatButtonRow(c, fresh);
    layout->addLayout(choices);
    aiChatBuildFirstUseBar(c, panel, layout);
    aiChatBuildReviewBar(c, panel);
    layout->addWidget(c->terminalNotice);
    aiChatBuildCarryBar(c, panel, layout);
    c->terminal->installEventFilter(new AiNewVideoInputFilter(c, c->terminal));
    layout->addWidget(c->view, 1);
    layout->addWidget(c->terminal, 1);
    layout->addWidget(c->reviewBar);
    layout->addWidget(c->reviewTerminal, 1);
    aiChatBuildTargetBar(c, window, panel);
    c->terminal->setSubmitHook([c](QString *extra) { return aiTerminalAddTarget(c, extra); });
    layout->addWidget(c->targetBar);
    layout->addWidget(c->input);
    layout->addLayout(buttons);
    c->dock->setWidget(panel);
    window->addDockWidget(Qt::RightDockWidgetArea, c->dock);
    c->dock->hide();
    c->repaint = new QTimer(c->dock);
    c->repaint->setSingleShot(true);
    c->repaint->setInterval(80);
    QObject::connect(c->repaint, &QTimer::timeout, c->dock, [c]() { aiChatRender(c); });
    aiChatLoadHistory(c);
    aiChatRender(c);
    aiChatShowFirstUse(c);
    aiChatCheckSignIn(c);
    aiChatApplyMode(c);
    aiChatConnectSend(c, window);
    QObject::connect(c->stop, &QPushButton::clicked, c->dock, [c]() { aiChatStopPressed(c); });
    QObject::connect(c->signIn, &QPushButton::clicked, c->dock, [c]() { aiChatSignInPressed(c); });
    QObject::connect(fresh, &QPushButton::clicked, c->dock, [c]() { aiChatNewChatPressed(c); });
    aiChatAddToAiMenu(c, window, engineName);
    aiChatRefreshChoices(c);
    aiChatRefreshHistory(c);
    auto *projectWatch = new QTimer(c->dock);
    projectWatch->setInterval(600);
    QObject::connect(projectWatch, &QTimer::timeout, c->dock, [c]() { aiChatFollowProject(c); });
    projectWatch->start();
    // shown again: what panel.json holds now (Connect Your AI, Codex's model list or a hand edit may have changed it)
    QObject::connect(c->dock, &QDockWidget::visibilityChanged, c->dock, [c](bool visible) {
        if (visible) {
            aiChatRefreshChoices(c);
            if (aiTerminalMode()) aiTerminalStart(c);
        }
    });
}
