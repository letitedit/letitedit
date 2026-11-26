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

// Review: the window, its keys, playing and stepping through the video, the buttons.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"
#include "letitedit/player/renderedpreview.h"

#include <QAbstractTextDocumentLayout>
#include <QTextEdit>

namespace ReviewMode {

namespace {
class NoteEditor : public QPlainTextEdit
{
public:
    std::function<void(bool)> done;
    explicit NoteEditor(QWidget *parent)
        : QPlainTextEdit(parent)
    {
        setLineWrapMode(QPlainTextEdit::WidgetWidth);
        setWordWrapMode(QTextOption::WrapAtWordBoundaryOrAnywhere);
        setTabChangesFocus(true);
        setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        connect(document()->documentLayout(), &QAbstractTextDocumentLayout::documentSizeChanged, this,
                [this]() { fit(); });
        fit();
    }
    // as tall as the words, two lines at least and six at most (then it scrolls)
    void fit()
    {
        const int lines = qMax(1, int(document()->documentLayout()->documentSize().height()));
        const int shown = qBound(2, lines, 6);
        setVerticalScrollBarPolicy(lines > 6 ? Qt::ScrollBarAsNeeded : Qt::ScrollBarAlwaysOff);
        const int h = shown * fontMetrics().lineSpacing() + 2 * (frameWidth() + int(document()->documentMargin())) + 6;
        if (height() != h)
            setFixedHeight(h);
    }

protected:
    void keyPressEvent(QKeyEvent *e) override
    {
        if ((e->key() == Qt::Key_Return || e->key() == Qt::Key_Enter) && !(e->modifiers() & Qt::ShiftModifier)) {
            if (done)
                done(true);
            return;
        }
        if (e->key() == Qt::Key_Escape) {
            if (done)
                done(false);
            return;
        }
        QPlainTextEdit::keyPressEvent(e);
    }
    void resizeEvent(QResizeEvent *e) override
    {
        QPlainTextEdit::resizeEvent(e);
        fit();
    }
};
} // namespace

QPlainTextEdit *noteEditor(const QString &text, QWidget *parent, const std::function<void(bool keep)> &done)
{
    auto edit = new NoteEditor(parent);
    edit->setPlainText(text);
    edit->done = done;
    edit->setPlaceholderText(QObject::tr("What should change?"));
    edit->fit();
    return edit;
}

ReviewWindow::ReviewWindow(MainWindow *window)
    : QWidget(window, Qt::Window)
    , m_window(window)
{
    setupAppearance();

    const QFileInfo project(window->fileName());
    // the project's own folder, <stem>.letitedit (an old <stem>.shotcut is moved there first)
    m_dir = window->fileName().isEmpty()
                ? project.dir().filePath(project.completeBaseName() + QStringLiteral(".letitedit/review"))
                : leSideFolder(window->fileName()) + QStringLiteral("/review");
    m_fps = MLT.profile().fps();
    if (window->multitrack())
        m_length = qMax(1, window->multitrack()->get_length());

    auto outer = new QVBoxLayout(this);
    outer->setContentsMargins(16, 12, 16, 12);
    outer->setSpacing(10);

    buildToolbar(outer, project);

    // middle: the picture, and the notes beside it
    auto middle = new QHBoxLayout;
    middle->setSpacing(14);
    auto left = new QVBoxLayout;
    buildCanvas(left);
    buildTransport(left);
    middle->addLayout(left, 1);

    auto sideOuter = new QVBoxLayout;
    auto side = buildNotesPanel(sideOuter);
    buildSettingsPopup();
    const QString prefsPath = Settings.appDataLocation() + QStringLiteral("/review-talk-draw.ini");
    QSettings reviewSettings(prefsPath, QSettings::IniFormat);
    restoreTalkSettings(reviewSettings, prefsPath);
    buildNoteControls(side);
    buildSubmitControls(sideOuter);
    auto sideWidget = new QWidget;
    sideWidget->setLayout(sideOuter);
    sideWidget->setFixedWidth(380);
    middle->addWidget(sideWidget);
    outer->addLayout(middle, 1);
    buildKeyboardHelp(left);

    connectPlayer();
    restoreReview(reviewSettings, prefsPath);
}

void ReviewWindow::setupAppearance()
{
    using namespace LetItEditColors;
    setObjectName(QStringLiteral("reviewWindow"));
    setAttribute(Qt::WA_DeleteOnClose);
    connect(m_window, &MainWindow::aboutToShutDown, this, [this]() {
        close();
        delete this;
    });
    setWindowTitle(tr("Review - letitedit"));
    setAutoFillBackground(true);
    QPalette pal = palette();
    pal.setColor(QPalette::Window, QColor(ink));
    setPalette(pal);
    setStyleSheet(QStringLiteral(
                      "#reviewWindow QPushButton, #reviewWindow QToolButton { background: %1; color: %2; border: 1px "
                      "solid %3; border-radius: 6px; padding: 6px 12px; }"
                      "#reviewWindow QToolButton:checked { background: %4; border-color: %5; }"
                      "#reviewWindow QPushButton:hover, #reviewWindow QToolButton:hover { border-color: %6; }"
                      "#reviewWindow QPushButton#reviewSubmit { background: %7; border-color: %7; font-weight: 600; }"
                      "#reviewWindow QPushButton#reviewSubmit:disabled { background: %1; color: %8; border-color: %3; }"
                      "#reviewWindow QPushButton#reviewTalk:checked { background: %7; border-color: %7; }"
                      "#reviewWindow QLineEdit, #reviewWindow QComboBox { background: %9; color: %2; border: 1px solid "
                      "%3; border-radius: 6px; padding: 7px; }"
                      "#reviewWindow QPlainTextEdit { background: %9; color: %2; border: 1px solid %5; border-radius: 6px; "
                      "padding: 3px; }"
                      "#reviewWindow QListWidget { background: %9; color: %2; border: 1px solid %3; border-radius: "
                      "6px; }"
                      "#reviewWindow QListWidget::item { padding: 8px 6px; border-bottom: 1px solid %3; }"
                      "#reviewWindow QListWidget::item:selected { background: %10; }"
                      "#reviewWindow QLabel { color: %2; }")
                      .arg(raised, cream, line, tealDeep, teal, muted, rust, dim, panel, tealDeep));
}

void ReviewWindow::buildToolbar(QVBoxLayout *outer, const QFileInfo &project)
{
    using namespace LetItEditColors;
    // top: what this is, undo a mark, close. Nothing to pick: press and draw.
    auto top = new QHBoxLayout;
    auto title = new QLabel(QStringLiteral("<b>%1</b> &nbsp;<span style='color:%2'>%3</span>")
                                .arg(tr("Review"), muted, project.completeBaseName().toHtmlEscaped()));
    top->addWidget(title);
    top->addSpacing(24);
    auto undo = flatButton(tr("Undo mark (Ctrl+Z)"));
    undo->setObjectName(QStringLiteral("reviewUndoMark"));
    undo->setToolTip(tr("Take back the last mark"));
    connect(undo, &QToolButton::clicked, this, [this]() { undoMark(); });
    top->addWidget(undo);
    auto clear = flatButton(tr("Clear this frame"));
    clear->setObjectName(QStringLiteral("reviewClear"));
    clear->setToolTip(tr("Remove every mark on this frame"));
    connect(clear, &QToolButton::clicked, this, [this]() {
        if (m_recording)
            return;
        if (auto strokes = activeStrokes()) {
            strokes->clear();
            dropIfEmpty();
            changed();
        }
    });
    top->addWidget(clear);
    top->addStretch(1);
    m_fullScreen = flatButton(tr("Full screen (F)"));
    m_fullScreen->setObjectName(QStringLiteral("reviewFullScreen"));
    m_fullScreen->setToolTip(tr("Fill the whole screen, or go back to a window (F or F11)"));
    connect(m_fullScreen, &QToolButton::clicked, this, [this]() { toggleFullScreen(); });
    top->addWidget(m_fullScreen);
    m_settings = flatButton(QStringLiteral("\u2699"));
    m_settings->setObjectName(QStringLiteral("reviewSettings"));
    m_settings->setToolTip(tr("Review settings"));
    m_settings->setStyleSheet(QStringLiteral("font-size: 15px; padding: 3px 10px;"));
    top->addWidget(m_settings);
    auto close = flatButton(tr("Back to editing (Esc)"));
    close->setObjectName(QStringLiteral("reviewClose"));
    close->setToolTip(tr("Back to editing. Notes you have not sent are kept for next time."));
    connect(close, &QToolButton::clicked, this, &QWidget::close);
    top->addWidget(close);
    outer->addLayout(top);
    buildOffer(outer);
}

void ReviewWindow::buildCanvas(QVBoxLayout *left)
{
    m_canvas = new Canvas(this);
    m_canvas->setObjectName(QStringLiteral("reviewCanvas"));
#ifdef Q_OS_WIN
    if (qEnvironmentVariable("LETITEDIT_LIVE_SCENES") != QLatin1String("0")) {
        m_liveScene = std::make_unique<LiveCodeOverlay>(m_canvas, true);
        m_canvas->markupChanged = [this]() { updateReviewMarkup(); };
    }
#endif
    m_canvas->dar = MLT.profile().dar() > 0 ? MLT.profile().dar() : 16.0 / 9.0;
    m_canvas->target = [this]() { return activeStrokes(); };
    m_canvas->shown = [this](QVector<Stroke> &strokes, QList<int> &numbers) { shownStrokes(strokes, numbers); };
    m_canvas->strokeStarted = [this](Stroke &s) {
        s.frame = m_position;
        if (!m_recording)
            return;
        s.t0 = m_prerollMs + m_clock.elapsed();
        // the player's frame itself: made into a picture when it is saved, never while drawing
        if (Timing::get().legacy)
            s.image = m_canvas->image;
        else {
            s.image = captureScenePicture();
            if (s.image.isNull())
                s.shot = m_frame;
        }
    };
    m_canvas->beginDraw = [this]() {
        if (m_recording)
            return; // the video keeps going while you talk and draw
        if (m_listening && startTake()) {
            m_takeByPen = true; // talking while drawing: the words and the marks are one note; no words, a drawing
            return;
        }
        stopPlaying();
        if (noteAt(m_position) < 0 && m_draft.isEmpty()) {
            m_draftFrame = m_position;
            if (Timing::get().legacy)
                m_draftImage = m_canvas->image;
            else {
                m_draftImage = captureScenePicture();
                if (m_draftImage.isNull())
                    m_draftShot = m_frame;
            }
        }
    };
    m_canvas->resized = [this]() {
        requestPicture();
#ifdef Q_OS_WIN
        if (m_liveScene) m_liveScene->setPictureRect(m_canvas->pictureRect());
#endif
    };
    m_canvas->changed = [this]() {
        if (m_recording) {
            if (!m_take.strokes.isEmpty() && m_take.strokes.last().t1 < 0)
                m_take.strokes.last().t1 = m_prerollMs + m_clock.elapsed();
            m_lastPenUpMs = m_audio ? m_audio->clock.elapsed() : 0;
            m_lastMarkId = -2;
            m_lastMarkIndex = m_take.strokes.size() - 1;
            m_lastMarkFrame = m_position;
            m_canvas->update();
            return;
        }
        if (auto strokes = activeStrokes(); strokes && !strokes->isEmpty()) {
            const int i = noteAt(m_position);
            m_lastMarkId = i < 0 ? 0 : m_notes[i].id;
            m_lastMarkIndex = strokes->size() - 1;
            m_lastMarkFrame = m_position;
        }
        changed();
    };
    left->addWidget(m_canvas, 1);
}

void ReviewWindow::buildTransport(QVBoxLayout *left)
{
    using namespace LetItEditColors;
    auto transport = new QHBoxLayout;
    m_play = flatButton(tr("Play"));
    m_play->setObjectName(QStringLiteral("reviewPlay"));
    m_play->setMinimumWidth(80);
    m_play->setToolTip(tr("Play or pause (Space)"));
    connect(m_play, &QToolButton::clicked, this, [this]() { togglePlay(); });
    transport->addWidget(m_play);
    for (const auto &[label, step, name] : {std::tuple<QString, int, const char *>{tr("-1s"), -qRound(m_fps), "reviewBackSecond"},
                                            {tr("-1 frame"), -1, "reviewBackFrame"},
                                            {tr("+1 frame"), 1, "reviewForwardFrame"},
                                            {tr("+1s"), qRound(m_fps), "reviewForwardSecond"}}) {
        auto b = flatButton(label);
        b->setObjectName(QString::fromLatin1(name));
        connect(b, &QToolButton::clicked, this, [this, step]() { stepFrame(step); });
        transport->addWidget(b);
    }
    // the speed it plays at, beside Play (T210); the engine plays slower than normal frame by frame, without sound
    auto speeds = new QHBoxLayout;
    speeds->setSpacing(0);
    for (const auto &[label, speed, name, tip] :
         {std::tuple<QString, double, const char *, QString>{QStringLiteral("\u00BC\u00D7"), 0.25, "reviewSpeed025", tr("Quarter speed (no sound)")},
          {QStringLiteral("\u00BD\u00D7"), 0.5, "reviewSpeed05", tr("Half speed (no sound)")},
          {QStringLiteral("1\u00D7"), 1.0, "reviewSpeed10", tr("Normal speed")},
          {QStringLiteral("2\u00D7"), 2.0, "reviewSpeed20", tr("Double speed (no sound)")}}) {
        auto b = flatButton(label, true);
        b->setObjectName(QString::fromLatin1(name));
        b->setToolTip(tip);
        b->setProperty("speed", speed);
        b->setStyleSheet(QStringLiteral("padding: 6px 8px;"));
        connect(b, &QToolButton::clicked, this, [this, speed]() { setSpeed(speed); });
        speeds->addWidget(b);
        m_speedButtons << b;
    }
    transport->addSpacing(6);
    transport->addLayout(speeds);
    m_scrubber = new Scrubber(this);
    m_scrubber->setObjectName(QStringLiteral("reviewScrubber"));
    m_scrubber->length = m_length;
    m_scrubber->seek = [this](int frame) {
        if (m_live) { // they stay in charge: scrubbing leaves it playing or paused
            m_window->seekTimeline(frame);
            return;
        }
        if (!m_recording)
            stopPlaying(); // a spoken note goes on as it was, playing or not, from the new place
        m_window->seekTimeline(frame);
    };
    transport->addWidget(m_scrubber, 1);
    m_time = new QLabel;
    m_time->setObjectName(QStringLiteral("reviewTime"));
    m_time->setFixedWidth(130); // a fixed width: the time changes every frame without moving the layout
    m_time->setAlignment(Qt::AlignRight | Qt::AlignVCenter);
    transport->addWidget(m_time);
    left->addLayout(transport);
    // T214: while a heavy video's smooth playback is being made in the background (it plays as it can meanwhile)
    m_smoothLine = new QLabel(tr("Preparing smooth playback"));
    m_smoothLine->setObjectName(QStringLiteral("reviewSmoothPlayback"));
    m_smoothLine->setStyleSheet(QStringLiteral("color: %1; font-size: 12px;").arg(muted));
    m_smoothLine->hide();
    left->addWidget(m_smoothLine);
    m_smoothTimer.setInterval(500);
    connect(&m_smoothTimer, &QTimer::timeout, this, [this]() {
        const bool preparing = RenderedPreview::preparing();
        if (m_smoothLine->isVisible() != preparing)
            m_smoothLine->setVisible(preparing);
    });
    m_smoothTimer.start();
}

QVBoxLayout *ReviewWindow::buildNotesPanel(QVBoxLayout *sideOuter)
{
    using namespace LetItEditColors;
    sideOuter->setSpacing(8);
    m_liveSwitch = new QCheckBox(tr("Live Review"));
    m_liveSwitch->setObjectName(QStringLiteral("reviewLiveSwitch"));
    m_liveSwitch->setFocusPolicy(Qt::NoFocus);
    m_liveSwitch->setStyleSheet(QStringLiteral("font-weight: 600; font-size: 14px;"));
    m_liveSwitch->setToolTip(tr("Watch and just talk and draw: your AI fixes things while you watch. Turn it off any time."));
    sideOuter->addWidget(m_liveSwitch);
    buildLiveBox(sideOuter);
    m_classicBox = new QWidget;
    auto side = new QVBoxLayout(m_classicBox);
    side->setContentsMargins(0, 0, 0, 0);
    side->setSpacing(8);
    auto how = new QLabel(tr("Talk and draw on the picture: what you say while you draw is one note. Or draw and type "
                             "a note."));
    how->setWordWrap(true);
    how->setStyleSheet(QStringLiteral("color: %1;").arg(muted));
    side->addWidget(how);
    m_listeningSign = new QLabel(tr("● Listening — microphone on"));
    m_listeningSign->setObjectName(QStringLiteral("reviewListening"));
    m_listeningSign->setToolTip(tr("While Review is open the microphone keeps only the last three seconds in memory, "
                                   "until you start a note by drawing or pressing T."));
    m_listeningSign->setStyleSheet(QStringLiteral("color: %1; font-weight: 600;").arg(tealLight));
    m_listeningSign->hide();
    side->addWidget(m_listeningSign);
    return side;
}

void ReviewWindow::buildSettingsPopup()
{
    using namespace LetItEditColors;
    m_settingsPanel = new QFrame(this, Qt::Popup);
    m_settingsPanel->setObjectName(QStringLiteral("reviewSettingsPanel"));
    m_settingsPanel->setStyleSheet(QStringLiteral("QFrame#reviewSettingsPanel { background: %1; border: 1px solid %2; "
                                                  "border-radius: 8px; } QLabel, QCheckBox { color: %3; }")
                                       .arg(panel, line, cream));
    auto settingsBox = new QVBoxLayout(m_settingsPanel);
    settingsBox->setContentsMargins(14, 12, 14, 12);
    settingsBox->setSpacing(10);
    m_listenSwitch = new QCheckBox(tr("Talk while I draw"));
    m_listenSwitch->setObjectName(QStringLiteral("reviewListenSwitch"));
    m_listenSwitch->setToolTip(tr("On: what you say while you draw becomes the note. The microphone keeps only the last "
                                  "three seconds in memory until you start a note."));
    settingsBox->addWidget(m_listenSwitch);
    auto pauseRow = new QHBoxLayout;
    pauseRow->addWidget(new QLabel(tr("Pause that ends a note:")));
    m_pauseBox = new QComboBox;
    m_pauseBox->setObjectName(QStringLiteral("reviewPause"));
    for (int ms : {1000, 1500, 2000, 3000})
        m_pauseBox->addItem(ms == kNotePauseMs ? tr("%1 seconds (usual)").arg(ms / 1000.0)
                            : ms == 1000        ? tr("1 second")
                                                : tr("%1 seconds").arg(ms / 1000.0),
                            ms);
    if (m_pauseBox->findData(kNotePauseMs) < 0)
        m_pauseBox->insertItem(0, tr("%1 seconds (usual)").arg(kNotePauseMs / 1000.0), kNotePauseMs);
    pauseRow->addWidget(m_pauseBox, 1);
    settingsBox->addLayout(pauseRow);
    m_autoSend = new QCheckBox(tr("Send after I finish speaking"));
    m_autoSend->setObjectName(QStringLiteral("reviewAutoSend"));
    m_autoSend->setToolTip(tr("Off: review, edit or delete the note, then press Send."));
    settingsBox->addWidget(m_autoSend);
    connect(m_settings, &QToolButton::clicked, this, [this]() {
        m_settingsPanel->adjustSize();
        m_settingsPanel->move(m_settings->mapToGlobal(QPoint(m_settings->width() - m_settingsPanel->width(),
                                                             m_settings->height() + 4)));
        m_settingsPanel->show();
    });
}

void ReviewWindow::restoreTalkSettings(QSettings &reviewSettings, const QString &prefsPath)
{
    m_autoSend->setChecked(reviewSettings.value(QStringLiteral("review/autoSend"), true).toBool());
    // a new key: the old switch's saved "off" (from when it sat on the main screen, off by default) is not carried over;
    // only a choice made behind the gear is kept
    m_listenSwitch->setChecked(reviewSettings.value(QStringLiteral("review/talkWhileDrawing"), true).toBool());
    {
        const int saved = reviewSettings.value(QStringLiteral("review/pauseMs"), kNotePauseMs).toInt();
        const int at = m_pauseBox->findData(saved);
        m_pauseBox->setCurrentIndex(at >= 0 ? at : m_pauseBox->findData(kNotePauseMs));
        m_pauseMs = m_pauseBox->currentData().toInt();
    }
    connect(m_pauseBox, &QComboBox::currentIndexChanged, this, [this, prefsPath]() {
        m_pauseMs = m_pauseBox->currentData().toInt();
        QSettings(prefsPath, QSettings::IniFormat).setValue(QStringLiteral("review/pauseMs"), m_pauseMs);
    });
    connect(m_listenSwitch, &QCheckBox::toggled, this, [this, prefsPath](bool on) {
        QSettings(prefsPath, QSettings::IniFormat).setValue(QStringLiteral("review/talkWhileDrawing"), on);
        if (!m_live)
            setListening(on);
    });
    connect(m_autoSend, &QCheckBox::toggled, this, [prefsPath](bool on) {
        QSettings(prefsPath, QSettings::IniFormat).setValue(QStringLiteral("review/autoSend"), on);
    });
}

void ReviewWindow::buildNoteControls(QVBoxLayout *side)
{
    auto talkRow = new QHBoxLayout;
    m_talk = new QPushButton(tr("Start spoken note (T)"));
    m_talk->setObjectName(QStringLiteral("reviewTalk"));
    m_talk->setCheckable(true);
    m_talk->setFocusPolicy(Qt::NoFocus);
    m_talk->setMinimumHeight(38);
    m_talk->setToolTip(tr("Starts a spoken note before the first mark. Press again to finish."));
    m_talkTimer.setInterval(200);
    connect(&m_talkTimer, &QTimer::timeout, this, [this]() { updateTalkButton(); checkPause(); });
    connect(m_talk, &QPushButton::clicked, this, [this](bool on) {
        if (on)
            startTake();
        else
            stopTake();
    });
    talkRow->addWidget(m_talk, 1);
    side->addLayout(talkRow);
    m_input = new QLineEdit;
    m_input->setObjectName(QStringLiteral("reviewInput"));
    m_input->setPlaceholderText(tr("Or type what should change here"));
    connect(m_input, &QLineEdit::returnPressed, this, [this]() { addNote(); });
    connect(m_input, &QLineEdit::textEdited, this, [this]() {
        if (m_recording && m_takeByPen && !m_heardSpeech && !m_live)
            stopTake(); // typing over a drawing nobody talked over: a typed note, the drawing goes with it
    });
    side->addWidget(m_input);
    auto row = new QHBoxLayout;
    m_whole = new QCheckBox(tr("About the whole video"));
    m_whole->setObjectName(QStringLiteral("reviewWhole"));
    m_whole->setFocusPolicy(Qt::NoFocus);
    row->addWidget(m_whole, 1);
    auto add = new QPushButton(tr("Add note"));
    add->setObjectName(QStringLiteral("reviewAdd"));
    add->setFocusPolicy(Qt::NoFocus);
    connect(add, &QPushButton::clicked, this, [this]() { addNote(); });
    row->addWidget(add);
    side->addLayout(row);
    m_list = new QListWidget;
    m_list->setObjectName(QStringLiteral("reviewNotes"));
    m_list->setWordWrap(true);
    m_list->setFocusPolicy(Qt::NoFocus); // the keys stay with the player (T210)
    connect(m_list, &QListWidget::itemDoubleClicked, this, [this]() { startEditClassic(); });
    connect(m_list, &QListWidget::itemClicked, this, [this](QListWidgetItem *item) {
        const int i = item->data(Qt::UserRole).toInt();
        if (m_recording || i < 0 || i >= m_notes.size() || m_notes[i].frame < 0)
            return;
        stopPlaying();
        m_window->seekTimeline(m_notes[i].frame);
    });
    side->addWidget(m_list, 1);
    // editing a note: a box that wraps and grows with the words (T210; it was a separate window)
    m_classicEditBox = new QWidget;
    auto editRow = new QVBoxLayout(m_classicEditBox);
    editRow->setContentsMargins(0, 0, 0, 0);
    editRow->setSpacing(4);
    m_classicEdit = noteEditor(QString(), m_classicEditBox, [this](bool keep) { finishEditClassic(keep); });
    m_classicEdit->setObjectName(QStringLiteral("reviewEditBox"));
    editRow->addWidget(m_classicEdit);
    auto editButtons = new QHBoxLayout;
    auto editDone = new QPushButton(tr("Done (Enter)"));
    editDone->setObjectName(QStringLiteral("reviewEditDone"));
    connect(editDone, &QPushButton::clicked, this, [this]() { finishEditClassic(true); });
    auto editCancel = new QPushButton(tr("Cancel (Esc)"));
    editCancel->setObjectName(QStringLiteral("reviewEditCancel"));
    connect(editCancel, &QPushButton::clicked, this, [this]() { finishEditClassic(false); });
    editButtons->addWidget(editDone);
    editButtons->addWidget(editCancel);
    editButtons->addStretch(1);
    editRow->addLayout(editButtons);
    m_classicEditBox->hide();
    side->addWidget(m_classicEditBox);
    auto noteButtons = new QHBoxLayout;
    auto remove = new QPushButton(tr("Delete note"));
    remove->setObjectName(QStringLiteral("reviewDelete"));
    remove->setFocusPolicy(Qt::NoFocus);
    connect(remove, &QPushButton::clicked, this, [this]() { deleteSelected(); });
    noteButtons->addWidget(remove);
    m_again = new QPushButton(tr("Record it again"));
    m_again->setObjectName(QStringLiteral("reviewRecordAgain"));
    m_again->setFocusPolicy(Qt::NoFocus);
    m_again->setToolTip(tr("Throw away this spoken note and record it again from the same moment"));
    connect(m_again, &QPushButton::clicked, this, [this]() { recordAgain(); });
    noteButtons->addWidget(m_again);
    side->addLayout(noteButtons);
    auto edit = new QPushButton(tr("Edit selected note"));
    edit->setObjectName(QStringLiteral("reviewEditNote"));
    edit->setToolTip(tr("Or double-click the note"));
    connect(edit, &QPushButton::clicked, this, [this]() { startEditClassic(); });
    side->addWidget(edit);
    auto range = new QPushButton(tr("Make the mark last until this frame"));
    range->setObjectName(QStringLiteral("reviewRange"));
    range->setToolTip(tr("Draw a mark, step to the frame where it should end, then press here. The mark then stays on screen for all those frames."));
    connect(range, &QPushButton::clicked, this, [this]() { setRangeEnd(); });
    side->addWidget(range);
    // a take whose words could not be written down: try again (the note can also go as it is)
    m_retry = new QPushButton(tr("Write it down again"));
    m_retry->setObjectName(QStringLiteral("reviewRetryWords"));
    m_retry->setFocusPolicy(Qt::NoFocus);
    m_retry->setToolTip(tr("Try again to write down what you said in the spoken notes that have no words yet"));
    m_retry->hide();
    connect(m_retry, &QPushButton::clicked, this, [this]() {
        const QList<int> ids = m_unwritten.values();
        for (int id : ids)
            m_live ? queueWords(id) : transcribe(id);
    });
    side->addWidget(m_retry);
    connect(m_list, &QListWidget::currentRowChanged, this, [this]() { updateAgain(); });
}

void ReviewWindow::buildSubmitControls(QVBoxLayout *sideOuter)
{
    using namespace LetItEditColors;
    sideOuter->addWidget(m_classicBox, 1);
    m_status = new QLabel;
    m_status->setObjectName(QStringLiteral("reviewStatus"));
    m_status->setWordWrap(true);
    m_status->setStyleSheet(QStringLiteral("color: %1;").arg(tealLight));
    sideOuter->addWidget(m_status);
    // T221: what the AI is on and what waits; notes sent while it works wait their turn and go by themselves
    m_queueLine = new QLabel;
    m_queueLine->setObjectName(QStringLiteral("reviewQueue"));
    m_queueLine->setWordWrap(true);
    m_queueLine->setStyleSheet(QStringLiteral("color: %1; font-weight: 600;").arg(cream));
    m_queueLine->hide();
    sideOuter->addWidget(m_queueLine);
    m_queueTimer.setInterval(500);
    connect(&m_queueTimer, &QTimer::timeout, this, [this]() {
        const bool wasStuck = m_submit && m_submit->text() == tr("Send the waiting notes again");
        refreshQueueLine();
        if (!m_live && m_notes.isEmpty() && wasStuck != NoteQueue::of(m_window).stuck())
            refresh();
    });
    m_queueTimer.start();
    m_submit = new QPushButton(tr("Send to your AI"));
    m_submit->setObjectName(QStringLiteral("reviewSubmit"));
    m_submit->setFocusPolicy(Qt::NoFocus);
    m_submit->setMinimumHeight(42);
    m_submit->setToolTip(tr("Your AI makes the changes, one Undo step each. The video as it is now is kept as an "
                            "earlier version."));
    connect(m_submit, &QPushButton::clicked, this, [this]() {
        if (!m_live && m_recording) { // a note still being spoken closes now and goes with the rest
            m_sendWhenWritten = true;
            stopTake();
            if (!m_transcribing && m_sendWhenWritten)
                submit();
            return;
        }
        m_live ? sendAllCards() : submit();
    });
    sideOuter->addWidget(m_submit);
}

void ReviewWindow::buildKeyboardHelp(QVBoxLayout *left)
{
    using namespace LetItEditColors;
    // the keys in one short line under the player, and how a note ends (T210)
    auto keys = new QLabel(tr("<b>Space</b> play / pause &nbsp; <b>\u2190 \u2192</b> or <b>A D</b> a frame, hold for "
                              "faster &nbsp; <b>J K L</b> back, stop, forward &nbsp; <b>\u2191 \u2193</b> or <b>W S</b> "
                              "previous / next note &nbsp; <b>T</b> spoken note &nbsp; <b>Ctrl+Z</b> undo a mark &nbsp; "
                              "<b>F</b> full screen &nbsp; <b>Esc</b> back to editing"));
    keys->setObjectName(QStringLiteral("reviewKeys"));
    keys->setStyleSheet(QStringLiteral("color: %1; font-size: 12px;").arg(muted));
    keys->setWordWrap(true);
    left->addWidget(keys);
    auto ends = new QLabel(tr("Talk while you watch and draw. A note ends when you stop talking for a moment."));
    ends->setObjectName(QStringLiteral("reviewHowNotesEnd"));
    ends->setStyleSheet(QStringLiteral("color: %1; font-size: 12px;").arg(muted));
    left->addWidget(ends);
}

void ReviewWindow::connectPlayer()
{
    // the real player drives the picture: what it shows (and plays, with sound) is what is drawn on
    if (auto video = qobject_cast<Mlt::VideoWidget *>(MLT.videoWidget()))
        connect(video, &Mlt::VideoWidget::frameDisplayed, this, [this](const SharedFrame &f) { onFrame(f); },
                Qt::QueuedConnection);
    m_stall.setInterval(5);
    connect(&m_stall, &QTimer::timeout, this, [this]() {
        Timing &t = Timing::get();
        const qint64 now = t.clock.nsecsElapsed();
        if (t.active && m_lastTick > 0)
            t.stallUs << qMax<qint64>(0, (now - m_lastTick) / 1000 - 5000);
        m_lastTick = now;
    });
    if (qEnvironmentVariableIsSet("LETITEDIT_QA"))
        m_stall.start();
    connect(m_window->player(), &Player::played, this, [this](double) { m_play->setText(tr("Pause")); });
    connect(m_window->player(), &Player::paused, this, [this](int) {
        m_play->setText(tr("Play"));
        QTimer::singleShot(0, this, [this]() { evaluateLoading(); });
    });

    m_slow.setInterval(40);
    connect(&m_slow, &QTimer::timeout, this, [this]() { slowTick(); });
}

void ReviewWindow::restoreReview(QSettings &reviewSettings, const QString &prefsPath)
{
    load();
    refresh();
    for (const auto &n : std::as_const(m_notes))
        if (n.take && !n.audio.isEmpty() && n.words.isEmpty() && n.text.isEmpty())
            transcribe(n.id); // closed before its words were written down
    m_position = qMax(0, m_window->player()->position());
    m_window->seekTimeline(m_position);
    RenderedPreview::reviewOpened(m_window, m_position);
    if (auto video = qobject_cast<Mlt::VideoWidget *>(MLT.videoWidget()))
        m_canvas->image = video->image();
    updateTime();
    updateAgain();
    const bool liveOn = reviewSettings.value(QStringLiteral("review/liveReview"), false).toBool();
    {
        const double saved = reviewSettings.value(QStringLiteral("review/speed"), 1.0).toDouble();
        setSpeed(saved == 0.25 || saved == 0.5 || saved == 2.0 ? saved : 1.0);
    }
    m_liveAutoSend->setChecked(reviewSettings.value(QStringLiteral("review/liveSendWithoutAsking"), false).toBool());
    connect(m_liveAutoSend, &QCheckBox::toggled, this, [prefsPath](bool on) {
        QSettings(prefsPath, QSettings::IniFormat).setValue(QStringLiteral("review/liveSendWithoutAsking"), on);
    });
    connect(m_liveSwitch, &QCheckBox::toggled, this, [this, prefsPath](bool on) {
        QSettings(prefsPath, QSettings::IniFormat).setValue(QStringLiteral("review/liveReview"), on);
        setLive(on);
    });
    if (auto session = LiveReview::Session::existing(m_window))
        attachSession(session);
    if (liveOn)
        m_liveSwitch->setChecked(true);
    else
        setLive(false); // talking and drawing together is the usual way: it listens from the start (T210)
    // nothing beside the picture takes the keys: they belong to the player (typing in a box still types)
    for (auto *b : findChildren<QAbstractButton *>())
        b->setFocusPolicy(Qt::NoFocus);
    m_canvas->setFocusPolicy(Qt::StrongFocus);
    qApp->installEventFilter(this);
    // the first time: what Live Review is, turn it on or watch without it
    if (!reviewSettings.value(QStringLiteral("review/liveOffered"), false).toBool()
        && !qEnvironmentVariableIsSet("LETITEDIT_QA_REVIEW_NO_OFFER"))
        m_offer->show();
    if (auto banner = m_window->player()->findChild<QWidget *>(QStringLiteral("liveReviewBanner")))
        banner->deleteLater();
}

ReviewWindow::~ReviewWindow()
{
    m_closing = true;
    updateCopyPause();
    m_alive = false;
    qApp->removeEventFilter(this);
    lightPreview(false);
    RenderedPreview::setStepping(false);
    RenderedPreview::reviewClosed();
}

QJsonObject ReviewWindow::state() const
{
    int takes = 0;
    for (const auto &n : m_notes)
        takes += n.take;
    return QJsonObject{{"open", true},
                       {"notes", int(m_notes.size())},
                       {"takes", takes},
                       {"recording", m_recording},
                       {"listening", m_listening},
                       {"listening_sign", m_listeningSign->isVisible()},
                       {"auto_send", m_autoSend->isChecked()},
                       {"pause_ms", m_pauseMs},
                       {"text_ready_ms", kTextReadyMs},
                       {"preview", QJsonObject{{"text", m_previewResult.value("text").toString()},
                                               {"text_after_last_word_ms", m_textReadyMs}}},
                       {"talk_while_draw", m_listenSwitch->isChecked()},
                       {"speed", m_speed},
                       {"playing", !MLT.isPaused() || m_slow.isActive()},
                       {"full_screen", isFullScreen()},
                       {"window", QJsonObject{{"width", width()}, {"height", height()}, {"maximized", isMaximized()}}},
                       {"focus", focusWidget() ? focusWidget()->objectName() : QString()},
                       {"editing_note", m_classicEditing >= 0 || m_editingId >= 0},
                       {"playback", QJsonObject{{"speed", m_playback.speed},
                                                {"seconds", m_playback.clock.isValid() ? m_playback.clock.elapsed() / 1000.0 : 0.0},
                                                {"frames_moved", m_playback.lastFrame - m_playback.startFrame},
                                                {"shown", m_playback.shown},
                                                {"skipped", m_playback.skipped},
                                                {"light_preview", m_previewLight}}},
                       {"preroll_ms", m_prerollMs},
                       {"transcribing", m_transcribing},
                       {"position", m_position},
                       {"status", m_status->text()},
                       {"queue", QJsonObject{{"line", m_queueLine ? m_queueLine->text() : QString()},
                                             {"working", NoteQueue::of(m_window).working()},
                                             {"waiting", NoteQueue::of(m_window).waiting()}}},
                       {"talk", m_talk->text()},
                       {"submit", m_submit->text()},
                       {"submit_enabled", m_submit->isEnabled()},
                       {"again_visible", m_again->isVisible()},
                       {"unwritten", int(m_unwritten.size())},
                       {"retry_visible", m_retry->isVisible()},
                       {"picture", QJsonObject{{"width", m_canvas->image.width()}, {"height", m_canvas->image.height()}}},
                       {"area", QJsonObject{{"width", m_canvas->pictureSize().width()},
                                            {"height", m_canvas->pictureSize().height()}}},
                       {"live", liveState()},
                       {"smooth_line", m_smoothLine->isVisible()},
                       {"rendered_preview", RenderedPreview::state()},
                       {"timing", Timing::get().json()}};
}

// The keys belong to the player (T210): whatever is under the mouse or was clicked last on the side, Space plays and
// the arrows step. Only a box being typed in keeps its keys (Esc leaves it).
static bool typingIn(QWidget *w)
{
    return qobject_cast<QLineEdit *>(w) || qobject_cast<QPlainTextEdit *>(w) || qobject_cast<QTextEdit *>(w);
}

bool ReviewWindow::eventFilter(QObject *watched, QEvent *event)
{
    const auto type = event->type();
    if (type != QEvent::KeyPress && type != QEvent::KeyRelease && type != QEvent::ShortcutOverride)
        return QWidget::eventFilter(watched, event);
    auto w = qobject_cast<QWidget *>(watched);
    if (!w || w->window() != this)
        return QWidget::eventFilter(watched, event);
    auto e = static_cast<QKeyEvent *>(event);
    if (typingIn(focusWidget())) {
        if (type == QEvent::KeyPress && e->key() == Qt::Key_Escape && m_editingId < 0 && m_classicEditing < 0) {
            m_canvas->setFocus(); // out of the box; the next Esc leaves Review
            return true;
        }
        return QWidget::eventFilter(watched, event);
    }
    if (type == QEvent::ShortcutOverride) {
        // the player's keys are this window's, never an editor shortcut's
        const auto mods = e->modifiers() & ~(Qt::ShiftModifier | Qt::KeypadModifier);
        static const QSet<int> mine{Qt::Key_Space, Qt::Key_Left, Qt::Key_Right, Qt::Key_Up, Qt::Key_Down, Qt::Key_A,
                                    Qt::Key_D, Qt::Key_W, Qt::Key_S, Qt::Key_J, Qt::Key_K, Qt::Key_L, Qt::Key_T,
                                    Qt::Key_F, Qt::Key_F11};
        if (mods == Qt::NoModifier && mine.contains(e->key())) {
            e->accept();
            return true;
        }
        return QWidget::eventFilter(watched, event);
    }
    if (watched == this)
        return QWidget::eventFilter(watched, event); // the window's own handlers below
    if (type == QEvent::KeyRelease) {
        keyReleaseEvent(e);
        return e->isAccepted();
    }
    return handleKey(e);
}

void ReviewWindow::changeEvent(QEvent *e)
{
    QWidget::changeEvent(e);
    if (e->type() == QEvent::WindowStateChange && m_fullScreen)
        m_fullScreen->setText(isFullScreen() ? tr("Window (F)") : tr("Full screen (F)"));
}

void ReviewWindow::keyPressEvent(QKeyEvent *e)
{
    if (!handleKey(e))
        QWidget::keyPressEvent(e);
}

void ReviewWindow::keyReleaseEvent(QKeyEvent *e)
{
    const int k = e->key();
    if (!e->isAutoRepeat() && (k == Qt::Key_Left || k == Qt::Key_Right || k == Qt::Key_A || k == Qt::Key_D)) {
        m_heldKey = 0;
        e->accept();
        return;
    }
    e->ignore();
}

bool ReviewWindow::handleKey(QKeyEvent *e)
{
    const int k = e->key();
    const auto mods = e->modifiers() & ~Qt::KeypadModifier;
    const bool plain = (mods & ~Qt::ShiftModifier) == Qt::NoModifier;
    if (k == Qt::Key_Escape) {
        if (m_editingId >= 0) {
            m_editingId = -1; // leaves the edit, as it was
            m_canvas->setFocus();
            refreshLiveList();
        } else if (m_classicEditing >= 0) {
            finishEditClassic(false);
        } else if (isFullScreen()) {
            toggleFullScreen();
        } else {
            close();
        }
    } else if (plain && (k == Qt::Key_Return || k == Qt::Key_Enter)) {
        if (m_live && m_recording)
            stopTake(); // the note closes now; its card then has Send
        else if (m_live)
            sendNewestCard();
        else if (m_recording && m_submit->isEnabled())
            m_submit->click();
        else
            return false;
    } else if (e->matches(QKeySequence::Undo)) {
        undoMark();
    } else if (!plain) {
        return false;
    } else if (k == Qt::Key_Space) {
        if (!e->isAutoRepeat())
            togglePlay();
    } else if (k == Qt::Key_K) {
        m_shuttle = 0;
        stopPlaying();
    } else if (k == Qt::Key_J || k == Qt::Key_L) {
        if (!e->isAutoRepeat())
            shuttle(k == Qt::Key_L ? 1 : -1);
    } else if (k == Qt::Key_T) {
        if (!e->isAutoRepeat())
            m_talk->click();
    } else if (k == Qt::Key_F || k == Qt::Key_F11) {
        if (!e->isAutoRepeat())
            toggleFullScreen();
    } else if (k == Qt::Key_Left || k == Qt::Key_Right || k == Qt::Key_A || k == Qt::Key_D) {
        const int direction = (k == Qt::Key_Left || k == Qt::Key_A) ? -1 : 1;
        int step = 1;
        if (mods & Qt::ShiftModifier) {
            step = qRound(m_fps);
        } else if (!e->isAutoRepeat() || m_heldKey != k) {
            m_heldKey = k;
            m_heldSince.start();
        } else {
            // held down: a frame at a time, then more and more frames per step, then a fast scrub
            const qint64 held = m_heldSince.elapsed();
            step = held < 600 ? 1 : held < 1500 ? 2 : held < 2500 ? 4 : held < 4000 ? qMax(1, qRound(m_fps / 4))
                                                                                   : qMax(1, qRound(m_fps / 2));
        }
        stepFrame(direction * step);
    } else if (k == Qt::Key_Up || k == Qt::Key_W || k == Qt::Key_Down || k == Qt::Key_S) {
        jumpNote(k == Qt::Key_Up || k == Qt::Key_W ? -1 : 1);
    } else if (k == Qt::Key_Delete && m_list->currentItem() && !m_live) {
        deleteSelected();
    } else {
        return false;
    }
    e->accept();
    return true;
}

void ReviewWindow::closeEvent(QCloseEvent *e)
{
    QElapsedTimer clock;
    clock.start();
    m_closing = true;
    if (m_recording)
        stopTake(); // the take is transcribed and kept even as the window closes
    setListening(false);
    // A speech helper can still be finishing when Review closes. Its finished/error signals
    // must not call back into a ReviewWindow while Qt tears down its child objects. The
    // recording is already in the draft; opening Review again retries its transcription.
    for (QProcess *process : findChildren<QProcess *>()) {
        process->disconnect(this);
        process->kill();
        delete process;
    }
    m_wordsProcess = nullptr;
    m_wordsTimer.stop();
    m_transcribing = 0;
    m_wordsQueue.clear();
    m_wordsBusy = 0;
    for (auto &n : m_notes)
        n.writing = false;
    commitDraft();
    save(); // the pictures are written after the window has gone
    if (m_session)
        showLiveBanner(m_window);
    Timing::get().closeMs = clock.elapsed();
    QWidget::closeEvent(e);
}

void ReviewWindow::stepFrame(int step)
{
    m_shuttle = 0;
    stopPlaying();
    // from where the last step went, while it is still on its way (a held key asks faster than frames are shown)
    const bool pending = m_stepTarget >= 0 && m_stepTarget != m_position && m_stepClock.isValid()
                         && m_stepClock.elapsed() < 500;
    const int from = pending ? m_stepTarget : m_position;
    m_stepTarget = qBound(0, from + step, m_length - 1);
    m_stepClock.restart();
    m_window->seekTimeline(m_stepTarget);
}

void ReviewWindow::setSpeed(double speed)
{
    const bool playing = (!MLT.isPaused() || m_slow.isActive()) && m_shuttle == 0;
    m_speed = speed;
    for (auto *b : std::as_const(m_speedButtons))
        b->setChecked(qFuzzyCompare(b->property("speed").toDouble(), speed));
    QSettings(Settings.appDataLocation() + QStringLiteral("/review-talk-draw.ini"), QSettings::IniFormat)
        .setValue(QStringLiteral("review/speed"), speed);
    if (playing)
        playAt(speed);
}

// J and L: back and forward, faster with each press (1, 2, 4, 8 times); K or Space stops.
void ReviewWindow::shuttle(int direction)
{
    const bool playing = !MLT.isPaused() || m_slow.isActive();
    int next = direction;
    if (playing && m_shuttle != 0 && (m_shuttle > 0) == (direction > 0))
        next = qBound(-8, m_shuttle * 2, 8);
    else if (playing && m_shuttle == 0 && direction > 0 && m_speed >= 1.0)
        next = 2; // already playing forward: L goes faster
    m_shuttle = next;
    playAt(next == 1 ? m_speed : double(next));
}

// Up and Down: the previous or next note; with no notes, the previous or next cut.
void ReviewWindow::jumpNote(int direction)
{
    const int here = m_stepTarget >= 0 && m_stepClock.isValid() && m_stepClock.elapsed() < 500 ? m_stepTarget : m_position;
    int target = -1;
    for (const auto &n : std::as_const(m_notes)) {
        if (n.frame < 0)
            continue;
        if (direction > 0 && n.frame > here && (target < 0 || n.frame < target))
            target = n.frame;
        if (direction < 0 && n.frame < here && (target < 0 || n.frame > target))
            target = n.frame;
    }
    bool anyNote = false;
    for (const auto &n : std::as_const(m_notes))
        anyNote = anyNote || n.frame >= 0;
    m_shuttle = 0;
    if (m_recording && target >= 0)
        stopTake(); // a jump elsewhere ends the note being spoken
    if (!m_recording)
        stopPlaying();
    if (target >= 0) {
        m_stepTarget = target;
        m_stepClock.restart();
        m_window->seekTimeline(target);
    } else if (!anyNote && m_window->timelineDock()) {
        if (direction > 0)
            m_window->timelineDock()->seekNextEdit();
        else
            m_window->timelineDock()->seekPreviousEdit();
    } else {
        m_status->setText(direction > 0 ? tr("No more notes after this.") : tr("No notes before this."));
    }
}

void ReviewWindow::toggleFullScreen()
{
    const bool full = !isFullScreen();
    if (full)
        showFullScreen();
    else
        showMaximized();
    QSettings(Settings.appDataLocation() + QStringLiteral("/review-talk-draw.ini"), QSettings::IniFormat)
        .setValue(QStringLiteral("review/fullScreen"), full);
}

void ReviewWindow::startEditClassic()
{
    auto item = m_list->currentItem();
    if (!item || m_recording)
        return;
    const int i = item->data(Qt::UserRole).toInt();
    if (i < 0 || i >= m_notes.size())
        return;
    m_classicEditing = m_notes[i].id;
    m_classicEdit->setPlainText(m_notes[i].text);
    m_classicEditBox->show();
    m_classicEdit->setFocus();
    m_classicEdit->moveCursor(QTextCursor::End);
}

void ReviewWindow::finishEditClassic(bool keep)
{
    const int i = noteIndex(m_classicEditing);
    m_classicEditing = -1;
    m_classicEditBox->hide();
    m_canvas->setFocus();
    if (keep && i >= 0) {
        m_notes[i].text = m_classicEdit->toPlainText().trimmed();
        changed();
    }
}

void ReviewWindow::setRangeEnd()
{
    QVector<Stroke> *marks = nullptr;
    if (m_lastMarkId == -2 && m_recording) marks = &m_take.strokes;
    else if (m_lastMarkId == 0) marks = &m_draft;
    else if (m_lastMarkId > 0) {
        const int i = noteIndex(m_lastMarkId);
        if (i >= 0) marks = &m_notes[i].strokes;
    }
    if (!marks || m_lastMarkIndex < 0 || m_lastMarkIndex >= marks->size()) {
        m_status->setText(tr("Draw a mark first, then step to its last frame."));
        return;
    }
    Stroke &mark = (*marks)[m_lastMarkIndex];
    const int first = mark.frame >= 0 ? mark.frame : m_lastMarkFrame;
    if (first < 0 || m_position <= first) {
        m_status->setText(tr("Step forward from the marked frame, then press Make the mark last until this frame."));
        return;
    }
    mark.endFrame = m_position;
    if (!m_recording) changed(); else m_canvas->update();
    m_status->setText(tr("Mark covers %1 to %2.").arg(stamp(mark.frame / m_fps), stamp(mark.endFrame / m_fps)));
}

QToolButton *ReviewWindow::flatButton(const QString &text, bool checkable)
{
    auto b = new QToolButton;
    b->setText(text);
    b->setCheckable(checkable);
    b->setFocusPolicy(Qt::NoFocus);
    return b;
}

void ReviewWindow::updateTalkButton()
{
    if (!m_recording)
        return;
    const int s = int(m_clock.elapsed() / 1000);
    m_talk->setText(tr("\u25CF Listening %1:%2 - press T when done").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0')));
}

void ReviewWindow::onFrame(const SharedFrame &frame)
{
    if (!frame.is_valid())
        return;
    Timing &t = Timing::get();
    const qint64 start = t.clock.nsecsElapsed();
    if (t.legacy) {
        const uint8_t *image = frame.get_image(mlt_image_rgba);
        if (!image)
            return;
        m_canvas->image = QImage(image, frame.get_image_width(), frame.get_image_height(), QImage::Format_RGBA8888).copy();
    } else {
        m_frame = frame;
        requestPicture();
    }
    const int position = frame.get_position();
    if (m_playback.clock.isValid() && position != m_playback.lastFrame && (!MLT.isPaused() || m_slow.isActive())) {
        const int expected = m_playback.speed >= 1.0 || m_playback.speed <= -1.0 ? qRound(m_playback.speed) : 1;
        ++m_playback.shown;
        m_playback.skipped += qMax(0, std::abs(position - m_playback.lastFrame) / qMax(1, std::abs(expected)) - 1);
        m_playback.lastFrame = position;
        // T214: the live picture can't keep up (a tenth of the frames skipped over the first second and a half):
        // a rendered preview is made for this video too
        const int moved = std::abs(m_playback.lastFrame - m_playback.startFrame);
        if (!m_previewAsked && std::abs(m_playback.speed) >= 1.0 && moved >= qRound(m_fps * 1.5)
            && m_playback.skipped * 10 > moved) {
            m_previewAsked = true;
            RenderedPreview::liveCannotKeepUp();
        }
    }
    if (position != m_position) {
        m_position = position;
        if (m_recording)
            m_take.clock.append({m_prerollMs + m_clock.elapsed(), m_position});
        else if (m_position != m_draftFrame)
            commitDraft();
        refreshActive();
        updateReviewMarkup();
        if (t.active)
            ++t.positions;
        if (m_session && m_position >= m_length - 2)
            evaluateLoading();
    }
#ifdef Q_OS_WIN
    if (m_liveScene) {
        m_liveScene->setPictureRect(m_canvas->pictureRect());
        m_liveScene->onFrame(position, m_fps);
    }
#endif
    updateTime();
    if (t.legacy)
        m_canvas->update();
    if (t.active) {
        ++t.framesShown;
        t.frameUs << (t.clock.nsecsElapsed() - start) / 1000;
    }
}

void ReviewWindow::updateTime()
{
    m_time->setText(QStringLiteral("%1 / %2").arg(stamp(m_position / m_fps), stamp(m_length / m_fps)));
    m_scrubber->position = m_position;
    m_scrubber->update();
}

void ReviewWindow::togglePlay()
{
    m_shuttle = 0;
    if (MLT.isPaused() && !m_slow.isActive())
        playAt(m_speed);
    else
        stopPlaying();
}

// The engine plays only whole frames per frame, so slower than normal is stepped here, one frame each frame-time at
// that speed (no sound). Normal, double and the J / L speeds are the engine's own.
void ReviewWindow::playAt(double speed)
{
    m_slow.stop();
    m_playback = Playback();
    m_playback.speed = speed;
    m_playback.startFrame = m_playback.lastFrame = m_position;
    m_playback.clock.start();
    lightPreview(true);
    RenderedPreview::setFocus(m_position);
    if (speed >= 1.0 || speed <= -1.0) {
        RenderedPreview::setStepping(false);
        m_window->player()->play(speed);
        return;
    }
    RenderedPreview::setStepping(true); // the stepped frames come from the preview where it is ready
    m_window->player()->pause();
    m_slow.setTimerType(Qt::PreciseTimer);
    m_slow.setInterval(qMax(10, qRound(1000.0 / (m_fps * speed))));
    m_slowStep = 1;
    m_slowPosition = m_position;
    m_slow.start();
    m_play->setText(tr("Pause"));
}

void ReviewWindow::stopPlaying()
{
    const bool stepped = m_slow.isActive();
    if (m_slow.isActive()) {
        m_slow.stop();
        m_play->setText(tr("Play"));
    }
    RenderedPreview::setStepping(false);
    m_window->player()->pause();
    lightPreview(false);
    if (stepped && RenderedPreview::inUse() && MLT.producer())
        MLT.refreshConsumer(); // the paused frame is drawn live again, at full quality for drawing on
}

void ReviewWindow::slowTick()
{
    if (m_slowPosition > m_position + 1) // the last frame isn't on screen yet: wait for it rather than pile up seeks
        return;
    if (std::abs(m_slowPosition - m_position) > 2)
        m_slowPosition = m_position; // moved by hand meanwhile
    m_slowPosition += m_slowStep;
    const int frame = int(m_slowPosition);
    if (frame >= m_length - 1) {
        stopPlaying();
        return;
    }
    if (frame != m_position)
        m_window->seekTimeline(frame);
}

// While it plays the picture can be made smaller; paused, it is made at full size again for drawing on. Only when the
// person's own preview is full size. Off unless LETITEDIT_REVIEW_PLAY_SCALE names the height while playing: measured
// on a long graded project, 720p and 540p rendered no faster than 1080p (decoding is the cost), so it isn't worth a
// softer picture (tests/t210/REPORT.md).
void ReviewWindow::lightPreview(bool playing)
{
    static const int playScale = qEnvironmentVariableIsSet("LETITEDIT_REVIEW_PLAY_SCALE")
                                     ? qEnvironmentVariableIntValue("LETITEDIT_REVIEW_PLAY_SCALE") : 0;
    const bool light = playing && playScale > 0 && Settings.playerPreviewScale() == 0
                       && MLT.profile().height() > playScale && m_alive;
    if (light == m_previewLight)
        return;
    m_previewLight = light;
    MLT.setPreviewScale(light ? playScale : Settings.playerPreviewScale());
    if (!light && MLT.producer())
        MLT.refreshConsumer();
}

} // namespace ReviewMode
