/*
 * Claude Bridge: a local-only control channel for driving Shotcut from an AI agent.
 *
 * Listens on a QLocalServer (a Windows named pipe / Unix socket) restricted to the
 * current user. Never listens on TCP. Protocol: newline-delimited JSON.
 *   request:  {"id": 1, "method": "state", "params": {...}}
 *   response: {"id": 1, "ok": true, "result": ...} or {"id": 1, "ok": false, "error": "..."}
 */

#ifndef CLAUDEBRIDGE_H
#define CLAUDEBRIDGE_H

#include <QHash>
#include <QFuture>
#include <QJsonObject>
#include <QJsonValue>
#include <QMap>
#include <QObject>
#include <memory>

class QLocalServer;
class QLocalSocket;
class QLockFile;
namespace Mlt { class Producer; }

class ClaudeBridge : public QObject
{
    Q_OBJECT

public:
    static constexpr const char *kServerName = "letitedit-bridge";

    explicit ClaudeBridge(QObject *parent = nullptr);
    ~ClaudeBridge();
    bool start();

private slots:
    void onNewConnection();
    void onReadyRead();

private:
    void readRequests(QLocalSocket *socket);
    QJsonObject handle(const QJsonObject &request);
    QJsonValue dispatch(const QString &method, const QJsonObject &params);
    QJsonValue loadFonts(const QJsonObject &params);
    QJsonValue qaSelection(const QJsonObject &params);
    QJsonValue qaPythonEncoding();
    QJsonValue myAssetsState(const QJsonObject &params);
    QJsonValue exportChecks(const QJsonObject &params);
    QJsonValue jobsState();
    QJsonValue grabWindow(const QJsonObject &params);
    QJsonValue addMusic(const QJsonObject &params);
    QJsonValue otherSizes(const QJsonObject &params);
    QJsonValue musicSuggestions(const QJsonObject &params);
    QJsonValue qaFirstEditState();
    QJsonValue qaEventLoop(const QJsonObject &params);
    QJsonValue qaPlaybackProbe(const QJsonObject &params);

    QJsonValue state();
    QString revision();
    QFuture<QString> revisionAsync();
    friend QString aiBridgeRevision();
    QJsonValue liveContext();
    QJsonValue editorState(const QJsonObject &params);
    QJsonValue voiceCommand(const QString &method, const QJsonObject &params);
    QJsonValue commandHelp(const QJsonObject &params);
    QJsonValue qaWidget(const QJsonObject &params);
    QJsonObject qaMouse(const QJsonObject &params);
    Qt::MouseButtons m_qaButtons = Qt::NoButton;
    QJsonValue synchronizedDelete(const QJsonObject &params);
    QJsonValue subtitleEdit(const QJsonObject &params);
    QJsonValue replaceTracks(const QJsonObject &params);
    QJsonValue setMarkers(const QJsonObject &params);
    QJsonValue applyTransaction(const QJsonObject &params);
    void prepareTransaction(const QJsonObject &request, QLocalSocket *socket);
    struct PreparedTransaction {
        QMap<QString, std::shared_ptr<Mlt::Producer>> after;
        QString error;
    };
    std::shared_ptr<PreparedTransaction> m_preparedTransaction;
    bool m_preparingTransaction = false;
    QJsonObject qaKey(const QJsonObject &params);
    void installCollaborationUi();
    QJsonValue listActions();
    QJsonValue trigger(const QJsonObject &params);
    QJsonValue seek(const QJsonObject &params);
    QJsonValue open(const QJsonObject &params);
    QJsonValue selectClip(const QJsonObject &params);
    QJsonValue selectTrack(const QJsonObject &params);
    QJsonValue selectTimeline();
    QJsonValue selectFilter(const QJsonObject &params);
    QJsonValue getFilterParams(const QJsonObject &params);
    QJsonValue removeFilter(const QJsonObject &params);
    QJsonValue listFilters();
    QJsonValue addFilter(const QJsonObject &params);
    QJsonValue setFilterParams(const QJsonObject &params);
    QJsonValue snapshot(const QJsonObject &params);
    QJsonValue projectXml();
    QJsonValue undoRedo(bool redo);
    QJsonValue closeDialog();
    QJsonValue dialogButton(const QJsonObject &params);
    QJsonValue importSrt(const QJsonObject &params);
    QJsonValue addClip(const QJsonObject &params);
    QJsonValue makeShort(const QJsonObject &params);
    QJsonValue save(const QJsonObject &params);
    QJsonValue splitClip(const QJsonObject &params);
    QJsonValue moveClip(const QJsonObject &params);
    QJsonValue removeClip(const QJsonObject &params);
    QJsonValue setTrack(const QJsonObject &params);

    QLocalServer *m_server;
    QHash<QLocalSocket *, QByteArray> m_buffers;
    QString m_instanceId;
    QString m_pipeName;
    std::unique_ptr<QLockFile> m_instanceLock;
};

#endif // CLAUDEBRIDGE_H
