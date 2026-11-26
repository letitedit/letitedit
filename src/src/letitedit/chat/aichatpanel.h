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
#ifndef AICHATPANEL_H
#define AICHATPANEL_H

#include "Logger.h"
#include "actions.h"
#include "letitedit/airoot.h"
#include "letitedit/chat/connectai.h"
#include "mainwindow.h"
#include "letitedit/player/previewobjects.h"
#include "settings.h"
#include "letitedit/chat/aiterminal.h"
#include "mltcontroller.h"
#include "docks/timelinedock.h"
#include "models/multitrackmodel.h"
#include <QActionGroup>
#include <QCryptographicHash>
#include <QDateTime>
#include <QDesktopServices>
#include <QDir>
#include <QDirIterator>
#include <QDockWidget>
#include <QFile>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QInputDialog>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QLockFile>
#include <QMenu>
#include <QMenuBar>
#include <QMessageBox>
#include <QMouseEvent>
#include <QPlainTextEdit>
#include <QPointer>
#include <QProcess>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QPushButton>
#include <QScrollBar>
#include <QSet>
#include <QStandardPaths>
#include <QTextBrowser>
#include <QTimer>
#include <QToolButton>
#include <QUuid>
#include <QVBoxLayout>
#include <QApplication>
#include <QAudioDevice>
#include <QAudioFormat>
#include <QAudioSource>
#include <QBuffer>
#include <QElapsedTimer>
#include <memory>
#include <QMediaDevices>
#include <QSaveFile>
#include <algorithm>
#include <functional>

struct AiChatBlock
{
    QString kind; // user | claude | tool | note | error
    QString text;
    QString detail;        // a request the app wrote: the full text the AI got (text is its short summary)
    bool expanded = false; // the detail is shown under the summary
    int repeats = 1;       // consecutive identical activity is one readable line
};

// The edits the window's bridge applied (the AI's tools land there): a running count and their labels, so a request's
// answer can say which changes the AI made while it ran (claudebridge.cpp).
int aiBridgeEditCount();
QString aiBridgeRevision();
QStringList aiBridgeEditsSince(int mark);

struct AiChat
{
    QWidget *targetBar = nullptr;     // T99: what's selected in the video, which a typed request is about
    QLabel *targetLabel = nullptr;
    QString typedTarget;              // its line, only while a typed request is being sent
    QHash<QString, QString> queuedTargets; // a connector takes one message at a time: each keeps its own target
    QDockWidget *dock = nullptr;
    QTextBrowser *view = nullptr;
    QPlainTextEdit *input = nullptr;
    AiTerminal *terminal = nullptr;
    QLabel *terminalNotice = nullptr;
    QWidget *firstUseBar = nullptr;   // the first-use notice, until the person has seen it
    QLabel *firstUseText = nullptr;
    bool signedOutShown = false;      // terminalNotice and Sign in are up because the program isn't signed in
    AiTerminal *reviewTerminal = nullptr; // a review as a visible second conversation (background runs off)
    QWidget *reviewBar = nullptr;
    QLabel *reviewLabel = nullptr;
    QPushButton *reviewStopButton = nullptr;
    QTimer *reviewWatch = nullptr;
    QString reviewRequestFile, reviewOut, reviewSpeed;
    QJsonObject reviewOptions;
    int reviewGeneration = 0;
    bool reviewNormalSpeed = false;
    QString reviewAnswer;             // the review.json it is to write
    QTimer *terminalPoll = nullptr;
    QString terminalWork;
    QString terminalEvents;
    QString terminalSessionFile;
    qint64 terminalEventOffset = 0;
    qint64 terminalSessionOffset = 0;
    QDateTime terminalLaunchedUtc;
    QByteArray terminalEventBuffer, terminalSessionBuffer;
    QSet<QString> terminalSeenMessages;
    bool terminalStopping = false;
    QPushButton *send = nullptr;
    QPushButton *stop = nullptr;
    QPushButton *signIn = nullptr;
    QLabel *status = nullptr;
    QProcess *proc = nullptr;
    QTimer *repaint = nullptr;
    QString sessionId;
    QString chatId;
    QString projectKey;
    QJsonArray history;
    QToolButton *historyButton = nullptr;
    QStringList queued;
    bool followBottom = true;
    bool rendering = false;
    QString engine; // 'claude' or 'codex': the CLI this conversation runs in
    QString procModel, procEffort; // claude: the model and effort the running Claude Code was started with
    QString procSpeed, retryContent, speedError;
    bool speedNormal = false, speedRetried = false, speedProduced = false;
    bool speedRestartPending = false;
    QString activeModel;           // the model answering this conversation, as the CLI reports it
    QJsonArray tools;              // claude: the tools Claude Code reported it has, and its permission mode
    QString permissionMode;
    QSet<QString> claudeChatAllowed;
    QString lastPermission;
    QToolButton *engineButton = nullptr; // the top row: the AI, its model and its effort
    QToolButton *modeButton = nullptr;
    QToolButton *modelButton = nullptr;
    QToolButton *effortButton = nullptr;
    bool turnOpen = false; // codex: a turn is running and has not reported turn.completed / turn.failed
    QString codexTurnId;
    QString codexPending;
    bool codexReady = false;
    int codexRpcNext = 1;
    QHash<int, QString> codexRpc;
    QHash<int, QString> codexSteers;
    bool sessionStarted = false;
    bool busy = false;
    bool permissionWaiting = false;
    // A New video is a long, self-contained job. It has its own AI session and
    // permission policy; ordinary chat keeps the person's normal policy.
    QString refusal;                  // why aiChatRequest last said no, when there are plain words for it
    bool autonomousNewVideo = false;
    bool carryAllowed = false;
    bool carryPending = false;
    bool carrySending = false;
    bool carryStopped = false;
    bool carryHumanInput = false;
    int carryCount = 0;
    qint64 carryStarted = 0;
    QString carryEngine, carryModel, carryEffort;
    QWidget *carryBar = nullptr;
    QLabel *carryLabel = nullptr;
    QPushButton *carryContinue = nullptr;
    // A usage limit (T193): the turn waits, then carries on by itself at limitCarryAt (epoch seconds); limitWaits caps
    // how often one run waits; limitChecked is the turn (turnNumber) whose ending was already read for a limit. The
    // app's carry-ons keep their request's id, so a turn is counted on its own.
    qint64 limitCarryAt = 0;
    QString limitWords;
    int limitWaits = 0;
    int limitChecked = 0;
    int turnNumber = 0;
    QTimer *limitTimer = nullptr;
    bool newVideoMakes = false;  // this chat makes a video (New video, not Learn): Stop leaves Carry on behind
    bool liveReviewHold = false; // Live Review keeps that unattended session open from one note to the next
    QString autonomousWriteDir;
    // This chat was started by New video or Learn from a video (saved with the chat): every turn of it runs unattended,
    // however it continues (the app's carry-on, Continue the edit, a typed message, the chat reopened after a restart).
    bool newVideoChat = false;
    // One conversation per stage (T194, bridge/new_video_stages.py): the run's request asks for a hand-over after
    // each big stage, and the next stage starts in a fresh session with the request and the hand-over. Saved with the
    // chat. runSessions: every session of this run, for its cost line (bridge/run_cost.py).
    bool stageSessions = false;
    QString newVideoRequest;
    QStringList runSessions;
    // T294: lean stage hand-offs (chat/ainewvideolean.h; off by default). The run's id, its seeded working project (or
    // why it couldn't be seeded), the transition being made (kept before a fresh session starts: {id, next, state:
    // prepared|launching|created, session, acked}), a transition to retry because no session was made for it, the
    // revision attested at the last check, and the repairs carried on in the same conversation. Saved with the chat.
    bool leanStages = false;
    QString leanRunId;
    QString leanProject;
    QString leanSeedRefused;
    bool leanSeeding = false;
    QJsonObject leanTransition;
    QString leanRetry;
    QString leanAttested;
    int leanRepairs = 0;
    int leanAcks = 0;
    int leanRechecks = 0; // checks asked again in this turn (a lost reply, a launch reconciled)
    QString leanAnswer;
    QTimer *leanPoll = nullptr;
    // T300: New video's first stage started complete through the bridge (chat/ainewvideostart.h). While its message is
    // prepared nothing else is sent; stageStart is what happened ({state: preparing|verified|refused|not_verified,
    // stage, bytes, sha256, project, folder, max_bytes, reason}). verbatimBytes >= 0: the next send goes out word for
    // word, with no context line, and only if its UTF-8 bytes hash to verbatimSha; verbatimDetail is what the chat's
    // request shows behind "Show the details" (the person's own request, not the attached skills).
    bool stageStartPending = false;
    int stageStartToken = 0;
    QJsonObject stageStart;
    qint64 verbatimBytes = -1;
    QString verbatimSha;
    QString verbatimDetail;
    // one line shown when a given project opens ("Edit with the AI myself", Home's empty timeline): no AI run
    QString readyProject;
    QString readyNote;
    // A turn can end with work it started still running (Claude Code moves a long tool call to the background, or the
    // AI started a job itself). The request isn't finished then: it stays open and Busy, and the AI's program is left
    // alone, until the AI has carried on and really ended a turn.
    bool turnHeld = false;
    bool heldOnUnseenWork = false;           // terminal: held on work the tool proxy can't see the end of
    QHash<QString, QString> backgroundTasks; // bubbles: what the stream says is running in the background (id -> type)
    QSet<QString> toolCallsRunning;          // terminal: letitedit calls the tool proxy saw go out and not come back
    QByteArray buffer;
    QList<AiChatBlock> blocks;
    int live = -1;
    // Push-to-talk (voice settings: "voice" in panel.json; bridge/voice_chat.py holds every default).
    MainWindow *window = nullptr;
    QPushButton *talk = nullptr;
    QAudioSource *mic = nullptr;
    QBuffer *recorded = nullptr;
    QAudioFormat recordFormat;
    QString micName;
    QTimer *recordLimit = nullptr;
    QElapsedTimer recordClock;
    QProcess *voiceHelper = nullptr;
    QByteArray voiceBuffer;
    int voiceNextId = 1;
    bool recording = false;
    bool spokenTurn = false;
    bool speaking = false;
    int turnStart = 0;
    QElapsedTimer turnClock; // since the request was sent
    QString stage;           // the stage of the request so far (aiChatStage)
    QString lastTranscript;
    QString lastSpoken;
    QString voiceStatus;
    QJsonObject lastTranscription;
    int voiceTurns = 0;
    QAction *talkAction = nullptr; // "Hold to talk": its shortcut is the push-to-talk key (Actions and Shortcuts)
    bool keyTalking = false;       // the take was started by holding the key (a lost key release still ends it)
    // Requests: every message sent gets an id. When its answer ends, the outcome (answered, failed or cancelled), the
    // AI's answer and the edits its tools made in this window while it ran are kept for whoever sent it
    // (aiChatWatchRequest), so nobody has to guess from a busy flag.
    int nextRequest = 1;
    int request = 0;      // the request being answered now (0: none)
    int requestEdits = 0; // aiBridgeEditCount() when it was sent
    QString requestSummary;
    QHash<int, QJsonObject> outcomes;
};

struct AiChatChoice
{
    QString value;  // what the CLI gets
    QString label;  // in the menu
    QString button; // on the button
    QString tip;
};

// What the rest of the editor calls; the panel itself is aichatpanel.cpp.
AiChat *&aiChatInstance();
QJsonObject aiChatRawSettings();
bool aiChatSaveSettings(const QJsonObject &changes);
QJsonObject aiEntry(const QString &id);
QStringList aiEngineIds();
bool aiEngineIsConnector(const QString &id);
QStringList aiConnectorIds();
bool aiConnectorSignedIn(const QJsonObject &settings, const QString &id);
bool aiEngineHere(const QJsonObject &settings, const QString &engine);
QJsonObject aiChatSettings();
bool aiChatIsCodex(const QJsonObject &s);
QString aiChatEngineId(const QJsonObject &s);
QString aiEngineShortName(const QString &id);
QString aiCodexHome();
QString aiTomlString(const QString &text);
QStringList aiCodexWindowArgs();
QString aiChatModelKeyOf(const QString &engine);
QString aiChatEffortKeyOf(const QString &engine);
QList<AiChatChoice> aiChatEngineChoicesHere(const QJsonObject &settings);
QList<AiChatChoice> aiChatModelChoices(const QJsonObject &s);
QList<AiChatChoice> aiChatEffortChoices(const QJsonObject &s);
QStringList aiClaudeLockdownArgs();
QJsonObject aiClaudeInstructionSettings(const QJsonObject &settings = aiChatSettings());
QStringList aiClaudeInstructionArgs(const QJsonObject &settings = aiChatSettings());
QJsonArray aiClaudeChatDenyRules();
QStringList aiClaudeChatSettingsArgs(const QJsonObject &settings = aiChatSettings());
QStringList aiClaudeChoiceArgs(const QJsonObject &s);
QStringList aiCodexChoiceArgs(const QJsonObject &s, QString *model = nullptr);
QString aiSpeedKey(const QString &engine);
QJsonArray aiSpeedChoices(const QJsonObject &settings, const QString &engine);
QString aiSpeedValue(const QJsonObject &settings, const QString &engine);
void aiChatWatchBusy(QObject *context, const std::function<void(bool)> &watcher);
void aiChatWatchRequest(QObject *context, int request, const std::function<void(const QJsonObject &)> &watcher);
// A New video start that answered with a request id and was refused afterwards: the request as the chat would have
// shown it, its short line, the reason ("" when an ordinary "try again" fits) and whether it was a carry-on.
using AiChatStartRefusedWatcher = std::function<void(const QString &request, const QString &summary,
                                                     const QString &why, bool carryOn)>;
void aiChatWatchStartRefused(QObject *context, const AiChatStartRefusedWatcher &watcher);
QJsonObject aiChatOutcome(int request);
void aiChatLiveEnd(AiChat *c);
int aiChatRequest(MainWindow *window, const QString &text, const QString &summary = QString(), bool spoken = false,
                  bool autonomousNewVideo = false);
void aiChatHandleLine(AiChat *c, const QJsonObject &msg);
QString aiChatRefusal();
QJsonObject aiChatState();
int aiChatReviewBatchSent(const QString &folder);
// The run the New video card shows (T193): the chat's own name for it, the same for every turn of that chat.
QString aiChatProgressRun();
// The card's Stop: the same as the chat's Stop. Carry on: the same as Continue the edit, once nothing is running.
void aiChatStopRun();
bool aiChatCarryOn(MainWindow *window);
QJsonObject aiVoiceSettings();
QAudioDevice aiVoiceDevice(const QString &want);
bool aiVoiceWriteWav(const QByteArray &pcm, const QAudioFormat &f, const QString &path);
QJsonObject aiVoiceCommand(MainWindow *window, const QString &method, const QJsonObject &params, QString *error);
void aiChatPickEngine(AiChat *c, const QString &engine);
void aiChatPickSetting(AiChat *c, bool effort, const QString &value);
QJsonObject aiChatVisibleReview(const QString &requestFile, const QString &out, const QJsonObject &more = QJsonObject());
void aiChatSettingsChanged();
void aiChatShowReady(const QString &project, const QString &note);
void installAiChatPanel(MainWindow *window);

#endif // AICHATPANEL_H
