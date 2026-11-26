/*
 * Claude Bridge: a local-only control channel for driving Shotcut from an AI agent.
 * See claudebridge.h for the protocol.
 */

#include "letitedit/bridge/claudebridge.h"
#include "letitedit/bridge/bridgehelpers.h"
#include "letitedit/panels/musicpicker.h"
#include "letitedit/export/othersizes.h"
#include "letitedit/export/exportchecks.h"
#include "letitedit/airoot.h"
#include "letitedit/startupwork.h"
#include "letitedit/panels/aiaudiolibrary.h"
#include "letitedit/bridge/aicollaboration.h"
#include "letitedit/panels/hookpanel.h"
#include "letitedit/panels/myassets.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/review/reviewmode.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/dialogs/problemreport.h"
#include "jobqueue.h"
#include "jobs/abstractjob.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/player/renderedpreview.h"
#include "letitedit/player/playbackquality.h"
#include "models/subtitlesselectionmodel.h"
#include "settings.h"
#include <QStandardPaths>
#include <QCryptographicHash>
#include <QXmlStreamReader>
#include <algorithm>
#include <QLineEdit>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QFormLayout>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QComboBox>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QTabWidget>
#include <QDialogButtonBox>
#include <QMenuBar>
#include <QDateTime>
#include <QPixmap>
#include <QWindow>
#include <qpa/qwindowsysteminterface.h>

#include "Logger.h"
#include "actions.h"
#include "commands/timelinecommands.h"
#include "commands/subtitlecommands.h"
#include "controllers/filtercontroller.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "qmltypes/qmlutilities.h"
#include "videowidget.h"
#include "mltcontroller.h"
#include "proxymanager.h"
#include "player.h"
#include "models/markersmodel.h"
#include "models/attachedfiltersmodel.h"
#include "models/metadatamodel.h"
#include "models/multitrackmodel.h"
#include "models/subtitles.h"
#include "models/subtitlesmodel.h"
#include "qmltypes/qmlfilter.h"
#include "qmltypes/qmlmetadata.h"

#include <QAbstractButton>
#include <QApplication>
#include <QDialog>
#include <QLabel>
#include <QMessageBox>
#include <QDockWidget>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalServer>
#include <QLocalSocket>
#include <QTimer>
#include <QtConcurrent/QtConcurrentRun>
#include <QUndoStack>
#include <QDir>
#include <QFontDatabase>
#include <QLockFile>
#include <QSaveFile>
#include <QQuickWidget>
#include <QQuickItem>
#include <QRegularExpression>

using namespace BridgeHelpers;

namespace BridgeHelpers {

QString requireString(const QJsonObject &params, const char *key)
{
    const QString value = params.value(key).toString();
    if (value.isEmpty())
        throw BridgeError(QStringLiteral("missing string param '%1'").arg(key));
    return value;
}

int requireInt(const QJsonObject &params, const char *key)
{
    if (!params.value(key).isDouble())
        throw BridgeError(QStringLiteral("missing integer param '%1'").arg(key));
    return params.value(key).toInt();
}

QString jsonToPropertyString(const QJsonValue &value)
{
    if (value.isDouble())
        return QString::number(value.toDouble(), 'g', 15);
    if (value.isBool())
        return value.toBool() ? QStringLiteral("1") : QStringLiteral("0");
    return value.toString();
}

QJsonObject actionToJson(const QString &name, QAction *action)
{
    return QJsonObject{
        {"name", name},
        {"text", action->text().remove('&')},
        {"enabled", action->isEnabled()},
        {"checkable", action->isCheckable()},
        {"checked", action->isChecked()},
        {"shortcut", action->shortcut().toString()},
    };
}

QAction *findAction(const QString &name)
{
    if (Actions.keys().contains(name))
        return Actions[name];
    for (auto *action : MAIN.findChildren<QAction *>()) {
        if (action->objectName() == name)
            return action;
    }
    return nullptr;
}

QString plainButtonText(const QAbstractButton *button)
{
    return button->text().remove('&').trimmed();
}

QJsonObject describeDialog(QWidget *dialog)
{
    QStringList texts;
    if (auto *box = qobject_cast<QMessageBox *>(dialog)) {
        texts << box->text() << box->informativeText();
    } else {
        for (auto *label : dialog->findChildren<QLabel *>()) {
            if (label->isVisible() && !label->text().trimmed().isEmpty())
                texts << label->text();
        }
    }
    texts.removeAll(QString());
    QJsonArray buttons;
    for (auto *button : dialog->findChildren<QAbstractButton *>()) {
        if (button->isVisible() && button->isEnabled() && !plainButtonText(button).isEmpty())
            buttons.append(plainButtonText(button));
    }
    return QJsonObject{{"title", dialog->windowTitle()},
                       {"text", texts.join("\n")},
                       {"buttons", buttons}};
}

QJsonObject metadataToJson(QmlMetadata *meta)
{
    return QJsonObject{
        {"id", meta->uniqueId()},
        {"name", meta->name()},
        {"mlt_service", meta->mlt_service()},
        {"isAudio", meta->isAudio()},
    };
}

} // namespace BridgeHelpers

static ClaudeBridge *s_revisionBridge = nullptr;

ClaudeBridge::ClaudeBridge(QObject *parent)
    : QObject(parent)
    , m_server(new QLocalServer(this))
{
    s_revisionBridge = this;
    QTimer::singleShot(0, this, [] { ReviewMode::initializeQueue(&MAIN); });
    m_server->setSocketOptions(QLocalServer::UserAccessOption);
    connect(m_server, &QLocalServer::newConnection, this, &ClaudeBridge::onNewConnection);
}

bool ClaudeBridge::start()
{
    m_instanceId = qEnvironmentVariable("LETITEDIT_INSTANCE", "main");
    if (!QRegularExpression(QStringLiteral("^[a-z0-9][a-z0-9_-]{0,59}$")).match(m_instanceId).hasMatch())
        return false;
    const QString folder = aiRootPath(QStringLiteral("instances/")) + m_instanceId;
    QDir().mkpath(folder);
    m_instanceLock = std::make_unique<QLockFile>(folder + QStringLiteral("/editor.lock"));
    m_instanceLock->setStaleLockTime(0);
    if (!m_instanceLock->tryLock()) {
        LOG_WARNING() << "AI Assist instance is already running:" << m_instanceId;
        return false;
    }
    m_pipeName = m_instanceId == "main" ? QString::fromLatin1(kServerName) : QStringLiteral("letitedit-") + m_instanceId;
    if (!m_server->listen(m_pipeName)) {
        LOG_WARNING() << "Claude bridge failed to listen:" << m_server->errorString();
        return false;
    }
    LOG_INFO() << "Claude bridge listening on" << m_server->fullServerName();
    QSaveFile registry(folder + QStringLiteral("/editor.json"));
    if (registry.open(QIODevice::WriteOnly)) {
        registry.write(QJsonDocument(QJsonObject{{"instance_id", m_instanceId},
            {"pid", QCoreApplication::applicationPid()}, {"pipe", m_pipeName},
            {"appdata", Settings.appDataLocation()},
            {"my_looks", qEnvironmentVariable("LETITEDIT_MY_LOOKS",
                m_instanceId == "main"
                    ? QDir(QStandardPaths::writableLocation(QStandardPaths::DocumentsLocation))
                          .filePath(QStringLiteral("letitedit/My Looks"))
                    : QDir(Settings.appDataLocation()).filePath(QStringLiteral("My Looks")))}}).toJson());
        registry.commit();
    }
    // Preserve Shotcut's own changing title while keeping the editor identity visible.
    const QString suffix = QStringLiteral(" [AI: %1]").arg(m_instanceId);
    connect(&MAIN, &QWidget::windowTitleChanged, this, [suffix](const QString &title) {
        if (!title.endsWith(suffix)) MAIN.setWindowTitle(title + suffix);
    });
    MAIN.setWindowTitle(MAIN.windowTitle() + suffix);
    QTimer::singleShot(0, this, [this]{ installCollaborationUi(); });
    return true;
}

ClaudeBridge::~ClaudeBridge() = default;

void ClaudeBridge::onNewConnection()
{
    while (QLocalSocket *socket = m_server->nextPendingConnection()) {
        connect(socket, &QLocalSocket::readyRead, this, &ClaudeBridge::onReadyRead);
        connect(socket, &QLocalSocket::disconnected, this, [this, socket]() {
            m_buffers.remove(socket);
            socket->deleteLater();
        });
    }
}

void ClaudeBridge::onReadyRead()
{
    auto *socket = qobject_cast<QLocalSocket *>(sender());
    if (!socket)
        return;
    // letitedit (T288): while the editor's fonts and filters still load behind its window, requests wait for them
    if (!StartupWork::instance().isReady()) {
        StartupWork::instance().whenReady(socket, [this, socket]() {
            QMetaObject::invokeMethod(socket, [this, socket]() { readRequests(socket); }, Qt::QueuedConnection);
        });
        return;
    }
    readRequests(socket);
}

void ClaudeBridge::readRequests(QLocalSocket *socket)
{
    QByteArray &buffer = m_buffers[socket];
    buffer.append(socket->readAll());
    int newline;
    while ((newline = buffer.indexOf('\n')) >= 0) {
        const QByteArray line = buffer.left(newline).trimmed();
        buffer.remove(0, newline + 1);
        if (line.isEmpty())
            continue;
        QJsonParseError parseError;
        const QJsonDocument doc = QJsonDocument::fromJson(line, &parseError);
        QJsonObject response;
        if (!doc.isObject()) {
            response = {{"id", QJsonValue::Null},
                        {"ok", false},
                        {"error", "invalid JSON: " + parseError.errorString()}};
        } else {
            const auto request = doc.object();
            const QString method = request.value("method").toString();
            if ((method == QLatin1String("apply_transaction") || method == QLatin1String("replace_tracks"))
                && !request.value("params").toObject().value("tracks").toArray().isEmpty()) {
                try {
                    prepareTransaction(request, socket);
                    continue;
                } catch (const BridgeError &error) {
                    response = {{"id", request.value("id")}, {"ok", false}, {"error", error.message}};
                }
            } else {
                response = handle(request);
            }
        }
        socket->write(QJsonDocument(response).toJson(QJsonDocument::Compact) + '\n');
        socket->flush();
    }
}

// Every edit the bridge applied, by its Undo label (or what it did), in order: a request to the AI says which changes
// its tools made while it ran (aiBridgeEditsSince in aichatpanel.h).
static QStringList &bridgeEditLog()
{
    static QStringList log;
    return log;
}

// The project's revision (T99): what an AI request about a selected item carries.
QString aiBridgeRevision()
{
    return s_revisionBridge ? s_revisionBridge->revision() : QString();
}

int aiBridgeEditCount()
{
    return bridgeEditLog().size();
}

QStringList aiBridgeEditsSince(int mark)
{
    return bridgeEditLog().mid(qMax(0, mark));
}

static QString bridgeEditLabel(const QString &method, const QJsonObject &params)
{
    static const QMap<QString, QString> plain{{"delete_section", "Delete a section"},
                                              {"edit_subtitles", "Edit captions"},
                                              {"add_clip", "Add a clip"},
                                              {"split_clip", "Split a clip"},
                                              {"move_clip", "Move a clip"},
                                              {"remove_clip", "Remove a clip"},
                                              {"set_track", "Change a track"},
                                              {"add_filter", "Add an effect"},
                                              {"remove_filter", "Remove an effect"},
                                              {"set_filter_params", "Change an effect"},
                                              {"import_srt", "Add captions"},
                                              {"add_music", "Add music"},
                                              {"set_look", "Set the Look"}};
    if (method == QLatin1String("replace_tracks") || method == QLatin1String("apply_transaction")
        || method == QLatin1String("set_markers"))
        return params.value("label").toString(QStringLiteral("AI edit"));
    return plain.value(method);
}

QJsonObject ClaudeBridge::handle(const QJsonObject &request)
{
    const QJsonValue id = request.value("id");
    const QString method = request.value("method").toString();
    try {
        const QJsonObject params = request.value("params").toObject();
        const QJsonValue result = dispatch(method, params);
        const QString edit = bridgeEditLabel(method, params);
        // a preview or a dry run changes nothing
        if (!edit.isEmpty() && !params.value("preview").toBool() && !params.value("dry_run").toBool())
            bridgeEditLog().append(edit);
        return {{"id", id}, {"ok", true}, {"result", result}};
    } catch (const BridgeError &e) {
        LOG_WARNING() << "Claude bridge" << method << "failed:" << e.message;
        return {{"id", id}, {"ok", false}, {"error", e.message}};
    }
}

QJsonValue ClaudeBridge::dispatch(const QString &method, const QJsonObject &params)
{
    // While a project is being replaced, the old timeline is being closed: a seek or an edit then could reach a
    // timeline that is going away (a rapid reopen + seek once crashed in the media engine). Answering dialogs,
    // reading state, the chat and the voice controls stay allowed; every edit waits for the open to finish
    // (the bridge client retries "still opening" for up to 20 s).
    static const QStringList duringOpen{"ping", "state", "editor_state", "live_context", "dialog_button",
                                        "close_dialog", "chat_state", "chat_send", "chat_outcome", "command_help",
                                        "grab_window", "my_style_state", "my_assets_state"};
    if (MAIN.isOpening() && !duringOpen.contains(method) && !method.startsWith(QLatin1String("voice_")))
        throw BridgeError("a project is still opening; try again in a moment");
    if (method == "live_context") return liveContext();
    if (method == "editor_state") return editorState(params);
    if (method.startsWith(QLatin1String("voice_"))) return voiceCommand(method, params);
    if (method == "command_help") return commandHelp(params);
    if (method == "delete_section") return synchronizedDelete(params);
    if (method == "edit_subtitles") return subtitleEdit(params);
    if (method == "replace_tracks") return replaceTracks(params);
    if (method == "set_markers") return setMarkers(params);
    if (method == "apply_transaction") return applyTransaction(params);
    if (method == "load_fonts") return loadFonts(params);
    if (method == "set_look") {
        // the project's style pack (letitedit_ai:style on the timeline) as one undo step: the AI's {op: style} on an
        // open window, and My style's Use on This Video. pack "" clears it.
        MyStyle::setProjectStyle(&MAIN, params.value("id").toString());
        return QJsonObject{{"look", MyStyle::projectStyle(&MAIN)}, {"modified", MAIN.isWindowModified()}};
    }
    if (method == "chat_send") {
        // summary: the short line the chat shows for a request an app button wrote; the AI gets the whole text
        // a test window can ask for New video's way of starting the AI (its checks, not its request)
        const bool autonomous = qEnvironmentVariableIsSet("LETITEDIT_QA") && params.value("autonomous").toBool();
        const int request = aiChatRequest(&MAIN, params.value("text").toString(), params.value("summary").toString(), false, autonomous);
        return QJsonObject{{"sent", request > 0}, {"request", request}, {"refusal", aiChatRefusal()}};
    }
    // Background runs off: the critic's review as a visible second conversation in the panel (critic.py asks).
    if (method == "chat_review") return aiChatVisibleReview(params.value("request").toString(), params.value("out").toString(), params);
    if (method == "chat_outcome") return aiChatOutcome(params.value("request").toInt());
    if (method == "chat_state") return aiChatState();
    if (method == "chat_scroll" && qEnvironmentVariableIsSet("LETITEDIT_QA")) {
        // A journey check moves the real chat scroll bar as the person does with the wheel.
        AiChat *c = aiChatInstance();
        if (!c || !c->view) throw BridgeError("chat is not open");
        const int wanted = params.value("position").toInt();
        c->view->verticalScrollBar()->setValue(wanted < 0 ? c->view->verticalScrollBar()->maximum() : wanted);
        return aiChatState();
    }
    if (method == "qa_chat_claude_settings" && qEnvironmentVariableIsSet("LETITEDIT_QA")) // T221: the chat's own rules
        return QJsonDocument::fromJson(aiClaudeChatSettingsArgs().value(1).toUtf8()).object();
    if (method == "chat_permission_mock" && qEnvironmentVariableIsSet("LETITEDIT_QA")) {
        // Exercise the same host permission callback Claude Code uses, without a subscription or a real action.
        AiChat *c = aiChatInstance();
        if (!c) throw BridgeError("chat is not open");
        const QJsonObject request{{"type", "control_request"}, {"request_id", "qa-permission"},
                                  {"request", QJsonObject{{"subtype", "can_use_tool"},
                                      {"tool_name", params.value("tool").toString("PowerShell")},
                                      {"input", QJsonObject{{"command", params.value("command").toString("whoami")}}}}}};
        QTimer::singleShot(0, c->dock, [c, request]() { aiChatHandleLine(c, request); });
        return QJsonObject{{"queued", true}};
    }
    if (method == "qa_key") return qaKey(params);
    if (method == "qa_selection") return qaSelection(params);
    if (method == "qa_mouse") return qaMouse(params);
    if (method == "qa_python_encoding") return qaPythonEncoding();
    if (method == "hook_state") return HookPanel::state();
    if (method == "my_style_state") {
        // select (QA): choose another style in the open panel's list, as a click would (its question may come up)
        if (params.contains("select") && qEnvironmentVariableIsSet("LETITEDIT_QA"))
            MyStyle::selectInPanel(params.value("select").toString());
        return MyStyle::panelState();
    }
    if (method == "my_assets_state") return myAssetsState(params);
    if (method == "export_checks") return exportChecks(params);
    if (method == "review_state") return ReviewMode::state();
    if (method == "features_state") return LeFeatures::state();
    if (method == "jobs_state") return jobsState();
    // T368: a report built with the real cleaning, without a window; a real crash for the crash-report check
    if (method == "qa_problem_report" && qEnvironmentVariableIsSet("LETITEDIT_QA")) return ProblemReport::qaReport(params);
    if (method == "qa_crash" && qEnvironmentVariableIsSet("LETITEDIT_QA")) {
        ProblemReport::qaCrash();
        return QJsonObject{{"crashing", true}};
    }
    if (method == "qa_widget") return qaWidget(params);
    if (method == "grab_window") return grabWindow(params);
    if (params.contains("expected_revision") && params.value("expected_revision").toString()!=revision())
        throw BridgeError("Edit conflict: project changed. Refresh live_context before editing.");
    // letitedit (T366): what a listing of the open windows needs (letitedit_instances.window_row), so finding a window
    // never makes each one write out its whole project as `state` does (0.3-1.3 s on a heavy project)
    if (method == "ping")
        return QJsonObject{{"pong", true}, {"version", QApplication::applicationVersion()},
            {"instance_id",m_instanceId}, {"pid",QCoreApplication::applicationPid()},
            {"project", MAIN.fileName()}, {"modified", MAIN.isWindowModified()}};
    if (method == "state")
        return state();
    if (method == "audio_library")
        return aiAudioLibraryCommand(&MAIN, params);
    if (method == "add_music") return addMusic(params);
    if (method == "other_sizes") return otherSizes(params);
    if (method == "music_suggestions") return musicSuggestions(params);
    if (method == "list_actions")
        return listActions();
    if (method == "trigger")
        return trigger(params);
    if (method == "seek")
        return seek(params);
    if (method == "open")
        return open(params);
    if (method == "select_clip")
        return selectClip(params);
    if (method == "select_track")
        return selectTrack(params);
    if (method == "select_timeline")
        return selectTimeline();
    if (method == "select_filter")
        return selectFilter(params);
    if (method == "get_filter_params")
        return getFilterParams(params);
    if (method == "remove_filter")
        return removeFilter(params);
    if (method == "list_filters")
        return listFilters();
    if (method == "add_filter")
        return addFilter(params);
    if (method == "set_filter_params")
        return setFilterParams(params);
    if (method == "snapshot")
        return snapshot(params);
    if (method == "project_xml")
        return projectXml();
    if (method == "qa_first_edit_state") return qaFirstEditState();
    if (method == "qa_event_loop") return qaEventLoop(params);
    if (method == "qa_playback_probe") return qaPlaybackProbe(params);
    if (method == "qa_rendered_preview") {
        if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
            throw BridgeError("qa_rendered_preview is only for test windows");
        return RenderedPreview::state(params.value("reset").toBool());
    }
    if (method == "qa_playback_xml") {
        if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
            throw BridgeError("qa_playback_xml is only for test windows");
        return MLT.XML(nullptr, true);
    }
    if (method == "undo")
        return undoRedo(false);
    if (method == "redo")
        return undoRedo(true);
    if (method == "close_dialog")
        return closeDialog();
    if (method == "dialog_button")
        return dialogButton(params);
    if (method == "import_srt")
        return importSrt(params);
    if (method == "add_clip")
        return addClip(params);
    if (method == "make_short")
        return makeShort(params);
    if (method == "save")
        return save(params);
    if (method == "split_clip")
        return splitClip(params);
    if (method == "move_clip")
        return moveClip(params);
    if (method == "remove_clip")
        return removeClip(params);
    if (method == "set_track")
        return setTrack(params);
    throw BridgeError("unknown method '" + method + "'");
}

QJsonValue ClaudeBridge::loadFonts(const QJsonObject &params)
{
    // T173: a font fetched on demand while this window is open (Google Fonts, bridge/google_fonts.py): the preview
    // draws it now instead of after a restart. Only font files inside the folders this window reads fonts from
    // (LETITEDIT_FONT_DIRS, set at start) are loaded; the project is not touched.
    const QStringList dirs = qEnvironmentVariable("LETITEDIT_FONT_DIRS").split(QLatin1Char(';'), Qt::SkipEmptyParts);
    static const QStringList kinds{QStringLiteral("ttf"), QStringLiteral("otf"), QStringLiteral("ttc"), QStringLiteral("otc")};
    QJsonArray loaded, refused;
    for (const auto &value : params.value("paths").toArray()) {
        const QString path = QDir::cleanPath(QFileInfo(value.toString()).absoluteFilePath());
        bool inside = false;
        for (const auto &dir : dirs) {
            const QString root = QDir::cleanPath(QFileInfo(dir.trimmed()).absoluteFilePath()) + QLatin1Char('/');
            if (path.startsWith(root, Qt::CaseInsensitive))
                inside = true;
        }
        if (!inside || !kinds.contains(QFileInfo(path).suffix().toLower()) || !QFileInfo(path).isFile()) {
            refused.append(path);
            continue;
        }
        if (QFontDatabase::addApplicationFont(path) >= 0)
            loaded.append(path);
        else
            refused.append(path);
    }
    LOG_INFO() << "letitedit fonts: loaded" << loaded.size() << "file(s) on request," << refused.size() << "refused";
    return QJsonObject{{"loaded", loaded}, {"refused", refused}};
}

QJsonValue ClaudeBridge::qaSelection(const QJsonObject &params)
{
    // T99, test windows only: what's selected in the video, and where the player's picture is on the screen
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_selection is only for test windows (LETITEDIT_QA)");
    auto *preview = MAIN.findChild<PreviewObjects *>();
    auto *video = qobject_cast<Mlt::VideoWidget *>(MLT.videoWidget());
    if (!preview || !video)
        throw BridgeError("no player");
    if (params.contains("choose"))
        preview->choose(params.value("choose").toInt());
    if (params.value("open_choose").toBool()) // queued: the list holds its own event loop while it's open
        if (auto *button = preview->bar()->findChild<QToolButton *>(QStringLiteral("playerSelectionChoose")))
            QTimer::singleShot(0, button, &QToolButton::showMenu);
    if (params.value("clear").toBool())
        preview->clearTarget();
    if (params.contains("x")) {
        const QVariantList items = preview->itemsAt(params.value("x").toDouble(), params.value("y").toDouble());
        return QJsonObject{{"items", QJsonValue::fromVariant(items)}};
    }
    const QRectF picture = video->rect();
    const QPoint origin = video->mapToGlobal(QPoint(0, 0));
    QJsonArray targets;
    for (const QVariantMap &item : preview->targets())
        targets.append(QJsonValue::fromVariant(item));
    QJsonArray choices;
    for (const QVariant &item : preview->choices())
        choices.append(QJsonValue::fromVariant(item));
    return QJsonObject{{"target", QJsonValue::fromVariant(preview->target())}, {"targets", targets}, {"choices", choices},
                       {"chip", preview->chipText()}, {"paused", MLT.isPaused()},
                       {"filter_overlay", video->source() != QmlUtilities::blankVui()},
                       {"picture", QJsonObject{{"x", origin.x() + picture.x()}, {"y", origin.y() + picture.y()},
                                               {"w", picture.width()}, {"h", picture.height()}}}};
}

QJsonValue ClaudeBridge::qaPythonEncoding()
{
    // QA: what a Python helper started by this window gets for its pipes (the app sets UTF-8 for every helper)
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_python_encoding is only for test windows (LETITEDIT_QA)");
    QProcess child;
    child.start(aiChatSettings().value("python").toString(),
                {QStringLiteral("-c"), QStringLiteral("import sys; print(sys.stdout.encoding, sys.flags.utf8_mode)")});
    child.waitForFinished(20000);
    return QJsonObject{{"PYTHONUTF8", qEnvironmentVariable("PYTHONUTF8")},
                       {"PYTHONIOENCODING", qEnvironmentVariable("PYTHONIOENCODING")},
                       {"child", QString::fromUtf8(child.readAllStandardOutput()).trimmed()}};
}

QJsonValue ClaudeBridge::myAssetsState(const QJsonObject &params)
{
    // QA: add files to or choose an item in the open My assets panel, as a person would (the file picker itself
    // is the system's)
    if (qEnvironmentVariableIsSet("LETITEDIT_QA")) {
        if (params.contains("add")) {
            QStringList paths;
            for (const auto &p : params.value("add").toArray())
                paths << p.toString();
            MyAssets::addToPanel(paths);
        }
        if (params.contains("select"))
            MyAssets::selectInPanel(params.value("select").toString());
    }
    return MyAssets::panelState();
}

QJsonValue ClaudeBridge::exportChecks(const QJsonObject &params)
{
    // the quick look before an export, as the Share screen runs it (read only): each check's level and words
    QJsonArray checks;
    for (const auto &c : ExportChecks::run(&MAIN, params.value("even_volume").toBool(true)))
        checks.append(QJsonObject{{"level", c.level == ExportChecks::Check::Good      ? QStringLiteral("good")
                                            : c.level == ExportChecks::Check::Warning ? QStringLiteral("warning")
                                                                                      : QStringLiteral("note")},
                                  {"text", c.text},
                                  {"button", c.button}});
    return QJsonObject{{"checks", checks}};
}

QJsonValue ClaudeBridge::jobsState()
{
    // the Jobs list (convert, proxy, reverse, analysis, export...): whether each ran under the PC render lock and
    // whether it is waiting for it now (read only)
    QJsonArray jobs;
    for (auto *job : JOBS.jobs())
        jobs.append(QJsonObject{{"label", job->label()}, {"ran", job->ran()}, {"finished", job->isFinished()},
                                {"stopped", job->stopped()}, {"waiting", job->waitingForLock()},
                                {"locked", job->log().contains(QLatin1String("[render_lock]"))},
                                {"log_tail", job->log().right(400)}});
    return QJsonObject{{"jobs", jobs}};
}

QJsonValue ClaudeBridge::grabWindow(const QJsonObject &params)
{
    // Screenshot of the whole editor window (panels, dialogs docked in it), for checking the UI;
    // dialog: true pictures the open dialog instead.
    const QString path = requireString(params, "path");
    QWidget *target = &MAIN;
    // object: a window of its own by object name (reviewWindow: Review's full-screen window)
    if (!params.value("object").toString().isEmpty()) {
        for (auto *top : QApplication::topLevelWidgets())
            if (top->isVisible() && top->objectName() == params.value("object").toString())
                target = top;
        if (target == &MAIN)
            throw BridgeError("no open window named '" + params.value("object").toString() + "'");
    } else if (params.value("dialog").toBool()) {
        if (QApplication::activeModalWidget()) {
            target = QApplication::activeModalWidget();
        } else {
            // a window-like dialog that does not block the editor
            for (auto *dialog : MAIN.findChildren<QDialog *>()) {
                if (dialog->isVisible())
                    target = dialog;
            }
        }
    }
    const QPixmap shot = target->grab();
    if (shot.isNull() || !shot.save(path))
        throw BridgeError("could not save the window picture to '" + path + "'");
    return QJsonObject{{"path", path}, {"width", shot.width()}, {"height", shot.height()}};
}

QJsonValue ClaudeBridge::addMusic(const QJsonObject &params)
{
    // The Add music dialog's work with a chosen song: {song, volume 0-2, duck, replace}.
    MusicPicker::Options options;
    options.song = requireString(params, "song");
    options.volume = params.value("volume").toInt(1);
    options.duck = params.value("duck").toBool(true);
    options.replace = params.value("replace").toBool(true);
    return QJsonObject{{"result", MusicPicker::apply(&MAIN, options)}};
}

QJsonValue ClaudeBridge::otherSizes(const QJsonObject &params)
{
    // {video, shapes: ["9x16", "1x1", "4x5", "16x9"], fill} -> the files made
    QJsonArray made;
    const QStringList wanted = params.value("shapes").toVariant().toStringList();
    for (const auto &shape : OtherSizes::shapes()) {
        if (wanted.contains(shape.key))
            made.append(OtherSizes::make(requireString(params, "video"), shape, params.value("fill").toBool()));
    }
    return QJsonObject{{"made", made}};
}

QJsonValue ClaudeBridge::musicSuggestions(const QJsonObject &params)
{
    const auto songs = MusicPicker::allSongs(MusicPicker::musicFolder());
    QJsonArray picks;
    for (const auto &song : MusicPicker::suggest(songs, params.value("seconds").toDouble(60.0),
                                                 quint32(params.value("seed").toInt(1))))
        picks.append(QJsonObject{{"path", song.path}, {"title", song.title}, {"artist", song.artist},
                                 {"seconds", song.seconds}});
    return QJsonObject{{"folder", MusicPicker::musicFolder()}, {"songs", songs.size()}, {"picks", picks}};
}

QJsonValue ClaudeBridge::qaFirstEditState()
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_first_edit_state is only for test windows");
    QJsonObject state;
    for (auto quick : MAIN.timelineDock()->findChildren<QQuickWidget *>()) {
        if (!quick->rootObject())
            continue;
        for (const auto &name : {QStringLiteral("timelineTrackHeaders"), QStringLiteral("timelineTracksViewport"),
                                 QStringLiteral("timelineVerticalScrollBar")}) {
            auto item = quick->rootObject()->findChild<QQuickItem *>(name);
            if (!item)
                continue;
            const QPointF origin = quick->mapTo(&MAIN, QPoint()) + item->mapToScene(QPointF());
            state[name] = QJsonObject{{"x", origin.x()}, {"y", origin.y()},
                                      {"width", item->width()}, {"height", item->height()},
                                      {"visible", item->isVisible()},
                                      {"contentY", item->property("contentY").toDouble()},
                                      {"contentHeight", item->property("contentHeight").toDouble()}};
        }
    }
    for (auto dock : MAIN.findChildren<QDockWidget *>()) {
        if (dock->objectName() == QStringLiteral("JobsDock"))
            state["jobs"] = QJsonObject{{"floating", dock->isFloating()}, {"visible", dock->isVisible()}};
    }
    return state;
}

QJsonValue ClaudeBridge::qaEventLoop(const QJsonObject &params)
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_event_loop is only for test windows");
    struct EventLoopProbe {
        QElapsedTimer clock;
        qint64 last = 0, longest = 0;
        int ticks = 0;
        QTimer *timer = nullptr;
    };
    static EventLoopProbe probe;
    if (!probe.timer) {
        probe.timer = new QTimer(this);
        probe.timer->setTimerType(Qt::PreciseTimer);
        probe.timer->setInterval(5);
        connect(probe.timer, &QTimer::timeout, this, [this] {
            const qint64 now = probe.clock.nsecsElapsed();
            if (now - probe.last > 250000000)
                qInfo() << "AI QA event gap ms" << (now - probe.last) / 1000000.0
                        << "at ms" << now / 1000000 << "preparing" << m_preparingTransaction;
            probe.longest = qMax(probe.longest, now - probe.last);
            probe.last = now;
            ++probe.ticks;
        });
    }
    if (params.value("reset").toBool()) {
        probe.clock.start();
        probe.last = probe.longest = 0;
        probe.ticks = 0;
        probe.timer->start();
    }
    return QJsonObject{{"longest_gap_ms", probe.longest / 1000000.0}, {"ticks", probe.ticks},
                       {"preparing", m_preparingTransaction},
                       {"modal", QApplication::activeModalWidget() != nullptr}};
}

QJsonValue ClaudeBridge::qaPlaybackProbe(const QJsonObject &params)
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_playback_probe is only for test windows");
    struct PlaybackProbe {
        QElapsedTimer clock;
        int first = -1;
        int last = -1;
        int shown = 0;
        int skipped = 0;
        double speed = 1;
        QMetaObject::Connection connection;
    };
    static PlaybackProbe probe;
    if (params.contains("speed")) {
        QObject::disconnect(probe.connection);
        probe = PlaybackProbe();
        probe.speed = params.value("speed").toDouble(1);
        auto *video = qobject_cast<Mlt::VideoWidget *>(MLT.videoWidget());
        if (!video || !MLT.producer())
            throw BridgeError("no video player");
        probe.connection = QObject::connect(video, &Mlt::VideoWidget::frameDisplayed, &MAIN, [](const SharedFrame &frame) {
            const int position = frame.get_position();
            if (position == probe.last)
                return;
            if (probe.first < 0)
                probe.first = position;
            if (probe.last >= 0)
                probe.skipped += qMax(0, std::abs(position - probe.last) / qMax(1, qRound(std::abs(probe.speed))) - 1);
            probe.last = position;
            ++probe.shown;
        });
        probe.clock.start();
        if (!params.value("observe_only").toBool())
            MLT.play(probe.speed);
    }
    if (params.value("stop").toBool()) {
        MAIN.player()->pause();
        QObject::disconnect(probe.connection);
    }
    return QJsonObject{{"shown", probe.shown}, {"skipped", probe.skipped},
                       {"preview_width", MLT.previewProfile().width()},
                       {"preview_height", MLT.previewProfile().height()},
                       {"frames_moved", probe.last - probe.first}, {"speed", probe.speed},
                       {"producer_speed", MLT.producer() ? MLT.producer()->get_speed() : 0.0},
                       {"playback_speed", MAIN.player()->playbackSpeed()},
                       {"consumer_volume", MLT.consumer() ? MLT.consumer()->get_double("volume") : 0.0},
                       {"seconds", probe.clock.isValid() ? probe.clock.elapsed() / 1000.0 : 0.0}};
}

QJsonValue ClaudeBridge::state()
{
    QJsonObject result;
    result["instance"] = QJsonObject{{"id",m_instanceId},{"pid",QCoreApplication::applicationPid()},{"pipe",m_pipeName}};
    result["open_focus"] = MAIN.lastOpenFocus();
    result["revision"] = revision();
    result["project"] = MAIN.fileName();
    result["modified"] = MAIN.isWindowModified();
    result["automatic_proxy_ready"] = MAIN.property("automaticProxyReady").toInt();
    result["automatic_proxy_workers"] = MAIN.property("automaticProxyWorkers").toInt();
    result["rendered_preview"] = RenderedPreview::state();
    result["playback_quality"] = PlaybackQuality::state();
    result["look"] = MyStyle::projectStyle(&MAIN); // letitedit_ai:style, the project's style pack (or "")
    result["adjust_layers"] = true; // apply_transaction's add_tracks takes above: <track>
    result["caption_styles"] = true; // apply_transaction's caption_styles sets how a caption track is drawn
    result["isMultitrack"] = MLT.isMultitrack();

    auto &profile = MLT.profile();
    result["profile"] = QJsonObject{{"width", profile.width()},
                                    {"height", profile.height()},
                                    {"fps", profile.fps()}};

    if (Mlt::Producer *producer = MLT.producer()) {
        result["player"] = QJsonObject{{"position", producer->position()},
                                       {"length", producer->get_length()}};
    }
    // Where the player's widget is in the window, in device pixels (the check for the live scene layer compares it with the native window's).
    if (auto *videoWidget = qobject_cast<QWidget *>(MLT.videoWidget())) {
        const qreal scale = videoWidget->devicePixelRatioF();
        const QPoint at = videoWidget->mapTo(videoWidget->window(), QPoint(0, 0));
        result["video_widget"] = QJsonObject{{"x", qRound(at.x() * scale)},
                                             {"y", qRound(at.y() * scale)},
                                             {"width", qRound(videoWidget->width() * scale)},
                                             {"height", qRound(videoWidget->height() * scale)},
                                             {"visible", videoWidget->isVisible()}};
    }

    TimelineDock *timeline = MAIN.timelineDock();
    QJsonArray selection;
    for (const QPoint &point : timeline->selection())
        selection.append(QJsonObject{{"track", point.y()}, {"clip", point.x()}});
    QJsonObject timelineJson{{"position", timeline->position()},
                             {"currentTrack", timeline->currentTrack()},
                             {"selection", selection}};

    MultitrackModel *model = timeline->model();
    QJsonArray tracks;
    for (int t = 0; t < model->rowCount(); ++t) {
        const QModelIndex trackIndex = model->index(t, 0);
        QJsonArray clips;
        for (int c = 0; c < model->rowCount(trackIndex); ++c) {
            const QModelIndex clipIndex = model->index(c, 0, trackIndex);
            clips.append(QJsonObject{
                {"index", c},
                {"name", clipIndex.data(MultitrackModel::NameRole).toString()},
                {"resource", clipIndex.data(MultitrackModel::ResourceRole).toString()},
                {"start", clipIndex.data(MultitrackModel::StartRole).toInt()},
                {"duration", clipIndex.data(MultitrackModel::DurationRole).toInt()},
                {"in", clipIndex.data(MultitrackModel::InPointRole).toInt()},
                {"out", clipIndex.data(MultitrackModel::OutPointRole).toInt()},
                {"blank", clipIndex.data(MultitrackModel::IsBlankRole).toBool()},
            });
        }
        tracks.append(QJsonObject{
            {"index", t},
            {"name", trackIndex.data(MultitrackModel::NameRole).toString()},
            {"audio", trackIndex.data(MultitrackModel::IsAudioRole).toBool()},
            {"mute", trackIndex.data(MultitrackModel::IsMuteRole).toBool()},
            {"hidden", trackIndex.data(MultitrackModel::IsHiddenRole).toBool()},
            {"locked", timeline->isTrackLocked(t)},
            {"clips", clips},
        });
    }
    timelineJson["tracks"] = tracks;
    result["timeline"] = timelineJson;

    QJsonArray subtitleTracks;
    SubtitlesModel *subtitles = timeline->subtitlesModel();
    for (int i = 0; i < subtitles->trackCount(); ++i) {
        const auto track = subtitles->getTrack(i);
        subtitleTracks.append(QJsonObject{{"index", i},
                                          {"name", track.name},
                                          {"lang", track.lang},
                                          {"items", subtitles->itemCount(i)}});
    }
    result["subtitleTracks"] = subtitleTracks;

    FilterController *filters = MAIN.filterController();
    AttachedFiltersModel *attached = filters->attachedModel();
    QJsonArray attachedJson;
    for (int i = 0; i < attached->rowCount(); ++i) {
        QmlMetadata *meta = attached->getMetadata(i);
        attachedJson.append(meta ? metadataToJson(meta)
                                 : QJsonObject{{"id", QJsonValue::Null}, {"name", "(unknown)"}});
    }
    result["filters"] = QJsonObject{{"attached", attachedJson},
                                    {"currentIndex", filters->currentIndex()}};

    QJsonArray docks;
    for (auto *dock : MAIN.findChildren<QDockWidget *>()) {
        if (dock->isVisible())
            docks.append(dock->windowTitle());
    }
    result["visibleDocks"] = docks;

    if (QWidget *modal = QApplication::activeModalWidget()) {
        result["modalDialog"] = modal->windowTitle();
        result["dialog"] = describeDialog(modal);
    } else {
        result["modalDialog"] = QJsonValue::Null;
        result["dialog"] = QJsonValue::Null;
    }

    QJsonArray windows;
    for (QWidget *widget : QApplication::topLevelWidgets()) {
        if (widget != &MAIN && widget->isVisible() && widget->isWindow()
            && !qobject_cast<QDockWidget *>(widget) && !widget->windowTitle().isEmpty())
            windows.append(widget->windowTitle());
    }
    result["otherWindows"] = windows;
    return result;
}

QJsonValue ClaudeBridge::closeDialog()
{
    // an open menu first (the innermost popup closes first)
    if (QApplication::activePopupWidget()) {
        for (int i = 0; i < 10 && QApplication::activePopupWidget(); ++i)
            QApplication::activePopupWidget()->close();
        return QJsonObject{{"closed", "menu"}};
    }
    QWidget *widget = QApplication::activeModalWidget();
    if (!widget) {
        for (QWidget *candidate : QApplication::topLevelWidgets()) {
            if (candidate != &MAIN && candidate->isVisible() && qobject_cast<QDialog *>(candidate)) {
                widget = candidate;
                break;
            }
        }
    }
    if (!widget)
        throw BridgeError("no dialog is open");
    const QString title = widget->windowTitle();
    // Queued so a nested dialog event loop unwinds after this reply is sent.
    QMetaObject::invokeMethod(
        widget,
        [widget]() {
            if (auto *dialog = qobject_cast<QDialog *>(widget))
                dialog->reject();
            else
                widget->close();
        },
        Qt::QueuedConnection);
    return QJsonObject{{"closed", title}};
}

QJsonValue ClaudeBridge::listActions()
{
    QJsonArray result;
    QSet<QAction *> seen;
    for (const QString &name : Actions.keys()) {
        QAction *action = Actions[name];
        if (!action)
            continue;
        seen.insert(action);
        result.append(actionToJson(name, action));
    }
    for (auto *action : MAIN.findChildren<QAction *>()) {
        if (seen.contains(action) || !action->objectName().startsWith("action"))
            continue;
        seen.insert(action);
        result.append(actionToJson(action->objectName(), action));
    }
    return result;
}

QJsonValue ClaudeBridge::trigger(const QJsonObject &params)
{
    const QString name = requireString(params, "name");
    QAction *action = findAction(name);
    if (!action)
        throw BridgeError("no action named '" + name + "'");
    if (!action->isEnabled())
        throw BridgeError("action '" + name + "' is disabled");
    // Queued so that actions which open modal dialogs do not block the bridge.
    QMetaObject::invokeMethod(action, &QAction::trigger, Qt::QueuedConnection);
    return QJsonObject{{"triggered", name}};
}

QJsonValue ClaudeBridge::seek(const QJsonObject &params)
{
    int frame;
    if (params.value("frame").isDouble())
        frame = params.value("frame").toInt();
    else if (params.value("seconds").isDouble())
        frame = qRound(params.value("seconds").toDouble() * MLT.profile().fps());
    else
        throw BridgeError("seek needs 'frame' or 'seconds'");
    if (MLT.isMultitrack())
        MAIN.seekTimeline(frame);
    else
        MLT.seek(frame);
    return QJsonObject{{"frame", frame}};
}

QJsonValue ClaudeBridge::open(const QJsonObject &params)
{
    const QString path = requireString(params, "path");
    QMetaObject::invokeMethod(
        &MAIN, [path]() { MAIN.openWithoutFocus(path); }, Qt::QueuedConnection);
    return QJsonObject{{"opening", path}};
}

QJsonValue ClaudeBridge::selectClip(const QJsonObject &params)
{
    const int track = requireInt(params, "track");
    const int clip = requireInt(params, "clip");
    TimelineDock *timeline = MAIN.timelineDock();
    MultitrackModel *model = timeline->model();
    if (track < 0 || track >= model->rowCount())
        throw BridgeError(QStringLiteral("track %1 out of range").arg(track));
    if (clip < 0 || clip >= model->rowCount(model->index(track, 0)))
        throw BridgeError(QStringLiteral("clip %1 out of range on track %2").arg(clip).arg(track));
    timeline->setSelection({QPoint(clip, track)});
    // The filter panel follows the selection after TimelineDock's 100 ms signal timer.
    return QJsonObject{{"track", track}, {"clip", clip}};
}

QJsonValue ClaudeBridge::selectTrack(const QJsonObject &params)
{
    const int track = requireInt(params, "track");
    TimelineDock *timeline = MAIN.timelineDock();
    if (track < 0 || track >= timeline->model()->rowCount())
        throw BridgeError(QStringLiteral("track %1 out of range").arg(track));
    timeline->selectTrackHead(track);
    return QJsonObject{{"track", track}};
}

QJsonValue ClaudeBridge::selectTimeline()
{
    if (!MLT.isMultitrack())
        throw BridgeError("no timeline is open");
    MAIN.timelineDock()->selectMultitrack();
    return QJsonObject{{"selected", "timeline output"}};
}

QJsonValue ClaudeBridge::selectFilter(const QJsonObject &params)
{
    const int index = requireInt(params, "index");
    FilterController *filters = MAIN.filterController();
    if (index < 0 || index >= filters->attachedModel()->rowCount())
        throw BridgeError(QStringLiteral("filter index %1 out of range").arg(index));
    filters->setCurrentFilter(index);
    QmlMetadata *meta = filters->attachedModel()->getMetadata(index);
    return QJsonObject{{"index", index},
                       {"filter", meta ? metadataToJson(meta) : QJsonObject()}};
}

QJsonValue ClaudeBridge::getFilterParams(const QJsonObject &params)
{
    QmlFilter *filter = MAIN.filterController()->currentFilter();
    if (!filter)
        throw BridgeError("no current filter (select a clip and a filter first)");
    const QJsonArray names = params.value("names").toArray();
    if (names.isEmpty())
        throw BridgeError("missing array param 'names'");
    QJsonObject values;
    for (const QJsonValue &name : names)
        values[name.toString()] = filter->get(name.toString());
    return values;
}

QJsonValue ClaudeBridge::removeFilter(const QJsonObject &params)
{
    const int index = requireInt(params, "index");
    AttachedFiltersModel *attached = MAIN.filterController()->attachedModel();
    if (index < 0 || index >= attached->rowCount())
        throw BridgeError(QStringLiteral("filter index %1 out of range").arg(index));
    QmlMetadata *meta = attached->getMetadata(index);
    attached->remove(index);
    return QJsonObject{{"removed", meta ? meta->name() : QString()}};
}

namespace BridgeHelpers {

MultitrackModel *checkedTrack(int track)
{
    if (!MLT.isMultitrack())
        throw BridgeError("no timeline is open");
    MultitrackModel *model = MAIN.timelineDock()->model();
    if (track < 0 || track >= model->rowCount())
        throw BridgeError(QStringLiteral("track %1 out of range").arg(track));
    return model;
}

void checkClip(MultitrackModel *model, int track, int clip)
{
    if (clip < 0 || clip >= model->rowCount(model->index(track, 0)))
        throw BridgeError(QStringLiteral("clip %1 out of range on track %2").arg(clip).arg(track));
}

int trackEnd(MultitrackModel *model, int track)
{
    // End of the last real clip; trailing blanks (Shotcut keeps a 1-frame blank on empty
    // tracks) do not count, so appending to an empty track starts at frame 0.
    const QModelIndex trackIndex = model->index(track, 0);
    for (int i = model->rowCount(trackIndex) - 1; i >= 0; --i) {
        const QModelIndex clip = model->index(i, 0, trackIndex);
        if (!clip.data(MultitrackModel::IsBlankRole).toBool())
            return clip.data(MultitrackModel::StartRole).toInt()
                   + clip.data(MultitrackModel::DurationRole).toInt();
    }
    return 0;
}

} // namespace BridgeHelpers

QJsonValue ClaudeBridge::importSrt(const QJsonObject &params)
{
    if (!MLT.isMultitrack())
        throw BridgeError("no timeline is open");
    const QString trackName = params.value("track_name").toString("Subtitles");
    const QString lang = params.value("lang").toString("eng");
    Subtitles::SubtitleVector parsed;
    if (params.contains("srt"))
        parsed = Subtitles::readFromSrtString(params.value("srt").toString().toStdString());
    else
        parsed = Subtitles::readFromSrtFile(requireString(params, "path").toStdString());
    if (parsed.empty())
        throw BridgeError("no subtitle items parsed (expects SRT: index, 'HH:MM:SS,mmm --> ...', text)");
    QList<Subtitles::SubtitleItem> items(parsed.begin(), parsed.end());

    SubtitlesModel *model = MAIN.timelineDock()->subtitlesModel();
    const int existing = model->getTrackIndex(trackName);
    if (existing >= 0) {
        model->importSubtitles(existing, 0, items); // overwrites overlapping items
    } else {
        SubtitlesModel::SubtitleTrack track{trackName, lang};
        model->importSubtitlesToNewTrack(track, items);
    }
    return QJsonObject{{"track_name", trackName},
                       {"items", int(items.size())},
                       {"new_track", existing < 0}};
}

QJsonValue ClaudeBridge::dialogButton(const QJsonObject &params)
{
    const QString text = requireString(params, "button");
    QWidget *dialog = QApplication::activeModalWidget();
    if (!dialog)
        throw BridgeError("no modal dialog is open");
    QAbstractButton *match = nullptr;
    QStringList available;
    for (auto *button : dialog->findChildren<QAbstractButton *>()) {
        if (!button->isVisible() || !button->isEnabled())
            continue;
        const QString label = plainButtonText(button);
        available << label;
        if (!match && label.compare(text, Qt::CaseInsensitive) == 0)
            match = button;
    }
    if (!match)
        throw BridgeError("no button '" + text + "'; available: " + available.join(", "));
    // Queued so the dialog's nested event loop unwinds after this reply is sent.
    QMetaObject::invokeMethod(match, &QAbstractButton::click, Qt::QueuedConnection);
    return QJsonObject{{"clicked", plainButtonText(match)}, {"dialog", dialog->windowTitle()}};
}

QJsonValue ClaudeBridge::addClip(const QJsonObject &params)
{
    const QString path = requireString(params, "path");
    const int track = requireInt(params, "track");
    MultitrackModel *model = checkedTrack(track);
    const QString mode = params.value("mode").toString("append");
    if (mode != "append" && mode != "insert" && mode != "overwrite")
        throw BridgeError("mode must be append, insert or overwrite");
    if (!QFileInfo::exists(path))
        throw BridgeError("file not found: " + path);

    Mlt::Producer raw(MLT.profile(), path.toUtf8().constData());
    if (!raw.is_valid())
        throw BridgeError("letitedit can't open " + path);
    // Configure it exactly like a drag-and-drop from Explorer: video in an Mlt::Chain (so timing
    // effects such as Speed/Time Remap can be added), default image duration, creation time.
    QScopedPointer<Mlt::Producer> configured(MLT.setupNewProducer(&raw));
    Mlt::Producer &producer = *configured;
    producer.set("shotcut:caption", QFileInfo(path).fileName().toUtf8().constData());
    const int length = producer.get_length();
    const int in = params.value("in").toInt(0);
    const int out = params.value("out").toInt(length - 1);
    if (in < 0 || out < in || out >= length)
        throw BridgeError(QStringLiteral("in/out %1-%2 outside the media (0-%3 frames)")
                              .arg(in)
                              .arg(out)
                              .arg(length - 1));
    producer.set_in_and_out(in, out);

    int position = trackEnd(model, track);
    if (mode != "append")
        position = params.value("position").toInt(MAIN.timelineDock()->position());
    const QString xml = MLT.XML(&producer);
    if (mode == "insert")
        MAIN.timelineDock()->insert(track, position, xml, false);
    else
        MAIN.timelineDock()->overwrite(track, position, xml, false);
    return QJsonObject{{"track", track},
                       {"position", position},
                       {"in", in},
                       {"out", out},
                       {"duration", out - in + 1},
                       {"mode", mode}};
}

QJsonValue ClaudeBridge::makeShort(const QJsonObject &params)
{
    // The same path as File > Make a Vertical Short: a new 9:16 project with the clips in order,
    // each filling the frame through an editable Crop: Source filter.
    QStringList paths;
    for (const auto &value : params.value("paths").toArray())
        paths << value.toString();
    if (paths.isEmpty())
        throw BridgeError("paths: a list of video or picture files, in order");
    for (const auto &path : paths) {
        if (!QFileInfo::exists(path))
            throw BridgeError("file not found: " + path);
    }
    if (MAIN.isWindowModified()) {
        if (!params.value("discard_unsaved").toBool())
            throw BridgeError("the open project has unsaved changes; save it first, or pass discard_unsaved: true");
        MAIN.setWindowModified(false);
    }
    MAIN.makeShort(paths);
    auto &profile = MLT.profile();
    return QJsonObject{{"profile",
                        QJsonObject{{"width", profile.width()},
                                    {"height", profile.height()},
                                    {"fps", profile.fps()}}},
                       {"clips", paths.size()}};
}

QJsonValue ClaudeBridge::save(const QJsonObject &params)
{
    QString path = params.value("path").toString();
    if (path.isEmpty())
        path = MAIN.fileName();
    if (path.isEmpty())
        throw BridgeError("project has never been saved; pass 'path' (a .mlt file)");
    if (!path.endsWith(".mlt", Qt::CaseInsensitive))
        path += ".mlt";
    // What File > Save As does after its dialog, without its error box (T329): the caller gets the reason
    QString why;
    if (!MAIN.newProject(path, false, true, &why))
        throw BridgeError("save failed for " + path + ": " + (why.isEmpty() ? QStringLiteral("unknown reason") : why));
    if (MAIN.isWindowModified())
        throw BridgeError("save failed for " + path);
    return QJsonObject{{"saved", path}};
}

QJsonValue ClaudeBridge::splitClip(const QJsonObject &params)
{
    const int track = requireInt(params, "track");
    const int clip = requireInt(params, "clip");
    const int position = requireInt(params, "position");
    MultitrackModel *model = checkedTrack(track);
    checkClip(model, track, clip);
    const QModelIndex index = model->index(clip, 0, model->index(track, 0));
    const int start = index.data(MultitrackModel::StartRole).toInt();
    const int duration = index.data(MultitrackModel::DurationRole).toInt();
    if (position <= start || position >= start + duration)
        throw BridgeError(QStringLiteral("position %1 is not inside clip %2 (frames %3-%4)")
                              .arg(position)
                              .arg(clip)
                              .arg(start)
                              .arg(start + duration - 1));
    if (!MAIN.timelineDock()->split(track, clip, position))
        throw BridgeError("split failed");
    return QJsonObject{{"track", track}, {"clip", clip}, {"position", position}};
}

QJsonValue ClaudeBridge::moveClip(const QJsonObject &params)
{
    const int track = requireInt(params, "track");
    const int clip = requireInt(params, "clip");
    const int toTrack = params.value("to_track").toInt(track);
    const int position = requireInt(params, "position");
    MultitrackModel *model = checkedTrack(track);
    checkClip(model, track, clip);
    checkedTrack(toTrack);
    // TimelineDock moves the *selected* clips, so select exactly this one first.
    MAIN.timelineDock()->setSelection({QPoint(clip, track)});
    if (!MAIN.timelineDock()->moveClip(track, toTrack, clip, position,
                                       params.value("ripple").toBool(false)))
        throw BridgeError("move refused (overlap, locked track, or incompatible track type)");
    return QJsonObject{{"to_track", toTrack}, {"position", position}};
}

QJsonValue ClaudeBridge::removeClip(const QJsonObject &params)
{
    const int track = requireInt(params, "track");
    const int clip = requireInt(params, "clip");
    MultitrackModel *model = checkedTrack(track);
    checkClip(model, track, clip);
    const bool ripple = params.value("ripple").toBool(true);
    if (ripple)
        MAIN.timelineDock()->remove(track, clip);
    else
        MAIN.timelineDock()->lift(track, clip);
    return QJsonObject{{"removed", clip}, {"track", track}, {"ripple", ripple}};
}

QJsonValue ClaudeBridge::setTrack(const QJsonObject &params)
{
    const int track = requireInt(params, "track");
    MultitrackModel *model = checkedTrack(track);
    TimelineDock *timeline = MAIN.timelineDock();
    const QModelIndex index = model->index(track, 0);
    // the volume and ducking are effects on the track: a locked track keeps them (checked before anything changes)
    if ((params.contains("gain_db") || params.contains("ducking")) && timeline->isTrackLocked(track))
        throw BridgeError("Track " + index.data(MultitrackModel::NameRole).toString()
                          + " is locked, so its volume and ducking can't change. Unlock it first; no changes made");
    if (params.contains("name"))
        timeline->setTrackName(track, params.value("name").toString());
    if (params.contains("mute")
        && params.value("mute").toBool() != index.data(MultitrackModel::IsMuteRole).toBool())
        timeline->toggleTrackMute(track);
    if (params.contains("hidden")
        && params.value("hidden").toBool() != index.data(MultitrackModel::IsHiddenRole).toBool())
        timeline->toggleTrackHidden(track);
    if (params.contains("gain_db") && !timeline->setTrackGain(track, params.value("gain_db").toDouble()))
        throw BridgeError("could not set track gain");
    if (params.contains("ducking")) {
        // Same undoable command as Track Properties > "Audio ducking": this track is turned
        // down while the tracks above it are louder than the threshold (dB).
        const bool enabled = params.value("ducking").toBool();
        const double threshold = params.value("duck_threshold_db").toDouble(-12.0);
        const int mltIndex = model->trackList().at(track).mlt_index;
        MAIN.undoStack()->push(new Timeline::ChangeDuckThresholdCommand(
            mltIndex,
            threshold,
            enabled,
            enabled ? QObject::tr("Enable Track Audio Ducking")
                    : QObject::tr("Disable Track Audio Ducking"),
            true));
    }
    return QJsonObject{{"track", track}};
}

QJsonValue ClaudeBridge::listFilters()
{
    MetadataModel *model = MAIN.filterController()->metadataModel();
    QJsonArray result;
    for (int i = 0; i < model->sourceRowCount(); ++i) {
        QmlMetadata *meta = model->getFromSource(i);
        if (meta && !meta->isHidden())
            result.append(metadataToJson(meta));
    }
    return result;
}

QJsonValue ClaudeBridge::addFilter(const QJsonObject &params)
{
    const QString id = requireString(params, "id");
    FilterController *filters = MAIN.filterController();
    QmlMetadata *meta = filters->metadata(id);
    if (!meta)
        throw BridgeError("no filter with id '" + id + "'");
    const int row = filters->attachedModel()->add(meta);
    if (row < 0)
        throw BridgeError("could not add '" + id
                          + "' (nothing selected, or not allowed on this target)");
    filters->setCurrentFilter(row);

    // Filter UIs write their defaults when they load, so apply requested values afterwards.
    const QJsonObject properties = params.value("properties").toObject();
    if (!properties.isEmpty()) {
        QTimer::singleShot(500, this, [properties]() {
            if (QmlFilter *filter = MAIN.filterController()->currentFilter()) {
                for (auto it = properties.begin(); it != properties.end(); ++it)
                    filter->set(it.key(), jsonToPropertyString(it.value()));
            }
        });
    }
    return QJsonObject{{"row", row}, {"filter", metadataToJson(meta)}};
}

QJsonValue ClaudeBridge::setFilterParams(const QJsonObject &params)
{
    QmlFilter *filter = MAIN.filterController()->currentFilter();
    if (!filter)
        throw BridgeError("no current filter (select a clip and a filter first)");
    const QJsonObject properties = params.value("properties").toObject();
    if (properties.isEmpty())
        throw BridgeError("missing object param 'properties'");
    QJsonObject applied;
    for (auto it = properties.begin(); it != properties.end(); ++it) {
        filter->set(it.key(), jsonToPropertyString(it.value()));
        applied[it.key()] = filter->get(it.key());
    }
    return applied;
}

QJsonValue ClaudeBridge::snapshot(const QJsonObject &params)
{
    const QString path = requireString(params, "path");
    Mlt::Producer *producer = MLT.producer();
    if (!producer || !producer->is_valid())
        throw BridgeError("nothing is loaded in the player");
    const int width = params.value("width").toInt(540);
    const int height = qRound(width * double(MLT.profile().height()) / MLT.profile().width());
    const int frame = params.value("frame").isDouble() ? params.value("frame").toInt()
                                                       : producer->position();
    Mlt::Producer original(MLT.profile(), "xml-string", ProxyManager::originalXML().toUtf8().constData());
    const QImage image = MLT.image(original, frame, width, height);
    if (image.isNull() || !image.save(path))
        throw BridgeError("failed to render or save frame to '" + path + "'");
    return QJsonObject{{"path", path}, {"frame", frame}, {"width", width}, {"height", height}};
}

QJsonValue ClaudeBridge::projectXml()
{
    MAIN.timelineDock()->subtitlesModel()->flushFeedCommit(); // the AI reads the captions as they are now
    Mlt::Tractor *tractor = MAIN.timelineDock()->model()->tractor();
    if (tractor)
        return ProxyManager::originalXML(tractor);
    if (Mlt::Producer *producer = MLT.producer())
        return ProxyManager::originalXML(producer);
    throw BridgeError("no project loaded");
}

QJsonValue ClaudeBridge::undoRedo(bool redo)
{
    QUndoStack *stack = MAIN.undoStack();
    const QString text = redo ? stack->redoText() : stack->undoText();
    if (redo ? !stack->canRedo() : !stack->canUndo())
        throw BridgeError(redo ? "nothing to redo" : "nothing to undo");
    redo ? stack->redo() : stack->undo();
    return QJsonObject{{redo ? "redid" : "undid", text}};
}

// The project as an edit, for the revision: element by element, attributes and properties sorted, ids numbered in
// order of appearance, and the properties that aren't edits left out (T221). Playing the video writes facts and
// measurements into the project: the decoders' meta.* (filled in as media is first read), the Loudness filter's
// read-only in_loudness, out_gain and reset_count, and LADSPA/LV2 output ports ("3[0]": a limiter's gain reduction).
// A playback copy swapped in or out re-creates every clip: new ids, its length written as a time instead of frames,
// properties in another order, and the decoder's creation_time and the "xml" marker. Counted, any edit made while
// the video played or a copy went in was refused as a clash.
static QByteArray revisionText(const QString &xml)
{
    static const QRegularExpression notEdit(
        QStringLiteral(R"RX(^(?:meta\..*|in_loudness|out_gain|reset_count|\d+\[\d+\]|creation_time|xml)$)RX"));
    struct Element {
        QByteArray head, body;
        QList<QPair<QString, QString>> properties;
        QString tag;
    };
    QHash<QString, QString> ids;
    const auto id = [&ids](const QString &value) {
        auto it = ids.find(value);
        if (it == ids.end())
            it = ids.insert(value, QStringLiteral("#%1").arg(ids.size()));
        return it.value();
    };
    QByteArray out;
    QList<Element> stack;
    QXmlStreamReader reader(xml);
    while (!reader.atEnd()) {
        const auto token = reader.readNext();
        if (token == QXmlStreamReader::StartElement && reader.name() == QLatin1String("property")) {
            const QString name = reader.attributes().value(QLatin1String("name")).toString();
            const QString value = reader.readElementText(QXmlStreamReader::IncludeChildElements);
            const bool clipLength = name == QLatin1String("length") && !stack.isEmpty()
                                    && (stack.last().tag == QLatin1String("chain")
                                        || stack.last().tag == QLatin1String("producer"));
            if (!stack.isEmpty() && !clipLength && !notEdit.match(name).hasMatch())
                stack.last().properties.append({name, value});
        } else if (token == QXmlStreamReader::StartElement) {
            Element e;
            e.tag = reader.name().toString();
            QList<QPair<QString, QString>> attributes;
            for (const auto &a : reader.attributes()) {
                const QString key = a.qualifiedName().toString();
                attributes.append({key, key == QLatin1String("id") || key == QLatin1String("producer")
                                            ? id(a.value().toString())
                                            : a.value().toString()});
            }
            std::sort(attributes.begin(), attributes.end());
            e.head = QByteArray("<") + e.tag.toUtf8();
            for (const auto &a : std::as_const(attributes))
                e.head += QByteArray(" ") + a.first.toUtf8() + QByteArray("=\"") + a.second.toUtf8() + QByteArray("\"");
            e.head += QByteArray(">\n");
            stack.append(e);
        } else if (token == QXmlStreamReader::EndElement && !stack.isEmpty()) {
            Element e = stack.takeLast();
            std::sort(e.properties.begin(), e.properties.end());
            QByteArray text = e.head;
            for (const auto &p : std::as_const(e.properties))
                text += p.first.toUtf8() + QByteArray("=") + p.second.toUtf8() + QByteArray("\n");
            text += e.body + QByteArray("</") + e.tag.toUtf8() + QByteArray(">\n");
            (stack.isEmpty() ? out : stack.last().body) += text;
        }
    }
    if (reader.hasError()) // never seen; the plain text still tells edits apart
        return xml.toUtf8();
    return out;
}

static QByteArray subtitleRevisionText()
{
    QByteArray bytes;
    auto *sub = MAIN.timelineDock()->subtitlesModel();
    for (int track = 0; track < sub->trackCount(); ++track)
        for (int index = 0; index < sub->itemCount(track); ++index) {
            const auto &cue = sub->getItem(track, index);
            bytes += QByteArray::number(cue.start) + ":" + QByteArray::number(cue.end) + ":"
                     + QByteArray::fromStdString(cue.text) + "\n";
        }
    return bytes;
}

QFuture<QString> ClaudeBridge::revisionAsync()
{
    const QString xml = projectXml().toString();
    const QByteArray captions = subtitleRevisionText();
    return QtConcurrent::run([xml, captions] {
        const QByteArray text = QCryptographicHash::hash(revisionText(xml), QCryptographicHash::Sha256);
        return QString::fromLatin1(QCryptographicHash::hash(text + captions, QCryptographicHash::Sha256).toHex());
    });
}

QString ClaudeBridge::revision()
{
    if(!MLT.producer())return QStringLiteral("empty");
    // Only edits change the revision (revisionText says what isn't one). The project's text is read for every call;
    // the sorting is done again only when that text changed (on Rat it adds about 100 ms).
    const QString xml=projectXml().toString();
    static QByteArray lastXml;
    static QByteArray lastText;
    const QByteArray xmlHash=QCryptographicHash::hash(xml.toUtf8(),QCryptographicHash::Sha256);
    if(xmlHash!=lastXml){
        lastText=QCryptographicHash::hash(revisionText(xml),QCryptographicHash::Sha256);
        lastXml=xmlHash;
    }
    QByteArray bytes=lastText;
    bytes += subtitleRevisionText();
    return QString::fromLatin1(QCryptographicHash::hash(bytes,QCryptographicHash::Sha256).toHex());
}

QJsonValue ClaudeBridge::liveContext()
{
    auto result=state().toObject();
    auto *timeline=MAIN.timelineDock(); auto *sub=timeline->subtitlesModel();
    auto *selection=timeline->subtitlesSelectionModel();
    QJsonArray tracks;
    for(int t=0;t<sub->trackCount();++t){
        QJsonArray cues;
        for(int i=0;i<sub->itemCount(t);++i){
            const auto &c=sub->getItem(t,i);
            cues.append(QJsonObject{{"row",i},{"start_ms",double(c.start)},{"end_ms",double(c.end)},
                {"text",QString::fromStdString(c.text)}, {"selected",selection->selectedTrack()==t && selection->isItemSelected(i)}});
        }
        tracks.append(QJsonObject{{"index",t},{"name",sub->getTrack(t).name},{"cues",cues}});
    }
    result["subtitles"]=tracks;
    result["selectedSubtitleTrack"]=selection->selectedTrack();
    result["selectedSubtitleRows"]=QJsonArray::fromVariantList(selection->selectedItems());
    auto *focus=QApplication::focusWidget();
    result["focus"]=focus?QJsonObject{{"class",focus->metaObject()->className()},{"name",focus->objectName()}}:QJsonObject{};
    auto *stack=MAIN.undoStack(); QJsonArray history;
    const int first=qMax(0,stack->index()-10),last=qMin(stack->count(),first+10);
    for(int i=first;i<last;++i) history.append(QJsonObject{{"index",i},{"label",stack->command(i)->text()},
        {"applied",i<stack->index()},{"childCommands",stack->command(i)->childCount()},{"origin","unknown"}});
    result["history"]=QJsonObject{{"cursor",stack->index()},{"total",stack->count()},
        {"entries",history},{"truncated",first>0 || last<stack->count()},{"canUndo",stack->canUndo()},{"canRedo",stack->canRedo()}};
    int start=-1,end=-1; if(!timeline->selection().isEmpty())timeline->getSelectionRange(&start,&end);
    result["selectedRange"]=QJsonObject{{"start_frame",start},{"end_frame_inclusive",end}};
    result["ripple"]=QJsonObject{{"all_tracks",Settings.timelineRippleAllTracks()},{"markers",Settings.timelineRippleMarkers()}};
    return result;
}

// What the person is looking at right now (C6): player tab, playhead, the source clip's in/out marks, the selected
// timeline items with their AI ids, markers, the undo step on top. Read-only; positions are frames.
QJsonValue ClaudeBridge::editorState(const QJsonObject &params)
{
    Q_UNUSED(params)
    QJsonObject result;
    const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
    result["fps"] = fps;
    result["project"] = MAIN.fileName();
    result["modified"] = MAIN.isWindowModified();
    Player *player = MAIN.player();
    const bool sourceTab = player && player->tabIndex() == Player::SourceTabIndex;
    result["player_tab"] = sourceTab ? QStringLiteral("source") : QStringLiteral("timeline");
    result["player_position"] = player ? player->position() : -1;
    Mlt::Producer *producer = MLT.producer();
    result["playing"] = producer && producer->is_valid() && producer->get_speed() != 0.0;
    TimelineDock *timeline = MAIN.timelineDock();
    MultitrackModel *model = timeline->model();
    result["timeline_open"] = model->tractor() != nullptr;
    result["timeline_position"] = timeline->position();
    result["current_track"] = timeline->currentTrack();
    if (Mlt::Tractor *tractor = model->tractor())
        result["timeline_length"] = tractor->get_playtime();
    // The clip in the player when it is a single clip (the Source tab): its in/out marks.
    if (producer && producer->is_valid() && MLT.isClip()) {
        result["source"] = QJsonObject{
            {"resource", QString::fromUtf8(producer->get("resource"))},
            {"caption", QString::fromUtf8(producer->get("shotcut:caption"))},
            {"position", producer->position()},
            {"in", producer->get_in()},
            {"out", producer->get_out()},
            {"length", producer->get_length()},
        };
    } else {
        result["source"] = QJsonValue::Null;
    }
    QJsonArray selection;
    for (const QPoint &p : timeline->selection()) {
        QJsonObject item{{"track", p.y()}, {"clip", p.x()}};
        if (p.y() >= 0 && p.y() < model->rowCount()) {
            const QModelIndex trackIndex = model->index(p.y(), 0);
            item["track_name"] = trackIndex.data(MultitrackModel::NameRole).toString();
            if (p.x() >= 0 && p.x() < model->rowCount(trackIndex)) {
                const QModelIndex clipIndex = model->index(p.x(), 0, trackIndex);
                item["blank"] = clipIndex.data(MultitrackModel::IsBlankRole).toBool();
                item["transition"] = clipIndex.data(MultitrackModel::IsTransitionRole).toBool();
                item["start"] = clipIndex.data(MultitrackModel::StartRole).toInt();
                item["duration"] = clipIndex.data(MultitrackModel::DurationRole).toInt();
                item["in"] = clipIndex.data(MultitrackModel::InPointRole).toInt();
                item["out"] = clipIndex.data(MultitrackModel::OutPointRole).toInt();
                item["resource"] = clipIndex.data(MultitrackModel::ResourceRole).toString();
                if (auto info = model->getClipInfo(p.y(), p.x())) {
                    if (info->producer && info->producer->is_valid()) {
                        Mlt::Producer parent(info->producer->parent());
                        item["ai_id"] = QString::fromUtf8(parent.get("letitedit_ai:id"));
                        item["caption"] = QString::fromUtf8(parent.get("shotcut:caption"));
                    }
                }
            }
        }
        selection.append(item);
    }
    result["selection"] = selection;
    int start = -1, end = -1;
    if (!timeline->selection().isEmpty())
        timeline->getSelectionRange(&start, &end);
    result["selected_range"] = QJsonObject{{"start_frame", start}, {"end_frame", end}};
    QJsonArray markers;
    const auto list = timeline->markersModel()->getMarkers();
    for (const auto &m : list)
        markers.append(QJsonObject{{"text", m.text}, {"start", m.start}, {"end", m.end}, {"color", m.color.name()}});
    result["markers"] = markers;
    QUndoStack *stack = MAIN.undoStack();
    result["undo"] = QJsonObject{{"undo_text", stack->undoText()}, {"redo_text", stack->redoText()},
                                 {"index", stack->index()}, {"count", stack->count()}, {"clean", stack->isClean()}};
    return result;
}

QJsonValue ClaudeBridge::voiceCommand(const QString &method, const QJsonObject &params)
{
    QString error;
    const QJsonObject result = aiVoiceCommand(&MAIN, method, params, &error);
    if (!error.isEmpty())
        throw BridgeError(error);
    return result;
}

QJsonValue ClaudeBridge::commandHelp(const QJsonObject &params)
{
    QFile file(aiRootPath(QStringLiteral("command-reference.json")));
    if(!file.open(QIODevice::ReadOnly))throw BridgeError("Command reference not installed");
    const auto all=QJsonDocument::fromJson(file.readAll()).array();
    const QString query=params.value("query").toString().trimmed(); QJsonArray found;
    for(auto value:all){
        auto o=value.toObject();
        if(!query.isEmpty() && !QString::fromUtf8(QJsonDocument(o).toJson()).contains(query,Qt::CaseInsensitive))continue;
        if(auto *a=findAction(o.value("action").toString())){
            o["shortcut"]=a->shortcut().toString();o["enabled_now"]=a->isEnabled();
        }
        found.append(o);
    }
    return found;
}

