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

// New video, step 6: Go (the summary, music, which AI, and the one big action).
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// Ready: the chosen Look, every box it needs, and the one big action. Nothing is asked after this.
// ---- Go (T164) ---------------------------------------------------------------------------------------------------
// The older music choices (AI music on this PC, Written music, Quiet background music) are one choice now: the AI picks
// the engine (the owner, 10 Nov). A saved older choice loads as it.
QString NewVideoDialog::musicChoice(const QString &saved)
{
    if (saved == QLatin1String("ai") || saved == QLatin1String("written") || saved == QLatin1String("backdrop"))
        return QStringLiteral("made");
    return saved;
}

// one simple choice of music, with a file where the choice needs one
QWidget *NewVideoDialog::musicRow(QWidget *parent)
{
    auto holder = new QWidget(parent);
    auto column = new QVBoxLayout(holder);
    column->setContentsMargins(0, 0, 0, 0);
    column->setSpacing(4);
    auto row = new QHBoxLayout;
    row->addWidget(new QLabel(tr("Music"), holder));
    auto music = new QComboBox(holder);
    music->setObjectName(QStringLiteral("newVideoMusic"));
    // six choices (the owner, 10 Nov): what each is, when to pick it and what it needs, on hover and on keyboard focus (T176)
    struct MusicOption
    {
        QString value, label, help;
    };
    const QList<MusicOption> musicOptions{
        {QStringLiteral("auto"), tr("Let the AI decide"),
         tr("Your AI picks what suits this video: a song from the library, music made for it, or none. Pick this if you're not "
            "sure. Needs nothing from you.")},
        {QStringLiteral("library"), tr("Song library"),
         tr("A ready-made song from letitedit's free library, chosen and cut to fit. Pick this for a familiar, finished sound "
            "that is safe to post anywhere. Needs nothing from you.")},
        {QStringLiteral("made"), tr("Made for this video"),
         tr("Your AI makes new music for this video, fitted to its length, mood and cuts, on this PC. Pick this when you want "
            "music that lands on your moments. Needs nothing from you; it can take a few minutes more.")},
        {QStringLiteral("own"), tr("My own song file"),
         tr("A song file from this PC goes into the video. Pick this when you have music you're allowed to use. Needs: choose "
            "the file below.")},
        {QStringLiteral("trending"), tr("I'll add music later in another app"),
         tr("No music in the exported video: your AI leaves the cut ready for a sound you add in TikTok, Instagram or YouTube "
            "when you post (that's how popular songs stay allowed). Optional: name the song below and it's cut to its beat.")},
        {QStringLiteral("none"), tr("No music"),
         tr("Just your voice and the sound you filmed. Pick this for talks, tutorials or when the real sound matters. Needs "
            "nothing from you.")}};
    for (const auto &option : musicOptions) {
        music->addItem(option.label, option.value);
        music->setItemData(music->count() - 1, option.help, Qt::ToolTipRole);
    }
    m_music = musicChoice(m_music);
    music->setCurrentIndex(qMax(0, music->findData(m_music)));
    row->addWidget(music, 1);
    column->addLayout(row);
    // the help box: the choice under the pointer or the keyboard in the open list, else the chosen one
    auto help = new QLabel(holder);
    help->setObjectName(QStringLiteral("newVideoMusicHelp"));
    help->setWordWrap(true);
    help->setProperty("studioMuted", true);
    help->setStyleSheet(QStringLiteral("QLabel { border-left: 3px solid %1; padding: 2px 0 2px 8px; }").arg(QString::fromLatin1(LetItEditColors::teal)));
    column->addWidget(help);
    const auto showHelp = [music, help](int index) {
        const QString text = music->itemData(index, Qt::ToolTipRole).toString();
        help->setText(text);
        if (index == music->currentIndex())
            music->setToolTip(text);
    };
    connect(music, &QComboBox::highlighted, holder, showHelp);
    if (auto view = music->view())
        connect(view, &QAbstractItemView::entered, holder, [showHelp](const QModelIndex &index) { showHelp(index.row()); });
    showHelp(music->currentIndex());
    auto fileRow = new QWidget(holder);
    fileRow->setObjectName(QStringLiteral("newVideoMusicFileRow"));
    auto fileLayout = new QHBoxLayout(fileRow);
    fileLayout->setContentsMargins(0, 0, 0, 0);
    m_musicFileEdit = new QLineEdit(m_musicFile, fileRow);
    m_musicFileEdit->setObjectName(QStringLiteral("newVideoMusicFile"));
    connect(m_musicFileEdit, &QLineEdit::textChanged, this, [this](const QString &text) { m_musicFile = text; });
    fileLayout->addWidget(m_musicFileEdit, 1);
    auto choose = new QPushButton(tr("Choose file..."), fileRow);
    choose->setAutoDefault(false);
    choose->setObjectName(QStringLiteral("newVideoMusicBrowse"));
    connect(choose, &QPushButton::clicked, this, [this]() {
        const auto path = QFileDialog::getOpenFileName(this, tr("Choose music"), QString(), tr("Audio (*.mp3 *.wav *.flac *.m4a *.ogg);;All files (*)"));
        if (!path.isEmpty())
            m_musicFileEdit->setText(path);
    });
    fileLayout->addWidget(choose);
    column->addWidget(fileRow);
    const auto showFile = [this, fileRow]() {
        fileRow->setVisible(m_music == QLatin1String("own") || m_music == QLatin1String("trending"));
        m_musicFileEdit->setPlaceholderText(m_music == QLatin1String("own") ? tr("Choose your song file")
                                                                             : tr("Optional: the song's name or a copy of it, to cut to"));
    };
    connect(music, &QComboBox::currentIndexChanged, this, [this, music, showFile, showHelp]() {
        m_music = music->currentData().toString();
        showFile();
        showHelp(music->currentIndex());
    });
    showFile();
    return holder;
}

// the video's one line, as it stands: format, content, style, Look, Theme
QString NewVideoDialog::summaryLine() const
{
    QStringList parts;
    parts << (m_kind == QLatin1String("long") ? tr("YouTube video") : m_kind == QLatin1String("short") ? tr("Short") : tr("Short and YouTube video"));
    parts << (m_noFootage ? tr("100% AI") : m_selectedFiles.isEmpty() ? tr("your footage") : tr("%n file(s)", "", m_selectedFiles.size()));
    const LookStyle *style = lookStyle(m_style);
    if (style)
        parts << style->label;
    parts << tr("Look: %1").arg(chosenLookName());
    QString theme = m_theme == QLatin1String("none") ? tr("none, as learned")
                    : m_theme == QLatin1String("pick")   ? tr("AI picks one")
                                                         : tr("Freestyle");
    for (const auto &value : m_themes)
        if (value.toObject().value("id").toString() == m_theme) {
            theme = value.toObject().value("title").toString();
        }
    parts << tr("Theme: %1").arg(theme);
    return parts.join(QStringLiteral("  ·  "));
}

QString NewVideoDialog::chosenLookName() const
{
    if (m_look == QLatin1String("pending-learn"))
        return tr("%1 (still learning)").arg(m_pendingLearnName);
    if (m_look == QLatin1String("freestyle"))
        return tr("Freestyle");
    if (const LookChoice *look = chosenLookCard())
        return look->label;
    return tr("AI picks");
}

// 100% AI: "What's it about?" is asked, by the Look's own box when it has one
bool NewVideoDialog::aboutRequired() const
{
    if (!noFootageForSummary())
        return false;
    if (const LookChoice *asking = askingLook())
        for (const LookAsk &ask : asking->asks)
            if (ask.role == QLatin1String("about"))
                return false;
    return true;
}

QWidget *NewVideoDialog::readyPage()
{
    QVBoxLayout *column = nullptr;
    auto w = page(tr("Ready to make your video"), tr("Your AI makes the creative choices."), &column);
    m_readyHeading = w->findChild<QLabel *>(QStringLiteral("newVideoHeading"));
    m_readyLead = w->findChild<QLabel *>(QStringLiteral("newVideoLead"));
    m_readyLead->setObjectName(QStringLiteral("newVideoReadyLead"));
    auto body = new QHBoxLayout;
    body->setSpacing(18);

    // the left side: the Look, the video, the AI
    auto sideScroll = new QScrollArea(w);
    sideScroll->setObjectName(QStringLiteral("newVideoReadySide"));
    sideScroll->setFrameShape(QFrame::NoFrame);
    sideScroll->setWidgetResizable(true);
    sideScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    sideScroll->setFixedWidth(280);
    auto side = new QWidget(sideScroll);
    auto sideColumn = new QVBoxLayout(side);
    sideColumn->setContentsMargins(0, 0, 8, 0);
    sideColumn->setSpacing(6);
    auto lookRow = new QHBoxLayout;
    lookRow->setSpacing(10);
    m_readyPicture = new QLabel(side);
    m_readyPicture->setObjectName(QStringLiteral("newVideoReadyPicture"));
    m_readyPicture->setFixedSize(84, 150);
    m_readyPicture->setAlignment(Qt::AlignCenter);
    lookRow->addWidget(m_readyPicture, 0, Qt::AlignTop);
    auto lookWords = new QVBoxLayout;
    lookWords->setSpacing(4);
    m_readyLook = new QLabel(side);
    m_readyLook->setObjectName(QStringLiteral("newVideoReadyLook"));
    m_readyLook->setWordWrap(true);
    m_readyLook->setStyleSheet(QStringLiteral("font-size: 15px; font-weight: 700;"));
    lookWords->addWidget(m_readyLook);
    m_readyLine = new QLabel(side);
    m_readyLine->setObjectName(QStringLiteral("newVideoReadyLine"));
    m_readyLine->setWordWrap(true);
    m_readyLine->setProperty("studioMuted", true);
    lookWords->addWidget(m_readyLine);
    lookWords->addStretch(1);
    lookRow->addLayout(lookWords, 1);
    sideColumn->addLayout(lookRow);
    auto change = new QPushButton(tr("Change Look"), side);
    change->setObjectName(QStringLiteral("newVideoChangeLook"));
    change->setAutoDefault(false);
    connect(change, &QPushButton::clicked, this, [this]() {
        m_customStylePage = false;
        go(PLook);
    });
    sideColumn->addWidget(change);
    const auto rule = [&]() {
        auto line = new QFrame(side);
        line->setFrameShape(QFrame::HLine);
        line->setStyleSheet(QStringLiteral("color: %1;").arg(QString::fromLatin1(LetItEditColors::line)));
        sideColumn->addWidget(line);
    };
    rule();
    auto videoTitle = new QLabel(tr("Your video"), side);
    videoTitle->setObjectName(QStringLiteral("newVideoSideTitle"));
    sideColumn->addWidget(videoTitle);
    m_summary = new QLabel(side);
    m_summary->setObjectName(QStringLiteral("newVideoSummary"));
    m_summary->setWordWrap(true);
    m_summary->setTextFormat(Qt::RichText);
    sideColumn->addWidget(m_summary);
    m_goFitNote = new QLabel(side);
    m_goFitNote->setObjectName(QStringLiteral("newVideoGoFitNote"));
    m_goFitNote->setWordWrap(true);
    m_goFitNote->hide();
    sideColumn->addWidget(m_goFitNote);
    rule();
    m_readyAi = new QLabel(side);
    m_readyAi->setObjectName(QStringLiteral("newVideoReadyAi"));
    m_readyAi->setStyleSheet(QStringLiteral("font-size: 13px; font-weight: 700;"));
    sideColumn->addWidget(m_readyAi);
    m_readyModel = new QLabel(side);
    m_readyModel->setObjectName(QStringLiteral("newVideoReadyModel"));
    m_readyModel->setWordWrap(true);
    m_readyModel->setProperty("studioMuted", true);
    sideColumn->addWidget(m_readyModel);
    auto aiSettings = new QPushButton(QStringLiteral("AI settings ▾"), side);
    aiSettings->setObjectName(QStringLiteral("newVideoAiSettings"));
    aiSettings->setAutoDefault(false);
    aiSettings->setToolTip(tr("Which AI makes this video, its model, effort and reply speed, and Connect Your AI"));
    m_aiMenu = new QMenu(this);
    m_aiMenu->setObjectName(QStringLiteral("newVideoAiMenu"));
    connect(aiSettings, &QPushButton::clicked, this, [this, aiSettings]() {
        m_aiMenu->popup(aiSettings->mapToGlobal(QPoint(0, aiSettings->height())));
    });
    sideColumn->addWidget(aiSettings);
    sideColumn->addStretch(1);
    sideScroll->setWidget(side);
    body->addWidget(sideScroll);

    buildReadyInputs(w, body);
    column->addLayout(body, 1);
    return w;
}

void NewVideoDialog::buildReadyInputs(QWidget *w, QHBoxLayout *body)
{
    // the right side: what it's about (or anything to know), the Look's boxes, references, length and music
    auto inputsScroll = new QScrollArea(w);
    inputsScroll->setObjectName(QStringLiteral("newVideoInputs"));
    inputsScroll->setWidgetResizable(true);
    inputsScroll->setFrameShape(QFrame::NoFrame);
    inputsScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    m_inputsHolder = new QWidget(inputsScroll);
    auto rightColumn = new QVBoxLayout(m_inputsHolder);
    rightColumn->setContentsMargins(0, 0, 8, 0);
    rightColumn->setSpacing(10);
    m_inputsGone = new QLabel(m_inputsHolder);
    m_inputsGone->setObjectName(QStringLiteral("newVideoInputsGone"));
    m_inputsGone->setWordWrap(true);
    m_inputsGone->setStyleSheet(QStringLiteral("color: %1;").arg(QString::fromLatin1(LetItEditColors::tealLight)));
    m_inputsGone->hide();
    rightColumn->addWidget(m_inputsGone);
    m_inputsColumn = new QVBoxLayout;
    m_inputsColumn->setSpacing(10);
    rightColumn->addLayout(m_inputsColumn);
    m_aboutBox = new QWidget(m_inputsHolder);
    m_aboutBox->setObjectName(QStringLiteral("newVideoAboutBox"));
    auto aboutColumn = new QVBoxLayout(m_aboutBox);
    aboutColumn->setContentsMargins(0, 0, 0, 0);
    aboutColumn->setSpacing(4);
    auto aboutRow = new QHBoxLayout;
    m_aboutTitle = new QLabel(m_aboutBox);
    m_aboutTitle->setObjectName(QStringLiteral("newVideoAboutTitle"));
    m_aboutTitle->setStyleSheet(QStringLiteral("font-size: 13px; font-weight: 700;"));
    aboutRow->addWidget(m_aboutTitle);
    m_aboutNeed = new QLabel(m_aboutBox);
    m_aboutNeed->setProperty("studioMuted", true);
    aboutRow->addWidget(m_aboutNeed);
    aboutRow->addStretch(1);
    aboutColumn->addLayout(aboutRow);
    m_about = new QPlainTextEdit(m_aboutBox);
    m_about->setObjectName(QStringLiteral("firstCutAbout"));
    m_about->setFixedHeight(110);
    aboutColumn->addWidget(m_about);
    rightColumn->addWidget(m_aboutBox);
    // 100% AI: characters, a logo, photos or a script go to the AI with the request
    m_referencesBox = new QWidget(m_inputsHolder);
    m_referencesBox->setObjectName(QStringLiteral("newVideoReferencesBox"));
    auto referencesColumn = new QVBoxLayout(m_referencesBox);
    referencesColumn->setContentsMargins(0, 0, 0, 0);
    referencesColumn->setSpacing(4);
    referencesColumn->addLayout(fieldTitle(tr("References"), tr("Optional"), m_referencesBox));
    auto referencesHint = new QLabel(tr("Add characters, a logo, photos or a script the AI should use. Your files are only read."), m_referencesBox);
    referencesHint->setWordWrap(true);
    referencesHint->setProperty("studioMuted", true);
    referencesColumn->addWidget(referencesHint);
    m_references = new AskFiles(QStringLiteral("references"), false, m_referencesBox);
    m_references->setObjectName(QStringLiteral("newVideoReferences"));
    m_references->setAccessibleName(tr("References"));
    referencesColumn->addWidget(m_references);
    auto referencesAdd = new QPushButton(tr("Add files..."), m_referencesBox);
    referencesAdd->setObjectName(QStringLiteral("newVideoReferencesAdd"));
    referencesAdd->setAutoDefault(false);
    connect(referencesAdd, &QPushButton::clicked, this, [this]() {
        const QStringList picked = QFileDialog::getOpenFileNames(
            this, tr("Choose files"), Settings.openPath(),
            tr("Pictures, text, video and sound (*.jpg *.jpeg *.png *.heic *.webp *.bmp *.txt *.md *.pdf *.docx *.mp4 *.mov *.m4v *.mkv *.wav *.mp3 *.m4a);;All files (*)"));
        QStringList clean;
        for (const QString &p : picked)
            clean << QDir::toNativeSeparators(p);
        m_references->addFiles(clean);
    });
    referencesColumn->addWidget(referencesAdd, 0, Qt::AlignLeft);
    // for tests and screen readers: paths set here (semicolon separated) are added, as if dropped
    auto referencesPaste = new QLineEdit(m_referencesBox);
    referencesPaste->setObjectName(QStringLiteral("newVideoReferencesPaste"));
    referencesPaste->setFixedSize(1, 1);
    referencesPaste->setStyleSheet(QStringLiteral("color: transparent; background: transparent; border: none;"));
    connect(referencesPaste, &QLineEdit::textChanged, this, [this, referencesPaste](const QString &text) {
        if (text.isEmpty())
            return;
        m_references->addFiles(text.split(QLatin1Char(';'), Qt::SkipEmptyParts));
        referencesPaste->clear();
    });
    referencesColumn->addWidget(referencesPaste);
    rightColumn->addWidget(m_referencesBox);
    rightColumn->addLayout(fieldTitle(tr("How long?"), QString(), m_inputsHolder));
    auto lengthRow = new QHBoxLayout;
    lengthRow->addWidget(m_aiLength);
    lengthRow->addWidget(m_length, 1);
    rightColumn->addLayout(lengthRow);
    rightColumn->addWidget(musicRow(m_inputsHolder));
    auto how = new QLabel(tr("Your AI makes the first cut on its own (usually an hour and a half to two and a half "
                             "hours; you'll see how far along it is) and opens it here. Then just tell it what to "
                             "change, or press Review to draw on the video. Runs your own AI subscription.")
                              + QLatin1Char(' ') + ConnectAi::privacyLine(),
                          m_inputsHolder);
    how->setObjectName(QStringLiteral("newVideoAutonomousHint"));
    how->setWordWrap(true);
    how->setProperty("studioMuted", true);
    rightColumn->addWidget(how);
    rightColumn->addStretch(1);
    inputsScroll->setWidget(m_inputsHolder);
    body->addWidget(inputsScroll, 1);
}

// Which AI is making it. Never changed by a Look or by Turbo: only by the person, here or in the chat.
void NewVideoDialog::refreshAi()
{
    const QJsonObject s = aiChatSettings();
    const QString engine = aiChatEngineId(s);
    m_readyAi->setText(tr("Made with %1").arg(aiEngineShortName(engine)));
    const QString modelNow = s.value(aiChatModelKeyOf(engine)).toString().trimmed();
    const QString effortNow = s.value(aiChatEffortKeyOf(engine)).toString().trimmed();
    const QList<AiChatChoice> models = aiChatModelChoices(s);
    const QList<AiChatChoice> efforts = aiChatEffortChoices(s);
    QStringList words;
    for (const auto &choice : models)
        if (choice.value == modelNow && !modelNow.isEmpty())
            words << choice.button;
    for (const auto &choice : efforts)
        if (choice.value == effortNow && !effortNow.isEmpty())
            words << tr("%1 effort").arg(choice.label);
    const QJsonArray speeds = aiSpeedChoices(s, engine);
    const QString speedNow = aiSpeedValue(s, engine);
    for (const auto &value : speeds) {
        const QJsonObject speed = value.toObject();
        if (speed.value("value").toString() == speedNow)
            words << tr("%1 replies").arg(speed.value("label").toString());
    }
    m_readyModel->setText(words.isEmpty() ? tr("Your chosen model and effort.") : words.join(QStringLiteral(", ")));

    for (auto sub : m_aiMenu->findChildren<QMenu *>(QString(), Qt::FindDirectChildrenOnly))
        sub->deleteLater();
    m_aiMenu->clear();
    const auto add = [this](const QString &title, const QString &kind, const QList<AiChatChoice> &choices, const QString &current,
                            const std::function<void(const QString &)> &pick) {
        QMenu *sub = m_aiMenu->addMenu(title);
        auto group = new QActionGroup(sub);
        for (const auto &choice : choices) {
            QAction *a = sub->addAction(choice.label);
            a->setObjectName(QStringLiteral("newVideoAi%1:%2").arg(kind, choice.value.isEmpty() ? QStringLiteral("default") : choice.value));
            a->setToolTip(choice.tip);
            a->setCheckable(true);
            a->setChecked(choice.value == current);
            group->addAction(a);
            connect(a, &QAction::triggered, this, [pick, value = choice.value]() { pick(value); });
        }
    };
    // the same steps as the chat's top row, so the chat shows the same choice afterwards
    const auto again = [this]() { QTimer::singleShot(0, this, [this]() { refreshAi(); }); };
    add(tr("AI"), QStringLiteral("Engine"), aiChatEngineChoicesHere(s), engine, [this, again](const QString &value) {
        if (value == QLatin1String("connect")) {
            ConnectAi::show(m_window);
        } else if (AiChat *c = aiChatInstance()) {
            aiChatPickEngine(c, value);
        } else {
            aiChatSaveSettings(QJsonObject{{"engine", value}});
        }
        again();
    });
    add(tr("Model"), QStringLiteral("Model"), models, modelNow, [again](const QString &value) {
        if (AiChat *c = aiChatInstance()) {
            aiChatPickSetting(c, false, value);
        } else {
            aiChatSaveSettings(QJsonObject{{aiChatModelKeyOf(aiChatEngineId(aiChatSettings())), value}});
        }
        again();
    });
    add(tr("Effort"), QStringLiteral("Effort"), efforts, effortNow, [again](const QString &value) {
        if (AiChat *c = aiChatInstance()) {
            aiChatPickSetting(c, true, value);
        } else {
            aiChatSaveSettings(QJsonObject{{aiChatEffortKeyOf(aiChatEngineId(aiChatSettings())), value}});
        }
        again();
    });
    if (!speeds.isEmpty()) {
        QMenu *sub = m_aiMenu->addMenu(tr("Reply speed"));
        auto group = new QActionGroup(sub);
        for (const auto &value : speeds) {
            const QJsonObject speed = value.toObject();
            const QString id = speed.value("value").toString();
            QAction *action = sub->addAction(speed.value("label").toString());
            action->setObjectName(QStringLiteral("newVideoAiSpeed:") + id);
            action->setToolTip(speed.value("tip").toString());
            action->setEnabled(speed.value("enabled").toBool());
            action->setCheckable(true);
            action->setChecked(id == speedNow);
            group->addAction(action);
            connect(action, &QAction::triggered, this, [engine, id, again]() {
                aiChatSaveSettings(QJsonObject{{aiSpeedKey(engine), id}});
                aiChatSettingsChanged();
                again();
            });
        }
    }
    m_aiMenu->addSeparator();
    QAction *connectAi = m_aiMenu->addAction(tr("Connect Your AI..."));
    connectAi->setObjectName(QStringLiteral("newVideoAiConnect"));
    connect(connectAi, &QAction::triggered, this, [this, again]() {
        ConnectAi::show(m_window);
        again();
    });
}

void NewVideoDialog::prepareReady()
{
    settleTheme();
    const LookChoice *asking = askingLook();
    showInputsFor(asking);
    const QString name = chosenName();
    m_readyHeading->setText(asking ? tr("Give %1 what it needs").arg(name) : tr("Ready to make your video"));
    m_readyLead->setText(summaryLine());
    m_readyLook->setText(name);
    m_readyLine->setText(chosenLine());
    m_readyPicture->setPixmap(chosenPicture(m_readyPicture->size()));
    const bool ai = noFootageForSummary();
    bool aboutAsked = false;
    if (asking)
        for (const LookAsk &ask : asking->asks)
            aboutAsked |= ask.role == QLatin1String("about");
    m_aboutBox->setVisible(!(ai && aboutAsked));
    m_aboutTitle->setText(ai ? tr("What's it about?") : tr("Anything the AI should know?"));
    m_aboutNeed->setText(ai ? tr("Required") : tr("Optional"));
    m_about->setAccessibleName(m_aboutTitle->text());
    m_about->setPlaceholderText(ai ? tr("e.g. How the first school bus was built, told as a newsreel, about 45 seconds.")
                                   : tr("e.g. keep the part where I laugh; leave out the drive there; end on the website."));
    m_about->setFixedHeight(asking ? 62 : 110);
    m_referencesBox->setVisible(ai);
    updateSummary();
    refreshAi();
    updateInputsState();
}

// The chosen Look's or style's name, line and picture, for Ready
const LookChoice *NewVideoDialog::chosenLookCard() const
{
    const LookStyle *ls = lookStyle(m_style);
    return ls ? findLook(*ls, m_look) : nullptr;
}

const StyleChoice *NewVideoDialog::chosenCatalogCard() const
{
    for (const auto &c : m_catalog)
        if (c.name == m_style)
            return &c;
    return nullptr;
}

QString NewVideoDialog::chosenName() const
{
    if (m_look == QLatin1String("pending-learn"))
        return tr("%1 (still learning)").arg(m_pendingLearnName);
    if (m_look == QLatin1String("freestyle"))
        return tr("Freestyle");
    if (const LookChoice *look = chosenLookCard())
        return look->label;
    if (lookStyle(m_style))
        return tabLooks(m_style).isEmpty() ? tr("Let the AI pick a Look") : tr("Let the AI pick a %1 Look").arg(lookStyle(m_style)->label);
    if (m_style == QLatin1String("custom"))
        return tr("Custom");
    if (const StyleChoice *c = chosenCatalogCard())
        return c->label + (c->mine ? tr(" (your Look)") : QString());
    return tr("Let the AI choose");
}

QString NewVideoDialog::chosenLine() const
{
    if (m_look == QLatin1String("freestyle"))
        return tr("No set Look: your AI edits it the way it thinks suits your clips.");
    if (const LookChoice *look = chosenLookCard())
        return look->line;
    if (lookStyle(m_style))
        return tr("It looks at your footage, picks one and tells you why.");
    if (m_style == QLatin1String("custom"))
        return tr("The settings you chose. Your AI decides the rest.");
    if (const StyleChoice *c = chosenCatalogCard())
        return c->summary;
    return tr("Your AI picks the pace, captions, effects and music.");
}

QPixmap NewVideoDialog::chosenPicture(const QSize &size) const
{
    if (m_look == QLatin1String("freestyle"))
        return freestylePicture(size);
    if (const LookChoice *look = chosenLookCard()) {
        const QPixmap poster(look->poster);
        if (!poster.isNull())
            return poster.scaled(size, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation)
                .copy(QRect(QPoint(0, 0), size));
    }
    if (m_style == QLatin1String("none") || m_style.isEmpty() || lookStyle(m_style))
        return aiPickPicture(size);
    return framedPicture(placeholderPicture(chosenName(), false), size);
}

void NewVideoDialog::updateSummary()
{
    const QString length = m_aiLength->isChecked() ? tr("Length chosen by your AI")
                                                   : (normalizedLength().isEmpty() ? m_length->text().trimmed().toHtmlEscaped()
                                                                                   : tr("About %1").arg(m_length->text().trimmed().toHtmlEscaped()));
    const QMap<QString, QString> kinds{{QStringLiteral("short"), tr("Short, vertical")},
                                       {QStringLiteral("long"), tr("YouTube video, horizontal")},
                                       {QStringLiteral("both"), tr("A YouTube video and a Short")},
                                       {QStringLiteral("custom"), m_custom->toPlainText().trimmed().left(120).toHtmlEscaped()}};
    QStringList rows{kinds.value(m_kind), length};
    if (noFootageForSummary()) {
        rows << tr("No footage: your AI draws everything");
    } else {
        const QString folder = QFileInfo(m_folder->text().trimmed()).fileName().toHtmlEscaped();
        rows << (m_selectedFiles.isEmpty() ? tr("Footage: the folder %1").arg(folder)
                                           : tr("Footage: %n file(s) from %1", "", m_selectedFiles.size()).arg(folder));
    }
    if (m_turbo && m_turbo->isChecked())
        rows << tr("Turbo on: sacrifices quality for speed");
    if (m_song && (!m_modern || m_music == QLatin1String("auto")) && !m_song->text().trimmed().isEmpty())
        rows << tr("Song to cut to: %1. You add it when you post; the file you upload has none of it.")
                    .arg(QFileInfo(m_song->text().trimmed().remove(QLatin1Char('"'))).fileName().toHtmlEscaped());
    m_summary->setText(rows.join(QStringLiteral("<br>")));
}

// the Look draws everything: no footage is named
bool NewVideoDialog::noFootageForSummary() const
{
    if (m_noFootage)
        return true;
    const LookStyle *ls = lookStyle(m_style);
    const LookChoice *look = ls ? findLook(*ls, m_look) : nullptr;
    return look && look->worksWith == QLatin1String("no-footage");
}

} // namespace NewVideo
