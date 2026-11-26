/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Codex app-server's newline-delimited JSON-RPC transport for the chat dock.
 * The app-server uses the person's Codex config, plugins, MCP servers and subscription.
 */
#ifndef AICODEXSERVER_H
#define AICODEXSERVER_H

int aiChatRequest(MainWindow *, const QString &, const QString &, bool, bool);

static int aiCodexRpc(AiChat *c, const QString &method, const QJsonObject &params, const QString &tag)
{
    if (!c->proc)
        return 0;
    const int id = c->codexRpcNext++;
    c->codexRpc.insert(id, tag);
    c->proc->write(QJsonDocument(QJsonObject{{"id", id}, {"method", method}, {"params", params}})
                       .toJson(QJsonDocument::Compact) + '\n');
    return id;
}

static QJsonArray aiCodexInput(const QString &content)
{
    return QJsonArray{QJsonObject{{"type", "text"}, {"text", content}, {"text_elements", QJsonArray()}}};
}

static void aiCodexRunQueued(AiChat *c)
{
    if (c->busy || c->queued.isEmpty())
        return;
    const QString next = c->queued.takeFirst();
    // The steer was already shown while the previous turn ran. Move it to the new turn's place.
    for (int i = c->blocks.size() - 1; i >= 0; --i)
        if (c->blocks[i].kind == QLatin1String("user") && c->blocks[i].text == next) {
            c->blocks.removeAt(i);
            break;
        }
    QTimer::singleShot(0, c->dock, [c, next]() { aiChatRequest(c->window, next, QString(), false); });
}

// Where Codex runs: the chat's own folder, as Claude and the Terminal view. Never the install folder or repo, whose
// AGENTS.md Codex would read as its instructions (T74: a test run obeyed it and committed to main).
static QString aiCodexWork()
{
    const QString work = aiChatSettings().value("work_dir").toString();
    QDir().mkpath(work);
    return work;
}

static void aiCodexStartTurn(AiChat *c)
{
    if (!c->codexReady || c->codexPending.isEmpty())
        return;
    const QJsonObject s = aiRunSettings(c);
    QString model;
    aiCodexChoiceArgs(s, &model);
    QJsonObject params{{"threadId", c->sessionId}, {"input", aiCodexInput(c->codexPending)},
                       {"cwd", aiCodexWork()}, {"model", model},
                       {"effort", s.value("codex_reasoning").toString()}};
    c->procSpeed = aiSpeedValue(s, QStringLiteral("codex"));
    params["serviceTier"] = aiCodexSpeedTier(s);
    params["serviceTierForTurn"] = params.value("serviceTier");
    // The selected model can offer less than xhigh. Use the effort actually passed to Codex.
    const QStringList choices = aiCodexChoiceArgs(s);
    for (int i = 0; i + 1 < choices.size(); ++i)
        if (choices[i] == QLatin1String("-c") && choices[i + 1].startsWith(QLatin1String("model_reasoning_effort="))) {
            QString effort = choices[i + 1].section(QLatin1Char('='), 1);
            if (effort.startsWith(QLatin1Char('"')) && effort.endsWith(QLatin1Char('"')))
                effort = effort.mid(1, effort.size() - 2);
            params["effort"] = effort;
        }
    if (c->autonomousNewVideo) {
        // The app-server policy is per turn. This is the equivalent of the
        // Terminal path's --approve-for-me --sandbox workspace-write --add-dir:
        // automatic review, never unrestricted filesystem access, and only the
        // video's output folder in addition to the workspace.
        QJsonArray writableRoots;
        if (!c->autonomousWriteDir.isEmpty())
            writableRoots.append(QDir::fromNativeSeparators(c->autonomousWriteDir));
        params["approvalPolicy"] = QStringLiteral("on-request");
        params["approvalsReviewer"] = QStringLiteral("auto_review");
        params["sandboxPolicy"] = QJsonObject{{"type", QStringLiteral("workspaceWrite")},
                                                {"writableRoots", writableRoots}};
    } else {
        params["approvalsReviewer"] = QStringLiteral("auto_review"); // T221: the automatic reviewer, never a box
    }
    c->codexPending.clear();
    aiCodexRpc(c, QStringLiteral("turn/start"), params, QStringLiteral("turn"));
}

static void aiCodexLoadThread(AiChat *c)
{
    const QJsonObject s = aiRunSettings(c);
    QFile prompt(s.value("prompt").toString());
    const QString instructions = prompt.open(QIODevice::ReadOnly) ? QString::fromUtf8(prompt.readAll()) : QString();
    // Ordinary chat keeps the person's Codex approval policy and sandbox, and its approvals go to Codex's automatic
    // reviewer as New video's do (T221: no box in ordinary use; a refusal goes back to Codex). A New video is an
    // isolated, unattended job: refusals return to Codex rather than waiting.
    const QString ownApproval = aiCodexConfigValue(QStringLiteral("approval_policy"));
    const QString ownSandbox = aiCodexConfigValue(QStringLiteral("sandbox_mode"));
    QJsonObject params{{"cwd", aiCodexWork()}, {"approvalsReviewer", QStringLiteral("auto_review")},
                       {"approvalPolicy", c->autonomousNewVideo ? QStringLiteral("on-request")
                                          : ownApproval == QLatin1String("never")
                                              ? QStringLiteral("never")
                                              : ownApproval == QLatin1String("untrusted")
                                                  ? QStringLiteral("untrusted") : QStringLiteral("on-request")},
                       {"sandbox", c->autonomousNewVideo ? QStringLiteral("workspace-write")
                                  : ownSandbox == QLatin1String("danger-full-access")
                                       ? QStringLiteral("danger-full-access")
                                       : ownSandbox == QLatin1String("read-only")
                                           ? QStringLiteral("read-only") : QStringLiteral("workspace-write")}};
    c->procSpeed = aiSpeedValue(s, QStringLiteral("codex"));
    params["serviceTier"] = aiCodexSpeedTier(s);
    if (c->sessionStarted && !c->sessionId.isEmpty()) {
        params["threadId"] = c->sessionId;
        aiCodexRpc(c, QStringLiteral("thread/resume"), params, QStringLiteral("thread"));
    } else {
        QString model;
        aiCodexChoiceArgs(s, &model);
        params["model"] = model;
        params["developerInstructions"] = instructions;
        aiCodexRpc(c, QStringLiteral("thread/start"), params, QStringLiteral("thread"));
    }
}

static void aiCodexApproval(AiChat *c, const QJsonObject &msg)
{
    const QString method = msg.value("method").toString();
    const QJsonObject params = msg.value("params").toObject();
    if (method == QLatin1String("item/tool/requestUserInput")) {
        QJsonObject answers;
        for (const QJsonValue &v : params.value("questions").toArray()) {
            const QJsonObject question = v.toObject();
            QStringList options;
            for (const QJsonValue &choice : question.value("options").toArray())
                options << choice.toObject().value("label").toString();
            bool accepted = false;
            const QString answer = options.isEmpty()
                ? QInputDialog::getText(c->dock, question.value("header").toString(),
                                        question.value("question").toString(),
                                        question.value("isSecret").toBool() ? QLineEdit::Password : QLineEdit::Normal,
                                        QString(), &accepted)
                : QInputDialog::getItem(c->dock, question.value("header").toString(),
                                        question.value("question").toString(), options, 0, true, &accepted);
            answers[question.value("id").toString()] = QJsonObject{{"answers", accepted
                ? QJsonArray{answer} : QJsonArray()}};
        }
        if (c->proc)
            c->proc->write(QJsonDocument(QJsonObject{{"id", msg.value("id")},
                             {"result", QJsonObject{{"answers", answers}}}}).toJson(QJsonDocument::Compact) + '\n');
        return;
    }
    QString action = params.value("command").toString();
    if (action.isEmpty())
        action = params.value("reason").toString();
    if (action.isEmpty() && method == QLatin1String("mcpServer/elicitation/request")) {
        action = params.value("message").toString();
        const QString service = params.value("serverName").toString(params.value("server").toString());
        if (action.isEmpty())
            action = service.isEmpty() ? QStringLiteral("Codex wants to use a connected tool to continue.")
                                       : QStringLiteral("Codex wants to use %1 to continue.").arg(service);
    }
    if (action.isEmpty())
        action = method;
    QMessageBox box(QMessageBox::Question, QStringLiteral("Codex asks permission"),
                    QStringLiteral("%1\n\n%2").arg(action.left(700), params.value("cwd").toString()),
                    QMessageBox::NoButton, c->dock);
    QPushButton *once = box.addButton(QStringLiteral("Allow once"), QMessageBox::AcceptRole);
    QPushButton *session = box.addButton(QStringLiteral("Allow for this chat"), QMessageBox::AcceptRole);
    box.addButton(QStringLiteral("Deny"), QMessageBox::RejectRole);
    c->permissionWaiting = true;
    box.exec();
    c->permissionWaiting = false;
    const bool allow = box.clickedButton() == once || box.clickedButton() == session;
    const bool keep = box.clickedButton() == session;
    c->lastPermission = allow ? QStringLiteral("allow") : QStringLiteral("deny");
    QJsonObject response;
    if (method == QLatin1String("item/commandExecution/requestApproval")
        || method == QLatin1String("item/fileChange/requestApproval"))
        response["decision"] = allow ? (keep ? QStringLiteral("acceptForSession") : QStringLiteral("accept"))
                                     : QStringLiteral("decline");
    else if (method == QLatin1String("item/permissions/requestApproval")) {
        const QJsonObject requested = params.value("permissions").toObject();
        response["permissions"] = allow ? requested : QJsonObject();
        response["scope"] = keep ? QStringLiteral("session") : QStringLiteral("turn");
    } else if (method == QLatin1String("mcpServer/elicitation/request")) {
        response["action"] = allow ? QStringLiteral("accept") : QStringLiteral("decline");
        response["content"] = QJsonValue::Null;
        response["_meta"] = QJsonValue::Null;
    } else
        response["decision"] = allow ? QStringLiteral("approved") : QStringLiteral("denied");
    if (c->proc)
        c->proc->write(QJsonDocument(QJsonObject{{"id", msg.value("id")}, {"result", response}})
                           .toJson(QJsonDocument::Compact) + '\n');
}

// A request of ours that the app-server refused: a refused speed is retried at Normal, a steer that came too late goes
// next, anything else ends the turn.
static void aiCodexRefused(AiChat *c, const QString &tag, const QString &steered, const QString &error)
{
    if ((tag == QLatin1String("turn") || tag == QLatin1String("thread")) && aiSpeedFallback(c, error)) {
        c->codexPending = c->retryContent;
        if (tag == QLatin1String("thread"))
            aiCodexLoadThread(c);
        else
            aiCodexStartTurn(c);
        return;
    }
    if (tag == QLatin1String("steer")) {
        aiChatAdd(c, QStringLiteral("note"), QStringLiteral("Codex finished before that steer; it is queued next."));
        if (!steered.isEmpty())
            c->queued.append(steered);
        aiCodexRunQueued(c);
    } else {
        aiChatAdd(c, QStringLiteral("error"), error);
        aiCodexTurnEnded(c, QStringLiteral("failed"), error);
        if (c->proc)
            c->proc->kill(); // a fresh process can retry initialization or resume
    }
}

// The app-server's answer to a request of ours (initialize, thread, turn, steer).
static void aiCodexAnswered(AiChat *c, const QJsonObject &msg)
{
    const int id = msg.value("id").toInt();
    const QString tag = c->codexRpc.take(id);
    const QString steered = c->codexSteers.take(id);
    if (msg.contains("error")) {
        aiCodexRefused(c, tag, steered, msg.value("error").toObject().value("message").toString());
        return;
    }
    const QJsonObject result = msg.value("result").toObject();
    if (tag == QLatin1String("initialize")) {
        c->proc->write("{\"method\":\"initialized\"}\n");
        aiCodexLoadThread(c);
    } else if (tag == QLatin1String("thread")) {
        c->sessionId = result.value("thread").toObject().value("id").toString(c->sessionId);
        c->sessionStarted = !c->sessionId.isEmpty();
        c->codexReady = true;
        aiChatSaveCurrent(c);
        aiLeanSessionCreated(c); // T294: a lean stage's new thread exists: its id is kept and acknowledged
        aiCodexStartTurn(c);
    } else if (tag == QLatin1String("turn")) {
        c->codexTurnId = result.value("turn").toObject().value("id").toString();
        if (!c->queued.isEmpty()) {
            const QString steer = c->queued.takeFirst();
            const int rpc = aiCodexRpc(c, QStringLiteral("turn/steer"),
                       QJsonObject{{"threadId", c->sessionId}, {"expectedTurnId", c->codexTurnId},
                                   {"input", aiCodexInput(aiChatContext(c->window) + QStringLiteral("\n\n") + steer)}},
                       QStringLiteral("steer"));
            c->codexSteers.insert(rpc, steer);
        }
    }
}

// Codex has started a step: a tool, a command or a file change is a line in the chat.
static void aiCodexItemStarted(AiChat *c, const QJsonObject &item)
{
    const QString kind = item.value("type").toString();
    if (kind == QLatin1String("mcpToolCall") || kind == QLatin1String("commandExecution")
        || kind == QLatin1String("fileChange")) {
        c->speedProduced = true;
        c->live = -1;
        const QString tool = item.value("tool").toString();
        const QString name = kind == QLatin1String("mcpToolCall") ? tool : kind;
        const QString phrase = kind == QLatin1String("commandExecution")
                                   ? aiChatCommandPhrase(item.value("command").toString())
                                   : kind == QLatin1String("mcpToolCall")
                                       && item.value("server").toString() != QLatin1String("letitedit")
                                       ? QStringLiteral("Using a connected tool")
                                       : aiChatToolPhrase(name, item.value("arguments").toObject());
        aiChatAdd(c, QStringLiteral("tool"), phrase);
        aiChatSetBusy(c, true, aiChatProgress(c, name, phrase));
    }
}

// What the app-server tells us as the turn goes: its id, the reply as it is written, each step, the turn's end, errors.
static void aiCodexNotified(AiChat *c, const QJsonObject &msg)
{
    const QString method = msg.value("method").toString();
    const QJsonObject p = msg.value("params").toObject();
    if (method == QLatin1String("turn/started")) {
        c->codexTurnId = p.value("turn").toObject().value("id").toString(c->codexTurnId);
    } else if (method == QLatin1String("item/agentMessage/delta")) {
        if (c->live < 0 || c->live >= c->blocks.size() || c->blocks[c->live].kind != QLatin1String("claude")) {
            c->blocks.append({QStringLiteral("claude"), QString()});
            c->live = c->blocks.size() - 1;
        }
        c->blocks[c->live].text += p.value("delta").toString();
        c->repaint->start();
    } else if (method == QLatin1String("item/started")) {
        aiCodexItemStarted(c, p.value("item").toObject());
    } else if (method == QLatin1String("item/completed")) {
        const QJsonObject item = p.value("item").toObject();
        if (item.value("type").toString() == QLatin1String("agentMessage")) {
            const QString answer = item.value("text").toString();
            if (!answer.isEmpty()) {
                if (c->live >= 0 && c->live < c->blocks.size())
                    c->blocks[c->live].text = answer;
                else
                    aiChatAdd(c, QStringLiteral("claude"), answer);
                c->live = -1;
                c->repaint->start();
            }
        }
    } else if (method == QLatin1String("turn/completed")) {
        const QJsonObject turn = p.value("turn").toObject();
        const QString status = turn.value("status").toString();
        if (status == QLatin1String("failed") && aiSpeedFallback(c, c->speedError + QString::fromUtf8(QJsonDocument(turn).toJson()))) {
            c->codexPending = c->retryContent;
            c->codexTurnId.clear();
            aiCodexStartTurn(c);
            return;
        }
        aiCodexTurnEnded(c, status == QLatin1String("completed") ? QStringLiteral("answered") : status);
        c->codexTurnId.clear();
        aiCodexRunQueued(c);
    } else if (method == QLatin1String("error")) {
        c->speedError = QString::fromUtf8(QJsonDocument(p).toJson());
        if (!c->speedProduced && aiSpeedRefused(c->speedError) && c->procSpeed != QLatin1String("normal"))
            return;
        aiChatAdd(c, QStringLiteral("error"), p.value("message").toString());
    }
}

static void aiCodexAppLine(AiChat *c, const QJsonObject &msg)
{
    if (msg.contains("id") && msg.contains("method")) {
        aiCodexApproval(c, msg);
        return;
    }
    if (msg.contains("id")) {
        aiCodexAnswered(c, msg);
        return;
    }
    aiCodexNotified(c, msg);
}

static bool aiCodexAppSend(AiChat *c, const QString &content)
{
    c->retryContent = content;
    c->codexPending = content;
    c->turnOpen = true;
    if (c->proc && c->codexReady) {
        aiCodexStartTurn(c);
        return true;
    }
    if (c->proc)
        return true; // initialization or thread resume is still in flight
    const QJsonObject s = aiChatSettings();
    const QString codex = s.value("codex").toString();
    if (codex.isEmpty() || !QFileInfo::exists(codex)) {
        aiChatAdd(c, QStringLiteral("error"), QStringLiteral("Codex isn't installed. Menu > AI > Connect Your AI can find it."));
        return false;
    }
    QStringList args{QStringLiteral("app-server"), QStringLiteral("--stdio")};
    const QString python = QDir::fromNativeSeparators(s.value("python").toString());
    const QString server = QDir::fromNativeSeparators(s.value("mcp_server").toString());
    args << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.command=") + aiTomlString(python)
         << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.args=[%1]").arg(aiTomlString(server))
         << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.env.PYTHONUTF8='1'")
         << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.env.PYTHONIOENCODING='utf-8'")
         << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.default_tools_approval_mode='approve'")
         << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.startup_timeout_sec=120")
         << QStringLiteral("-c") << QStringLiteral("mcp_servers.letitedit.tool_timeout_sec=3600");
    args << aiCodexWindowArgs();
    args << QStringLiteral("-c") << QStringLiteral("service_tier=\"default\"");
    args << aiCodexSpeedConfigArgs();
    c->proc = new QProcess(c->dock);
    c->proc->setProgram(codex);
    c->proc->setArguments(args);
    c->proc->setWorkingDirectory(aiCodexWork());
    auto env = QProcessEnvironment::systemEnvironment();
    env.remove(QStringLiteral("LETITEDIT_OWNER"));
    const QString path = aiChatPythonPath(s);
    if (!path.isEmpty())
        env.insert(QStringLiteral("PATH"), path);
    c->proc->setProcessEnvironment(env);
    QObject::connect(c->proc, &QProcess::readyReadStandardOutput, c->dock, [c]() {
        if (!c->proc)
            return;
        c->buffer += c->proc->readAllStandardOutput();
        int nl;
        while ((nl = c->buffer.indexOf('\n')) >= 0) {
            const QJsonDocument doc = QJsonDocument::fromJson(c->buffer.left(nl).trimmed());
            c->buffer.remove(0, nl + 1);
            if (doc.isObject())
                aiCodexAppLine(c, doc.object());
        }
    });
    QObject::connect(c->proc, &QProcess::finished, c->dock, [c](int code, QProcess::ExitStatus) {
        if (!c->proc)
            return;
        const QString error = QString::fromUtf8(c->proc->readAllStandardError()).right(500);
        if (c->busy) {
            const QString reason = error.isEmpty() ? QStringLiteral("Codex stopped (exit %1).").arg(code) : error;
            aiChatAdd(c, QStringLiteral("error"), reason);
            aiCodexTurnEnded(c, QStringLiteral("failed"), reason);
        }
        c->proc->deleteLater();
        c->proc = nullptr;
        c->codexReady = false;
        c->codexTurnId.clear();
        c->codexRpc.clear();
        c->codexSteers.clear();
    });
    c->proc->start();
    if (!c->proc->waitForStarted(15000)) {
        aiChatAdd(c, QStringLiteral("error"), QStringLiteral("Could not start Codex: ") + c->proc->errorString());
        c->proc->deleteLater();
        c->proc = nullptr;
        return false;
    }
    aiCodexRpc(c, QStringLiteral("initialize"), QJsonObject{{"clientInfo", QJsonObject{{"name", "letitedit"},
                   {"title", "letitedit"}, {"version", "1.0"}}},
                   {"capabilities", QJsonObject{{"experimentalApi", true}, {"requestAttestation", false}}}},
               QStringLiteral("initialize"));
    return true;
}

#endif // AICODEXSERVER_H
