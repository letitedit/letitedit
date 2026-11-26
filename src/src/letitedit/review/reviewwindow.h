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

// Review (letitedit): the window and its parts, declared for the files of letitedit/review/ (the file beside
// each method group names it). The rest of the editor sees only reviewmode.h.
#ifndef REVIEWWINDOW_H
#define REVIEWWINDOW_H

#include "letitedit/review/reviewmode.h"

#include "actions.h"
#include "letitedit/chat/aichatpanel.h"
#include "docks/timelinedock.h"
#include "letitedit/workspace/focusworkspace.h"
#include "letitedit/workspace/leside.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "player.h"
#include "settings.h"
#include "sharedframe.h"
#include "util.h"
#include "videowidget.h"
#include "letitedit/player/livecodeoverlay.h"
#include "letitedit/review/livereview.h"

#include <QAudioSource>
#include <QCheckBox>
#include <QComboBox>
#include <QDateTime>
#include <QDir>
#include <QDockWidget>
#include <QElapsedTimer>
#include <QFile>
#include <QFrame>
#include <QScrollArea>
#include <QScrollBar>
#include <QUndoStack>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QKeyEvent>
#include <QLabel>
#include <QLineEdit>
#include <QInputDialog>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QMouseEvent>
#include <QMutex>
#include <QPainter>
#include <QPainterPath>
#include <QPointer>
#include <QProcess>
#include <QPushButton>
#include <QHash>
#include <QRegularExpression>
#include <QRunnable>
#include <QSet>
#include <QSaveFile>
#include <QFileInfo>
#include <QSettings>
#include <QStandardPaths>
#include <QTextDocumentFragment>
#include <QThreadPool>
#include <QTimer>
#include <QToolButton>
#include <QVBoxLayout>

#include <algorithm>
#include <climits>
#include <cmath>
#include <cstring>
#include <functional>
#include <memory>
#include <numeric>
#include <tuple>
#include <utility>

namespace ReviewMode {

enum Tool { Pen, Arrow, Circle, Box };

struct Stroke
{
    Tool tool = Pen;
    QColor color;
    QVector<QPointF> points; // 0..1 across the frame's picture
    // in a spoken take: the frame it was drawn on and when, in ms from the start of the recording
    int frame = -1;
    int endFrame = -1; // an optional range for a mark that lasts across frames
    qint64 t0 = -1;
    qint64 t1 = -1;
    QImage image;      // that frame, as the player showed it (loaded or converted only when a file needs it)
    SharedFrame shot;  // the player's own frame, made into a picture off the screen thread when it is saved
    QString imageFile; // its PNG from an earlier session
    bool hasImage() const { return !image.isNull() || shot.is_valid() || !imageFile.isEmpty(); }
};

struct Word
{
    QString text;
    double start = 0; // seconds from the start of the recording
    double end = 0;
};

struct Note
{
    int id = 0;
    int frame = -1; // -1: about the whole video
    int endFrame = -1;
    QString text;
    QString audio; // file name in the review folder
    QVector<Stroke> strokes;
    QImage image; // the frame as the player showed it, when the note was made (typed notes)
    SharedFrame shot;
    QString imageFile;
    bool hasImage() const { return !image.isNull() || shot.is_valid() || !imageFile.isEmpty(); }
    // a spoken take: talking and drawing while the video moves on
    bool take = false;
    qint64 leadInMs = 0;
    QVector<Word> words;
    QVector<QPair<qint64, int>> clock; // ms into the recording -> the frame on screen then
    // Live Review: a small picture for the list, and whether its words are still being written down or were the video's own
    QImage thumb;
    bool writing = false;
    bool heardVideo = false;
};

const char *toolName(Tool t);

Tool toolFromName(const QString &name);

QImage frameImage(const SharedFrame &frame);

QThreadPool &writerPool();

// QA measurements (LETITEDIT_QA): how long the screen thread spends painting and taking frames, how long a pen
// movement waits to be painted, how late the event loop runs, and how fast Review opens and closes.
struct Timing
{
    QElapsedTimer clock;
    QVector<qint64> paintUs, frameUs, inputUs, stallUs;
    qint64 pendingInputNs = -1; // the latest pen movement handled and not painted yet
    qint64 openMs = -1, closeMs = -1, firstPaintNs = -1, openStartNs = -1;
    int framesShown = 0, positions = 0;
    bool legacy = false; // the drawing and saving code as it was before 20261030 (for before/after checks)
    bool active = false;
    static Timing &get()
    {
        static Timing t;
        if (!t.clock.isValid())
            t.clock.start();
        return t;
    }
    void reset()
    {
        paintUs.clear();
        frameUs.clear();
        inputUs.clear();
        stallUs.clear();
        pendingInputNs = -1;
        framesShown = positions = 0;
    }
    static QJsonObject stats(QVector<qint64> v)
    {
        if (v.isEmpty())
            return QJsonObject{{"n", 0}};
        std::sort(v.begin(), v.end());
        const auto at = [&v](double q) { return double(v[qMin(int(v.size()) - 1, int(q * v.size()))]) / 1000.0; };
        const double mean = std::accumulate(v.begin(), v.end(), 0.0) / v.size() / 1000.0;
        return QJsonObject{{"n", int(v.size())}, {"mean_ms", std::round(mean * 100) / 100},
                           {"p50_ms", at(0.5)}, {"p95_ms", at(0.95)}, {"max_ms", double(v.last()) / 1000.0}};
    }
    QJsonObject json() const
    {
        return QJsonObject{{"legacy", legacy},
                           {"paint", stats(paintUs)},
                           {"frame_on_screen_thread", stats(frameUs)},
                           {"pen_to_screen", stats(inputUs)},
                           {"event_loop_late", stats(stallUs)},
                           {"frames_shown", framesShown},
                           {"positions", positions},
                           {"open_ms", openMs},
                           {"close_ms", closeMs}};
    }
};

QString stamp(double seconds);

void paintStrokes(QPainter &p, const QRectF &r, const QVector<Stroke> &strokes, const QList<int> &numbers = {});

// A note's words as a box that wraps and grows with them (up to a few lines, then it scrolls). Enter keeps the words,
// Shift+Enter starts a new line, Esc leaves it as it was.
QPlainTextEdit *noteEditor(const QString &text, QWidget *parent, const std::function<void(bool keep)> &done);

// A spoken note has two clocks (T210). After kTextReadyMs of quiet its words so far are written down and shown, with
// Send; the note itself stays open until kNotePauseMs of quiet (the default behind the gear), so a breath mid-sentence
// never splits it: words said before then join it and are written down again. His talking heads pause 0.7-1.5 s
// mid-sentence ("user, | the" 1.46 s), voice detection's pauses inside a note were up to 0.58 s (tests/t210/REPORT.md).
constexpr int kTextReadyMs = 650;
constexpr int kNotePauseMs = 2000;
// A drawing nobody talks over is kept as a drawing this long after the pen lifts.
constexpr int kDrawOnlyMs = 3000;

// The microphone writes here only while Review's listening switch is on. Before a press we retain at most
// three seconds in memory. A note takes that lead-in and then all new samples; neither is written until the
// person has actually started a note. The small PCM level check is also used by the pause detector.
class RollingAudio : public QIODevice
{
public:
    QAudioFormat format;
    QByteArray recent;
    QByteArray take;
    qint64 lastVoiceMs = -1;
    qint64 prerollMs = 0;
    bool recording = false;
    double thresholdDb = -45.0;
    QElapsedTimer clock;
    QMutex mutex;
    bool followRoom = false;
    double roomDb = -70.0;
    qint64 voicedRunMs = 0;
    QVector<double> roomBuckets; // the level of each fifth of a second, the last 8 seconds
    double bucketEnergy = 0;
    double bucketMs = 0;
    QByteArray speechPending;
    explicit RollingAudio(QObject *parent = nullptr);
    void feed(const char *data, qint64 len);
    qint64 voicedRun();
    void begin(qint64 leadInUs = 0);
    QByteArray finish();
    QByteArray soFar(); // the note's sound so far, while it goes on
    qint64 cappedRecentMs();
    qint64 lastVoice();
    QByteArray speechChunk();
    void detectedSpeech(qint64 lastMs, qint64 runMs);
protected:
    qint64 readData(char *, qint64) override;
    qint64 writeData(const char *data, qint64 len) override;

private:
    void noteLevel(double rms, qint64 len);
};

void showLiveBanner(MainWindow *window);

// T221: Review's notes, sent, in the order they go to the AI. A send while the AI is busy waits here and goes by itself
// when it's free; each send is one request, and the AI makes each note one Undo step (send.cpp).
struct NoteBatch
{
    QString sent;       // review/<time>/: the notes' copy the AI reads
    QStringList lines;  // one line per note
    QString takes;      // how a spoken note reads, when there is one
    int count = 0;
};

class NoteQueue : public QObject
{
public:
    static NoteQueue &of(MainWindow *window);
    bool add(const NoteBatch &batch);
    void recover();
    int working() const { return m_onCount; } // notes the AI is on now
    int waiting() const;                      // notes waiting for it
    QString line() const;                     // "Your AI is on 1 note" / "... 2 notes waiting"
    QString problem() const { return m_problem; }
    bool stuck() const { return !m_problem.isEmpty() && !m_waiting.isEmpty(); } // waiting on the person (problem)
    void retry()
    {
        m_problem.clear();
        pump();
        if (!m_waiting.isEmpty() && m_problem.isEmpty())
            m_timer.start();
    }

private:
    explicit NoteQueue(MainWindow *window);
    void pump();
    bool go(const NoteBatch &batch);
    bool persist(const NoteBatch &batch, const QString &state);
    MainWindow *m_window;
    QList<NoteBatch> m_waiting;
    QTimer m_timer;
    int m_onRequest = 0;
    int m_onCount = 0;
    int m_done = 0; // notes finished since the queue was last empty
    QString m_problem;
    QString m_project;
    int m_recovered = 0;
    QLabel *m_recoveryLine = nullptr;
};

void showSentBanner(MainWindow *window, int count, const QString &before, int request, const QString &requestText,
                    const QString &summary);
QString newProjectFile(const QString &name);
bool timelineHasClips(MainWindow *window);
bool putClipOnTimeline(MainWindow *window);
void showOpenOffer(MainWindow *window);

class Canvas : public QWidget
{
public:
    std::function<QVector<Stroke> *()> target; // where a new stroke goes (the take, the note at this frame, the draft)
    std::function<void(QVector<Stroke> &, QList<int> &)> shown; // what to paint now, with mark numbers
    std::function<void(Stroke &)> strokeStarted;
    std::function<void()> beginDraw;
    std::function<void()> changed;
    std::function<void()> markupChanged;
    std::function<void()> resized; // the picture area changed size: the frame is made again at the new size
    Tool tool = Pen;
    QColor color = QColor(LetItEditColors::rust);
    QImage image; // the frame on screen, made at the picture area's size (any size while that changes)
    double dar = 16.0 / 9.0;
    QSize pictureSize() const;
    explicit Canvas(QWidget *parent);
    QRectF pictureRect() const;

protected:
    void paintEvent(QPaintEvent *e) override;
    void resizeEvent(QResizeEvent *e) override;
    QRectF strokeBounds(const Stroke &s) const;
    void noteInput();

public:
    qint64 qaInputNs = -1; // QA: when the synthetic pen movement being handled was due

protected:
    QPointF normalized(const QPointF &pos) const;
    void mousePressEvent(QMouseEvent *e) override;
    void mouseMoveEvent(QMouseEvent *e) override;
    void mouseReleaseEvent(QMouseEvent *e) override;

private:
    QVector<Stroke> *m_strokes = nullptr; // the list the stroke being drawn belongs to
};

// The whole video as a bar: what has played, the playhead, and a pin at every note.
class Scrubber : public QWidget
{
public:
    std::function<void(int)> seek;
    int length = 1;
    int position = 0;
    QList<int> pins;
    int activePin = -1;
    explicit Scrubber(QWidget *parent);

protected:
    QRectF track() const;
    double xAt(int frame) const;
    void paintEvent(QPaintEvent *) override;
    void seekTo(double x);
    void mousePressEvent(QMouseEvent *e) override;
    void mouseMoveEvent(QMouseEvent *e) override;
};

class ReviewWindow;
QPointer<ReviewWindow> &openWindow();

class ReviewWindow : public QWidget
{
public:

    // reviewwindow.cpp
    explicit ReviewWindow(MainWindow *window);
    ~ReviewWindow() override;
    QJsonObject state() const;

    // qa.cpp
    void qaNextSound(const QString &path);
    void qaDraw(bool talk, double seconds, const QString &out);

protected:

    // reviewwindow.cpp
    void keyPressEvent(QKeyEvent *e) override;
    void keyReleaseEvent(QKeyEvent *e) override;
    bool eventFilter(QObject *watched, QEvent *event) override;
    void changeEvent(QEvent *e) override;
    void closeEvent(QCloseEvent *e) override;

private:
    // Construction steps (reviewwindow.cpp).
    void setupAppearance();
    void buildToolbar(QVBoxLayout *outer, const QFileInfo &project);
    void buildCanvas(QVBoxLayout *left);
    void buildTransport(QVBoxLayout *left);
    QVBoxLayout *buildNotesPanel(QVBoxLayout *sideOuter);
    void buildSettingsPopup();
    void restoreTalkSettings(QSettings &reviewSettings, const QString &prefsPath);
    void buildNoteControls(QVBoxLayout *side);
    void buildSubmitControls(QVBoxLayout *sideOuter);
    void buildKeyboardHelp(QVBoxLayout *left);
    void connectPlayer();
    void restoreReview(QSettings &reviewSettings, const QString &prefsPath);

    struct RowButton
    {
        QString label;
        QString name;
        std::function<void()> run;
        bool main = false;
    };

    // reviewwindow.cpp
    bool handleKey(QKeyEvent *e);
    void stepFrame(int step);
    void setSpeed(double speed);
    void shuttle(int direction);
    void jumpNote(int direction);
    void toggleFullScreen();
    void lightPreview(bool playing);
    void startEditClassic();
    void finishEditClassic(bool keep);
    void setRangeEnd();
    QToolButton *flatButton(const QString &text, bool checkable = false);
    void updateTalkButton();
    void onFrame(const SharedFrame &frame);
    void updateTime();
    void togglePlay();
    void playAt(double speed);
    void stopPlaying();
    void slowTick();

    // drawing.cpp
    void requestPicture();
    void pictureReady(const QImage &picture);
    static QThreadPool &writerPictures();
    QVector<Stroke> *activeStrokes();
    void shownStrokes(QVector<Stroke> &strokes, QList<int> &numbers);
    void updateReviewMarkup();

    // notes.cpp
    int againNote() const;
    void updateAgain();
    void recordAgain();
    int noteAt(int frame) const;
    void commitDraft();
    void addNote();
    void undoMark();
    void dropIfEmpty();
    void deleteSelected();
    void sortNotes();
    void changed();
    void refreshActive();
    void refresh();

    // takes.cpp
    static int frameAt(const Note &n, qint64 ms);
    QString script(const Note &n) const;
    void setListening(bool on);
    void checkLive();
    void checkPause();
    bool startTake();
    void stopTake();
    void keepTake(const Note &take);
    int noteIndex(int id) const;
    void transcribe(int id);
    void finishTranscription(int id, bool ok, const QJsonObject &r, const QString &why);

    // files.cpp
    QImage marked(const QImage &image, const QVector<Stroke> &strokes, const QList<int> &numbers = {}) const;
    QImage markedTake(const Note &n, int k) const;
    QImage captureScenePicture();
    static void writeMarked(const SharedFrame &shot, const QImage &image, const QString &imageFile, const QString &clean,
                            const QString &markedPath, const QVector<Stroke> &strokes, const QList<int> &numbers,
                            double dar, bool writeClean);
    static QByteArray drawingSignature(const QVector<Stroke> &strokes);
    static QString frameFile(const Note &n);
    static QString markedFile(const Note &n);
    static QString markFrameFile(const Note &n, int k);
    static QString markFile(const Note &n, int k);
    QStringList files(const Note &n) const;
    QJsonObject toJson(const Note &n) const;
    void save();
    void refinePicture(const QString &xml, int frame, const QString &clean, const QString &markedPath,
                       const QVector<Stroke> &strokes, const QList<int> &numbers, double dar);
    void updateCopyPause();
    void saveLegacy();
    void load();
    void submit();
    QStringList draftComplete();
    QString noteLine(const Note &n, int number) const;
    static QString takesExplained();

    // live.cpp
    void buildOffer(QVBoxLayout *outer);
    void buildLiveBox(QVBoxLayout *sideOuter);
    static QImage smallPicture(const QImage &image);
    void setLive(bool on);
    QProcess *runLive(const QStringList &args, const std::function<void(int, const QJsonObject &)> &done);
    void loadVideoWords(const QString &project);
    void queueWords(int id);
    void startWords();
    void detectSpeech();
    void pumpWords();
    void readWords();
    void wordsEnded(const QString &why);
    void cleanWords(int id);
    void afterWords(int id);
    void addLiveTyped();
    QList<int> sendableCards() const;
    void sendAllCards();
    void sendNewestCard();
    void sendLive(int id);
    void sendLiveWritten(int id);
    void attachSession(LiveReview::Session *session);
    void deleteCard(int id);
    void startEdit(int id);
    void finishEdit();
    QFrame *liveRow(const QString &key, const QImage &thumb, const QString &picture, const QString &when, int jumpFrame,
                    QWidget *words, const QString &state, const QString &stateColor, const QString &detail,
                    const QList<RowButton> &buttons, bool highlighted);
    QWidget *wordsLabel(const QString &text, const QString &key);
    QWidget *draftNoteRow(const Note &n);
    void refreshLiveList();
    void evaluateLoading();
    void loadChanges();
    void changesLoaded(double first, const QString &problem, int count, qint64 ms);
    QJsonObject liveState() const;

    // send.cpp
    bool sendNotes();
    void refreshQueueLine();

    MainWindow *m_window;
    QString m_dir;
    double m_fps = 30.0;
    int m_length = 1;
    int m_position = 0;
    int m_nextId = 1;
    QVector<Note> m_notes;
    QVector<Stroke> m_draft;
    int m_draftFrame = -1;
    QImage m_draftImage;
    Canvas *m_canvas = nullptr;
    Scrubber *m_scrubber = nullptr;
    QToolButton *m_play = nullptr;
    QLabel *m_time = nullptr;
    QLineEdit *m_input = nullptr;
    QPushButton *m_talk = nullptr;
    QLabel *m_listeningSign = nullptr;
    QCheckBox *m_autoSend = nullptr;
    // behind the gear (T210, the owner: keep the settings, out of the way): talking while drawing, the pause that ends a note
    QToolButton *m_settings = nullptr;
    QFrame *m_settingsPanel = nullptr;
    QCheckBox *m_listenSwitch = nullptr;
    QComboBox *m_pauseBox = nullptr;
    int m_pauseMs = kNotePauseMs;
    // T210: the speeds beside Play (1/4, 1/2, 1, 2), full screen, the keys
    QList<QToolButton *> m_speedButtons;
    QToolButton *m_fullScreen = nullptr;
    bool m_takeByPen = false;   // the take was started by drawing (no words: it stays a drawing)
    int m_shuttle = 0;          // J / L: -8..8 times normal, 0 when not shuttling
    int m_heldKey = 0;          // an arrow held down, and since when: steps grow the longer it is held
    QElapsedTimer m_heldSince;
    // the words of the note being spoken, written down after a short quiet while it stays open (T210)
    void notePreview(qint64 heard, qint64 quietFor);
    void previewReady(const QJsonObject &r);
    int m_previewBusy = 0;          // the request in flight (negative ids)
    int m_previewSeq = 0;
    qint64 m_previewAskedVoice = -1; // the last speech the request covered
    qint64 m_previewVoice = -1;      // ... and the one the words shown cover
    QJsonObject m_previewResult;
    qint64 m_textReadyMs = -1;       // QA: from the last word to its text on screen
    qint64 m_lastHeard = -1;
    int m_stepTarget = -1;      // the frame the last step asked for (frames may show later than keys repeat)
    QElapsedTimer m_stepClock;
    bool m_previewLight = false; // a lighter picture while it plays (T210)
    QPlainTextEdit *m_classicEdit = nullptr;
    QWidget *m_classicEditBox = nullptr;
    int m_classicEditing = -1;
    QPoint m_editClick{-1, -1}; // where the words were clicked: the cursor goes there
    // what playing did, for the test window's measurements
    struct Playback
    {
        QElapsedTimer clock;
        double speed = 0;
        int startFrame = -1, lastFrame = -1, shown = 0, skipped = 0;
    } m_playback;
    QCheckBox *m_whole = nullptr;
    QListWidget *m_list = nullptr;
    QLabel *m_status = nullptr;
    QLabel *m_queueLine = nullptr; // T221: what the AI is on and what waits (NoteQueue)
    QTimer m_queueTimer;
    QPushButton *m_submit = nullptr;
    QPushButton *m_again = nullptr;
    QPushButton *m_retry = nullptr;
    QSet<int> m_unwritten; // spoken notes whose words could not be written down (Write it down again)
    bool m_sending = false;
    bool m_sendWhenWritten = false; // Send was pressed while words were being written down
    // Live Review
    bool m_live = false;
    QCheckBox *m_liveSwitch = nullptr;
    QWidget *m_liveBox = nullptr;
    QWidget *m_classicBox = nullptr;
    QFrame *m_offer = nullptr;
    QLabel *m_liveListening = nullptr;
    QCheckBox *m_liveAutoSend = nullptr;
    QFrame *m_liveBar = nullptr;
    QLabel *m_liveBarText = nullptr;
    QPushButton *m_liveWatch = nullptr;
    QPushButton *m_liveWait = nullptr;
    QLabel *m_liveCounts = nullptr;
    QScrollArea *m_liveScroll = nullptr;
    QVBoxLayout *m_liveRows = nullptr;
    QLineEdit *m_liveInput = nullptr;
    QPointer<LiveReview::Session> m_session;
    QProcess *m_wordsProcess = nullptr;
    QTimer m_wordsTimer;
    QList<int> m_wordsQueue;
    int m_wordsBusy = 0;
    bool m_vadPending = false;
    bool m_vadReset = true;
    int m_vadEpoch = 0;
    QElapsedTimer m_vadRequestClock;
    QElapsedTimer m_wordsRestartClock;
    QString m_videoWords;
    QString m_videoSpeechProject;
    QVector<Stroke> m_sentMarks;
    QSet<int> m_sendingIds;
    int m_editingId = -1;
    QString m_editingText;
    qint64 m_lastPenUpMs = -1;
    bool m_waitChosen = false;
    qint64 m_loadMs = -1;
    // the take being recorded
    bool m_recording = false;
    bool m_listening = false;
    bool m_closing = false;
    bool m_heardSpeech = false;
    qint64 m_prerollMs = 0;
    qint64 m_audioStartMs = 0;
    int m_autoPendingId = -1;
    int m_lastMarkId = -1; // -2: current take, 0: draft, positive: note id
    int m_lastMarkIndex = -1;
    int m_lastMarkFrame = -1;
    int m_transcribing = 0; // takes being written down
    double m_speed = 0.5;
    Note m_take;
    QElapsedTimer m_clock;
    QTimer m_slow;
    double m_slowStep = 0;
    double m_slowPosition = 0;
    QAudioSource *m_mic = nullptr;
    RollingAudio *m_audio = nullptr;
    QAudioFormat m_format;
    QTimer m_qaAudioTimer;
    QElapsedTimer m_qaFed;
    qint64 m_qaOwedMs = 0;
    QByteArray m_qaPcm;
    int m_qaOffset = 0;
    QTimer m_talkTimer;
    int m_lastTakeId = -1;
    // the frame on screen and the picture made from it
    SharedFrame m_frame;
#ifdef Q_OS_WIN
    std::unique_ptr<LiveCodeOverlay> m_liveScene;
#endif
    SharedFrame m_draftShot;
    bool m_converting = false;
    bool m_morePending = false;
    bool m_alive = true;
    QHash<int, QByteArray> m_written; // note id -> the drawing its marked picture was written with
    QHash<QString, QPointer<QProcess>> m_pictureRefinements;
    QSet<QString> m_writtenMarks;     // take marks written ("<note>-<mark>")
    QTimer m_stall;                   // QA: how late the event loop runs
    qint64 m_lastTick = 0;
    // T214: the rendered preview being made for smooth playback, and the plain line that says so
    QLabel *m_smoothLine = nullptr;
    QTimer m_smoothTimer;
    bool m_previewAsked = false; // playing dropped frames once: a preview was asked for
};

} // namespace ReviewMode

#endif // REVIEWWINDOW_H
