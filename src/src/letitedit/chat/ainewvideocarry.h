#ifndef AINEWVIDEOCARRY_H
#define AINEWVIDEOCARRY_H

int aiChatRequest(MainWindow *, const QString &, const QString &, bool, bool);
static void aiChatEndRequest(AiChat *, const QString &, const QString &);
QString aiChatRefusal();

class AiNewVideoInputFilter : public QObject
{
public:
    AiNewVideoInputFilter(AiChat *chat, QObject *parent) : QObject(parent), m_chat(chat) {}
protected:
    bool eventFilter(QObject *, QEvent *event) override
    {
        if (!m_chat->autonomousNewVideo)
            return false;
        if (event->type() == QEvent::ContextMenu || event->type() == QEvent::InputMethod
            || (event->type() == QEvent::MouseButtonPress && static_cast<QMouseEvent *>(event)->button() == Qt::MiddleButton))
            m_chat->carryHumanInput = true;
        if (event->type() == QEvent::KeyPress) {
            auto *key = static_cast<QKeyEvent *>(event);
            if (!key->text().isEmpty() || key->key() == Qt::Key_Escape || key->key() == Qt::Key_Backspace)
                m_chat->carryHumanInput = true;
            if (key->key() == Qt::Key_Escape || (key->key() == Qt::Key_C && key->modifiers() == Qt::ControlModifier))
                m_chat->carryAllowed = false;
        }
        return false;
    }
private:
    AiChat *m_chat;
};

static QString aiNewVideoCarryWords()
{
    return QStringLiteral("Carry on with the edit in this SAME New video. Inspect its saved project and existing jobs, "
                          "then perform the next unfinished editing stage now. Reuse completed work and wait for existing jobs. "
                          "This is an editing request, not a request for a status report. Finish the requested video and its checks. "
                          "End only with the finished video and its checks, or a specific blocker that actually prevents finishing: "
                          "write 'Blocked: ' followed by what you cannot do and why. Keep the original brief and permissions.");
}

static void aiNewVideoStopped(AiChat *c, const QString &reason)
{
    c->carryAllowed = false;
    c->carryPending = false;
    c->carryStopped = true;
    aiChatAdd(c, QStringLiteral("new-video-stopped"),
              QStringLiteral("Your video stopped before it was finished. ") + reason);
    if (c->carryBar) {
        c->carryLabel->setText(QStringLiteral("Your video stopped before it was finished. ") + reason);
        c->carryContinue->show();
        c->carryBar->show();
    }
}

// The person has stepped in on New video's run: something typed in the message box, or a recording.
static bool aiNewVideoPersonTyping(AiChat *c)
{
    return (c->input && !c->input->toPlainText().trimmed().isEmpty()) || c->recording;
}

// The AI, model or effort is no longer the one New video's run started with.
static bool aiNewVideoChoiceChanged(AiChat *c)
{
    return c->carryEngine != aiChatEngineId(aiChatSettings())
        || c->carryModel != aiChatSettings().value(aiChatModelKeyOf(c->carryEngine)).toString()
        || c->carryEffort != aiChatSettings().value(aiChatEffortKeyOf(c->carryEngine)).toString();
}

// letitedit sends the run's next request itself: the bar says so (barText). If the AI can't take it, the run stops and
// whyNot says why.
static bool aiNewVideoSendItself(AiChat *c, const QString &barText, const QString &text, const QString &summary,
                                 const QString &whyNot)
{
    if (c->carryBar) {
        c->carryLabel->setText(barText);
        c->carryContinue->hide();
        c->carryBar->show();
    }
    c->busy = false;
    const int sent = aiChatRequest(c->window, text, summary, false, false);
    c->carrySending = false;
    c->verbatimBytes = -1; // T300: a word-for-word send is for that one message, sent or not
    c->verbatimSha.clear();
    c->verbatimDetail.clear();
    if (!sent) {
        aiNewVideoStopped(c, whyNot);
        aiChatEndRequest(c, QStringLiteral("failed"), aiChatRefusal());
        aiChatSetBusy(c, false);
    }
    return sent;
}

// The AI's plan ran out of usage (T193): read its words (bridge/usage_limit.py); a limit is waited out and the same
// request carries on by itself at the reset plus a minute (every 30 min, at most kLimitWaits waits, when it gives no
// time). Anything else goes on as before: returns false when the turn's text says nothing of a limit.
static const int kLimitWaits = 8;

static void aiNewVideoLimitTick(AiChat *c)
{
    if (!c->limitCarryAt || !c->carryPending || QDateTime::currentSecsSinceEpoch() < c->limitCarryAt)
        return;
    c->limitTimer->stop();
    c->limitCarryAt = 0;
    c->limitWords.clear();
    c->carryPending = false;
    c->carrySending = true;
    if (!aiNewVideoSendItself(c, QStringLiteral("letitedit: the usage limit has reset; carrying on with the edit"),
                              aiNewVideoCarryWords(), QStringLiteral("Carry on with the edit"),
                              QStringLiteral("Your AI could not take the continuation.")))
        return;
    // the card's record works again, in the phase it was in (a carry-on keeps its request, so nothing else restarts it)
    const QString run = aiChatProgressRun();
    if (!run.isEmpty())
        QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(),
                                {QDir(aiRoot()).filePath(QStringLiteral("bridge/progress_feed.py")), QStringLiteral("working"),
                                 QStringLiteral("--json"),
                                 QString::fromUtf8(QJsonDocument(QJsonObject{{QStringLiteral("run"), run}}).toJson(QJsonDocument::Compact))});
}

static bool aiNewVideoLimit(AiChat *c, const QString &outcome, const QString &said)
{
    static const QRegularExpression quick(QStringLiteral("hit your|usage limit|limit reached|reached your [\\w -]*limit|"
                                                         "out of usage|limit will reset|quota exceeded"),
                                          QRegularExpression::CaseInsensitiveOption);
    if (c->limitChecked == c->turnNumber || !quick.match(said).hasMatch())
        return false;
    c->limitChecked = c->turnNumber;
    if (c->limitWaits >= kLimitWaits) {
        aiNewVideoStopped(c, QStringLiteral("Your AI's usage limit was reached again, and letitedit has waited %1 times. "
                                            "Press Continue the edit once it has reset.").arg(kLimitWaits));
        return false;
    }
    c->carryPending = true;
    const int request = c->request;
    const QString chat = c->chatId;
    auto *process = new QProcess(c->dock);
    process->setProgram(aiChatSettings().value(QStringLiteral("python")).toString());
    process->setArguments({QDir(aiRoot()).filePath(QStringLiteral("bridge/usage_limit.py"))});
    const QString error = said.section(QLatin1Char('\n'), 0, 0);
    const auto decide = [c, request, chat, outcome, error](const QJsonObject &read) {
        if (!c->carryPending || c->request != request || c->chatId != chat)
            return;
        c->carryPending = false;
        if (!read.value(QStringLiteral("limit")).toBool()) {
            // not a limit: the turn ends as it would have (limitChecked keeps this from being read twice)
            aiChatEndRequest(c, outcome, error);
            aiChatSetBusy(c, false);
            return;
        }
        ++c->limitWaits;
        c->carryPending = true;
        c->limitWords = read.value(QStringLiteral("words")).toString();
        c->limitCarryAt = qint64(read.value(QStringLiteral("carry_at")).toDouble());
        // QA: LETITEDIT_QA_LIMIT_CARRY_S fast-forwards the reset (a journey can't wait hours)
        if (qEnvironmentVariableIsSet("LETITEDIT_QA_LIMIT_CARRY_S"))
            c->limitCarryAt = QDateTime::currentSecsSinceEpoch() + qEnvironmentVariableIntValue("LETITEDIT_QA_LIMIT_CARRY_S");
        aiChatAdd(c, QStringLiteral("note"), c->limitWords);
        if (c->carryBar) {
            c->carryLabel->setText(c->limitWords);
            c->carryContinue->hide();
            c->carryBar->show();
        }
        if (!c->limitTimer) {
            c->limitTimer = new QTimer(c->dock);
            QObject::connect(c->limitTimer, &QTimer::timeout, c->dock, [c]() { aiNewVideoLimitTick(c); });
        }
        c->limitTimer->start(qEnvironmentVariableIsSet("LETITEDIT_QA_LIMIT_CARRY_S") ? 1000 : 30000);
        // the card's record waits too (bridge/progress_feed.py limit)
        const QJsonObject meta{{QStringLiteral("run"), aiChatProgressRun()}, {QStringLiteral("words"), c->limitWords},
                               {QStringLiteral("resets_at"), read.value(QStringLiteral("resets_at"))}};
        QProcess::startDetached(aiChatSettings().value(QStringLiteral("python")).toString(),
                                {QDir(aiRoot()).filePath(QStringLiteral("bridge/progress_feed.py")), QStringLiteral("limit"),
                                 QStringLiteral("--json"), QString::fromUtf8(QJsonDocument(meta).toJson(QJsonDocument::Compact))});
    };
    QObject::connect(process, &QProcess::finished, c->dock, [process, decide](int code) {
        decide(code == 0 ? QJsonDocument::fromJson(process->readAllStandardOutput()).object() : QJsonObject());
        process->deleteLater();
    });
    QObject::connect(process, &QProcess::errorOccurred, c->dock, [process, decide](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            decide(QJsonObject());
            process->deleteLater();
        }
    });
    QTimer::singleShot(12000, process, [process]() { if (process->state() != QProcess::NotRunning) process->kill(); });
    process->start();
    process->write(QJsonDocument(QJsonObject{{"text", said}, {"engine", c->engine}}).toJson(QJsonDocument::Compact));
    process->closeWriteChannel();
    return true;
}

// T194: the next stage in a fresh conversation. The AI running between turns is ended (its conversation is saved), and
// the next request starts a new session: the same chat record, so the card and its progress record (nv-<chatId>) stay
// one run, and the transcript goes on below.
static void aiNewVideoFreshSession(AiChat *c)
{
    if (aiTerminalMode())
        aiTerminalStop(c);
    else if (c->proc)
        aiChatStopClaude(c);
    if (!c->sessionId.isEmpty() && !c->runSessions.contains(c->sessionId))
        c->runSessions << c->sessionId;
    c->sessionId = QUuid::createUuid().toString(QUuid::WithoutBraces);
    c->sessionStarted = false;
    c->runSessions << c->sessionId;
    aiChatSaveCurrent(c);
}

// T194: a stage was handed over; the next one starts in a fresh conversation (bridge/new_video_stages.py)
static void aiNewVideoCarryOn(AiChat *c, int request, const QString &chat, const QString &decision,
                              const QString &leanReason = QString());

static void aiNewVideoNextStage(AiChat *c, int request, const QString &chat, const QJsonObject &result)
{
    if (!c->carryPending || c->request != request || c->chatId != chat)
        return;
    if (c->leanStages) {
        // T294: the transition is kept with the chat before any fresh session is made (a stop below leaves it
        // prepared, with no session: the next check retries the same launch)
        c->leanRetry.clear();
        c->leanTransition = QJsonObject{{"id", result.value(QStringLiteral("transition_id")).toString()},
                                        {"next", result.value(QStringLiteral("next")).toString()},
                                        {"state", QStringLiteral("prepared")}};
        aiChatSaveCurrent(c);
    }
    const bool typing = aiNewVideoPersonTyping(c);
    const bool changed = aiNewVideoChoiceChanged(c);
    const QString next = result.value(QStringLiteral("next")).toString();
    const QString text = result.value(QStringLiteral("request")).toString();
    if (typing || c->carryHumanInput || changed || text.isEmpty()) {
        aiNewVideoStopped(c, typing || c->carryHumanInput
            ? QStringLiteral("Your message is kept; send it when you are ready.")
            : changed ? QStringLiteral("Your AI choice changed.")
            : QStringLiteral("letitedit could not check the saved video."));
        aiChatEndRequest(c, QStringLiteral("answered"), QString());
        aiChatSetBusy(c, false);
        return;
    }
    if (c->leanStages && aiLeanRevision(c) != c->leanAttested) {
        // T294: attested again just before dispatch: the timeline changed since the check, so the old conversation goes
        // on (the person's window is never saved, closed or reloaded for this)
        aiNewVideoCarryOn(c, request, chat, QStringLiteral("unfinished"),
                          QStringLiteral("The timeline changed while the next stage was being prepared."));
        return;
    }
    c->carryPending = false;
    c->carrySending = true;
    c->carryCount = 0; // each stage's conversation has its own two carry-ons
    aiNewVideoFreshSession(c);
    if (c->leanStages) {
        c->leanTransition["state"] = QStringLiteral("launching");
        aiChatSaveCurrent(c);
    }
    // T300: the bridge's startup checksums come with its request: the transport sends it word for word, no context
    // line, and only if it is exactly that text
    const QJsonObject startup = result.value(QStringLiteral("startup")).toObject();
    if (startup.contains(QStringLiteral("sha256")) && startup.contains(QStringLiteral("bytes"))) {
        c->verbatimBytes = qint64(startup.value(QStringLiteral("bytes")).toDouble(-1));
        c->verbatimSha = startup.value(QStringLiteral("sha256")).toString();
        c->verbatimDetail.clear();
    }
    const bool sent = aiNewVideoSendItself(c, QStringLiteral("letitedit: the %1 stage starts in a fresh conversation").arg(next), text,
                                           QStringLiteral("Next stage: %1").arg(next), QStringLiteral("Your AI could not take the next stage."));
    if (c->leanStages && c->leanTransition.value(QStringLiteral("state")).toString() == QLatin1String("launching")) {
        if (!sent) {
            c->leanTransition["state"] = QStringLiteral("prepared"); // nothing was made: a later check retries it
            aiChatSaveCurrent(c);
        } else if (c->engine != QLatin1String("codex")) {
            aiLeanSessionCreated(c); // Claude's new session (--session-id) started with the process
        }                            // Codex: once its new thread has an id (aicodexserver.h)
    }
}

// The video isn't finished: carry on in the same conversation (twice at most), unless the person has stepped in.
static void aiNewVideoCarryOn(AiChat *c, int request, const QString &chat, const QString &decision,
                              const QString &leanReason)
{
    if (!c->carryPending || c->request != request || c->chatId != chat)
        return;
    const bool typing = aiNewVideoPersonTyping(c);
    const bool changed = aiNewVideoChoiceChanged(c);
    // T294: the lean hand-off kept this stage here (a repair the bridge asks for): not one of the run's two carry-ons
    const bool repair = !leanReason.isEmpty() && c->leanRepairs < kLeanRepairs;
    if (typing || c->carryHumanInput || changed || decision != QLatin1String("unfinished") || (!repair && c->carryCount >= 2)) {
        aiNewVideoStopped(c, typing || c->carryHumanInput
            ? c->terminal && c->terminal->running()
                ? QStringLiteral("You started typing; letitedit did not send anything.")
                : QStringLiteral("Your message is kept; send it when you are ready.")
            : changed ? QStringLiteral("Your AI choice changed.")
            : decision != QLatin1String("unfinished") ? QStringLiteral("letitedit could not check the saved video.")
            : QStringLiteral("letitedit tried carrying on twice."));
        aiChatEndRequest(c, QStringLiteral("answered"), QString());
        aiChatSetBusy(c, false);
        return;
    }
    c->carryPending = false;
    c->carrySending = true;
    if (repair) {
        ++c->leanRepairs;
        // a run that could not be seeded can't hand over at all: it simply goes on here
        const QString why = c->leanSeedRefused.isEmpty()
            ? leanReason
            : QStringLiteral("lean hand-offs are off for this run (%1).").arg(c->leanSeedRefused);
        // a run that stops after a stage (a Studio preview) still stops there: no further stage
        const QString stop = qEnvironmentVariable("LETITEDIT_NEW_VIDEO_STOP_AFTER").trimmed();
        const QString words = stop.isEmpty()
            ? aiNewVideoCarryWords()
                  + QStringLiteral("\n\nletitedit kept this stage in this conversation: %1 If that names something you "
                                   "can fix (the structured `handover:` note, a job still running), fix it and end your "
                                   "turn again; otherwise go straight on to the next stage in this conversation.").arg(why)
            : QStringLiteral("This New video stops after the %1 stage. letitedit could not seal its hand-off: %2 If that "
                             "names something you can fix (the structured `handover:` note, a job still running), fix it, "
                             "then end your turn with `Stage %1 done; stopping here`. Start no further stage, review or "
                             "export.").arg(stop, why);
        aiNewVideoSendItself(c, QStringLiteral("letitedit: Carry on with the edit in this conversation"), words,
                             QStringLiteral("Carry on with the edit"), QStringLiteral("Your AI could not take the continuation."));
        return;
    }
    ++c->carryCount;
    aiNewVideoSendItself(c, QStringLiteral("letitedit: Carry on with the edit (%1 of 2)").arg(c->carryCount),
                         aiNewVideoCarryWords(), QStringLiteral("Carry on with the edit"),
                         QStringLiteral("Your AI could not take the continuation."));
}

// T294: a lean run's carry check: seeded first if it isn't yet, the last fresh session acknowledged if its receipt was
// lost, then the check with the run's live state (chat/ainewvideolean.h).
static void aiNewVideoDecided(AiChat *c, int request, const QString &chat, const QJsonObject &result);

static void aiLeanInspect(AiChat *c, int request, const QString &chat)
{
    const auto live = [c, request, chat]() { return c->carryPending && c->request == request && c->chatId == chat; };
    aiLeanSeed(c, [c, request, chat, live]() {
        if (!live())
            return;
        aiLeanAck(c, [c, request, chat, live]() {
            if (!live())
                return;
            QJsonObject carry{{"folder", c->autonomousWriteDir}, {"since", c->carryStarted / 1000.0},
                              {"answer", c->leanAnswer}, {"cost", c->newVideoMakes},
                              {"sessions", QJsonArray::fromStringList(c->runSessions)},
                              {"stage_sessions", true}, {"request", c->newVideoRequest}};
            if (!c->leanProject.isEmpty())
                carry["stage_state"] = aiLeanStageState(c);
            aiLeanPython(c, QStringLiteral("bridge/new_video_carry.py"), carry, 30000,
                         [c, request, chat](const QJsonObject &r) { aiNewVideoDecided(c, request, chat, r); });
        });
    });
}

// stage_pending: a launch was prepared for this boundary and not acknowledged. What the chat kept says what happened:
// a session was made (acknowledge it, then check again), or none was (retry the same launch); never a second launch.
static void aiLeanPending(AiChat *c, int request, const QString &chat, const QJsonObject &result)
{
    const QString id = result.value(QStringLiteral("transition_id")).toString();
    const bool ours = !id.isEmpty() && c->leanTransition.value(QStringLiteral("id")).toString() == id;
    QString state = ours ? c->leanTransition.value(QStringLiteral("state")).toString() : QString();
    if (state == QLatin1String("launching") && c->sessionStarted) {
        aiLeanSessionCreated(c); // it was made (the receipt never came back): kept and acknowledged now
        state = QStringLiteral("created");
    }
    if (c->leanRechecks >= 3) {
        QTimer::singleShot(1500, c->dock, [c, request, chat]() {
            aiNewVideoCarryOn(c, request, chat, QStringLiteral("unfinished"),
                              QStringLiteral("A fresh stage's launch could not be reconciled."));
        });
        return;
    }
    ++c->leanRechecks;
    if (state == QLatin1String("created")) {
        c->leanTransition["acked"] = false;
        aiLeanAck(c, [c, request, chat]() { aiLeanInspect(c, request, chat); });
        return;
    }
    c->leanRetry = id; // no session was made for it: the identical launch again
    aiLeanInspect(c, request, chat);
}

// What the carry-on check said about the saved video (bridge/new_video_carry.py): the next stage, finished or blocked,
// or not finished yet.
static void aiNewVideoDecided(AiChat *c, int request, const QString &chat, const QJsonObject &result)
{
    const QString decision = result.value(QStringLiteral("decision")).toString();
    if (!c->carryPending || c->request != request || c->chatId != chat)
        return;
    if (c->leanStages) {
        const QString reason = result.value(QStringLiteral("reason")).toString();
        if (decision == QLatin1String("stage_pending")) {
            aiLeanPending(c, request, chat, result);
            return;
        }
        if ((decision.isEmpty() || decision == QLatin1String("unknown")) && c->leanRechecks < 3) {
            ++c->leanRechecks; // a lost or garbled reply: nothing was launched for it, so ask again
            QTimer::singleShot(1500, c->dock, [c, request, chat]() { aiLeanInspect(c, request, chat); });
            return;
        }
        if (decision == QLatin1String("unfinished") && !reason.isEmpty()) {
            QTimer::singleShot(1500, c->dock, [c, request, chat, decision, reason]() {
                aiNewVideoCarryOn(c, request, chat, decision, reason);
            });
            return;
        }
    }
    if (decision == QLatin1String("next_stage")) {
        QTimer::singleShot(1500, c->dock, [c, request, chat, result]() { aiNewVideoNextStage(c, request, chat, result); });
        return;
    }
    if (decision == QLatin1String("finished") || decision == QLatin1String("blocked")) {
        c->carryPending = false;
        c->carryAllowed = false;
        if (c->carryBar)
            c->carryBar->hide();
        aiChatEndRequest(c, QStringLiteral("answered"), QString());
        aiChatSetBusy(c, false);
        return;
    }
    QTimer::singleShot(1500, c->dock, [c, request, chat, decision]() { aiNewVideoCarryOn(c, request, chat, decision); });
}

static bool aiNewVideoCarry(AiChat *c, const QString &outcome, const QString &answer, const QString &said = QString())
{
    if (!c->autonomousNewVideo || c->liveReviewHold || !c->carryAllowed)
        return false;
    if (c->carryPending && (c->limitCarryAt || c->limitChecked == c->turnNumber))
        return true; // waiting for a usage limit, or reading whether it was one
    if (outcome != QLatin1String("cancelled") && aiNewVideoLimit(c, outcome, said))
        return true;
    if (outcome != QLatin1String("answered") || !c->queued.isEmpty()) {
        c->carryAllowed = false;
        c->carryPending = false;
        return false;
    }
    if (c->carryPending)
        return true;
    c->carryPending = true;
    const int request = c->request;
    const QString chat = c->chatId;
    if (c->leanStages) {
        if (!c->sessionId.isEmpty() && !c->runSessions.contains(c->sessionId))
            c->runSessions << c->sessionId;
        c->leanAnswer = answer;
        c->leanRechecks = 0;
        aiLeanInspect(c, request, chat);
        return true;
    }
    auto *process = new QProcess(c->dock);
    process->setProgram(aiChatSettings().value(QStringLiteral("python")).toString());
    process->setArguments({QDir(aiRoot()).filePath(QStringLiteral("bridge/new_video_carry.py"))});
    const auto finish = [c, request, chat](const QJsonObject &result) { aiNewVideoDecided(c, request, chat, result); };
    QObject::connect(process, &QProcess::finished, c->dock, [process, finish](int code) {
        const QJsonObject result = QJsonDocument::fromJson(process->readAllStandardOutput()).object();
        finish(code == 0 ? result : QJsonObject());
        process->deleteLater();
    });
    QObject::connect(process, &QProcess::errorOccurred, c->dock, [process, finish](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            finish(QJsonObject());
            process->deleteLater();
        }
    });
    QTimer::singleShot(12000, process, [process]() { if (process->state() != QProcess::NotRunning) process->kill(); });
    process->start();
    // T194: Codex names its own thread, so the current id joins the run's sessions here
    if (!c->sessionId.isEmpty() && !c->runSessions.contains(c->sessionId))
        c->runSessions << c->sessionId;
    QJsonObject carry{{"folder", c->autonomousWriteDir}, {"since", c->carryStarted / 1000.0}, {"answer", answer},
                      // the run's cost line beside the project when it is finished (bridge/run_cost.py)
                      {"cost", c->newVideoMakes}, {"sessions", QJsonArray::fromStringList(c->runSessions)}};
    if (c->stageSessions && !c->newVideoRequest.isEmpty()) {
        carry["stage_sessions"] = true;
        carry["request"] = c->newVideoRequest;
        // T300: a fresh stage's first message is built to the receiving AI's own one-message limit
        const qint64 limit = aiStageStartMaxBytes(c);
        if (limit > 0)
            carry["stage_state"] = QJsonObject{{"stage_start_max_bytes", double(limit)}};
    }
    process->write(QJsonDocument(carry).toJson(QJsonDocument::Compact));
    process->closeWriteChannel();
    return true;
}

#endif
