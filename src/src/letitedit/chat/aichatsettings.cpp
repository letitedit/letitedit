/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The chat's settings (aichatpanel.h): panel.json and the history file, the one list of AIs (bridge/ai_list.json),
 * and the model, effort and speed choices each AI offers. The chat panel itself is aichatpanel.cpp.
 */

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/chat/aichatsettings.h"

// The chat's settings file: <root>/chat/panel.json, or the file LETITEDIT_CHAT_SETTINGS names (a test window's own
// copy, so a test never changes what the person's own windows use).
QString aiChatSettingsPath()
{
    const QString own = qEnvironmentVariable("LETITEDIT_CHAT_SETTINGS");
    return own.isEmpty() ? aiRootPath(QStringLiteral("chat/panel.json")) : QDir::fromNativeSeparators(own);
}

QString aiChatHistoryPath()
{
    // A test window's settings stay isolated; installed copies keep history in the user's profile.
    if (qEnvironmentVariableIsSet("LETITEDIT_CHAT_SETTINGS"))
        return QFileInfo(aiChatSettingsPath()).absolutePath() + QStringLiteral("/history.json");
    const QString local = QProcessEnvironment::systemEnvironment().value(QStringLiteral("LOCALAPPDATA"));
    return local + QStringLiteral("/letitedit/chat/history.json");
}

// panel.json as written (the person's choices), without the defaults aiChatSettings() fills in.
QJsonObject aiChatRawSettings()
{
    QFile f(aiChatSettingsPath());
    return f.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(f.readAll()).object() : QJsonObject();
}

// Writes changes into panel.json and keeps every other key.
bool aiChatSaveSettings(const QJsonObject &changes)
{
    QJsonObject s = aiChatRawSettings();
    // The first write on a new install: it starts in chat bubbles, so saying so here keeps it there. (A settings file
    // with no view in it is an older install, which has been on the real program screen: see aiChatSettings.)
    if (!QFileInfo::exists(aiChatSettingsPath()) && !changes.contains(QStringLiteral("view_mode")))
        s.insert(QStringLiteral("view_mode"), QStringLiteral("bubbles"));
    for (auto it = changes.begin(); it != changes.end(); ++it)
        s.insert(it.key(), it.value());
    QSaveFile f(aiChatSettingsPath());
    if (!f.open(QIODevice::WriteOnly))
        return false;
    f.write(QJsonDocument(s).toJson());
    return f.commit();
}

// The one list of AIs letitedit can run (bridge/ai_list.json, also read by bridge/ai_clis.py; LETITEDIT_AI_LIST for a test's own).
// Each id is also its key in panel.json for the program's path. Without the file, the two older AIs still work.
static const QList<QJsonObject> &aiListRows()
{
    static const QList<QJsonObject> rows = []() {
        QList<QJsonObject> out;
        const QString own = qEnvironmentVariable("LETITEDIT_AI_LIST");
        QFile f(own.isEmpty() ? aiRootPath(QStringLiteral("bridge/ai_list.json")) : own);
        if (f.open(QIODevice::ReadOnly)) {
            for (const QJsonValue &v : QJsonDocument::fromJson(f.readAll()).object().value("ais").toArray()) {
                if (!v.toObject().value("id").toString().isEmpty())
                    out << v.toObject();
            }
        }
        if (out.isEmpty()) {
            const auto row = [](const char *id, const char *name, const char *shortName, const char *label, const char *button,
                                const char *tip, const char *model, const char *effort, const QJsonArray &status) {
                return QJsonObject{{"id", id}, {"name", name}, {"short", shortName}, {"protocol", id},
                                   {"picker", QJsonObject{{"label", label}, {"button", button}, {"tip", tip}}},
                                   {"model_key", model}, {"effort_key", effort}, {"status_args", status},
                                   {"can", QJsonObject{{"chat", true}, {"terminal", true}, {"background", true}}}};
            };
            out << row("claude", "Claude Code", "Claude", "Claude", "Claude", "Runs Claude Code on this PC, on your own plan", "model",
                       "effort", QJsonArray{"auth", "status"})
                << row("codex", "Codex", "Codex", "ChatGPT (Codex)", "ChatGPT", "Runs Codex on this PC, on your own ChatGPT plan",
                       "codex_model", "codex_reasoning", QJsonArray{"login", "status"});
        }
        return out;
    }();
    return rows;
}

QJsonObject aiEntry(const QString &id)
{
    for (const QJsonObject &row : aiListRows()) {
        if (row.value("id").toString() == id)
            return row;
    }
    return QJsonObject();
}

QStringList aiEngineIds()
{
    QStringList ids;
    for (const QJsonObject &row : aiListRows())
        ids << row.value("id").toString();
    return ids;
}

// An AI letitedit runs through its connector host (bridge/acp_host.py) in the chat view.
bool aiEngineIsConnector(const QString &id)
{
    return aiEntry(id).value("protocol").toString() == QLatin1String("acp");
}

QStringList aiConnectorIds()
{
    QStringList ids;
    for (const QString &id : aiEngineIds()) {
        if (aiEngineIsConnector(id))
            ids << id;
    }
    return ids;
}

// What the list says an AI can do ("terminal", "background", "draw").
bool aiEngineCan(const QString &id, const QString &what)
{
    const QJsonObject can = aiEntry(id).value("can").toObject();
    return can.isEmpty() || can.value(what).toBool();
}

// The folder a connector AI lives in: its download, and its private sign-in profile. Nothing under the person's own folders changes.
static QString aiConnectorHome(const QJsonObject &settings, const QString &id)
{
    const QString chosen = settings.value(id + QStringLiteral("_ai_home")).toString();
    if (!chosen.isEmpty())
        return QDir::fromNativeSeparators(chosen);
    const QString base = qEnvironmentVariable("LETITEDIT_AI_HOME");
    return (base.isEmpty() ? QDir::fromNativeSeparators(qEnvironmentVariable("LOCALAPPDATA")) + QStringLiteral("/letitedit/ai")
                           : QDir::fromNativeSeparators(base)) + QLatin1Char('/') + id;
}

static QString aiConnectorProfile(const QJsonObject &settings, const QString &id)
{
    const QString chosen = settings.value(id + QStringLiteral("_profile")).toString();
    return chosen.isEmpty() ? aiConnectorHome(settings, id) + QStringLiteral("/profile") : QDir::fromNativeSeparators(chosen);
}

// Whether its sign-in file is in the private profile: by name only, never opened. No program starts, so this is instant.
bool aiConnectorSignedIn(const QJsonObject &settings, const QString &id)
{
    const QString profile = aiConnectorProfile(settings, id);
    for (const QJsonValue &name : aiEntry(id).value("signed_in_files").toArray()) {
        if (QFileInfo::exists(profile + QLatin1Char('/') + name.toString()))
            return true;
    }
    return false;
}

// On this PC and able to answer: a connector AI that isn't signed in isn't offered.
bool aiEngineHere(const QJsonObject &settings, const QString &engine)
{
    if (!QFileInfo(settings.value(engine).toString()).isFile())
        return false;
    return !aiEngineIsConnector(engine) || aiConnectorSignedIn(settings, engine);
}

static QJsonObject aiToolSettings()
{
    const QString path = qEnvironmentVariableIsSet("LETITEDIT_SETTINGS") ? qEnvironmentVariable("LETITEDIT_SETTINGS")
                                                                        : aiRootPath(QStringLiteral("settings.json"));
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return {};
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    return QJsonDocument::fromJson(data).object();
}

static bool aiToolSwitch(const char *variable, const QString &key, bool fallback)
{
    const QString forced = qEnvironmentVariable(variable).trimmed().toLower();
    if (forced == QLatin1String("1") || forced == QLatin1String("true") || forced == QLatin1String("on")
        || forced == QLatin1String("yes"))
        return true;
    if (forced == QLatin1String("0") || forced == QLatin1String("false") || forced == QLatin1String("off")
        || forced == QLatin1String("no"))
        return false;
    return aiToolSettings().value(key).toBool(fallback);
}

bool aiAutoRouting()
{
    return aiToolSwitch("LETITEDIT_AUTO_ROUTING", QStringLiteral("auto_routing"), true);
}

QString aiChatPythonPath(const QJsonObject &settings)
{
    // Same rule as studio/session_runner.py: use the tool server's Python directory once, ahead of inherited PATH.
    if (!aiToolSwitch("LETITEDIT_SESSION_PYTHON_ON_PATH", QStringLiteral("session_python_on_path"), true))
        return {};
    const QString python = settings.value(QStringLiteral("python")).toString();
    const QString folder = QFileInfo(python).path();
    if (python.isEmpty() || !QFileInfo(folder).isDir())
        return {};
#ifdef Q_OS_WIN
    constexpr auto sensitivity = Qt::CaseInsensitive;
#else
    constexpr auto sensitivity = Qt::CaseSensitive;
#endif
    const QString cleanFolder = QDir::cleanPath(QDir::fromNativeSeparators(folder));
    const auto separator = QDir::listSeparator();
    QStringList paths{QDir::toNativeSeparators(folder)};
    for (const auto &path : qEnvironmentVariable("PATH").split(separator, Qt::SkipEmptyParts)) {
        if (QDir::cleanPath(QDir::fromNativeSeparators(path)).compare(cleanFolder, sensitivity) != 0)
            paths << path;
    }
    return paths.join(separator);
}

QJsonObject aiRouting(const QString &engine)
{
    return aiEntry(engine).value(QStringLiteral("routing")).toObject();
}

bool aiModelIsAuto(const QString &model)
{
    return model.trimmed().compare(QLatin1String("auto"), Qt::CaseInsensitive) == 0;
}

// A role's row, or the max row; empty when the list's model isn't one of this AI's own (Auto never leaves the AI).
static QJsonObject aiRoutingRow(const QString &engine, const QString &role, bool max)
{
    const QJsonObject table = aiRouting(engine);
    const QJsonObject row = max && table.contains(QStringLiteral("max"))
                                ? table.value(QStringLiteral("max")).toObject()
                                : table.value(QStringLiteral("roles")).toObject().value(role).toObject();
    const QRegularExpression own(QStringLiteral("^(?:%1)$").arg(table.value(QStringLiteral("model_pattern")).toString()));
    const QString model = row.value(QStringLiteral("model")).toString();
    if (model.isEmpty() || table.value(QStringLiteral("model_pattern")).toString().isEmpty() || !own.match(model).hasMatch())
        return QJsonObject();
    return row;
}

QJsonObject aiResolvedChoice(const QJsonObject &settings)
{
    QJsonObject s = settings;
    for (const QString &engine : {QStringLiteral("claude"), QStringLiteral("codex")}) {
        const QString modelKey = aiChatModelKeyOf(engine), effortKey = aiChatEffortKeyOf(engine);
        if (!aiModelIsAuto(s.value(modelKey).toString()))
            continue;
        const bool max = s.value(QStringLiteral("routing_max")).toBool(false);
        const QJsonObject row = aiRoutingRow(engine, QStringLiteral("plan"), max);
        // a list without a usable row: the app's default model for the AI (as bridge ai_clis.DEFAULT_CHOICE)
        s[modelKey] = row.value(QStringLiteral("model")).toString(engine == QLatin1String("codex") ? QStringLiteral("gpt-6.1-sol")
                                                                                                 : QStringLiteral("opus"));
        const QString saved = s.value(effortKey).toString().trimmed();
        if (max || saved.isEmpty())
            s[effortKey] = row.value(QStringLiteral("effort")).toString(saved.isEmpty() ? QStringLiteral("medium") : saved);
    }
    return s;
}

QJsonObject aiChatSettings()
{
    QJsonObject s = aiChatRawSettings();
    const QString appdata = QProcessEnvironment::systemEnvironment().value(QStringLiteral("APPDATA"));
    const QString local = QProcessEnvironment::systemEnvironment().value(QStringLiteral("LOCALAPPDATA"));
    // Wherever Claude Code is (its own installer, npm, PATH), and a saved path only while that file is there.
    if (!QFileInfo(s.value("claude").toString()).isFile()) {
        const QString found = ConnectAi::claudeExe();
        s["claude"] = found.isEmpty() ? appdata + QStringLiteral("/npm/node_modules/@anthropic-ai/claude-code/bin/claude.exe")
                                      : found;
    }
    if (s.value("python").toString().isEmpty()) {
        // an install's own tool environment, else the build PC's Python
        const QString own = aiRootPath(QStringLiteral("env/Scripts/python.exe"));
        s["python"] = QFileInfo::exists(own) ? own : local + QStringLiteral("/Programs/Python/Python314/python.exe");
    }
    if (s.value("mcp_server").toString().isEmpty())
        s["mcp_server"] = aiRootPath(QStringLiteral("bridge/letitedit_mcp.py"));
    if (s.value("work_dir").toString().isEmpty())
        s["work_dir"] = qEnvironmentVariableIsSet("LETITEDIT_CHAT_SETTINGS")
            ? QFileInfo(aiChatSettingsPath()).absolutePath() + QStringLiteral("/work")
            : local + QStringLiteral("/letitedit/chat");
    if (s.value("prompt").toString().isEmpty())
        s["prompt"] = aiRootPath(QStringLiteral("chat/panel-prompt.md"));
    // New installs start in chat bubbles. A person who already has settings keeps the view they have been using.
    if (s.value("view_mode").toString().isEmpty())
        s["view_mode"] = QFileInfo::exists(aiChatSettingsPath()) ? QStringLiteral("terminal") : QStringLiteral("bubbles");
    // Nothing chosen: the starred default, else Auto when its switch is on (T331 P10), else Opus / GPT-6.1-Sol.
    const bool autoFirst = aiAutoRouting();
    if (s.value("model").toString().isEmpty())
        s["model"] = s.value("default_claude_model").toString(autoFirst && !aiRouting(QStringLiteral("claude")).isEmpty()
                                                                   ? QStringLiteral("auto") : QStringLiteral("opus"));
    if (s.value("codex_model").toString().isEmpty())
        s["codex_model"] = s.value("default_codex_model").toString(autoFirst && !aiRouting(QStringLiteral("codex")).isEmpty()
                                                                       ? QStringLiteral("auto") : QStringLiteral("gpt-6.1-sol"));
    // Medium effort for anyone who hasn't chosen (the owner, 11 Nov 2026); a saved choice is never touched. Under Auto the
    // planning role's effort from the list.
    if (s.value("effort").toString().isEmpty())
        s["effort"] = aiModelIsAuto(s.value("model").toString())
                          ? aiRouting(QStringLiteral("claude")).value("roles").toObject().value("plan").toObject()
                                .value("effort").toString(QStringLiteral("medium"))
                          : QStringLiteral("medium");
    if (s.value("codex_reasoning").toString().isEmpty())
        s["codex_reasoning"] = aiModelIsAuto(s.value("codex_model").toString())
                                   ? aiRouting(QStringLiteral("codex")).value("roles").toObject().value("plan").toObject()
                                         .value("effort").toString(QStringLiteral("medium"))
                                   : QStringLiteral("medium");
    if (!QFileInfo(s.value("codex").toString()).isFile()) {
        // The Codex app's own CLI (newest copy), else a codex on PATH.
        QString best;
        QDateTime newest;
        QDir bin(local + QStringLiteral("/OpenAI/Codex/bin"));
        for (const QFileInfo &d : bin.entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot)) {
            const QFileInfo exe(d.absoluteFilePath() + QStringLiteral("/codex.exe"));
            if (exe.exists() && (best.isEmpty() || exe.lastModified() > newest)) {
                best = exe.absoluteFilePath();
                newest = exe.lastModified();
            }
        }
        if (best.isEmpty())
            best = QStandardPaths::findExecutable(QStringLiteral("codex"));
        s["codex"] = best;
    }
    for (const QString &id : aiConnectorIds()) {
        const QJsonObject entry = aiEntry(id);
        if (!QFileInfo(s.value(id).toString()).isFile())
            s[id] = entry.value("program").toString().replace(QStringLiteral("{ai_home}"), aiConnectorHome(s, id));
        const QString model = entry.value("model_key").toString(), effort = entry.value("effort_key").toString();
        if (s.value(model).toString().isEmpty())
            s[model] = s.value(QStringLiteral("default_%1_model").arg(id)).toString(entry.value("default_model").toString());
        if (s.value(effort).toString().isEmpty())
            s[effort] = entry.value("default_effort").toString();
    }
    // The saved AI while its program is here, else the first AI that is: nobody starts on a dead default. The saved choice
    // itself stays in panel.json, so it comes back with the program.
    QString engine = s.value("engine").toString().trimmed().toLower();
    if (engine.isEmpty() || !aiEngineHere(s, engine)) {
        for (const QString &id : aiEngineIds()) {
            if (aiEngineHere(s, id)) {
                engine = id;
                break;
            }
        }
    }
    s["engine"] = engine.isEmpty() ? aiEngineIds().first() : engine;
    return s;
}

// An AI with no terminal view of its own (a connector) always shows as chat bubbles.
bool aiTerminalMode()
{
    const QJsonObject s = aiChatSettings();
    return (qEnvironmentVariable("LETITEDIT_QA_MOCK_AI").isEmpty()
            || (qEnvironmentVariableIsSet("LETITEDIT_QA")
                && qEnvironmentVariableIsSet("LETITEDIT_QA_TERMINAL_VIEW")))
           && s.value("view_mode").toString() != QLatin1String("bubbles")
           && aiEngineCan(s.value("engine").toString(), QStringLiteral("terminal"));
}

// "codex" or "claude" (panel.json "engine"): which AI the panel and push-to-talk talk to.
bool aiChatIsCodex(const QJsonObject &s)
{
    return s.value("engine").toString().trimmed().toLower() == QLatin1String("codex");
}

// The AI the panel talks to, by its id in the list.
QString aiChatEngineId(const QJsonObject &s)
{
    return s.value("engine").toString();
}

QString aiEngineShortName(const QString &id)
{
    return aiEntry(id).value("short").toString(id);
}

QString aiChatEngineName()
{
    return aiEngineShortName(aiChatEngineId(aiChatSettings()));
}

// Codex's own folder: CODEX_HOME, else ~/.codex.
QString aiCodexHome()
{
    const QString dir = qEnvironmentVariable("CODEX_HOME");
    return dir.isEmpty() ? QDir::homePath() + QStringLiteral("/.codex") : QDir::fromNativeSeparators(dir);
}

// A top-level `key = "value"` from Codex's own config (config.toml), for the model the person chose there.
QString aiCodexConfigValue(const QString &key)
{
    QFile f(aiCodexHome() + QStringLiteral("/config.toml"));
    if (!f.open(QIODevice::ReadOnly | QIODevice::Text))
        return {};
    const QRegularExpression re(QStringLiteral("^\\s*") + QRegularExpression::escape(key)
                                + QStringLiteral("\\s*=\\s*[\"']([^\"']*)[\"']"));
    while (!f.atEnd()) {
        const QString line = QString::fromUtf8(f.readLine());
        if (line.trimmed().startsWith(QLatin1Char('[')))
            break; // tables start: only top-level keys
        const auto m = re.match(line);
        if (m.hasMatch())
            return m.captured(1);
    }
    return {};
}

// A TOML basic string (JSON string escapes are TOML-compatible) for `codex -c key=value`.
QString aiTomlString(const QString &text)
{
    QString json = QString::fromUtf8(QJsonDocument(QJsonArray{text}).toJson(QJsonDocument::Compact));
    return json.mid(1, json.size() - 2);
}

// Pass the editor's tool-server configuration explicitly. Codex starts MCP servers with only a small inherited
// environment. The server must use the same instance, install root and media settings as the window that launched it.
QStringList aiCodexWindowArgs()
{
    QStringList args;
    for (const char *name : {"LETITEDIT_INSTANCE", "LETITEDIT_ROOT", "LETITEDIT_SETTINGS",
                             "LETITEDIT_PROGRESS_DIR", "LETITEDIT_PROGRESS_RUN", "LETITEDIT_MY_LOOKS",
                             "LETITEDIT_RENDER_LOCK", "LETITEDIT_WHISPER_CPU", "LETITEDIT_LEAN_STAGE_HANDOFFS",
                             "CUDA_VISIBLE_DEVICES",
                             "OMP_NUM_THREADS", "MKL_NUM_THREADS", "PYTHON_CPU_COUNT"}) {
        const QString value = qEnvironmentVariable(name);
        if (!value.isEmpty())
            args << QStringLiteral("-c")
                 << QStringLiteral("mcp_servers.letitedit.env.%1=%2").arg(QLatin1String(name), aiTomlString(value));
    }
    return args;
}

// ------------------------------------------------------------------ the AI, its model and its effort
// The chat's top row. panel.json "engine" picks the AI; Claude takes "model" and "effort", Codex "codex_model" and
// "codex_reasoning". The selected model is explicit and one can be starred as the default.

// An AI's model and effort keys in panel.json, by its id: they come from the list.
QString aiChatModelKeyOf(const QString &engine)
{
    return aiEntry(engine).value("model_key").toString(QStringLiteral("model"));
}

QString aiChatEffortKeyOf(const QString &engine)
{
    return aiEntry(engine).value("effort_key").toString(QStringLiteral("effort"));
}

QString aiChatEffortWord(const QString &effort)
{
    static const QMap<QString, QString> words{{"none", "None"},   {"minimal", "Minimal"}, {"low", "Low"},
                                              {"medium", "Medium"}, {"high", "High"},       {"xhigh", "Extra high"},
                                              {"max", "Max"},     {"ultra", "Ultra"}};
    QString word = words.value(effort, effort);
    if (!word.isEmpty())
        word[0] = word[0].toUpper();
    return word;
}

static QList<AiChatChoice> aiChatEngineChoices()
{
    QList<AiChatChoice> choices;
    for (const QJsonObject &row : aiListRows()) {
        const QJsonObject picker = row.value("picker").toObject();
        const QString id = row.value("id").toString();
        choices << AiChatChoice{id, picker.value("label").toString(id), picker.value("button").toString(id), picker.value("tip").toString()};
    }
    return choices;
}

// What the AI button offers: only the AIs on this PC; with none, the way to set one up. A file check, so it costs nothing.
QList<AiChatChoice> aiChatEngineChoicesHere(const QJsonObject &settings)
{
    QList<AiChatChoice> here;
    for (const AiChatChoice &choice : aiChatEngineChoices()) {
        if (aiEngineHere(settings, choice.value))
            here << choice;
    }
    if (here.isEmpty())
        here << AiChatChoice{QStringLiteral("connect"), QStringLiteral("Set up an AI..."), QStringLiteral("Set up an AI"),
                             QStringLiteral("Opens Connect Your AI")};
    return here;
}

// Claude Code's model names: each is the newest model of that family (Claude Code 2.1.304: fable = claude-fable-5-1,
// opus = claude-opus-5-5, sonnet = claude-sonnet-5-5, haiku = claude-haiku-5-5). Every one takes every effort.
static QList<AiChatChoice> aiClaudeModels()
{
    return {{QStringLiteral("fable"), QStringLiteral("Fable (most capable)"), QStringLiteral("Fable"),
             QStringLiteral("Claude Fable, its newest version (Fable 5.1 now): the most capable, for the hardest "
                            "edits. Slower, and uses the most of your plan.")},
            {QStringLiteral("opus"), QStringLiteral("Opus (very capable)"), QStringLiteral("Opus"),
             QStringLiteral("Claude Opus, its newest version (Opus 5.5 now): very capable, for most editing.")},
            {QStringLiteral("sonnet"), QStringLiteral("Sonnet (faster)"), QStringLiteral("Sonnet"),
             QStringLiteral("Claude Sonnet, its newest version (Sonnet 5.5 now): quicker, for everyday edits.")},
            {QStringLiteral("haiku"), QStringLiteral("Haiku (fastest)"), QStringLiteral("Haiku"),
             QStringLiteral("Claude Haiku, its newest version (Haiku 5.5 now): the quickest and the lightest on your "
                            "plan, for small requests.")}};
}

static QList<AiChatChoice> aiClaudeEfforts()
{
    return {{QStringLiteral("low"), QStringLiteral("Low"), QStringLiteral("Low effort"),
             QStringLiteral("Quick answers with light thinking")},
            {QStringLiteral("medium"), QStringLiteral("Medium"), QStringLiteral("Medium effort"),
             QStringLiteral("A balance of speed and care")},
            {QStringLiteral("high"), QStringLiteral("High"), QStringLiteral("High effort"),
             QStringLiteral("More careful, for bigger edits")},
            {QStringLiteral("xhigh"), QStringLiteral("Extra high"), QStringLiteral("Extra high effort"),
             QStringLiteral("Very careful, for hard edits; slower")},
            {QStringLiteral("max"), QStringLiteral("Max"), QStringLiteral("Max effort"),
             QStringLiteral("The deepest thinking: the slowest, and uses the most of your plan")}};
}

// Codex's own list of models (CODEX_HOME/models_cache.json, which Codex keeps up to date), in its order, each with
// the efforts it supports and whether its picker shows it. Empty before Codex has run on this PC.
QString aiCodexModelsPath()
{
    return QFileInfo(aiChatHistoryPath()).absolutePath() + QStringLiteral("/codex-models.json");
}

static QList<QJsonObject> aiCodexModelCache()
{
    QFile snapshot(aiCodexModelsPath());
    const QJsonObject live = snapshot.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(snapshot.readAll()).object() : QJsonObject();
    const double fetched = live.value("fetched_at").toDouble();
    const double now = QDateTime::currentMSecsSinceEpoch() / 1000.0;
    const double changed = qMax(QFileInfo(aiCodexHome() + QStringLiteral("/models_cache.json")).lastModified().toMSecsSinceEpoch(),
                               QFileInfo(aiCodexHome() + QStringLiteral("/auth.json")).lastModified().toMSecsSinceEpoch()) / 1000.0;
    if (live.value("home").toString().compare(QDir(aiCodexHome()).absolutePath(), Qt::CaseInsensitive) == 0
        && now >= fetched && now - fetched < 300 && changed <= fetched && live.value("data").isArray()) {
        QList<QJsonObject> offered;
        for (const auto &value : live.value("data").toArray()) {
            QJsonObject model = value.toObject();
            const QString id = model.value("model").toString(model.value("id").toString());
            if (id.isEmpty())
                continue;
            model["slug"] = id;
            model["display_name"] = model.value("displayName");
            model["visibility"] = model.value("hidden").toBool() ? QStringLiteral("hide") : QStringLiteral("list");
            model["service_tiers"] = model.value("serviceTiers");
            model["supported_reasoning_levels"] = model.value("supportedReasoningEfforts");
            offered << model;
        }
        return offered;
    }
    static QDateTime stamp;
    static QString source;
    static QList<QJsonObject> models;
    const QFileInfo info(aiCodexHome() + QStringLiteral("/models_cache.json"));
    if (!info.exists())
        return {};
    if (info.lastModified() == stamp && source == info.absoluteFilePath())
        return models;
    QFile f(info.absoluteFilePath());
    QJsonParseError error;
    const QJsonDocument doc = f.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(f.readAll(), &error) : QJsonDocument();
    if (!doc.isObject())
        return models; // being written: the last good list
    QList<QJsonObject> found;
    for (const auto &v : doc.object().value("models").toArray()) {
        if (!v.toObject().value("slug").toString().isEmpty())
            found << v.toObject();
    }
    std::stable_sort(found.begin(), found.end(), [](const QJsonObject &a, const QJsonObject &b) {
        return a.value("priority").toInt() < b.value("priority").toInt();
    });
    stamp = info.lastModified();
    source = info.absoluteFilePath();
    models = found;
    return models;
}

// The models Codex's picker shows; before Codex has written its list, the ones it showed in October 2026.
static QList<AiChatChoice> aiCodexModels()
{
    QList<AiChatChoice> list;
    for (const auto &m : aiCodexModelCache()) {
        if (m.value("visibility").toString() == QLatin1String("list"))
            list.append({m.value("slug").toString(), m.value("display_name").toString(m.value("slug").toString()),
                         m.value("display_name").toString(m.value("slug").toString()), m.value("description").toString()});
    }
    if (list.isEmpty())
        list = {{QStringLiteral("gpt-6-astra"), QStringLiteral("GPT-6-Astra"), QStringLiteral("GPT-6-Astra"),
                 QStringLiteral("Frontier intelligence for the most demanding work.")},
                {QStringLiteral("gpt-6.1-sol"), QStringLiteral("GPT-6.1-Sol"), QStringLiteral("GPT-6.1-Sol"),
                 QStringLiteral("Current workhorse model.")},
                {QStringLiteral("gpt-6-sol"), QStringLiteral("GPT-6-Sol"), QStringLiteral("GPT-6-Sol"),
                 QStringLiteral("Previous generation workhorse model.")},
                {QStringLiteral("gpt-6-luna"), QStringLiteral("GPT-6-Luna"), QStringLiteral("GPT-6-Luna"),
                 QStringLiteral("Fast and affordable model for easier tasks.")}};
    return list;
}

// The efforts a Codex model supports, with what each means; empty for a model Codex's list doesn't have.
static QList<AiChatChoice> aiCodexModelEfforts(const QString &model)
{
    QList<AiChatChoice> efforts;
    for (const auto &m : aiCodexModelCache()) {
        if (m.value("slug").toString() != model)
            continue;
        for (const auto &v : m.value("supported_reasoning_levels").toArray()) {
            const QString effort = v.toObject().value("effort").toString(v.toObject().value("reasoningEffort").toString());
            if (!effort.isEmpty())
                efforts.append({effort, aiChatEffortWord(effort), aiChatEffortWord(effort) + QStringLiteral(" effort"),
                                v.toObject().value("description").toString()});
        }
        break;
    }
    return efforts;
}

// The efforts to offer for a Codex model: its own; for a model the list doesn't have (newer than the list, or typed
// by hand), the ones every listed model has; with no list at all, low, medium and high.
QList<AiChatChoice> aiCodexEffortChoicesFor(const QString &model)
{
    QList<AiChatChoice> efforts = aiCodexModelEfforts(model);
    if (!efforts.isEmpty())
        return efforts;
    bool first = true;
    for (const auto &m : aiCodexModelCache()) {
        if (m.value("visibility").toString() != QLatin1String("list"))
            continue;
        const QList<AiChatChoice> own = aiCodexModelEfforts(m.value("slug").toString());
        if (first)
            efforts = own;
        else
            efforts.erase(std::remove_if(efforts.begin(), efforts.end(),
                                         [&own](const AiChatChoice &e) {
                                             return std::none_of(own.begin(), own.end(), [&e](const AiChatChoice &o) {
                                                 return o.value == e.value;
                                             });
                                         }),
                          efforts.end());
        first = false;
    }
    if (efforts.isEmpty()) {
        for (const auto &e : aiClaudeEfforts().mid(0, 4))
            efforts.append(e);
    }
    return efforts;
}

bool aiChatHasChoice(const QList<AiChatChoice> &choices, const QString &value)
{
    return std::any_of(choices.begin(), choices.end(), [&value](const AiChatChoice &c) { return c.value == value; });
}

// The effort among `takes` nearest the chosen one on the scale none..max (a tie goes to the lower, lighter one); an
// effort that isn't on the scale is measured from medium, the default. Empty when `takes` is empty.
QString aiNearestEffort(const QList<AiChatChoice> &takes, const QString &chosen)
{
    static const QStringList scale{"none", "minimal", "low", "medium", "high", "xhigh", "max", "ultra"};
    int want = scale.indexOf(chosen.trimmed().toLower());
    if (want < 0)
        want = scale.indexOf(QStringLiteral("medium"));
    QString best;
    int bestGap = 1000;
    for (const auto &e : takes) {
        const int at = scale.indexOf(e.value);
        const int gap = at < 0 ? 999 : qAbs(at - want);
        if (best.isEmpty() || gap < bestGap) {
            best = e.value;
            bestGap = gap;
        }
    }
    return best;
}

// A connector AI's models or thinking levels: what this account was offered at its last start (the host saves it), in the list's
// words where the list knows them; before any start, the list.
static QList<AiChatChoice> aiConnectorChoices(const QJsonObject &s, const QString &engine, const QString &which)
{
    const QJsonArray listed = aiEntry(engine).value(which).toArray();
    const auto known = [&listed](const QString &value) {
        for (const QJsonValue &row : listed) {
            if (row.toObject().value("value").toString() == value)
                return row.toObject();
        }
        return QJsonObject();
    };
    QFile f(aiConnectorProfile(s, engine) + QStringLiteral("/letitedit-choices.json"));
    const QJsonArray offered = f.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(f.readAll()).object().value(which).toArray() : QJsonArray();
    QList<AiChatChoice> out;
    for (const QJsonValue &row : offered.isEmpty() ? listed : offered) {
        const QString value = row.toObject().value("value").toString();
        const QJsonObject words = known(value);
        const QString label = words.value("label").toString(row.toObject().value("label").toString(value));
        out << AiChatChoice{value, label, words.value("button").toString(label), words.value("tip").toString()};
    }
    return out;
}

// A value typed into panel.json by hand that the model list lacks is kept and shown as it is.
QList<AiChatChoice> aiChatModelChoices(const QJsonObject &s)
{
    const bool codex = aiChatIsCodex(s);
    const QString engine = aiChatEngineId(s);
    QList<AiChatChoice> list;
    if (aiEngineIsConnector(engine)) {
        list += aiConnectorChoices(s, engine, QStringLiteral("models"));
    } else if (codex) {
        list += aiCodexModels();
    } else {
        list += aiClaudeModels();
    }
    const QString current = s.value(aiChatModelKeyOf(engine)).toString().trimmed();
    // Auto first, while its switch is on or it is the saved choice (T331 P10)
    const QJsonObject autoWords = aiRouting(engine).value(QStringLiteral("auto")).toObject();
    if (!autoWords.isEmpty() && (aiAutoRouting() || aiModelIsAuto(current))) {
        const QString label = autoWords.value(QStringLiteral("label")).toString(QStringLiteral("Auto"));
        list.prepend({QStringLiteral("auto"), label, autoWords.value(QStringLiteral("button")).toString(label),
                      autoWords.value(QStringLiteral("tip")).toString()});
    }
    if (!current.isEmpty() && !aiChatHasChoice(list, current) && !aiModelIsAuto(current))
        list.append({current, current, current, QStringLiteral("Set in %1").arg(QDir::toNativeSeparators(aiChatSettingsPath()))});
    return list;
}

// The effort menu shows what the chosen model takes.
QList<AiChatChoice> aiChatEffortChoices(const QJsonObject &s)
{
    const bool codex = aiChatIsCodex(s);
    const QString engine = aiChatEngineId(s);
    QList<AiChatChoice> list;
    if (aiEngineIsConnector(engine)) {
        list += aiConnectorChoices(s, engine, QStringLiteral("efforts"));
    } else if (codex) {
        QString model = s.value(QStringLiteral("codex_model")).toString().trimmed();
        if (model.isEmpty())
            model = aiCodexConfigValue(QStringLiteral("model"));
        list += aiCodexEffortChoicesFor(model);
    } else {
        list += aiClaudeEfforts();
    }
    const QString current = s.value(aiChatEffortKeyOf(engine)).toString().trimmed();
    if (!current.isEmpty() && !aiChatHasChoice(list, current))
        list.append({current, aiChatEffortWord(current), aiChatEffortWord(current) + QStringLiteral(" effort"),
                     QStringLiteral("Set in %1").arg(QDir::toNativeSeparators(aiChatSettingsPath()))});
    return list;
}

// Retained for Connect Your AI's launch path. The chat now inherits the person's full tool set.
QStringList aiClaudeLockdownArgs()
{
    return {}; // inherit the person's tools and permission rules
}

QString aiSpeedKey(const QString &engine)
{
    return aiEntry(engine).value(QStringLiteral("speed_key")).toString();
}

QJsonArray aiSpeedChoices(const QJsonObject &settings, const QString &engine)
{
    const QString model = settings.value(aiChatModelKeyOf(engine)).toString();
    const QJsonObject entry = aiEntry(engine);
    QJsonArray rows = entry.value("speeds").toArray();
    if (engine == QLatin1String("codex")) {
        QSet<QString> seen{QStringLiteral("normal"), QStringLiteral("default")};
        for (const auto &row : aiCodexModelCache()) {
            if (row.value("slug").toString() == model) {
                for (const auto &value : row.value("service_tiers").toArray()) {
                    const QJsonObject offer = value.toObject();
                    const QString id = offer.value("id").toString();
                    const QString name = offer.value("name").toString();
                    const QString description = offer.value("description").toString();
                    if (id.trimmed().isEmpty() || name.trimmed().isEmpty() || description.trimmed().isEmpty() || seen.contains(id))
                        continue;
                    seen.insert(id);
                    const QJsonObject costs = entry.value("speed_costs").toObject();
                    const QString cost = costs.value(name.toLower()).toString(costs.value("other").toString());
                    rows.append(QJsonObject{{"value", id}, {"label", name}, {"models", QJsonArray{model}},
                                            {"tip", description + QStringLiteral(". ") + cost + QLatin1Char(' ') + entry.value("speed_tip").toString()},
                                            {"pass", QJsonObject{{"config", QStringLiteral("service_tier")}, {"value", id}}}});
                }
                break;
            }
        }
    }
    QJsonArray choices;
    for (const auto &value : rows) {
        QJsonObject choice = value.toObject();
        const QJsonObject overrides = choice.value("model_overrides").toObject().value(model).toObject();
        for (auto field = overrides.begin(); field != overrides.end(); ++field)
            choice[field.key()] = field.value();
        const QString speed = choice.value("value").toString();
        bool enabled = speed == QLatin1String("normal") || choice.value("models").toArray().contains(model);
        choice["enabled"] = enabled;
        if (!enabled)
            choice["tip"] = QStringLiteral("%1 is not offered for %2. Normal speed is used. ")
                                .arg(choice.value("label").toString(), model) + choice.value("tip").toString();
        choices.append(choice);
    }
    return choices;
}

QString aiSpeedValue(const QJsonObject &settings, const QString &engine)
{
    const QString wanted = settings.value(aiSpeedKey(engine)).toString(QStringLiteral("normal"));
    for (const auto &value : aiSpeedChoices(settings, engine)) {
        const QJsonObject choice = value.toObject();
        if (choice.value("value").toString() == wanted && choice.value("enabled").toBool())
            return wanted;
    }
    return QStringLiteral("normal");
}

QString aiCodexSpeedTier(const QJsonObject &settings)
{
    const QString selected = aiSpeedValue(settings, QStringLiteral("codex"));
    for (const auto &value : aiSpeedChoices(settings, QStringLiteral("codex"))) {
        const QJsonObject choice = value.toObject();
        if (choice.value("value").toString() == selected)
            return choice.value("pass").toObject().value("value").toString();
    }
    return QStringLiteral("default");
}

QStringList aiCodexSpeedConfigArgs()
{
    QStringList args;
    const QJsonObject config = aiEntry(QStringLiteral("codex")).value("speed_config").toObject();
    for (auto setting = config.begin(); setting != config.end(); ++setting) {
        const QByteArray encoded = QJsonDocument(QJsonArray{setting.value()}).toJson(QJsonDocument::Compact);
        args << QStringLiteral("-c") << setting.key() + QLatin1Char('=') + QString::fromUtf8(encoded.mid(1, encoded.size() - 2));
    }
    return args;
}
