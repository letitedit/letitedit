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

// The New video dialog: the shell, the steps at the top, Back and Next, what is kept for next time.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

NewVideoDialog::NewVideoDialog(MainWindow *window, bool shortEntry)
    : QDialog(window)
    , m_window(window)
    , m_shortEntry(shortEntry)
{
    setupDialogAppearance(window);

    auto outer = new QVBoxLayout(this);
    outer->setContentsMargins(24, 12, 24, 14);
    outer->setSpacing(8);

    buildStageNavigation(outer);

    m_pages = new QStackedWidget(this);
    m_pages->setObjectName(QStringLiteral("newVideoPages"));
    m_pages->addWidget(formatPage());
    m_pages->addWidget(contentPage());
    m_pages->addWidget(styleChoicePage());
    m_pages->addWidget(stylePage());
    m_pages->addWidget(themePage());
    m_pages->addWidget(readyPage());
    outer->addWidget(m_pages, 1);

    buildStepNotices(outer);

    buildNavigationButtons(outer);

    restore();
    if (shortEntry) {
        m_kind = QStringLiteral("short");
        m_kinds->button(0)->setChecked(true);
        m_useFootageButton->setChecked(true);
    }
    loadStyles();
    loadLooks();
    go(shortEntry ? PContent : PFormat);
}

void NewVideoDialog::setupDialogAppearance(MainWindow *window)
{
    using namespace LetItEditColors;
    setObjectName(QStringLiteral("newVideoDialog"));
    setWindowTitle(tr("New video"));
    setMinimumSize(900, 620);
    // most of the window, so Ready's boxes can use its width, and never taller than the screen (T94: a 768-high laptop)
    QSize wanted(1060, 690);
    if (window)
        wanted = QSize(qBound(900, window->width() - 60, 1500), qBound(620, window->height() - 40, 920));
    if (QScreen *screen = window ? window->screen() : nullptr)
        wanted = wanted.boundedTo(screen->availableGeometry().size() - QSize(16, 40)).expandedTo(minimumSize());
    resize(wanted);
    setStyleSheet(QStringLiteral(
                      "QPushButton[newVideoCard=\"true\"] { background: %1; border: 1px solid %2; border-radius: 12px; "
                      "padding: 0; text-align: left; }"
                      "QPushButton[newVideoCard=\"true\"]:hover { background: %3; border-color: #4A545B; }"
                      "QPushButton[newVideoCard=\"true\"]:checked { background: %4; border: 2px solid %5; }"
                      "QPushButton[newVideoCard=\"true\"]:focus { border-color: %9; }"
                      "QLabel#newVideoCardTitle { font-size: 15px; font-weight: 700; color: %6; }"
                      "QLabel#newVideoCardText { font-size: 12px; color: %7; }"
                      "QLabel#newVideoCardTags { font-size: 11px; color: %8; }"
                      "QLabel#newVideoCardBadge { font-size: 11px; font-weight: 700; color: %6; background: %5; "
                      "border-radius: 8px; padding: 2px 8px; }"
                      "QLabel#newVideoHeading { font-size: 22px; font-weight: 700; color: %6; }"
                      "QLabel#newVideoLead { font-size: 13px; color: %7; }"
                      "QLabel#newVideoSideTitle { font-size: 13px; font-weight: 700; color: %6; }"
                      "QLabel#newVideoFieldTitle { font-size: 13px; font-weight: 700; color: %6; }"
                      "QPushButton[newVideoDot=\"true\"] { background: transparent; border: none; border-radius: 0; "
                      "border-bottom: 2px solid transparent; color: %7; font-size: 13px; padding: 6px 12px; }"
                      "QPushButton[newVideoDot=\"true\"]:hover { color: %6; }"
                      "QPushButton[newVideoDot=\"true\"]:focus { color: %6; border-bottom-color: %8; }"
                      "QPushButton[newVideoDot=\"true\"][current=\"true\"] { color: %6; font-weight: 700; border-bottom-color: %5; }"
                      "QPushButton[newVideoDot=\"true\"][done=\"true\"] { color: %9; }"
                      "QPushButton[newVideoDot=\"true\"][skipped=\"true\"] { color: %8; text-decoration: line-through; }"
                      "QPushButton[newVideoFilter=\"true\"] { background: %1; border: 1px solid %2; border-radius: 13px; "
                      "padding: 4px 14px; color: %6; }"
                      "QPushButton[newVideoFilter=\"true\"]:hover { background: %3; }"
                      "QPushButton[newVideoFilter=\"true\"]:focus { border-color: %9; }"
                      "QPushButton[newVideoFilter=\"true\"]:checked { background: %4; border-color: %5; }")
                      .arg(panel, line, raised, tealDeep, teal, cream, muted, dim, tealLight));
}

void NewVideoDialog::buildStageNavigation(QVBoxLayout *outer)
{
    // where you are: three stages in a row; the one you are on is underlined, and any can be pressed
    auto dots = new QHBoxLayout;
    dots->setSpacing(2);
    // T179: no Style stage. The Style is a row of tabs on the Look stage, so its page stays (the pages keep their numbers)
    // but its button is never shown
    const QStringList names{tr("1   Format"), tr("2   Content"), tr("Style"), tr("3   Look"), tr("4   Theme"), tr("5   Go")};
    for (int i = 0; i < names.size(); ++i) {
        if (i > 0 && i != PStyle) {
            auto between = new QLabel(QStringLiteral("›"), this);
            between->setProperty("studioMuted", true);
            dots->addWidget(between);
        }
        auto dot = new QPushButton(names[i], this);
        dot->setObjectName(QStringLiteral("newVideoStage_%1").arg(i + 1));
        dot->setProperty("newVideoDot", true);
        dot->setAutoDefault(false);
        dot->setCursor(Qt::PointingHandCursor);
        connect(dot, &QPushButton::clicked, this, [this, i]() { jump(i); });
        m_dots << dot;
        dots->addWidget(dot);
        dot->setVisible(i != PStyle);
    }
    dots->addStretch(1);
    // for tests and screen readers: which stage this is, in words
    m_stepLabel = new QLabel(this);
    m_stepLabel->setObjectName(QStringLiteral("newVideoStep"));
    m_stepLabel->setFixedSize(1, 1);
    m_stepLabel->setStyleSheet(QStringLiteral("color: transparent; background: transparent;"));
    dots->addWidget(m_stepLabel);
    outer->addLayout(dots);
}

void NewVideoDialog::buildStepNotices(QVBoxLayout *outer)
{
    using namespace LetItEditColors;
    // what Ready still needs, always in sight whatever the boxes scroll to
    m_inputsNote = new QLabel(this);
    m_inputsNote->setObjectName(QStringLiteral("newVideoInputsNote"));
    m_inputsNote->setWordWrap(true);
    m_inputsNote->setStyleSheet(QStringLiteral("color: %1;").arg(QString::fromLatin1(tealLight)));
    m_inputsNote->hide();
    outer->addWidget(m_inputsNote);

    // what stopped the next step, shown here so nothing typed is lost
    m_problem = new QLabel(this);
    m_problem->setObjectName(QStringLiteral("firstCutProblem"));
    m_problem->setWordWrap(true);
    m_problem->setStyleSheet(QStringLiteral("color: #ff8a80;"));
    m_problem->hide();
    outer->addWidget(m_problem);

    // what Turbo does to the video, in plain words (T80), once it is on. Turbo never cuts you out, on any PC (the owner, 5 Nov:
    // little simple graphics that aren't behind you, not a cut-out that takes time), so there is one sentence for everyone
    const QString turboWords = tr("The first cut is made much sooner: a plain cut with simple captions and music, every scene, card and "
                                  "effect very simple and brief, no AI review, no voice clean-up, one export. Nothing is put behind you: a "
                                  "Look that does that gets a brief full-screen scene or simple graphics instead.");
    m_turboNote = new QLabel(turboWords, this);
    m_turboNote->setObjectName(QStringLiteral("newVideoTurboNote"));
    m_turboNote->setWordWrap(true);
    m_turboNote->setProperty("studioMuted", true);
    m_turboNote->hide();
    outer->addWidget(m_turboNote);
}

void NewVideoDialog::buildNavigationButtons(QVBoxLayout *outer)
{
    auto buttons = new QHBoxLayout;
    m_back = new QPushButton(tr("Back"), this);
    m_back->setObjectName(QStringLiteral("newVideoBack"));
    m_back->setToolTip(tr("The step before (Alt+Left)"));
    m_back->setShortcut(QKeySequence(Qt::ALT | Qt::Key_Left));
    m_back->setAutoDefault(false);
    connect(m_back, &QPushButton::clicked, this, [this]() { back(); });
    buttons->addWidget(m_back);
    auto cancel = new QPushButton(tr("Cancel"), this);
    cancel->setObjectName(QStringLiteral("newVideoCancel"));
    cancel->setToolTip(tr("Close; what you chose and typed is kept for next time"));
    cancel->setAutoDefault(false);
    connect(cancel, &QPushButton::clicked, this, &QDialog::reject);
    buttons->addWidget(cancel);
    buttons->addStretch(1);
    // Turbo (T70): off every time a new video starts, never kept from the last one; it never touches the AI, model or
    // effort. On Ready, for every Look
    m_turboRow = new QWidget(this);
    auto turboRow = new QHBoxLayout(m_turboRow);
    turboRow->setContentsMargins(0, 0, 0, 0);
    turboRow->setSpacing(8);
    m_turbo = new QCheckBox(tr("Turbo"), m_turboRow);
    m_turbo->setObjectName(QStringLiteral("newVideoTurbo"));
    m_turbo->setAccessibleName(tr("Turbo: Sacrifices quality for speed"));
    m_turbo->setChecked(false);
    m_turbo->setToolTip(tr("Your AI skips what takes time on this first run through, so it finishes sooner. It uses the "
                           "same AI, model and effort you chose. Notes you send afterwards are handled as normal."));
    m_turbo->setStyleSheet(QStringLiteral("QCheckBox { font-weight: 700; } "
                                          "QCheckBox::indicator { width: 32px; height: 18px; border-radius: 11px; background: #59646A; border: 2px solid #59646A; } "
                                          "QCheckBox::indicator:checked { background: #2A8597; border: 2px solid #A8E1E7; }"));
    connect(m_turbo, &QCheckBox::toggled, this, [this](bool on) {
        m_turboNote->setVisible(on && m_pages->currentIndex() == PGo);
        updateSummary();
    });
    turboRow->addWidget(m_turbo);
    auto turboWordsLabel = new QLabel(tr("Sacrifices quality for speed"), m_turboRow);
    turboWordsLabel->setObjectName(QStringLiteral("newVideoTurboWords"));
    turboWordsLabel->setProperty("studioMuted", true);
    turboRow->addWidget(turboWordsLabel);
    buttons->addWidget(m_turboRow);
    buttons->addStretch(1);
    m_goHint = new QLabel(tr("You can change the finished video."), this);
    m_goHint->setObjectName(QStringLiteral("newVideoGoHint"));
    m_goHint->setProperty("studioMuted", true);
    buttons->addWidget(m_goHint);
    m_next = new QPushButton(tr("Next"), this);
    m_next->setObjectName(QStringLiteral("newVideoNext"));
    m_next->setProperty("studioPrimary", true);
    m_next->setMinimumWidth(130);
    connect(m_next, &QPushButton::clicked, this, [this]() { next(); });
    buttons->addWidget(m_next);
    m_go = new QPushButton(tr("Make my video"), this);
    m_go->setObjectName(QStringLiteral("firstCutGo"));
    m_go->setProperty("studioPrimary", true);
    m_go->setMinimumWidth(170);
    m_go->setToolTip(tr("Your AI starts on the first cut; follow along in the chat"));
    connect(m_go, &QPushButton::clicked, this, [this]() { send(); });
    buttons->addWidget(m_go);
    outer->addLayout(buttons);
}

// Kept for next time on Cancel (a closed or failed request loses nothing).
void NewVideoDialog::remember()
{
    // in this window's own letitedit-choices.ini (each window and test window keeps its own)
    QSettings &memory = leSettings();
    if (QFileInfo(m_folder->text().trimmed()).isDir()) {
        m_recentFolders.removeAll(m_folder->text().trimmed());
        m_recentFolders.prepend(m_folder->text().trimmed());
        while (m_recentFolders.size() > 8)
            m_recentFolders.removeLast();
    }
    memory.setValue(QStringLiteral("firstCut/kind"), m_kind);
    memory.setValue(QStringLiteral("firstCut/noFootage"), m_noFootage);
    memory.setValue(QStringLiteral("firstCut/aiLength"), m_aiLength->isChecked());
    memory.setValue(QStringLiteral("firstCut/length"), m_length->text());
    memory.setValue(QStringLiteral("firstCut/about"), m_about->toPlainText());
    if (m_song)
        memory.setValue(QStringLiteral("firstCut/song"), m_song->text());
    memory.setValue(QStringLiteral("firstCut/custom"), m_custom->toPlainText());
    // a style the person picked is kept for the draft; the default (their own style or none) is worked out anew
    if (m_personChose)
        memory.setValue(QStringLiteral("firstCut/style"), m_style);
    else
        memory.remove(QStringLiteral("firstCut/style"));
    memory.setValue(QStringLiteral("firstCut/look"), m_look);
    memory.setValue(QStringLiteral("firstCut/theme"), m_theme);
    memory.setValue(QStringLiteral("firstCut/captions"), m_caption);
    memory.setValue(QStringLiteral("firstCut/music"), m_music);
    memory.setValue(QStringLiteral("firstCut/musicFile"), m_musicFile);
    memory.setValue(QStringLiteral("firstCut/styleExplicit"), m_styleExplicit);
    memory.setValue(QStringLiteral("firstCut/tab"), m_tab);
    memory.setValue(QStringLiteral("firstCut/tabChosen"), m_tabChosen);
    memory.setValue(QStringLiteral("firstCut/freestyleByDefault"), m_freestyleByDefault);
    memory.setValue(QStringLiteral("firstCut/tabFor"), m_tabFor);
    captureInputsDraft();
    memory.setValue(QStringLiteral("firstCut/inputs"), QJsonDocument(m_inputsDraft).toJson(QJsonDocument::Compact));
    memory.sync();
    memory.setValue(QStringLiteral("firstCut/recent"), m_recentFolders);
    if (!m_folder->text().trimmed().isEmpty())
        Settings.setOpenPath(m_folder->text().trimmed());
}

// A scan or a list still running when the window closes is killed as its child, and "finished" would call back into a
// window whose widgets are being deleted: the editor crashed on Cancel or Make my video during a folder's first scan (T97).
NewVideoDialog::~NewVideoDialog()
{
    if (m_resizeTimer)
        m_resizeTimer->stop();
    for (QProcess *process : findChildren<QProcess *>())
        process->disconnect();
}

void NewVideoDialog::reject()
{
    remember();
    QDialog::reject();
}

// the cards are sized to the window: a resized window lays them out again, once it has settled
void NewVideoDialog::resizeEvent(QResizeEvent *event)
{
    QDialog::resizeEvent(event);
    if (!m_resizeTimer) {
        m_resizeTimer = new QTimer(this);
        m_resizeTimer->setSingleShot(true);
        m_resizeTimer->setInterval(200);
        connect(m_resizeTimer, &QTimer::timeout, this, [this]() {
            refreshChoicePages();
        });
    }
    m_resizeTimer->start();
}

QWidget *NewVideoDialog::page(const QString &heading, const QString &lead, QVBoxLayout **body)
{
    auto w = new QWidget(this);
    auto column = new QVBoxLayout(w);
    column->setContentsMargins(0, 2, 0, 0);
    column->setSpacing(8);
    auto h = new QLabel(heading, w);
    h->setObjectName(QStringLiteral("newVideoHeading"));
    column->addWidget(h);
    if (!lead.isEmpty()) {
        auto l = new QLabel(lead, w);
        l->setObjectName(QStringLiteral("newVideoLead"));
        l->setWordWrap(true);
        column->addWidget(l);
    }
    *body = column;
    return w;
}

// A field's name with how much it is needed beside it
QHBoxLayout *NewVideoDialog::fieldTitle(const QString &title, const QString &need, QWidget *parent)
{
    auto row = new QHBoxLayout;
    row->setSpacing(8);
    auto name = new QLabel(title, parent);
    name->setObjectName(QStringLiteral("newVideoFieldTitle"));
    row->addWidget(name);
    if (!need.isEmpty()) {
        auto how = new QLabel(need, parent);
        how->setProperty("studioMuted", true);
        row->addWidget(how);
    }
    row->addStretch(1);
    return row;
}

// The widgets the pages share: the format cards (Both and Something else are kept but not shown), the text of
// Something else, the length and the song. Each page puts in place the ones it shows.
void NewVideoDialog::makeParts(QWidget *w)
{
    m_kinds = new QButtonGroup(this);
    const QList<QStringList> kinds = {
        {QStringLiteral("short"), tr("Short"), tr("Vertical, under a minute: TikTok, YouTube Shorts and Reels."), tr("Vertical, under a minute, for TikTok, YouTube Shorts and Reels")},
        {QStringLiteral("long"), tr("YouTube video"), tr("Horizontal, any length, for YouTube."), tr("Horizontal and longer, a few minutes or more")},
        {QStringLiteral("both"), tr("Both"), tr("One of each"), tr("A YouTube video and a Short from the same footage")},
        {QStringLiteral("custom"), tr("Something else"), tr("Say what you want"), tr("Type what you want: a trailer, an ad, a recap...")}};
    for (int i = 0; i < kinds.size(); ++i) {
        auto card = new ChoiceCard(kinds[i][1], kinds[i][2], w, QString(), i < 2 ? formatPicture(i == 0) : QPixmap());
        card->setObjectName(QStringLiteral("newVideoKind_%1").arg(kinds[i][0]));
        card->setProperty("kind", kinds[i][0]);
        card->setToolTip(kinds[i][3]);
        card->setMinimumHeight(i < 2 ? 150 : 58);
        card->setMinimumWidth(150);
        m_kinds->addButton(card, i);
        if (i >= 2)
            card->hide(); // Both and Something else wait; their code stays
    }
    // toggled, not clicked: a keyboard, a click and a screen reader's toggle all count
    connect(m_kinds, &QButtonGroup::buttonToggled, this, [this](QAbstractButton *b, bool checked) {
        if (!checked)
            return;
        m_kind = b->property("kind").toString();
        m_custom->setVisible(false);
        m_customLabel->setVisible(false);
        m_problem->hide();
        // a Look that suits only the other format is let go
        if (m_modern)
            dropLookForFormat();
        updateShapeNote();
    });
    m_customLabel = new QLabel(tr("Describe what you want to make"), w);
    m_customLabel->hide();
    m_custom = new QPlainTextEdit(w);
    m_custom->setObjectName(QStringLiteral("newVideoCustom"));
    m_custom->setAccessibleName(tr("Describe what you want to make"));
    m_custom->setPlaceholderText(tr("e.g. a 30-second ad for our coffee stand, or a 2-minute trip recap with music"));
    m_custom->setFixedHeight(62);
    m_custom->hide();
    m_aiLength = new QCheckBox(tr("Let the AI choose the length"), w);
    m_aiLength->setObjectName(QStringLiteral("newVideoAiLength"));
    m_aiLength->setChecked(true);
    m_length = new QLineEdit(w);
    m_length->setObjectName(QStringLiteral("newVideoLength"));
    m_length->setAccessibleName(tr("Length"));
    m_length->setPlaceholderText(tr("e.g. 1:30, 90 s"));
    m_length->setEnabled(false);
    connect(m_aiLength, &QCheckBox::toggled, m_length, &QWidget::setDisabled);
    // Go's summary follows the length as it is typed
    connect(m_aiLength, &QCheckBox::toggled, this, [this]() { if (m_summary) updateSummary(); });
    connect(m_length, &QLineEdit::textChanged, this, [this]() { if (m_summary) updateSummary(); });
    // T72's song to cut to: only the older, non-modern picker used it
    m_songPanel = new QWidget(w);
    m_song = new QLineEdit(m_songPanel);
    m_song->setObjectName(QStringLiteral("newVideoSong"));
    m_songPanel->hide();
}

void NewVideoDialog::restore()
{
    QSettings &memory = leSettings();
    m_kind = memory.value(QStringLiteral("firstCut/kind"), QStringLiteral("short")).toString();
    if (m_kind != QLatin1String("short") && m_kind != QLatin1String("long"))
        m_kind = QStringLiteral("short"); // Both and Something else wait
    for (auto b : m_kinds->buttons())
        if (b->property("kind").toString() == m_kind)
            b->setChecked(true);
    if (!m_kinds->checkedButton()) {
        m_kind = QStringLiteral("short");
        m_kinds->button(0)->setChecked(true);
    }
    m_aiLength->setChecked(memory.value(QStringLiteral("firstCut/aiLength"), true).toBool());
    m_length->setText(memory.value(QStringLiteral("firstCut/length")).toString());
    m_recentFolders = memory.value(QStringLiteral("firstCut/recent")).toStringList();
    if (!m_recentFolders.isEmpty() && QFileInfo(m_recentFolders.first()).isDir())
        m_folder->setText(m_recentFolders.first());
    else if (!QFileInfo(m_folder->text()).isDir())
        m_folder->setText(QStandardPaths::writableLocation(QStandardPaths::MoviesLocation));
    m_about->setPlainText(memory.value(QStringLiteral("firstCut/about")).toString());
    if (m_song)
        m_song->setText(memory.value(QStringLiteral("firstCut/song")).toString());
    m_custom->setPlainText(memory.value(QStringLiteral("firstCut/custom")).toString());
    m_custom->setVisible(m_kind == QLatin1String("custom"));
    m_customLabel->setVisible(m_kind == QLatin1String("custom"));
    // a style picked in an unsent draft comes back; a new video starts with the person's own style when they
    // have one (A3), else "Let the AI decide"
    m_personChose = memory.contains(QStringLiteral("firstCut/style"));
    m_style = m_personChose ? memory.value(QStringLiteral("firstCut/style")).toString() : mineByDefault();
    m_look = memory.value(QStringLiteral("firstCut/look"), QStringLiteral("auto")).toString();
    if (m_look == QLatin1String("pending-learn")) {
        // New video was closed while a Look was being learned (T167): still learning, it stays the choice; finished, the
        // new Look is chosen; stopped, "Let the AI pick"
        const QString newest = LearnLooks::newestJob(false);
        const QJsonObject job = LearnLooks::readJob(newest);
        const QString learned = job.value(QStringLiteral("look_id")).toString();
        if (LearnLooks::running(job) && !LearnLooks::orphaned(job)) {
            m_pendingLearnJob = newest;
            m_pendingLearnName = job.value(QStringLiteral("name")).toString(); // T189: empty until the AI has named it
            if (m_pendingLearnName.isEmpty())
                m_pendingLearnName = tr("Your new Look");
        } else {
            m_look = QStringLiteral("auto");
            if (job.value(QStringLiteral("state")).toString() == QLatin1String("done") && !learned.isEmpty())
                m_selectLook = learned;
        }
    }
    m_theme = memory.value(QStringLiteral("firstCut/theme"), QStringLiteral("freestyle")).toString();
    if (m_theme == QLatin1String("auto")) // a draft from before the split: the old default is Freestyle (T179)
        m_theme = QStringLiteral("freestyle");
    m_caption = QStringLiteral("auto"); // Captions & pace is no longer asked
    m_themeChosen = m_theme != QLatin1String("freestyle");
    m_music = musicChoice(memory.value(QStringLiteral("firstCut/music"), QStringLiteral("auto")).toString());
    m_musicFile = memory.value(QStringLiteral("firstCut/musicFile")).toString();
    // Go's Music choice is built before the draft is read: show what was kept
    if (auto music = findChild<QComboBox *>(QStringLiteral("newVideoMusic"))) {
        const QString kept = m_music;
        music->setCurrentIndex(qMax(0, music->findData(kept)));
        m_music = music->currentData().toString();
        if (m_musicFileEdit)
            m_musicFileEdit->setText(m_musicFile);
    }
    m_styleExplicit = memory.value(QStringLiteral("firstCut/styleExplicit")).toBool();
    // T179: the Style tab. A draft kept from before the tabs picks the tab of the Style chosen then
    m_tab = memory.value(QStringLiteral("firstCut/tab"), QStringLiteral("all")).toString();
    m_tabChosen = memory.value(QStringLiteral("firstCut/tabChosen")).toBool();
    m_freestyleByDefault = m_look == QLatin1String("freestyle") && memory.value(QStringLiteral("firstCut/freestyleByDefault")).toBool();
    m_tabFor = memory.value(QStringLiteral("firstCut/tabFor")).toString();
    if (!memory.contains(QStringLiteral("firstCut/tab")) && m_styleExplicit && m_personChose && !m_style.isEmpty()
        && m_style != QLatin1String("none")) {
        m_tab = m_style;
        m_tabChosen = true;
        m_tabFor = m_folder->text().trimmed(); // kept from before the tabs: it was for the folder kept with it
    }
    m_inputsDraft = QJsonDocument::fromJson(memory.value(QStringLiteral("firstCut/inputs")).toByteArray()).object();
    m_routeRemembered = memory.contains(QStringLiteral("firstCut/noFootage"));
    m_scanTimer->start();
    // after the folder above, which would count as choosing footage
    QScopedValueRollback<bool> restoringRoute(m_restoringRoute, true);
    if (memory.value(QStringLiteral("firstCut/noFootage")).toBool())
        m_noFootageButton->setChecked(true);
}

void NewVideoDialog::clearLayout(QLayout *layout, const std::function<void(QWidget *)> &forget)
{
    while (auto item = layout->takeAt(0)) {
        if (auto w = item->widget()) {
            if (forget)
                forget(w);
            w->hide();
            w->deleteLater();
        }
        if (auto child = item->layout()) { // a nested layout is its own item
            clearLayout(child, forget);
            delete child;
            continue;
        }
        delete item;
    }
}

// ---- Style, Look and Theme (T164) --------------------------------------------------------------------------------
// The height a card's one-line explanation needs when shown in full (wrapped) at the card's width; every card of a row takes
// the tallest, so the cards line up and nothing is cut short with "..."
int NewVideoDialog::cardTextHeight(const QString &text, int width)
{
    QLabel probe(text, this);
    probe.setObjectName(QStringLiteral("newVideoCardText"));
    probe.setWordWrap(true);
    probe.ensurePolished();
    return qMax(18, probe.heightForWidth(width));
}

void NewVideoDialog::refreshChoicePages()
{
    const int p = m_pages->currentIndex();
    if (p == PStyle)
        fillStyleChoices();
    else if (p == PLook && !m_customStylePage)
        fillBrowser();
    else if (p == PTheme)
        fillThemePage();
}

bool NewVideoDialog::check(int step)
{
    QString why;
    if (step == PFormat) {
        if (m_kind == QLatin1String("custom") && m_custom->toPlainText().trimmed().isEmpty())
            why = tr("Type what you want to make, or pick Short or YouTube video.");
    } else if (step == PContent) {
        const QString path = m_folder->text().trimmed();
        if (!m_noFootage && path.isEmpty())
            why = tr("Choose the folder with your footage first.");
        else if (!m_noFootage && !QFileInfo(path).isDir() && m_selectedFiles.isEmpty())
            why = tr("That folder doesn't exist. Choose it with the buttons, or check the spelling.");
    } else if (step == PStyle) {
        // T179: no Style stage; the Look stage's tabs hold it
    } else if (step == PLook) {
        const LookStyle *ls = lookStyle(m_style);
        const bool looked = m_look == QLatin1String("pending-learn") || m_look == QLatin1String("freestyle") || editMyself()
                            || (ls && (findLook(*ls, m_look) || (m_look == QLatin1String("auto") && (m_modern || ls->footage != QLatin1String("no")))));
        if ((!m_modern && m_noFootage && !looked) || (ls && !looked))
            why = tr("Pick a Look to go on.");
    } else if (step == PGo) {
        if (!m_aiLength->isChecked() && normalizedLength().isEmpty())
            why = tr("Enter a length such as 1:30, 90 s or 2.5 min, or let the AI choose.");
        else if (m_modern && m_music == QLatin1String("own") && !QFileInfo(m_musicFile).isFile())
            why = tr("Choose your song file, or let the AI decide.");
        else if (aboutRequired() && m_about->toPlainText().trimmed().isEmpty())
            why = tr("Say what the video is about.");
        else
            why = missingInputsLine();
    }
    m_problem->setText(why);
    m_problem->setVisible(!why.isEmpty());
    return why.isEmpty();
}

void NewVideoDialog::back()
{
    const int step = m_pages->currentIndex();
    if (step == PLook && m_customStylePage) { // from Adjust to the Looks
        m_customStylePage = false;
        go(PLook);
    } else {
        go(step - 1);
    }
}

void NewVideoDialog::next()
{
    const int step = m_pages->currentIndex();
    if (!check(step))
        return;
    if (step == PLook && editMyself() && !m_customStylePage) { // Edit with the AI myself: Theme and Go are skipped
        openEditorMyself();
        return;
    }
    if (step < m_pages->count() - 1)
        go(step + 1);
    else
        send();
}

// A stage pressed at the top: back at once, forward only past what checks out
void NewVideoDialog::jump(int to)
{
    const int from = m_pages->currentIndex();
    if (to <= from) {
        if (to == PLook)
            m_customStylePage = false;
        go(to);
        return;
    }
    if (editMyself() && to > PLook)
        to = PLook; // Theme and Go are skipped: Open the editor is on the Look stage
    for (int step = from; step < to; ++step) {
        if (!check(step)) {
            if (step != from) {
                const QString why = m_problem->text();
                go(step);
                m_problem->setText(why);
                m_problem->show();
            }
            return;
        }
        // the Look page has to be seen once so its choice (and a Theme the Look comes with) is settled
    }
    go(to);
}

void NewVideoDialog::go(int step)
{
    step = qBound(0, step, m_pages->count() - 1);
    if (step == PStyle) // T179: no Style stage: on to the Look, or back to the Content
        step = m_pages->currentIndex() > PStyle ? PContent : PLook;
    m_problem->hide();
    if (step != PLook)
        m_lookNote.clear(); // said once, on the Look stage
    if (step != PLook)
        m_customStylePage = false;
    m_pages->setCurrentIndex(step);
    if (step == PStyle)
        fillStyleChoices();
    if (step == PLook) {
        m_styleSlides->setCurrentIndex(m_customStylePage ? 1 : m_modern ? 2 : 0);
        showStylePageTexts();
        if (!m_customStylePage)
            fillBrowser();
    }
    if (step == PTheme)
        fillThemePage();
    const bool skipping = editMyself();
    for (int i = 0; i < m_dots.size(); ++i) {
        const bool skipped = skipping && i > PLook;
        m_dots[i]->setProperty("current", i == step);
        m_dots[i]->setProperty("done", i < step);
        m_dots[i]->setProperty("skipped", skipped);
        m_dots[i]->setToolTip(skipped ? tr("Skipped: Edit with the AI myself opens the editor") : QString());
        m_dots[i]->style()->unpolish(m_dots[i]);
        m_dots[i]->style()->polish(m_dots[i]);
    }
    // the stages as numbered on screen: Format, Content, Look, Theme, Go (the Style page is never shown)
    static const QStringList titles{QObject::tr("Format"), QObject::tr("Content"), QObject::tr("Style"), QObject::tr("Look"), QObject::tr("Theme"), QObject::tr("Go")};
    const int shown = step > PStyle ? step : step + 1;
    m_stepLabel->setText(tr("Step %1 of %2: %3").arg(shown).arg(m_pages->count() - 1).arg(titles.value(step)));
    if (step == PLook && m_customStylePage)
        m_stepLabel->setText(tr("Step 3 of 5: Adjust"));
    m_back->setEnabled(step > 0);
    const bool last = step == m_pages->count() - 1;
    m_next->setText(step == PLook && skipping ? tr("Open the editor") : tr("Next"));
    m_next->setVisible(!last && !(step == PLook && m_customStylePage));
    m_go->setVisible(last);
    m_goHint->setVisible(last);
    m_turboRow->setVisible(last);
    m_turboNote->setVisible(last && m_turbo->isChecked());
    (last ? m_go : m_next)->setDefault(true);
    if (last) {
        prepareReady();
    } else {
        m_inputsNote->hide();
    }
    if (step == PContent && !m_noFootage)
        m_folder->setFocus();
    else if (step == PContent)
        m_noFootageButton->setFocus();
    else if (last) {
        QWidget *first = m_about;
        for (const QString &id : m_askOrder)
            if (auto text = m_askText.value(id)) {
                first = text;
                break;
            }
        first->setFocus();
    } else if (m_next->isVisible())
        m_next->setFocus();
}

} // namespace NewVideo
