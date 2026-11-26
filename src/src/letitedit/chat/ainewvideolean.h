/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef AINEWVIDEOLEAN_H
#define AINEWVIDEOLEAN_H

// T294: New video's lean stage hand-offs, the editor's side (T290's bridge: bridge/letitedit/app/stage_handoff.py and
// new_video_carry.py; the seed: bridge/new_video_lean.py). Off by default: LETITEDIT_LEAN_STAGE_HANDOFFS (1 or 0) wins,
// else settings.json new_video_lean_stage_handoffs. Off, nothing here runs and New video behaves as before.
//
// On, a run that already takes one conversation per stage (stageSessions: not Turbo, not a connector, not Learn):
// - its request declares the lean hand-offs once (stagesessionsline.h);
// - once its working project and brief exist, the run is seeded (new_video_lean.py -> stage_begin), before its first
//   stage can finish (a poll while the AI works, and again at the turn's end if it hasn't been);
// - each carry check carries stage_state: the run, the project, the resolved AI, the live timeline's revision (the saved
//   file's SHA-256 when the window has no unsaved changes to it; the live timeline's own when it has, which the bridge
//   refuses: the old conversation goes on, and the person's window is never saved, closed or reloaded), and every
//   in-flight job (the window's own jobs and the bridge's; null when a job's state can't be read);
// - next_stage: the transition is kept with the chat before a fresh session is made, the timeline is attested again,
//   the departing AI process ends (not the window), a new Claude session or a new Codex thread starts with the bridge's
//   request, and once the session exists its id is acknowledged (stage_ack); stage_pending is reconciled from what was
//   kept: acknowledged again when a session exists, retried (retry_transition) when none was made, never launched twice;
// - an unfinished check with a reason (the bridge asks for a repair) carries on in the same conversation with that
//   reason, up to kLeanRepairs times, without using up the run's two ordinary carry-ons.

#include "jobqueue.h"

#include <functional>

static const int kLeanRepairs = 6;

// The switch, read when a run starts.
static bool aiLeanStageHandoffsOn()
{
    const QString forced = qEnvironmentVariable("LETITEDIT_LEAN_STAGE_HANDOFFS").trimmed().toLower();
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
        return false;
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    return QJsonDocument::fromJson(data).object().value(QStringLiteral("new_video_lean_stage_handoffs")).toBool(false);
}

static QString aiLeanSha256(const QByteArray &data)
{
    return QString::fromLatin1(QCryptographicHash::hash(data, QCryptographicHash::Sha256).toHex());
}

// The live timeline's revision. The project open in this window with unsaved changes: its live timeline, serialised
// in memory (nothing is saved); otherwise the saved file. Empty when it can't be read (the bridge then refuses).
static QString aiLeanRevision(AiChat *c)
{
    if (c->leanProject.isEmpty())
        return QString();
    const QString open = c->window ? c->window->fileName() : QString();
    const bool same = !open.isEmpty()
                      && QFileInfo(open).absoluteFilePath().compare(QFileInfo(c->leanProject).absoluteFilePath(),
                                                                    Qt::CaseInsensitive) == 0;
    if (same && c->window->isWindowModified()) {
        Mlt::Producer *timeline = c->window->multitrack();
        return aiLeanSha256(MLT.XML(timeline).toUtf8());
    }
    QFile file(c->leanProject);
    if (!file.open(QIODevice::ReadOnly))
        return QString();
    return aiLeanSha256(file.readAll());
}

// Every job in flight: the window's own (exports, proxies) and the bridge's background jobs made since the run began.
// Null (not an empty list) when a job's state can't be told.
static QJsonValue aiLeanPendingJobs(AiChat *c)
{
    QJsonArray pending;
    for (AbstractJob *job : JOBS.jobs()) {
        if (!job->ran() || job->state() == QProcess::Running)
            pending.append(QStringLiteral("editor:%1").arg(job->label()));
    }
    const QString root = qEnvironmentVariableIsSet("LETITEDIT_JOBS") ? qEnvironmentVariable("LETITEDIT_JOBS")
                                                                    : QDir(aiRoot()).filePath(QStringLiteral("jobs"));
    const QDateTime since = QDateTime::fromMSecsSinceEpoch(c->carryStarted - 5000);
    const QFileInfoList dirs = QDir(root).entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot);
    for (const QFileInfo &dir : dirs) {
        if (dir.lastModified() < since)
            continue;
        QFile status(QDir(dir.absoluteFilePath()).filePath(QStringLiteral("status.json")));
        if (!status.exists()) {
            if (QFileInfo::exists(QDir(dir.absoluteFilePath()).filePath(QStringLiteral("spec.json"))))
                pending.append(dir.fileName()); // made, not started yet
            continue;
        }
        if (!status.open(QIODevice::ReadOnly))
            return QJsonValue::Null;
        QByteArray data = status.readAll();
        if (data.startsWith("\xEF\xBB\xBF"))
            data.remove(0, 3);
        const QJsonDocument doc = QJsonDocument::fromJson(data);
        if (!doc.isObject())
            return QJsonValue::Null;
        const QString state = doc.object().value(QStringLiteral("state")).toString();
        if (state.isEmpty())
            return QJsonValue::Null;
        if (state == QLatin1String("queued") || state == QLatin1String("running") || state == QLatin1String("interrupted"))
            pending.append(dir.fileName());
    }
    return pending;
}

static QJsonObject aiLeanAi(AiChat *c)
{
    // the run's resolved choice, as the AI was started with it (an empty saved value means the AI's own default)
    return QJsonObject{{"engine", c->carryEngine},
                       {"model", c->carryModel.isEmpty() ? QStringLiteral("default") : c->carryModel},
                       {"effort", c->carryEffort.isEmpty() ? QStringLiteral("default") : c->carryEffort}};
}

static qint64 aiStageStartMaxBytes(AiChat *c); // T300 (chat/ainewvideostart.h)

// stage_state for a carry check; also remembers the revision attested, for the check again before dispatch.
static QJsonObject aiLeanStageState(AiChat *c)
{
    c->leanAttested = aiLeanRevision(c);
    QJsonObject state{{"run_id", c->leanRunId}, {"project", c->leanProject}, {"ai", aiLeanAi(c)},
                      {"revision", c->leanAttested}, {"pending_jobs", aiLeanPendingJobs(c)}};
    if (!c->leanRetry.isEmpty())
        state["retry_transition"] = c->leanRetry;
    // T300: the next stage's first message is built to the receiving AI's own one-message limit
    const qint64 limit = aiStageStartMaxBytes(c);
    if (limit > 0)
        state["stage_start_max_bytes"] = double(limit);
    return state;
}

// QA: LETITEDIT_QA_LEAN_LOSE=<file>, one decision per line ("next_stage", "stage_started"): the next reply with that
// decision is lost once (the line goes), as when the check's process dies before its answer arrives.
static bool aiLeanQaLose(const QString &decision)
{
    const QString path = qEnvironmentVariable("LETITEDIT_QA_LEAN_LOSE");
    QFile file(path);
    if (path.isEmpty() || decision.isEmpty() || !file.open(QIODevice::ReadOnly))
        return false;
    QStringList lines;
    for (const QString &line : QString::fromUtf8(file.readAll()).split(QLatin1Char('\n'), Qt::SkipEmptyParts))
        if (!line.trimmed().isEmpty())
            lines << line.trimmed();
    file.close();
    const int at = lines.indexOf(decision);
    if (at < 0)
        return false;
    lines.removeAt(at);
    if (file.open(QIODevice::WriteOnly | QIODevice::Truncate))
        file.write(lines.join(QLatin1Char('\n')).toUtf8());
    return true;
}

// A bridge script with JSON on stdin and one JSON object out; done() gets {} on any failure (or a QA-lost reply).
static void aiLeanPython(AiChat *c, const QString &script, const QJsonObject &input, int timeoutMs,
                         const std::function<void(const QJsonObject &)> &done)
{
    auto *process = new QProcess(c->dock);
    process->setProgram(aiChatSettings().value(QStringLiteral("python")).toString());
    process->setArguments({QDir(aiRoot()).filePath(script)});
    auto answered = std::make_shared<bool>(false);
    const auto finish = [answered, done](const QJsonObject &result) {
        if (*answered)
            return;
        *answered = true;
        done(aiLeanQaLose(result.value(QStringLiteral("decision")).toString()) ? QJsonObject() : result);
    };
    QObject::connect(process, &QProcess::finished, c->dock, [process, finish](int code) {
        const QByteArray out = process->readAllStandardOutput().trimmed();
        const QJsonObject result = QJsonDocument::fromJson(out.mid(out.lastIndexOf('\n') + 1)).object();
        finish(code == 0 ? result : QJsonObject());
        process->deleteLater();
    });
    QObject::connect(process, &QProcess::errorOccurred, c->dock, [process, finish](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            finish(QJsonObject());
            process->deleteLater();
        }
    });
    QTimer::singleShot(timeoutMs, process, [process]() { if (process->state() != QProcess::NotRunning) process->kill(); });
    process->start();
    process->write(QJsonDocument(input).toJson(QJsonDocument::Compact));
    process->closeWriteChannel();
}

// Seed the run once its working project and brief exist; then() runs after the answer (whatever it was).
static void aiLeanSeed(AiChat *c, const std::function<void()> &then = {})
{
    if (c->leanSeeding && then) { // the poll's seed is on its way: the check waits for it
        QTimer::singleShot(1000, c->dock, [c, then]() { aiLeanSeed(c, then); });
        return;
    }
    if (!c->leanStages || !c->leanProject.isEmpty() || !c->leanSeedRefused.isEmpty() || c->leanSeeding) {
        if (then)
            then();
        return;
    }
    c->leanSeeding = true;
    const QString chat = c->chatId;
    const QString run = c->leanRunId;
    QJsonObject input{{"folder", c->autonomousWriteDir}, {"since", c->carryStarted / 1000.0}, {"run_id", run},
                      {"request", c->newVideoRequest}, {"ai", aiLeanAi(c)}};
    const QString open = c->window ? c->window->fileName() : QString();
    if (!open.isEmpty())
        input["project"] = open;
    aiLeanPython(c, QStringLiteral("bridge/new_video_lean.py"), input, 120000, [c, chat, run, then](const QJsonObject &r) {
        if (c->chatId != chat || c->leanRunId != run)
            return;
        c->leanSeeding = false;
        const QString decision = r.value(QStringLiteral("decision")).toString();
        if (decision == QLatin1String("stage_ready")) {
            c->leanProject = r.value(QStringLiteral("project")).toString();
            aiChatSaveCurrent(c);
        } else if (decision == QLatin1String("refused")) {
            c->leanSeedRefused = r.value(QStringLiteral("reason")).toString(QStringLiteral("the run could not be seeded"));
            aiChatSaveCurrent(c);
        }
        if (then)
            then();
    });
}

// While a lean run works: seed it as soon as a brief appears in its folder.
static void aiLeanPollTick(AiChat *c)
{
    if (!c->leanStages || !c->leanProject.isEmpty() || !c->leanSeedRefused.isEmpty() || !c->autonomousNewVideo) {
        if (c->leanPoll)
            c->leanPoll->stop();
        return;
    }
    if (c->leanSeeding)
        return;
    const QDir folder(c->autonomousWriteDir);
    for (const QFileInfo &side : folder.entryInfoList({QStringLiteral("*.letitedit")}, QDir::Dirs)) {
        if (QFileInfo::exists(QDir(side.absoluteFilePath()).filePath(QStringLiteral("brief.json")))) {
            aiLeanSeed(c);
            return;
        }
    }
}

// A run starts: its lean state is new (a run id of its own: a final continued from a preview is a new run).
static void aiLeanStart(AiChat *c)
{
    c->leanRunId = c->leanStages
        ? QStringLiteral("nv-%1-%2").arg(c->chatId.left(8)).arg(c->carryStarted)
        : QString();
    c->leanProject.clear();
    c->leanSeedRefused.clear();
    c->leanSeeding = false;
    c->leanTransition = QJsonObject();
    c->leanRetry.clear();
    c->leanAttested.clear();
    c->leanRepairs = 0;
    if (!c->leanStages) {
        if (c->leanPoll)
            c->leanPoll->stop();
        return;
    }
    if (!c->leanPoll) {
        c->leanPoll = new QTimer(c->dock);
        QObject::connect(c->leanPoll, &QTimer::timeout, c->dock, [c]() { aiLeanPollTick(c); });
    }
    c->leanPoll->start(3000);
}

// The fresh session exists (Claude: its process started with the new session id; Codex: its new thread has its id):
// keep the id with the transition, then acknowledge it.
static void aiLeanAck(AiChat *c, const std::function<void()> &then = {});

static void aiLeanSessionCreated(AiChat *c)
{
    if (!c->leanStages || c->leanTransition.value(QStringLiteral("state")).toString() != QLatin1String("launching"))
        return;
    c->leanTransition["state"] = QStringLiteral("created");
    c->leanTransition["session"] = c->sessionId;
    if (!c->runSessions.contains(c->sessionId))
        c->runSessions << c->sessionId;
    aiChatSaveCurrent(c);
    aiLeanAck(c);
}

static void aiLeanAck(AiChat *c, const std::function<void()> &then)
{
    const QJsonObject t = c->leanTransition;
    if (t.value(QStringLiteral("state")).toString() != QLatin1String("created") || t.value(QStringLiteral("acked")).toBool()
        || c->leanProject.isEmpty()) {
        if (then)
            then();
        return;
    }
    const QString chat = c->chatId;
    const QString id = t.value(QStringLiteral("id")).toString();
    c->leanAcks += 1;
    aiLeanPython(c, QStringLiteral("bridge/new_video_carry.py"),
                 QJsonObject{{"action", "stage_ack"}, {"project", c->leanProject}, {"run_id", c->leanRunId},
                             {"transition_id", id}, {"session_id", t.value(QStringLiteral("session"))}},
                 12000, [c, chat, id, then](const QJsonObject &r) {
                     if (c->chatId != chat || c->leanTransition.value(QStringLiteral("id")).toString() != id)
                         return;
                     if (r.value(QStringLiteral("decision")).toString() == QLatin1String("stage_started")) {
                         c->leanTransition["acked"] = true;
                         aiChatSaveCurrent(c);
                     }
                     if (then)
                         then();
                 });
}

static QJsonObject aiLeanRecord(AiChat *c)
{
    return QJsonObject{{"on", c->leanStages}, {"run_id", c->leanRunId}, {"project", c->leanProject},
                       {"seed_refused", c->leanSeedRefused}, {"transition", c->leanTransition}};
}

static void aiLeanLoad(AiChat *c, const QJsonObject &lean)
{
    c->leanStages = c->stageSessions && lean.value(QStringLiteral("on")).toBool();
    c->leanRunId = lean.value(QStringLiteral("run_id")).toString();
    c->leanProject = lean.value(QStringLiteral("project")).toString();
    c->leanSeedRefused = lean.value(QStringLiteral("seed_refused")).toString();
    c->leanTransition = lean.value(QStringLiteral("transition")).toObject();
    c->leanSeeding = false;
    c->leanRetry.clear();
    c->leanAttested.clear();
    c->leanRepairs = 0;
    if (c->leanPoll)
        c->leanPoll->stop();
}

#endif // AINEWVIDEOLEAN_H
