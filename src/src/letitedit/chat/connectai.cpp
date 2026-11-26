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

#include "letitedit/chat/connectai.h"

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "letitedit/letitedit.h"
#include "mainwindow.h"

#include <QAction>
#include <QButtonGroup>
#include <QCheckBox>
#include <QHBoxLayout>
#include <QMap>
#include <QProcess>
#include <QProcessEnvironment>
#include <QSet>
#include <QTimer>
#include <QMenu>
#include <QMenuBar>
#include <QDesktopServices>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QGridLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocale>
#include <QSettings>
#include <QLabel>
#include <QPushButton>
#include <QRadioButton>
#include <QRegularExpression>
#include <QStandardPaths>
#include <QUrl>
#include <QVBoxLayout>

namespace ConnectAi {

namespace {

const QString kAsk = QStringLiteral("Call the letitedit_guide tool once, then reply with only the word READY.");

QString claudeHome()
{
    const QString dir = qEnvironmentVariable("CLAUDE_CONFIG_DIR");
    return dir.isEmpty() ? QDir::homePath() + QStringLiteral("/.claude") : QDir::fromNativeSeparators(dir);
}

QString claudeConfigFile()
{
    const QString dir = qEnvironmentVariable("CLAUDE_CONFIG_DIR");
    return dir.isEmpty() ? QDir::homePath() + QStringLiteral("/.claude.json")
                         : QDir::fromNativeSeparators(dir) + QStringLiteral("/.claude.json");
}

QString codexHome()
{
    return aiCodexHome();
}

QString python()
{
    return QDir::fromNativeSeparators(aiChatSettings().value("python").toString());
}

QString server()
{
    return QDir::fromNativeSeparators(aiChatSettings().value("mcp_server").toString());
}

bool pythonReady()
{
    // What the tool server needs to start.
    return QFileInfo::exists(python())
           && leRun(python(), {"-c", "import mcp, numpy, yaml"}, nullptr, nullptr, 30000);
}

bool skillsIn(const QString &home)
{
    return QFileInfo::exists(home + QStringLiteral("/skills/letitedit/SKILL.md"));
}

QString workDir()
{
    const QString work = aiChatSettings().value("work_dir").toString();
    QDir().mkpath(work);
    return work;
}

} // namespace

QString privacyLine()
{
    return QObject::tr("Editing and media processing happen on this PC. Your requests, and the transcript text and "
                       "preview pictures your AI looks at, go to the AI service you chose.");
}

bool anyAi()
{
    if (qEnvironmentVariableIsSet("LETITEDIT_QA")
        && QFileInfo::exists(qEnvironmentVariable("LETITEDIT_QA_NO_AI_FILE")))
        return false;
    if (!qEnvironmentVariable("LETITEDIT_QA_MOCK_AI").isEmpty() || !claudeExe().isEmpty() || !codexExe().isEmpty())
        return true;
    const QJsonObject settings = aiChatSettings();
    for (const QString &id : aiConnectorIds()) {
        if (aiEngineHere(settings, id))
            return true;
    }
    return false;
}

QString programName(const QString &engine)
{
    return aiEntry(engine).value("name").toString(engine);
}

QString firstUseNotice()
{
    return QObject::tr("letitedit runs your own AI subscription on this PC, sometimes in the background to review your video. "
                       "It runs on your own plan, and letitedit never sees your login. You can turn background runs off in "
                       "Connect Your AI.");
}

QString connectorNotice(const QString &engine)
{
    return aiEntry(engine).value("first_use_notice").toString();
}

// The program for an AI, or "" when it isn't on this PC.
static QString programOf(const QString &engine)
{
    if (engine == QLatin1String("claude"))
        return claudeExe();
    if (engine == QLatin1String("codex"))
        return codexExe();
    const QString found = aiChatSettings().value(engine).toString();
    return QFileInfo(found).isFile() ? QDir::fromNativeSeparators(found) : QString();
}

QString missingWords(const QString &engine)
{
    if (aiEngineIsConnector(engine))
        return QString(); // Connect Your AI offers its download again
    if (!aiChatSettings().contains(engine) || QFileInfo(engine == QLatin1String("codex") ? codexExe() : claudeExe()).isFile())
        return QString();
    const bool savedPathGone = !aiChatRawSettings().value(engine).toString().isEmpty();
    const bool shimLeft = !QStandardPaths::findExecutable(engine).isEmpty();
    if (!savedPathGone && !shimLeft)
        return QString();
    if (engine == QLatin1String("codex"))
        return QObject::tr("Codex's program is missing from this PC. An update may have stopped partway. To reinstall it, follow "
                           "https://developers.openai.com/codex/cli and then try again.");
    return QObject::tr("Claude Code's program is missing from this PC. An update may have stopped partway. To reinstall it, open "
                       "a terminal and run: npm install -g @anthropic-ai/claude-code (or follow "
                       "https://docs.claude.com/en/docs/claude-code/setup) and then try again.");
}

QString anyMissingWords()
{
    for (const QString &engine : aiEngineIds()) {
        const QString words = missingWords(engine);
        if (!words.isEmpty())
            return words;
    }
    return QString();
}

QString newVideoTooOldWords(const QString &engine)
{
    // One entry per AI that needs a flag for New video.
    static const QMap<QString, QString> needs{{QStringLiteral("codex"), QStringLiteral("--approve-for-me")}};
    const QString exe = aiChatSettings().value(engine).toString();
    const QFileInfo program(exe);
    if (!needs.contains(engine) || !program.isFile())
        return QString();
    static QMap<QString, bool> known;
    const QString key = exe + program.lastModified().toString(Qt::ISODate);
    if (!known.contains(key)) {
        QProcess help;
        help.setProcessChannelMode(QProcess::MergedChannels);
        help.start(exe, {QStringLiteral("--help")});
        help.closeWriteChannel();
        const bool done = help.waitForFinished(8000);
        const QByteArray printed = help.readAll();
        if (!done)
            help.kill();
        if (!done || help.exitStatus() != QProcess::NormalExit || help.exitCode() != 0 || printed.isEmpty())
            return QString(); // it can't say: nothing here stops New video
        known.insert(key, printed.contains(needs.value(engine).toUtf8()));
    }
    if (known.value(key))
        return QString();
    return QObject::tr("Your copy of %1 is too old to make a video on its own. Please update it "
                       "(https://developers.openai.com/codex/cli), then press Make my video again. Everything here stays filled in.")
        .arg(programName(engine));
}

bool firstUseNoticeSeen(const QString &engine)
{
    return leSettings().value(engine.isEmpty() ? QStringLiteral("connect/notice_seen") : QStringLiteral("connect/%1/notice_seen").arg(engine)).toBool();
}

void setFirstUseNoticeSeen(const QString &engine)
{
    leSettings().setValue(engine.isEmpty() ? QStringLiteral("connect/notice_seen") : QStringLiteral("connect/%1/notice_seen").arg(engine), true);
    leSettings().sync();
}

void checkSignedIn(const QString &engine, QObject *context, const std::function<void(int)> &done)
{
    // From the list: its status command, and the key that it runs on instead of a sign-in.
    const QJsonObject entry = aiEntry(engine);
    QStringList statusArgs;
    for (const QJsonValue &arg : entry.value("status_args").toArray())
        statusArgs << arg.toString();
    const QString keyVar = entry.value("api_key_var").toString();
    const QString exe = aiChatSettings().value(engine).toString();
    if (aiEngineIsConnector(engine) && qEnvironmentVariable("LETITEDIT_QA_MOCK_AI").isEmpty()) {
        // No status command, and starting one takes 15 s: its sign-in file, by name only.
        const int answer = !QFileInfo(exe).isFile() ? -1 : aiConnectorSignedIn(aiChatSettings(), engine) ? 1 : 0;
        QTimer::singleShot(0, context, [done, answer]() { done(answer); });
        return;
    }
    if (!qEnvironmentVariable("LETITEDIT_QA_MOCK_AI").isEmpty() || statusArgs.isEmpty() || !QFileInfo(exe).isFile()
        || (!keyVar.isEmpty() && !qEnvironmentVariable(keyVar.toUtf8().constData()).isEmpty())) {
        QTimer::singleShot(0, context, [done]() { done(-1); });
        return;
    }
    auto *process = new QProcess(context);
    process->setProcessChannelMode(QProcess::MergedChannels);
    auto answered = std::make_shared<bool>(false);
    const auto answer = [process, done, answered](int value) {
        if (*answered)
            return;
        *answered = true;
        process->deleteLater();
        done(value);
    };
    QObject::connect(process, &QProcess::finished, context, [process, answer](int code, QProcess::ExitStatus status) {
        const QByteArray printed = process->readAll().toLower();
        if (status == QProcess::NormalExit && code == 0)
            answer(1);
        else if (status == QProcess::NormalExit && (printed.contains("loggedin") || printed.contains("not logged in")))
            answer(0);
        else
            answer(-1); // an older program with no such command, say
    });
    QObject::connect(process, &QProcess::errorOccurred, context, [answer](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            answer(-1);
    });
    QTimer::singleShot(20000, process, [process]() { process->kill(); });
    process->start(exe, statusArgs);
    process->closeWriteChannel();
}

Status status(const QString &engine)
{
    Status st;
    st.exe = programOf(engine);
    if (st.exe.isEmpty()) {
        st.state = QStringLiteral("missing");
        return st;
    }
    QSettings &s = leSettings();
    const QString key = QStringLiteral("connect/%1/").arg(engine);
    // a result counts for the program it was made with (a new install is tested again)
    if (s.value(key + QStringLiteral("exe")).toString() != st.exe || !s.contains(key + QStringLiteral("ok"))) {
        st.state = QStringLiteral("untested");
        return st;
    }
    const bool ok = s.value(key + QStringLiteral("ok")).toBool();
    st.state = ok ? QStringLiteral("ready") : QStringLiteral("attention");
    st.when = QDateTime::fromString(s.value(key + (ok ? QStringLiteral("last_ok") : QStringLiteral("when"))).toString(),
                                    Qt::ISODate);
    st.text = s.value(key + QStringLiteral("text")).toString();
    return st;
}

void record(const QString &engine, bool ok, const QString &text)
{
    const QString exe = programOf(engine);
    if (exe.isEmpty())
        return;
    QSettings &s = leSettings();
    const QString key = QStringLiteral("connect/%1/").arg(engine);
    const QString now = QDateTime::currentDateTime().toString(Qt::ISODate);
    s.setValue(key + QStringLiteral("exe"), exe);
    s.setValue(key + QStringLiteral("ok"), ok);
    s.setValue(key + QStringLiteral("when"), now);
    s.setValue(key + QStringLiteral("text"), text.left(300));
    if (ok)
        s.setValue(key + QStringLiteral("last_ok"), now);
    s.sync();
}

QString statusWords(const Status &st)
{
    const auto when = [](const QDateTime &t) {
        if (!t.isValid())
            return QString();
        const QDate day = t.date();
        const QString time = QLocale().toString(t.time(), QLocale::ShortFormat);
        if (day == QDate::currentDate())
            return QObject::tr("today at %1").arg(time);
        if (day == QDate::currentDate().addDays(-1))
            return QObject::tr("yesterday at %1").arg(time);
        return QObject::tr("on %1").arg(QLocale().toString(day, QLocale::ShortFormat));
    };
    if (st.state == QLatin1String("missing"))
        return QObject::tr("not set up - get this AI to start");
    if (st.state == QLatin1String("untested"))
        return QObject::tr("installed - test the connection to check it");
    if (st.state == QLatin1String("ready"))
        return st.when.isValid() ? QObject::tr("ready (worked %1)").arg(when(st.when)) : QObject::tr("ready");
    QString why = st.text.trimmed();
    if (why.size() > 90)
        why = why.left(87) + QStringLiteral("...");
    return why.isEmpty() ? QObject::tr("needs attention") : QObject::tr("needs attention: %1").arg(why);
}

QString claudeExe()
{
    QStringList candidates;
    const QString chosen = aiChatRawSettings().value("claude").toString();
    if (!chosen.isEmpty())
        candidates << chosen;
    candidates << qEnvironmentVariable("USERPROFILE", QDir::homePath()) + QStringLiteral("/.local/bin/claude.exe") // the native installer
               << qEnvironmentVariable("APPDATA")
                      + QStringLiteral("/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe"); // npm
    const QString onPath = QStandardPaths::findExecutable(QStringLiteral("claude"));
    if (onPath.endsWith(QLatin1String(".cmd"), Qt::CaseInsensitive)) // an npm shim: the program it starts
        candidates << QFileInfo(onPath).dir().filePath(
            QStringLiteral("node_modules/@anthropic-ai/claude-code/bin/claude.exe"));
    else if (!onPath.isEmpty())
        candidates << onPath;
    for (const auto &candidate : candidates) {
        if (QFileInfo(candidate).isFile())
            return QDir::fromNativeSeparators(candidate);
    }
    return QString();
}

QString codexExe()
{
    const QString found = aiChatSettings().value("codex").toString();
    return QFileInfo(found).isFile() ? QDir::fromNativeSeparators(found) : QString();
}

bool claudeHasTools()
{
    QFile file(claudeConfigFile());
    if (!file.open(QIODevice::ReadOnly))
        return false;
    return QJsonDocument::fromJson(file.readAll()).object().value("mcpServers").toObject().contains("letitedit");
}

bool chatUsesCodex()
{
    return aiChatIsCodex(aiChatSettings());
}

bool codexHasTools()
{
    // The tools as an MCP server ([mcp_servers.letitedit], or [mcp_servers.shotcut] from before the rename), or the
    // letitedit plugin when it isn't switched off ([plugins."letitedit@<marketplace>"] enabled = true).
    QFile file(codexHome() + QStringLiteral("/config.toml"));
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return false;
    const QString toml = QString::fromUtf8(file.readAll());
    if (toml.contains(QLatin1String("[mcp_servers.letitedit]")) || toml.contains(QLatin1String("[mcp_servers.shotcut]")))
        return true;
    static const QRegularExpression plugin(QStringLiteral("^\\s*\\[plugins\\.\"letitedit@[^\"]*\"\\]\\s*$((?:\\n(?!\\s*\\[).*)*)"),
                                           QRegularExpression::MultilineOption);
    static const QRegularExpression off(QStringLiteral("^\\s*enabled\\s*=\\s*false\\b"), QRegularExpression::MultilineOption);
    for (auto it = plugin.globalMatch(toml); it.hasNext();) {
        if (!off.match(it.next().captured(1)).hasMatch())
            return true;
    }
    return false;
}

QString addToolsToClaude()
{
    const QString claude = claudeExe();
    if (claude.isEmpty())
        return QObject::tr("Claude Code was not found.");
    QByteArray printed;
    if (!leRun(claude,
               // the name before -e: -e takes every value up to the next option
               {"mcp", "add", "--scope", "user", "letitedit", "-e", "PYTHONUTF8=1", "--", python(), server()},
               nullptr,
               &printed,
               60000)
        && !claudeHasTools())
        return QString::fromUtf8(printed).trimmed().right(300);
    return QString();
}

QString addToolsToCodex()
{
    if (codexHasTools())
        return QString();
    QDir().mkpath(codexHome());
    QFile file(codexHome() + QStringLiteral("/config.toml"));
    if (!file.open(QIODevice::Append | QIODevice::Text))
        return QObject::tr("Could not change %1.").arg(QDir::toNativeSeparators(file.fileName()));
    const QString block = QStringLiteral("\n# letitedit's video editing tools (added by letitedit > Connect Your AI)\n"
                                         "[mcp_servers.letitedit]\n"
                                         "command = %1\n"
                                         "args = [%2]\n"
                                         "startup_timeout_sec = 120\n"
                                         "tool_timeout_sec = 3600\n"
                                         "\n[mcp_servers.letitedit.env]\n"
                                         "PYTHONUTF8 = \"1\"\n")
                              .arg(aiTomlString(python()), aiTomlString(server()));
    file.write(block.toUtf8());
    return QString();
}

QString installSkills()
{
    QByteArray printed;
    if (!leRun(python(), {aiRootPath(QStringLiteral("skills/install.py"))}, nullptr, &printed, 60000))
        return QString::fromUtf8(printed).trimmed().right(300);
    return QString();
}

static Result runTest(const QString &engine, QProgressDialog *progress);

Result test(const QString &engine, QProgressDialog *progress)
{
    // QA hook: LETITEDIT_QA_CONNECT_RESULT=ok | fail:<why> answers for the AI (a check never spends a subscription)
    const QString qa = qEnvironmentVariable("LETITEDIT_QA_CONNECT_RESULT");
    Result result;
    if (!qa.isEmpty()) {
        result.ok = qa == QLatin1String("ok");
        result.text = result.ok ? QObject::tr("It works: the AI used the editor's tools and answered in 1 s.")
                                : qa.section(QLatin1Char(':'), 1).trimmed();
    } else {
        result = runTest(engine, progress);
    }
    if (!result.text.isEmpty() && !programOf(engine).isEmpty()
        && !result.text.contains(QLatin1String("stopped")))
        record(engine, result.ok, result.text);
    return result;
}

namespace {

// What one test heard: everything the AI printed, and whether it used an editor tool and answered READY. stopped: the
// test ended early, in words for the person.
struct Heard
{
    QByteArray printed;
    bool usedTool = false;
    bool answered = false;
    QString stopped;
};

// The chat's own way for a connector AI: the connector host, one small request, nothing left running.
Heard testConnector(const QString &engine, QProgressDialog *progress, const QElapsedTimer &clock)
{
    Heard heard;
    QProcess process;
    process.setProcessChannelMode(QProcess::SeparateChannels);
    process.start(python(), QStringList{aiRootPath(QStringLiteral("bridge/acp_host.py")), QStringLiteral("chat"), QStringLiteral("--ai"), engine,
                                        QStringLiteral("--work"), workDir(), QStringLiteral("--effort"), QStringLiteral("low")});
    const QJsonObject envelope{{"type", "user"}, {"message", QJsonObject{{"role", "user"},
                               {"content", QJsonArray{QJsonObject{{"type", "text"}, {"text", kAsk}}}}}}};
    process.write(QJsonDocument(envelope).toJson(QJsonDocument::Compact) + '\n');
    QByteArray pending;
    bool finished = false;
    while (!finished && process.state() != QProcess::NotRunning) {
        process.waitForReadyRead(100);
        pending += process.readAllStandardOutput();
        QCoreApplication::processEvents();
        int nl;
        while ((nl = pending.indexOf('\n')) >= 0) {
            const QByteArray line = pending.left(nl);
            heard.printed += line + '\n';
            pending.remove(0, nl + 1);
            const QJsonObject event = QJsonDocument::fromJson(line).object();
            if (line.contains("\"name\":\"mcp__letitedit__") || line.contains("\"name\": \"mcp__letitedit__"))
                heard.usedTool = true;
            if (event.value("type").toString() == QLatin1String("result")) {
                heard.answered = !event.value("is_error").toBool() && event.value("result").toString().contains(QLatin1String("READY"));
                if (!heard.answered)
                    heard.printed = event.value("result").toString().toUtf8();
                finished = true;
            }
        }
        if ((progress && progress->wasCanceled()) || clock.elapsed() > 240000) {
            process.kill();
            process.waitForFinished(2000);
            heard.stopped = QObject::tr("The test was stopped.");
            return heard;
        }
    }
    process.closeWriteChannel();
    if (!process.waitForFinished(10000))
        process.kill();
    if (!finished)
        heard.printed = process.readAllStandardError();
    return heard;
}

// The chat panel's way for Codex: only the letitedit tools, no shell, its model and effort, answer on stdout as JSON
// lines.
Heard testCodex(QProgressDialog *progress, const QElapsedTimer &clock)
{
    Heard heard;
    const QString codex = codexExe();
    if (codex.isEmpty()) {
        heard.stopped = QObject::tr("Codex was not found.");
        return heard;
    }
    QByteArray status;
    // Its exit code says (its words for signed out, "Not logged in", contain "logged in"). The person's own API key
    // is a way of running with no sign-in.
    if (!leRun(codex, {"login", "status"}, progress, &status, 30000)
        && qEnvironmentVariable("CODEX_API_KEY").isEmpty()) {
        heard.stopped = QObject::tr("Codex is not signed in yet. Open a terminal, type codex login and finish in the browser, then test again.");
        return heard;
    }
    QProcess process;
    process.setProcessChannelMode(QProcess::MergedChannels);
    process.start(codex,
                  QStringList{"exec", "--json", "--skip-git-repo-check", "--ignore-user-config", "-s", "read-only",
                              "--disable", "shell_tool", "--disable", "unified_exec",
                              "-c", "approval_policy='never'", "-c",
                              "mcp_servers.letitedit.command=" + aiTomlString(python()), "-c",
                              QStringLiteral("mcp_servers.letitedit.args=[%1]").arg(aiTomlString(server())), "-c",
                              "mcp_servers.letitedit.default_tools_approval_mode='approve'", "-c",
                              "mcp_servers.letitedit.startup_timeout_sec=120"}
                      + aiCodexWindowArgs() + aiCodexChoiceArgs(aiChatSettings())
                      + QStringList{"-C", workDir(), "-"});
    process.write(kAsk.toUtf8());
    process.closeWriteChannel();
    while (process.state() != QProcess::NotRunning && !process.waitForFinished(100)) {
        QCoreApplication::processEvents();
        if ((progress && progress->wasCanceled()) || clock.elapsed() > 240000) {
            process.kill();
            process.waitForFinished(2000);
            heard.stopped = QObject::tr("The test was stopped.");
            return heard;
        }
    }
    heard.printed = process.readAll();
    for (const auto &line : heard.printed.split('\n')) {
        const QJsonObject event = QJsonDocument::fromJson(line).object();
        const QJsonObject item = event.value("item").toObject();
        if (item.value("type").toString() == QLatin1String("mcp_tool_call"))
            heard.usedTool = true;
        if (item.value("type").toString() == QLatin1String("agent_message")
            && item.value("text").toString().contains(QLatin1String("READY")))
            heard.answered = true;
    }
    return heard;
}

// Claude Code, headless, with the same letitedit permission grant as the real chat.
Heard testClaude(QProgressDialog *progress)
{
    Heard heard;
    const QString claude = claudeExe();
    if (claude.isEmpty()) {
        heard.stopped = QObject::tr("Claude Code was not found.");
        return heard;
    }
    const QString config = workDir() + QStringLiteral("/mcp-test.json");
    QFile file(config);
    if (file.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        const QJsonObject tools{{"command", python()},
                                {"args", QJsonArray{server()}},
                                {"env", QJsonObject{{"PYTHONUTF8", "1"}}}};
        file.write(QJsonDocument(QJsonObject{{"mcpServers", QJsonObject{{"letitedit", tools}}}}).toJson());
        file.close();
    }
    // The same letitedit permission grant as the real chat. Without it, a
    // headless Claude test can report a healthy connection while every tool is denied.
    leRun(claude,
          QStringList{"-p", kAsk, "--mcp-config", config, "--strict-mcp-config", "--output-format", "stream-json",
                      "--verbose", "--max-turns", "4", "--allowedTools", "mcp__letitedit__*"}
              + aiClaudeLockdownArgs() + aiClaudeInstructionArgs() + aiClaudeChoiceArgs(aiChatSettings()),
          progress,
          &heard.printed,
          240000);
    for (const auto &line : heard.printed.split('\n')) {
        if (line.contains("\"name\":\"mcp__letitedit__"))
            heard.usedTool = true;
        const QJsonObject event = QJsonDocument::fromJson(line).object();
        if (event.value("type").toString() == QLatin1String("result") && !event.value("is_error").toBool()
            && event.value("result").toString().contains(QLatin1String("READY")))
            heard.answered = true;
    }
    if (!heard.answered && (heard.printed.contains("login") || heard.printed.contains("Invalid API key")))
        heard.stopped = QObject::tr("Claude Code is not signed in yet. Open a terminal, type claude, then type /login and finish in the browser; then test again.");
    return heard;
}

} // namespace

static Result runTest(const QString &engine, QProgressDialog *progress)
{
    Result result;
    QElapsedTimer clock;
    clock.start();
    const Heard heard = aiEngineIsConnector(engine) ? testConnector(engine, progress, clock)
                        : engine == QLatin1String("codex") ? testCodex(progress, clock)
                                                           : testClaude(progress);
    if (!heard.stopped.isEmpty()) {
        result.text = heard.stopped;
        return result;
    }
    const double seconds = clock.elapsed() / 1000.0;
    result.ok = heard.usedTool && heard.answered;
    result.text = result.ok ? QObject::tr("It works: the AI used the editor's tools and answered in %1 s.")
                                  .arg(seconds, 0, 'f', 0)
                  : heard.answered ? QObject::tr("The AI answered but did not reach the editor's tools. The line above about the "
                                                 "editor's tools says what to fix.")
                                   : QObject::tr("No answer. What it said: %1")
                                         .arg(QString::fromUtf8(heard.printed).simplified().right(240));
    LOG_INFO() << "connect your AI test:" << engine << result.ok << seconds << "s";
    return result;
}

namespace {

QString mark(bool ok)
{
    return ok ? QStringLiteral("<span style='color:#5ec8b4'>✓</span>")
              : QStringLiteral("<span style='color:#ffb347'>✗</span>");
}

// installed, not tested yet: a neutral dot; ready: a tick; not found or failing: a cross
QString markFor(const Status &st)
{
    return st.state == QLatin1String("untested") ? QStringLiteral("<span style='color:#AFA9A0'>●</span>")
                                                 : mark(st.state == QLatin1String("ready"));
}

// Each connector AI in the list: its own line, one button (Get it, then Sign in, then Sign out), and its notice.
struct ConnectorRow {
    QString id;
    QLabel *line = nullptr;
    QPushButton *button = nullptr;
    QLabel *about = nullptr;
    QRadioButton *use = nullptr;
    QProcess *running = nullptr;
    QString said;     // what its last step said, kept until the next one
    bool aboutHeld = false; // Google's verify message is showing: the notice steps aside for it
};

// Connect Your AI while it is open: its lines, buttons and choices, and what the person has asked for so far.
struct ConnectWindow
{
    explicit ConnectWindow(QDialog &d) : dialog(d) {}

    QDialog &dialog;
    QVBoxLayout *layout = nullptr;
    QGridLayout *grid = nullptr;
    QLabel *claudeLine = nullptr;
    QLabel *codexLine = nullptr;
    QLabel *pythonLine = nullptr;
    QLabel *ownLine = nullptr;
    QPushButton *getClaude = nullptr;
    QPushButton *getCodex = nullptr;
    QPushButton *addAnother = nullptr;
    QPushButton *addOwn = nullptr;
    QRadioButton *useClaude = nullptr;
    QRadioButton *useCodex = nullptr;
    QLabel *notice = nullptr;
    QLabel *result = nullptr;
    QPushButton *test = nullptr;
    QList<ConnectorRow *> connectorRows;
    bool showBoth = false;
    QSet<QString> signedOut;

    void buildIntro();
    void buildLines();
    void buildChoice();
    void buildFooter();
    void refresh();
    void refreshConnectors(const QJsonObject &settingsNow, bool hideOthers);
    void refreshOwn(const QString &claude, const QString &codex);
    void showChosen(const QString &claude, const QString &codex, bool someHere);
    void runStep(ConnectorRow *row, const QString &step);
    void heardStep(ConnectorRow *row, const QJsonObject &said);
    void connectRows();
    void addOwnTools();
    void testConnection();
    void closed();
};

void ConnectWindow::buildIntro()
{
    layout = new QVBoxLayout(&dialog);
    auto *intro = new QLabel(QObject::tr("letitedit runs your own AI program on this PC, on the plan you already have. "
                                         "Nothing else to sign up for."));
    intro->setWordWrap(true);
    layout->addWidget(intro);
    auto *privacy = new QLabel(privacyLine());
    privacy->setObjectName(QStringLiteral("connectPrivacy"));
    privacy->setWordWrap(true);
    privacy->setProperty("studioMuted", true);
    layout->addWidget(privacy);
    grid = new QGridLayout;
    grid->setColumnStretch(1, 1);
    grid->setVerticalSpacing(8);
    layout->addLayout(grid);
}

// A line for Claude Code, Codex, the editor's tools and the person's own AI, each with its button, then a line for each
// connector AI.
void ConnectWindow::buildLines()
{
    claudeLine = new QLabel;
    claudeLine->setObjectName(QStringLiteral("connectClaude"));
    codexLine = new QLabel;
    codexLine->setObjectName(QStringLiteral("connectCodex"));
    pythonLine = new QLabel;
    pythonLine->setObjectName(QStringLiteral("connectPython"));
    ownLine = new QLabel;
    ownLine->setObjectName(QStringLiteral("connectOwn"));
    for (auto *label : {claudeLine, codexLine, pythonLine, ownLine}) {
        label->setWordWrap(true);
        label->setTextFormat(Qt::RichText);
    }
    getClaude = new QPushButton(QObject::tr("Get Claude Code"));
    getClaude->setObjectName(QStringLiteral("connectGetClaude"));
    QObject::connect(getClaude, &QPushButton::clicked, &dialog, []() {
        QDesktopServices::openUrl(QUrl(QStringLiteral("https://docs.claude.com/en/docs/claude-code/setup")));
    });
    getCodex = new QPushButton(QObject::tr("Get Codex"));
    getCodex->setObjectName(QStringLiteral("connectGetCodex"));
    // With one AI here, the other stays out of sight until the person asks for it.
    addAnother = new QPushButton(QObject::tr("Add another AI"));
    addAnother->setObjectName(QStringLiteral("connectAddAnother"));
    addAnother->setFlat(true);
    addAnother->setCursor(Qt::PointingHandCursor);
    QObject::connect(getCodex, &QPushButton::clicked, &dialog, []() {
        QDesktopServices::openUrl(QUrl(QStringLiteral("https://developers.openai.com/codex/cli")));
    });
    addOwn = new QPushButton(QObject::tr("Set Up"));
    addOwn->setObjectName(QStringLiteral("connectSetUp"));
    addOwn->setToolTip(QObject::tr("Gives your own AI the letitedit tools and skills, so you can edit by talking to it "
                                   "outside letitedit too"));
    grid->addWidget(claudeLine, 0, 1);
    grid->addWidget(getClaude, 0, 2);
    grid->addWidget(codexLine, 1, 1);
    grid->addWidget(getCodex, 1, 2);
    grid->addWidget(pythonLine, 2, 1);
    grid->addWidget(ownLine, 3, 1);
    grid->addWidget(addOwn, 3, 2);
    for (const QString &id : aiConnectorIds()) {
        auto *row = new ConnectorRow;
        row->id = id;
        row->line = new QLabel;
        row->line->setObjectName(QStringLiteral("connectLine_") + id);
        row->line->setWordWrap(true);
        row->line->setTextFormat(Qt::RichText);
        row->line->setOpenExternalLinks(true);
        row->line->setTextInteractionFlags(Qt::TextBrowserInteraction);
        row->button = new QPushButton;
        row->button->setObjectName(QStringLiteral("connectButton_") + id);
        row->about = new QLabel(connectorNotice(id));
        row->about->setObjectName(QStringLiteral("connectAbout_") + id);
        row->about->setWordWrap(true);
        row->about->setProperty("studioMuted", true);
        const int at = grid->rowCount();
        grid->addWidget(row->line, at, 1);
        grid->addWidget(row->button, at, 2);
        grid->addWidget(row->about, at + 1, 1, 1, 2);
        connectorRows << row;
    }
}

// Which AI the chat in letitedit uses: one choice per AI, and Add another AI.
void ConnectWindow::buildChoice()
{
    auto *engineRow = new QHBoxLayout;
    engineRow->addWidget(new QLabel(QObject::tr("The chat in letitedit uses:")));
    auto *engines = new QButtonGroup(&dialog);
    useClaude = new QRadioButton(QObject::tr("Claude"));
    useClaude->setObjectName(QStringLiteral("connectUseClaude"));
    useCodex = new QRadioButton(QObject::tr("ChatGPT (Codex)"));
    useCodex->setObjectName(QStringLiteral("connectUseCodex"));
    engines->addButton(useClaude);
    engines->addButton(useCodex);
    engineRow->addWidget(useClaude);
    engineRow->addWidget(useCodex);
    for (ConnectorRow *row : connectorRows) {
        row->use = new QRadioButton(aiEntry(row->id).value("picker").toObject().value("label").toString(row->id));
        row->use->setObjectName(QStringLiteral("connectUse_") + row->id);
        engines->addButton(row->use);
        engineRow->addWidget(row->use);
    }
    engineRow->addStretch(1);
    engineRow->addWidget(addAnother);
    layout->addLayout(engineRow);
}

// The notice, the background-work choice, the test's result, then Test the Connection and Close.
void ConnectWindow::buildFooter()
{
    notice = new QLabel;
    notice->setObjectName(QStringLiteral("connectNotice"));
    notice->setWordWrap(true);
    layout->addWidget(notice);
    auto *background = new QCheckBox(QObject::tr("Let my AI work in the background on reviews and new openings"));
    background->setObjectName(QStringLiteral("connectBackground"));
    background->setToolTip(QObject::tr("Off: a review runs as a second conversation you can watch in the AI panel, and New "
                                       "hook can't write new words for the opening."));
    background->setChecked(aiChatRawSettings().value("background_jobs").toBool(true));
    QObject::connect(background, &QCheckBox::toggled, &dialog, [](bool on) {
        aiChatSaveSettings(QJsonObject{{"background_jobs", on}});
    });
    layout->addWidget(background);
    result = new QLabel;
    result->setObjectName(QStringLiteral("connectResult"));
    result->setWordWrap(true);
    layout->addWidget(result);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Close);
    test = buttons->addButton(QObject::tr("Test the Connection"), QDialogButtonBox::ActionRole);
    test->setObjectName(QStringLiteral("connectTest"));
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);
}

// Every line and button as things are now.
void ConnectWindow::refresh()
{
    const QString claude = claudeExe(), codex = codexExe();
    // where each one is installed is a detail: it shows when you point at the line
    const Status cs = status(QStringLiteral("claude")), xs = status(QStringLiteral("codex"));
    const auto words = [this](const QString &engine, const Status &st) {
        return signedOut.contains(engine) ? QObject::tr("not signed in - run it once in a terminal and sign in")
                                          : statusWords(st);
    };
    claudeLine->setText(markFor(cs) + ' '
                        + QObject::tr("Claude Code: %1").arg(words(QStringLiteral("claude"), cs).toHtmlEscaped()));
    claudeLine->setToolTip(claude.isEmpty() ? QString() : QDir::toNativeSeparators(claude));
    codexLine->setText(markFor(xs) + ' '
                       + QObject::tr("Codex: %1").arg(words(QStringLiteral("codex"), xs).toHtmlEscaped()));
    codexLine->setToolTip(codex.isEmpty() ? QString() : QDir::toNativeSeparators(codex));
    const QJsonObject settingsNow = aiChatSettings();
    bool connectorHere = false, connectorMissing = false;
    for (ConnectorRow *row : connectorRows) {
        const bool here = aiEngineHere(settingsNow, row->id);
        connectorHere = connectorHere || here;
        connectorMissing = connectorMissing || !here;
    }
    // With an AI here, the others stay out of sight until the person asks for them.
    const bool someHere = !claude.isEmpty() || !codex.isEmpty() || connectorHere;
    const bool hideOthers = someHere && !showBoth;
    claudeLine->setVisible(!claude.isEmpty() || !hideOthers);
    codexLine->setVisible(!codex.isEmpty() || !hideOthers);
    getClaude->setVisible(claude.isEmpty() && !hideOthers);
    getCodex->setVisible(codex.isEmpty() && !hideOthers);
    addAnother->setVisible(someHere && !showBoth && (claude.isEmpty() || codex.isEmpty() || connectorMissing));
    useClaude->setVisible(!claude.isEmpty() || !someHere);
    useCodex->setVisible(!codex.isEmpty() || !someHere);
    refreshConnectors(settingsNow, hideOthers);
    notice->setText(firstUseNotice());
    const QString broken = anyMissingWords();
    if (!broken.isEmpty() && result->text().isEmpty())
        result->setText(broken);
    refreshOwn(claude, codex);
    showChosen(claude, codex, someHere);
}

// Each connector AI's line, button and notice.
void ConnectWindow::refreshConnectors(const QJsonObject &settingsNow, bool hideOthers)
{
    for (ConnectorRow *row : connectorRows) {
        const QString name = programName(row->id);
        const bool installed = QFileInfo(settingsNow.value(row->id).toString()).isFile();
        const bool here = aiEngineHere(settingsNow, row->id);
        const bool busy = row->running != nullptr;
        const QString words = !row->said.isEmpty() ? row->said
                              : here ? statusWords(status(row->id)).toHtmlEscaped()
                              : installed ? QObject::tr("not signed in yet")
                                          : QObject::tr("not set up");
        row->line->setText((here ? markFor(status(row->id)) : mark(false)) + QLatin1Char(' ') + name.toHtmlEscaped() + QStringLiteral(": ") + words);
        row->line->setToolTip(installed ? QDir::toNativeSeparators(settingsNow.value(row->id).toString()) : QString());
        row->button->setText(here ? QObject::tr("Sign out") : installed ? QObject::tr("Sign in")
                                  : aiEntry(row->id).value("get_label").toString(QObject::tr("Get %1").arg(name)));
        row->button->setEnabled(!busy);
        const bool show = here || !hideOthers;
        row->line->setVisible(show);
        row->button->setVisible(show);
        row->about->setVisible(show && !row->aboutHeld && !row->about->text().isEmpty());
        row->use->setVisible(here);
        row->use->setEnabled(here);
    }
}

// The editor's tools for the AI, and whether the person's own AI has the letitedit tools and skills.
void ConnectWindow::refreshOwn(const QString &claude, const QString &codex)
{
    const bool ready = pythonReady();
    pythonLine->setText(mark(ready) + ' '
                        + (ready ? QObject::tr("The editor's tools for your AI are ready.")
                                 : QObject::tr("The editor's tools for your AI cannot start.")));
    pythonLine->setToolTip(QObject::tr("Python: %1").arg(QDir::toNativeSeparators(python())));
    // with neither AI installed there is nothing to give the tools to (this used to say both had them)
    const bool any = !claude.isEmpty() || !codex.isEmpty();     // the person's own programs: a connector AI has its skills in its profile
    const bool own = any && (claude.isEmpty() || (claudeHasTools() && skillsIn(claudeHome())))
                     && (codex.isEmpty() || (codexHasTools() && skillsIn(codexHome())));
    const QString yours = QObject::tr("AI");
    ownLine->setText(mark(own) + ' '
                     + (own ? QObject::tr("Your own %1: the letitedit tools and skills are in.").arg(yours)
                            : !any ? QObject::tr("Install an AI first (the buttons above).")
                                   : QObject::tr("Optional: give your own %1 the letitedit tools and skills, to edit "
                                                 "by talking to it outside letitedit.").arg(yours)));
    addOwn->setVisible(any && !own);
}

// The AI chosen now, and which choices and Test can be used.
void ConnectWindow::showChosen(const QString &claude, const QString &codex, bool someHere)
{
    // The AI chosen now, read here and not from settingsNow above: the Python check a few lines up waits with the event
    // loop running, so a click on a radio button lands in the middle of this refresh and settingsNow is then the choice
    // from before it, which this would put back (Codex chosen, Claude saved again a moment later).
    // Showing what is saved is not a change, so none of these radio buttons saves anything while it is set.
    const QString chosenNow = aiChatEngineId(aiChatSettings());
    bool chosenConnector = false;
    for (ConnectorRow *row : connectorRows) {
        if (row->id == chosenNow) {
            const QSignalBlocker quiet(row->use);
            row->use->setChecked(true);
            chosenConnector = true;
        }
    }
    if (!chosenConnector) {
        QRadioButton *shown = chosenNow == QLatin1String("codex") ? useCodex : useClaude;
        const QSignalBlocker quiet(shown);
        shown->setChecked(true);
    }
    useClaude->setEnabled(!claude.isEmpty());
    useCodex->setEnabled(!codex.isEmpty());
    test->setEnabled(someHere);
}

// One line from a connector AI's setup step: what it says on the AI's line (Google's verify link in full).
void ConnectWindow::heardStep(ConnectorRow *row, const QJsonObject &said)
{
    const QString state = said.value("state").toString();
    QString words = said.value("message").toString().toHtmlEscaped();
    if (state == QLatin1String("downloading") && said.contains("percent"))
        words += QStringLiteral(" %1%").arg(said.value("percent").toInt());
    if (state == QLatin1String("verify")) {
        // Google's words and its whole link, plainly. Not a crash, and not a failed sign-in.
        const QString link = said.value("url").toString();
        words += QStringLiteral("<br>") + QObject::tr("Google says: %1").arg(said.value("google_said").toString().toHtmlEscaped());
        if (!link.isEmpty())
            words += QStringLiteral("<br><a href=\"%1\">%2</a>").arg(link.toHtmlEscaped(), QObject::tr("Verify your account"));
        words += QStringLiteral(" · <a href=\"%1\">%2</a>").arg(said.value("learn_more").toString().toHtmlEscaped(), QObject::tr("Learn more"));
        if (!link.isEmpty()) {
            // the whole link in words too, able to wrap: it runs to about 320 characters with no spaces
            QString shown = link;
            for (int at = shown.size() - (shown.size() % 60); at > 0; at -= 60)
                shown.insert(at, QChar(0x200B));
            words += QStringLiteral("<br><small>%1</small>").arg(shown.toHtmlEscaped());
        }
        row->about->hide(); // the person has read it before pressing Sign in, and this is what matters now
        row->aboutHeld = true;
    } else {
        row->aboutHeld = false;
    }
    row->said = words;
    refresh();
    QTimer::singleShot(0, &dialog, [this]() { dialog.adjustSize(); }); // a longer message makes room for itself
}

// A step of a connector AI's setup (bridge/acp_host.py): each line it prints is one thing to say. Nothing here sees a link, a code or a token,
// except Google's own verify link, which is there for the person to open.
void ConnectWindow::runStep(ConnectorRow *row, const QString &step)
{
    auto *process = new QProcess(&dialog);
    row->running = process;
    process->setProcessChannelMode(QProcess::SeparateChannels);
    auto pending = std::make_shared<QByteArray>();
    QObject::connect(process, &QProcess::readyReadStandardOutput, &dialog, [this, row, process, pending]() {
        *pending += process->readAllStandardOutput();
        int nl;
        while ((nl = pending->indexOf('\n')) >= 0) {
            const QJsonObject said = QJsonDocument::fromJson(pending->left(nl)).object();
            pending->remove(0, nl + 1);
            heardStep(row, said);
        }
    });
    QObject::connect(process, &QProcess::finished, &dialog, [this, row, process]() {
        row->running = nullptr;
        process->deleteLater();
        aiChatSettingsChanged();
        refresh();
    });
    QObject::connect(process, &QProcess::errorOccurred, &dialog, [this, row, process](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            row->running = nullptr;
            row->said = QObject::tr("The editor's tools for your AI cannot start.");
            process->deleteLater();
            refresh();
        }
    });
    process->start(python(), QStringList{aiRootPath(QStringLiteral("bridge/acp_host.py")), step, QStringLiteral("--ai"), row->id});
    process->closeWriteChannel();
    refresh();
}

// Each connector AI's button runs its next step, and its choice makes it the chat's AI.
void ConnectWindow::connectRows()
{
    for (ConnectorRow *row : connectorRows) {
        QObject::connect(row->button, &QPushButton::clicked, &dialog, [this, row]() {
            const QJsonObject now = aiChatSettings();
            const bool installed = QFileInfo(now.value(row->id).toString()).isFile();
            row->said.clear();
            runStep(row, aiEngineHere(now, row->id) ? QStringLiteral("signout") : installed ? QStringLiteral("signin") : QStringLiteral("install"));
        });
        QObject::connect(row->use, &QRadioButton::toggled, &dialog, [row](bool on) {
            if (on)
                aiChatSaveSettings({{"engine", row->id}});
        });
    }
}

// Set Up: the letitedit tools for the person's own Claude Code and Codex, and the skills.
void ConnectWindow::addOwnTools()
{
    QStringList problems;
    if (!claudeExe().isEmpty() && !claudeHasTools())
        problems << addToolsToClaude();
    if (!codexExe().isEmpty() && !codexHasTools())
        problems << addToolsToCodex();
    problems << installSkills();
    problems.removeAll(QString());
    result->setText(problems.isEmpty() ? QObject::tr("Done: your own AI can use letitedit too.")
                                       : problems.join('\n'));
    refresh();
}

// Test the Connection: one small question to the AI chosen now.
void ConnectWindow::testConnection()
{
    QString engine = useCodex->isChecked() ? QStringLiteral("codex") : QStringLiteral("claude");
    for (ConnectorRow *row : connectorRows) {
        if (row->use->isChecked())
            engine = row->id;
    }
    QProgressDialog progress(QObject::tr("Asking %1 one small question...")
                                 .arg(aiEngineShortName(engine)),
                             QObject::tr("Cancel"),
                             0,
                             0,
                             &dialog);
    progress.setWindowTitle(QObject::tr("Connect Your AI"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);
    const Result r = ConnectAi::test(engine, &progress);
    progress.close();
    result->setText(mark(r.ok) + ' ' + r.text.toHtmlEscaped());
    result->setTextFormat(Qt::RichText);
    refresh(); // the lines above say ready or needs attention now
}

// The window has closed.
void ConnectWindow::closed()
{
    // a sign-in check still running calls back into what this function holds, which is about to go: closing the window in
    // the first seconds crashed the editor (T97)
    for (QProcess *process : dialog.findChildren<QProcess *>())
        process->disconnect();
    for (ConnectorRow *row : connectorRows) {
        if (row->running) { // closed in the middle: the host's end takes its connector with it
            row->running->disconnect();
            row->running->kill();
            row->running->waitForFinished(3000);
        }
    }
    qDeleteAll(connectorRows);
}

} // namespace

void show(MainWindow *window)
{
    QDialog dialog(window);
    dialog.setObjectName(QStringLiteral("connectAiDialog"));
    dialog.setWindowTitle(QObject::tr("Connect Your AI"));
    dialog.setMinimumWidth(600);
    ConnectWindow w(dialog);
    w.buildIntro();
    w.buildLines();
    w.buildChoice();
    w.buildFooter();
    w.connectRows();
    w.refresh(); // before the choice is connected: showing the current engine is not a change
    QObject::connect(w.addAnother, &QPushButton::clicked, &dialog, [&w]() {
        w.showBoth = true;
        w.refresh();
    });
    // A second AI installed while this is open shows up, with no restart.
    auto *again = new QTimer(&dialog);
    again->setInterval(3000);
    QObject::connect(again, &QTimer::timeout, &dialog, [&w]() { w.refresh(); });
    again->start();
    for (const QString &engine : {QStringLiteral("claude"), QStringLiteral("codex")}) { // a connector AI's row says so itself
        checkSignedIn(engine, &dialog, [&w, engine](int answer) {
            if (answer == 0)
                w.signedOut.insert(engine);
            w.refresh();
        });
    }
    QObject::connect(w.useClaude, &QRadioButton::toggled, &dialog, [](bool on) {
        if (!on)
            return;
        QJsonObject changes{{"engine", "claude"}};
        if (aiChatRawSettings().value("claude").toString() != claudeExe())
            changes.insert("claude", claudeExe());
        aiChatSaveSettings(changes);
    });
    QObject::connect(w.useCodex, &QRadioButton::toggled, &dialog, [](bool on) {
        if (on)
            aiChatSaveSettings({{"engine", "codex"}});
    });
    QObject::connect(w.addOwn, &QPushButton::clicked, &dialog, [&w]() { w.addOwnTools(); });
    QObject::connect(w.test, &QPushButton::clicked, &dialog, [&w]() { w.testConnection(); });
    dialog.exec();
    w.closed();
    aiChatSettingsChanged(); // the chat's top row and names follow the AI chosen here
}

void install(MainWindow *window)
{
    auto *action = new QAction(QObject::tr("Connect Your AI..."), window);
    action->setObjectName(QStringLiteral("connectAiAction"));
    action->setToolTip(QObject::tr("Runs your own AI subscription: find it, set it up, test it"));
    QObject::connect(action, &QAction::triggered, window, [window]() { show(window); });
    window->addAction(action);
    for (QAction *menu : window->menuBar()->actions()) {
        if (menu->menu() && menu->text() == QLatin1String("AI")) {
            menu->menu()->insertAction(menu->menu()->actions().value(1), action);
            break;
        }
    }
}

} // namespace ConnectAi
