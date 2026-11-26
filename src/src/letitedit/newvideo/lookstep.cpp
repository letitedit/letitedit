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

// New video, step 4: Look (Let the AI pick, the Style's Looks, Match a video I like, Adjust).
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

#include <QImageReader>

namespace NewVideo {

QWidget *NewVideoDialog::stylePage()
{
    QVBoxLayout *column = nullptr;
    auto w = page(tr("Pick a Look"),
                  tr("Not sure? Keep \"Let the AI choose\". Press the speaker on a preview to hear it."),
                  &column);
    m_styleHeading = w->findChild<QLabel *>(QStringLiteral("newVideoHeading"));
    m_styleLead = w->findChild<QLabel *>(QStringLiteral("newVideoLead"));
    buildLookFilters(w, column);
    buildLookFitChoice(w, column);
    m_styleSlides = new QStackedWidget(w);
    buildLegacyLookBrowser(w);
    buildCustomLookPage(w);
    buildModernLookPage(w);
    column->addWidget(m_styleSlides, 1);
    m_styleNote = new QLabel(w);
    m_styleNote->setObjectName(QStringLiteral("newVideoStyleNote"));
    m_styleNote->setProperty("studioMuted", true);
    m_styleNote->setWordWrap(true);
    column->addWidget(m_styleNote);
    connectLookChoices();
    return w;
}

void NewVideoDialog::buildMasterSlider(QWidget *customBody, QVBoxLayout *sliders)
{
    auto masterRow = new QHBoxLayout;
    auto masterToy = new SliderToy(QStringLiteral("master"), customBody);
    masterToy->setObjectName(QStringLiteral("newVideoToy_master"));
    masterToy->setLevel(-1);
    masterRow->addWidget(masterToy);
    auto masterTitle = new QLabel(tr("How much is going on?"), customBody);
    masterTitle->setObjectName(QStringLiteral("newVideoMasterTitle"));
    masterRow->addWidget(masterTitle);
    auto master = new CustomSlider(customBody);
    m_master = master;
    master->setObjectName(QStringLiteral("newVideoSlider_master"));
    master->setRange(0, 6);
    master->setValue(3);
    master->setTickInterval(1);
    master->setTickPosition(QSlider::TicksBelow);
    auto masterScale = new QVBoxLayout;
    masterScale->addWidget(master);
    auto masterEnds = new QHBoxLayout;
    masterEnds->addWidget(new QLabel(tr("None"), customBody));
    masterEnds->addStretch();
    masterEnds->addWidget(new QLabel(tr("Max"), customBody));
    masterScale->addLayout(masterEnds);
    masterRow->addLayout(masterScale, 1);
    auto masterValue = new QLabel(customBody);
    masterValue->setObjectName(QStringLiteral("newVideoValue_master"));
    masterValue->setMinimumWidth(96);
    masterRow->addWidget(masterValue);
    auto masterAi = new QCheckBox(customBody);
    masterAi->setAccessibleName(tr("Let the AI decide how much is going on"));
    masterAi->setToolTip(tr("Let the AI choose this setting"));
    m_masterAi = masterAi;
    masterAi->setObjectName(QStringLiteral("newVideoAi_master"));
    masterAi->setChecked(true);
    masterAi->setStyleSheet(QStringLiteral("QCheckBox::indicator { width: 32px; height: 18px; border-radius: 9px; background: #59646A; } QCheckBox::indicator:checked { background: #2A8597; border: 2px solid #A8E1E7; }"));
    masterRow->addWidget(masterAi);
    sliders->addLayout(masterRow);
    auto refreshMaster = [master, masterAi, masterValue, masterToy]() {
        static const QStringList words{QObject::tr("None"), QObject::tr("A little"), QObject::tr("Some"),
                                       QObject::tr("Balanced"), QObject::tr("Packed"), QObject::tr("A lot"), QObject::tr("Max")};
        masterValue->setText(masterAi->isChecked() ? QObject::tr("AI decides") : words[master->value()]);
        masterToy->setLevel(masterAi->isChecked() ? -1 : master->value());
        master->setStyleSheet(masterAi->isChecked() ? QStringLiteral("QSlider::groove:horizontal { background: #59646A; } QSlider::sub-page:horizontal { background: #59646A; } QSlider::handle:horizontal { background: #89959A; width: 18px; border-radius: 9px; }")
                                               : QStringLiteral("QSlider::sub-page:horizontal { background: #2A8597; } QSlider::handle:horizontal { background: #C8653B; width: 18px; border-radius: 9px; }"));
    };
    master->onTouch([this, masterAi]() { if (!m_loadingPreset) m_legacyStyle.clear(); masterAi->setChecked(false); });
    connect(masterAi, &QCheckBox::toggled, this, [this, master, refreshMaster](bool automatic) {
        refreshMaster();
        if (m_loadingPreset)
            return;
        m_legacyStyle.clear();
        for (auto it = m_sliders.cbegin(); it != m_sliders.cend(); ++it) {
            if (it.key() == QLatin1String("cutting") || it.key() == QLatin1String("dialogue") || it.key() == QLatin1String("pauses"))
                continue;
            it.value()->setValue(master->value());
            m_aiSwitches.value(it.key())->setChecked(automatic);
        }
    });
    connect(master, &QSlider::valueChanged, this, [this, masterAi, refreshMaster](int level) {
        if (!m_loadingPreset)
            m_legacyStyle.clear();
        masterAi->setChecked(false);
        refreshMaster();
        for (auto it = m_sliders.cbegin(); it != m_sliders.cend(); ++it) {
            if (it.key() == QLatin1String("cutting") || it.key() == QLatin1String("dialogue") || it.key() == QLatin1String("pauses"))
                continue;
            it.value()->setValue(level);
            m_aiSwitches.value(it.key())->setChecked(false);
        }
    });
    refreshMaster();
    masterValue->setMinimumWidth(105);
}

void NewVideoDialog::buildStyleSliders(QWidget *customBody, QVBoxLayout *sliders)
{
    const QList<QStringList> fields = {
        {"courage", tr("Courage"), tr("None|Curious|Bold|Daring|Wild|Unhinged|Max"), tr("Keep it familiar|Try one surprise|Take a few risks|Make bold choices|Mix unexpected ideas|Let the AI get weird|Push every fitting idea")},
        {"transitions", tr("Transitions"), tr("None|Soft|Some|Lively|Bold|Wild|Max"), tr("No added transitions|A gentle change|A few smooth joins|Changes mark sections|Strong visual changes|Frequent varied wipes|Every fitting join can play")},
        {"punch_ins", tr("Punch-ins and zooms"), tr("None|A nudge|Some|Often|Lots|Punchy|Max"), tr("No added zooms|One key moment|Zoom on a few points|Zoom on key words|Most key points pop|Big close-up energy|Every fitting beat moves")},
        {"emoji", tr("Emoji and stickers"), tr("None|A sprinkle|Some|Lots|Everywhere|Mind blown|Max"), tr("No stickers|One small reaction|A few relevant reactions|Many playful moments|Most beats get a reaction|Big reactions throughout|Every fitting moment pops")},
        {"captions", tr("Captions"), tr("None|Quiet|Clear|Expressive|Word pop|Big|Max"), tr("No on-screen captions|A few key phrases|Readable speech captions|Emphasize key words|Words pop with the beat|Large animated phrases|Words become the design")},
        {"three_d", tr("3D effects"), tr("None|A hint|Some depth|Turning|Bold depth|Playful 3D|Max"), tr("No added 3D|A touch of depth|A few dimensional details|Objects turn for emphasis|Depth drives key scenes|Frequent 3D moments|Go dimensional when it fits")},
        {"motion", tr("Motion graphics"), tr("None|Gentle|Some|Lively|Big|Explosive|Max"), tr("No motion graphics|A soft title move|A few moving details|Animated key points|Motion leads sections|Large bursts and reveals|Full motion treatment")},
        {"overlays", tr("Overlays"), tr("None|A layer|Some|Layered|Busy|Stacked|Max"), tr("No added overlays|One subtle layer|A few helpful labels|Layers explain key ideas|Several layers at once|Dense but readable stacks|Every fitting layer appears")},
        {"cutting", tr("Cutting speed"), tr("Snail|Turtle|Walking|Running|Driving|Rocket|Frantic"), tr("Let shots breathe|Slow and steady|Comfortable pace|Quick on key beats|Fast through the story|Rapid cuts|As fast as clarity allows")},
        {"pauses", tr("Natural pauses ↔ Jump cuts"), tr("Natural|Roomy|Relaxed|Balanced|Tight|Jump cuts|Max jumps"), tr("Keep natural pauses|Leave generous breaths|Trim only long drag|Balance breaths and momentum|Tighten most dead air|Favor jump cuts|Tighten hard without clipping words")},
        {"dialogue", tr("Dialogue kept"), tr("Best lines|Highlights|Selective|Balanced|Talk-led|Almost all|Every word"), tr("Only the strongest lines|Keep the main points|Keep useful explanations|Balance words and visuals|Let talking lead|Trim only clear repeats|Keep every useful word")},
        {"music", tr("Music"), tr("None|A hint|Underneath|Present|Driving|Big|Max"), tr("No score|A quiet touch|Music supports speech|Music shapes sections|Music drives the energy|Big musical lifts|Score every fitting moment")},
        {"sound", tr("Sound effects"), tr("None|A touch|Some|Lively|Lots|Whooshy|Max"), tr("No added sounds|One accent|A few useful cues|Sounds mark key beats|Many playful accents|Frequent whooshes and hits|Sound design throughout")},
        {"broll", tr("B-roll"), tr("None|A glimpse|Some|Often|Lots|Picture-led|Max"), tr("No added B-roll|One proving shot|Show a few details|Cover key explanations|Show many examples|Let picture tell the story|Use every fitting visual")}};
    for (const auto &field : fields) {
        auto row = new QHBoxLayout;
        auto toy = new SliderToy(field[0], customBody);
        toy->setObjectName(QStringLiteral("newVideoToy_%1").arg(field[0]));
        row->addWidget(toy);
        auto words = new QVBoxLayout;
        words->setSpacing(1);
        auto title = new QLabel(field[1], customBody);
        if (field[0] == QLatin1String("courage")) {
            // the one name here that doesn't say what it changes
            title->setText(tr("Courage: how adventurous the choices are"));
            title->setToolTip(tr("How far the AI may go from the safe, familiar choice for this video. It changes the ideas it "
                                 "tries, not how many effects it uses: those have their own sliders."));
        }
        words->addWidget(title);
        auto meaning = new QLabel(customBody);
        meaning->setObjectName(QStringLiteral("newVideoMeaning_%1").arg(field[0]));
        meaning->setProperty("studioMuted", true);
        meaning->setWordWrap(true);
        words->addWidget(meaning);
        row->addLayout(words, 1);
        auto slider = new CustomSlider(customBody);
        slider->setObjectName(QStringLiteral("newVideoSlider_%1").arg(field[0]));
        slider->setRange(0, 6);
        slider->setValue(3);
        slider->setTickInterval(1);
        slider->setTickPosition(QSlider::TicksBelow);
        m_sliders.insert(field[0], slider);
        auto scale = new QVBoxLayout;
        scale->addWidget(slider);
        auto ends = new QHBoxLayout;
        ends->addWidget(new QLabel(field[0] == QLatin1String("cutting") ? tr("Slow")
                                   : field[0] == QLatin1String("pauses") ? tr("Natural pauses")
                                   : field[0] == QLatin1String("dialogue") ? tr("Best lines") : tr("None"), customBody));
        ends->addStretch();
        ends->addWidget(new QLabel(field[0] == QLatin1String("cutting") ? tr("Fast")
                                   : field[0] == QLatin1String("pauses") ? tr("Jump cuts")
                                   : field[0] == QLatin1String("dialogue") ? tr("Every word") : tr("Max"), customBody));
        scale->addLayout(ends);
        row->addLayout(scale, 2);
        auto value = new QLabel(customBody);
        value->setObjectName(QStringLiteral("newVideoValue_%1").arg(field[0]));
        value->setMinimumWidth(95);
        const QStringList labels = field[2].split(QLatin1Char('|'));
        const QStringList descriptions = field[3].split(QLatin1Char('|'));
        m_sliderFields.append({field[0], field[1], labels, descriptions});
        auto ai = new QCheckBox(customBody);
        ai->setAccessibleName(tr("Let the AI decide: %1").arg(field[1]));
        ai->setToolTip(tr("Let the AI choose this setting"));
        ai->setObjectName(QStringLiteral("newVideoAi_%1").arg(field[0]));
        ai->setChecked(true);
        ai->setStyleSheet(m_masterAi->styleSheet());
        m_aiSwitches.insert(field[0], ai);
        auto refresh = [slider, ai, value, meaning, toy, labels, descriptions]() {
            const bool automatic = ai->isChecked();
            value->setText(automatic ? QObject::tr("AI decides") : labels.value(slider->value()));
            meaning->setText(automatic ? QString() : descriptions.value(slider->value()));
            meaning->setVisible(!automatic); // "AI decides" beside the switch already says it
            toy->setLevel(automatic ? -1 : slider->value());
            slider->setStyleSheet(automatic ? QStringLiteral("QSlider::groove:horizontal { background: #59646A; } QSlider::sub-page:horizontal { background: #59646A; } QSlider::handle:horizontal { background: #89959A; width: 18px; border-radius: 9px; }")
                                            : QStringLiteral("QSlider::sub-page:horizontal { background: #2A8597; } QSlider::handle:horizontal { background: #C8653B; width: 18px; border-radius: 9px; }"));
        };
        slider->onTouch([this, ai]() { if (!m_loadingPreset) m_legacyStyle.clear(); ai->setChecked(false); });
        connect(ai, &QCheckBox::toggled, this, [this, refresh](bool) { if (!m_loadingPreset) m_legacyStyle.clear(); refresh(); });
        connect(slider, &QSlider::valueChanged, this, [this, ai, refresh](int) {
            if (!m_loadingPreset)
                m_legacyStyle.clear();
            ai->setChecked(false);
            refresh();
        });
        refresh();
        row->addWidget(value);
        row->addWidget(ai);
        sliders->addLayout(row);
    }
}

void NewVideoDialog::buildLookFilters(QWidget *w, QVBoxLayout *column)
{
    // categories, as filters on this one screen; they come from looks\manifest.json, and a long list scrolls
    auto filtersScroll = new QScrollArea(w);
    filtersScroll->setObjectName(QStringLiteral("newVideoLookFilters"));
    filtersScroll->setFrameShape(QFrame::NoFrame);
    filtersScroll->setFixedHeight(40);
    filtersScroll->setWidgetResizable(true);
    filtersScroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    auto filtersBody = new QWidget(filtersScroll);
    m_filterRow = new QHBoxLayout(filtersBody);
    m_filterRow->setContentsMargins(0, 0, 0, 0);
    m_filterRow->setSpacing(6);
    filtersScroll->setWidget(filtersBody);
    m_filtersScroll = filtersScroll;
    column->addWidget(filtersScroll);
    m_chosenLine = new QLabel(w);
    m_chosenLine->setObjectName(QStringLiteral("newVideoChosen"));
    m_chosenLine->setProperty("studioMuted", true);
    m_chosenLine->setWordWrap(true);
    m_chosenLine->hide();
    column->addWidget(m_chosenLine);
}

void NewVideoDialog::buildLookFitChoice(QWidget *w, QVBoxLayout *column)
{
    // T174: the fit check's line for a learned Look, and its way out when the clips don't fit
    m_fitHolder = new QWidget(w);
    m_fitHolder->setObjectName(QStringLiteral("newVideoFit"));
    auto fitRow = new QHBoxLayout(m_fitHolder);
    fitRow->setContentsMargins(0, 0, 0, 0);
    fitRow->setSpacing(10);
    m_fitNote = new QLabel(m_fitHolder);
    m_fitNote->setObjectName(QStringLiteral("newVideoFitNote"));
    m_fitNote->setWordWrap(true);
    fitRow->addWidget(m_fitNote, 1);
    m_lookOnly = new QCheckBox(tr("Make it with only the look"), m_fitHolder);
    m_lookOnly->setObjectName(QStringLiteral("newVideoLookOnly"));
    m_lookOnly->setToolTip(tr("Keep this Look's captions, graphics, colour and pace, and cut your clips the way they suit "
                              "instead of following its format."));
    m_lookOnly->hide();
    fitRow->addWidget(m_lookOnly);
    m_fitHolder->hide();
    column->addWidget(m_fitHolder);
}

void NewVideoDialog::buildLegacyLookBrowser(QWidget *w)
{
    auto scroll = new QScrollArea(w);
    m_styleScroll = scroll;
    scroll->setObjectName(QStringLiteral("newVideoStyles"));
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    m_styleHolder = new QWidget(scroll);
    m_styleGrid = new QGridLayout(m_styleHolder);
    m_styleGrid->setSpacing(12);
    m_styleGrid->setContentsMargins(0, 0, 8, 0);
    scroll->setWidget(m_styleHolder);
    m_styleSlides->addWidget(scroll);
}

void NewVideoDialog::buildCustomLookPage(QWidget *w)
{
    auto customScroll = new QScrollArea(w);
    customScroll->setObjectName(QStringLiteral("newVideoCustomSliders"));
    customScroll->setWidgetResizable(true);
    auto customBody = new QWidget(customScroll);
    auto sliders = new QVBoxLayout(customBody);
    auto intro = new QLabel(tr("AI decides on each setting until you take over. Move a slider or turn its switch off. Save a mix below to use it again."), customBody);
    intro->setWordWrap(true);
    sliders->addWidget(intro);
    auto presetRow = new QHBoxLayout;
    m_presetList = new QComboBox(customBody);
    m_presetList->setObjectName(QStringLiteral("newVideoPresets"));
    m_presetList->setMinimumWidth(170);
    presetRow->addWidget(m_presetList, 1);
    m_presetName = new QLineEdit(customBody);
    m_presetName->setObjectName(QStringLiteral("newVideoPresetName"));
    m_presetName->setPlaceholderText(tr("Name for this mix"));
    presetRow->addWidget(m_presetName, 1);
    auto savePreset = new QPushButton(tr("Save new"), customBody);
    savePreset->setObjectName(QStringLiteral("newVideoPresetSave"));
    presetRow->addWidget(savePreset);
    auto renamePreset = new QPushButton(tr("Rename"), customBody);
    renamePreset->setObjectName(QStringLiteral("newVideoPresetRename"));
    presetRow->addWidget(renamePreset);
    auto deletePreset = new QPushButton(tr("Delete"), customBody);
    deletePreset->setObjectName(QStringLiteral("newVideoPresetDelete"));
    presetRow->addWidget(deletePreset);
    auto defaultPreset = new QPushButton(tr("☆ Default"), customBody);
    defaultPreset->setObjectName(QStringLiteral("newVideoPresetDefault"));
    presetRow->addWidget(defaultPreset);
    sliders->addLayout(presetRow);
    m_presetNote = new QLabel(customBody);
    m_presetNote->setWordWrap(true);
    m_presetNote->setProperty("studioMuted", true);
    m_presetNote->setObjectName(QStringLiteral("newVideoPresetNote"));
    sliders->addWidget(m_presetNote);
    buildMasterSlider(customBody, sliders);
    auto reset = new QPushButton(tr("Reset all to AI decides"), customBody);
    reset->setObjectName(QStringLiteral("newVideoResetSliders"));
    sliders->addWidget(reset, 0, Qt::AlignLeft);
    connect(reset, &QPushButton::clicked, this, [this]() {
        resetCustom();
    });
    buildStyleSliders(customBody, sliders);
    connect(m_presetList, qOverload<int>(&QComboBox::currentIndexChanged), this, [this](int) { loadSelectedPreset(); });
    connect(savePreset, &QPushButton::clicked, this, [this]() { saveCurrentPreset(); });
    connect(renamePreset, &QPushButton::clicked, this, [this]() { renameSelectedPreset(); });
    connect(deletePreset, &QPushButton::clicked, this, [this]() { deleteSelectedPreset(); });
    connect(defaultPreset, &QPushButton::clicked, this, [this]() { starSelectedPreset(); });
    m_defaultPresetButton = defaultPreset;
    fillPresets();
    // Adjust keeps a Look of its own: the older saved mixes of settings are not offered here
    for (QWidget *old : {static_cast<QWidget *>(m_presetList), static_cast<QWidget *>(m_presetName), static_cast<QWidget *>(savePreset),
                         static_cast<QWidget *>(renamePreset), static_cast<QWidget *>(deletePreset), static_cast<QWidget *>(defaultPreset),
                         static_cast<QWidget *>(m_presetNote)})
        old->hide();
    auto saveRow = new QHBoxLayout;
    m_adjustName = new QLineEdit(customBody);
    m_adjustName->setObjectName(QStringLiteral("newVideoAdjustName"));
    m_adjustName->setPlaceholderText(tr("Name of your Look"));
    saveRow->addWidget(m_adjustName, 1);
    auto saveAdjust = new QPushButton(tr("Save as my Look"), customBody);
    saveAdjust->setObjectName(QStringLiteral("newVideoAdjustSave"));
    saveAdjust->setProperty("studioPrimary", true);
    saveAdjust->setAutoDefault(false);
    saveAdjust->setToolTip(tr("Keep these settings as a Look of your own under Your Looks, and use it for this video"));
    connect(saveAdjust, &QPushButton::clicked, this, [this]() { saveAdjusted(); });
    saveRow->addWidget(saveAdjust);
    sliders->addStretch(1);
    customScroll->setWidget(customBody);
    auto customPage = new QWidget(w);
    auto customPageColumn = new QVBoxLayout(customPage);
    customPageColumn->setContentsMargins(0, 0, 0, 0);
    customPageColumn->addWidget(customScroll, 1);
    customPageColumn->addLayout(saveRow);
    m_styleSlides->addWidget(customPage);
}

void NewVideoDialog::buildModernLookPage(QWidget *w)
{
    auto modernScroll = new QScrollArea(w);
    modernScroll->setObjectName(QStringLiteral("newVideoChoices"));
    modernScroll->setWidgetResizable(true);
    modernScroll->setFrameShape(QFrame::NoFrame);
    m_modernBody = new QWidget(modernScroll);
    m_modernColumn = new QVBoxLayout(m_modernBody);
    m_modernColumn->setContentsMargins(0, 0, 8, 0);
    m_modernColumn->setSpacing(8);
    m_lookCardsHolder = new QWidget(m_modernBody);
    m_lookCardsLayout = new QVBoxLayout(m_lookCardsHolder);
    m_lookCardsLayout->setContentsMargins(0, 0, 0, 0);
    m_modernColumn->addWidget(m_lookCardsHolder);
    auto adjustRow = new QHBoxLayout;
    m_adjustButton = new QPushButton(tr("Adjust..."), m_modernBody);
    m_adjustButton->setObjectName(QStringLiteral("newVideoAdjust"));
    m_adjustButton->setAutoDefault(false);
    m_adjustButton->setEnabled(false);
    connect(m_adjustButton, &QPushButton::clicked, this, [this]() {
        m_customStylePage = true;
        go(PLook);
    });
    adjustRow->addWidget(m_adjustButton);
    adjustRow->addStretch(1);
    m_modernColumn->addLayout(adjustRow);
    // Match a video I like: the same learning as Home's Learn from a video, started from here
    m_learnHolder = new QWidget(m_modernBody);
    m_learnHolder->setObjectName(QStringLiteral("newVideoLearnHolder"));
    auto learnColumn = new QVBoxLayout(m_learnHolder);
    learnColumn->setContentsMargins(0, 0, 0, 0);
    auto learnTitle = new QLabel(tr("Match a video I like"), m_learnHolder);
    learnTitle->setObjectName(QStringLiteral("newVideoFieldTitle"));
    learnColumn->addWidget(learnTitle);
    m_learnPanel = new LearnLooks::Panel(m_window, m_learnHolder);
    m_learnPanel->onStarted([this](const QString &path, const QString &name) {
        m_pendingLearnJob = path;
        m_pendingLearnName = name;
        m_look = QStringLiteral("pending-learn");
        m_theme = QStringLiteral("freestyle");
        m_themeChosen = false;
        m_personChose = true;
        QTimer::singleShot(0, this, [this]() { refreshChoicePages(); });
    });
    m_learnPanel->onLearned([this](const QString &id, const QString &) {
        m_pendingLearnJob.clear();
        m_selectLook = id;
        loadLooks();
    });
    learnColumn->addWidget(m_learnPanel);
    m_learnHolder->hide();
    m_modernColumn->addWidget(m_learnHolder);
    m_modernColumn->addStretch(1);
    modernScroll->setWidget(m_modernBody);
    m_styleSlides->addWidget(modernScroll);
}

void NewVideoDialog::connectLookChoices()
{
    // one choice across the whole browser: a card says which Style it is and, for a Look, which Look
    m_styles = new QButtonGroup(this);
    connect(m_styles, &QButtonGroup::buttonToggled, this, [this](QAbstractButton *b, bool checked) {
        if (!checked || m_filling)
            return;
        m_style = b->property("style").toString();
        const QString look = b->property("look").toString();
        m_look = look.isEmpty() ? QStringLiteral("auto") : look;
        m_personChose = true;
        m_freestyleByDefault = false;
        if (m_modern) {
            m_styleExplicit = true;
            m_theme = QStringLiteral("freestyle");
            m_themeChosen = false;
            QTimer::singleShot(0, this, [this]() { go(PLook); }); // the row again, and Next says Open the editor for Edit with the AI myself
        }
        m_lookNote.clear();
        m_chosenLine->hide();
        m_problem->hide();
        if (m_styleScroll) {
            QPointer<QAbstractButton> card(b);
            QTimer::singleShot(0, m_styleScroll, [this, card]() {
                if (card)
                    m_styleScroll->ensureWidgetVisible(card);
            });
        }
    });
}

// ---- Adjust: the sliders, kept as "<Look> (yours)" under Your Looks ---------------------------------------------
void NewVideoDialog::saveAdjusted()
{
    const LookStyle *style = lookStyle(m_style);
    const LookChoice *base = style ? findLook(*style, m_look) : nullptr;
    if (!base) {
        m_problem->setText(tr("Pick a Look to adjust first."));
        m_problem->show();
        return;
    }
    const QString name = m_adjustName->text().trimmed().isEmpty() ? tr("%1 (yours)").arg(base->label) : m_adjustName->text().trimmed();
    QJsonObject levels;
    QJsonArray left;
    for (const SliderField &field : std::as_const(m_sliderFields)) {
        auto slider = m_sliders.value(field.key);
        auto ai = m_aiSwitches.value(field.key);
        if (!slider || !ai)
            continue;
        if (ai->isChecked()) {
            left << field.title;
            continue;
        }
        levels.insert(field.key, QJsonObject{{"title", field.title},
                                              {"label", field.labels.value(slider->value())},
                                              {"meaning", field.descriptions.value(slider->value())}});
    }
    if (levels.isEmpty()) {
        m_problem->setText(tr("Move a slider first, or turn its AI switch off. Everything is still on AI decides."));
        m_problem->show();
        return;
    }
    QProcess process;
    process.start(aiChatSettings().value("python").toString(),
                  {aiRootPath(QStringLiteral("bridge/look_adjust.py")), QStringLiteral("save"), QStringLiteral("--base"), base->id,
                   QStringLiteral("--name"), name, QStringLiteral("--settings"), QStringLiteral("-")});
    if (!process.waitForStarted(5000)) {
        m_problem->setText(tr("Couldn't keep your Look. Try again in a moment."));
        m_problem->show();
        return;
    }
    process.write(QJsonDocument(QJsonObject{{"levels", levels}, {"ai", left}}).toJson());
    process.closeWriteChannel();
    if (!process.waitForFinished(20000))
        process.kill();
    const QJsonObject result = QJsonDocument::fromJson(process.readAllStandardOutput()).object();
    if (process.exitCode() != 0 || !result.contains("id")) {
        m_problem->setText(tr("Couldn't keep your Look: %1").arg(QString::fromUtf8(process.readAllStandardError()).trimmed().right(200)));
        m_problem->show();
        return;
    }
    m_selectLook = result.value("id").toString();
    m_customStylePage = false;
    resetCustom();
    loadLooks();
    go(PLook);
}

// The Look stage's heading and lead: the one browser, or the detailed settings
void NewVideoDialog::showStylePageTexts()
{
    if (!m_styleHeading || !m_styleLead)
        return;
    const bool custom = m_customStylePage;
    m_filtersScroll->setVisible(!custom && !m_modern);
    if (custom) {
        m_chosenLine->hide();
        m_styleNote->hide();
        const LookStyle *adjusting = lookStyle(m_style);
        const LookChoice *base = adjusting ? findLook(*adjusting, m_look) : nullptr;
        m_styleHeading->setText(base ? tr("Adjust %1").arg(base->label) : tr("Adjust"));
        m_styleLead->setText(tr("Nobody has to touch these. Anything left on AI decides stays your AI's call. Saving keeps your settings as a Look of your own."));
        if (m_adjustName && base && m_adjustName->text().trimmed().isEmpty())
            m_adjustName->setText(tr("%1 (yours)").arg(base->label));
    } else {
        m_styleHeading->setText(tr("Pick a Look"));
        m_styleLead->setText(m_noFootage ? tr("With no footage, your AI draws the whole video. These Looks do that. Press the speaker on a preview to hear it.")
                                         : tr("Not sure? Keep \"Let the AI choose\". Press the speaker on a preview to hear it."));
    }
}

// the chosen Look's name on its card
QString NewVideoDialog::currentLookLabel(const LookStyle &style) const
{
    if (m_look == QLatin1String("auto"))
        return tr("Let the AI pick");
    if (m_look == QLatin1String("freestyle"))
        return tr("Freestyle");
    if (editMyself())
        return tr("Edit with the AI myself");
    for (const auto &look : style.looks)
        if (look.id == m_look)
            return look.label;
    return tr("Let the AI pick");
}

// "Let the AI pick": a calm block with a spark and a line, the same size as a preview
QPixmap NewVideoDialog::aiPickPicture(const QSize &size, bool showLabel)
{
    QPixmap picture(size);
    picture.fill(QColor(LetItEditColors::tealDeep));
    QPainter p(&picture);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(LetItEditColors::cream));
    const QPointF c(size.width() / 2.0, size.height() * 0.38);
    const qreal r = size.width() * 0.2;
    QPainterPath spark; // a four-pointed star
    spark.moveTo(c.x(), c.y() - r);
    spark.quadTo(c.x(), c.y(), c.x() + r, c.y());
    spark.quadTo(c.x(), c.y(), c.x(), c.y() + r);
    spark.quadTo(c.x(), c.y(), c.x() - r, c.y());
    spark.quadTo(c.x(), c.y(), c.x(), c.y() - r);
    p.drawPath(spark);
    QFont f = p.font();
    f.setBold(true);
    f.setPixelSize(qMax(12, size.width() / 10));
    p.setFont(f);
    p.setPen(QColor(LetItEditColors::cream));
    if (showLabel)
        p.drawText(QRect(6, int(size.height() * 0.55), size.width() - 12, size.height() / 3), Qt::AlignHCenter | Qt::AlignTop | Qt::TextWordWrap,
                   tr("Your AI picks the Look"));
    return picture;
}

// A picture of another shape, centred on a block the size of a preview, so every card lines up
QPixmap NewVideoDialog::framedPicture(const QPixmap &source, const QSize &size)
{
    QPixmap picture(size);
    picture.fill(QColor(LetItEditColors::deep));
    QPainter p(&picture);
    p.setRenderHint(QPainter::SmoothPixmapTransform);
    const QPixmap fitted = source.scaled(size, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    const QSizeF shown = QSizeF(fitted.size()) / fitted.devicePixelRatio();
    p.drawPixmap(QPointF((size.width() - shown.width()) / 2.0, (size.height() - shown.height()) / 2.0), fitted);
    return picture;
}

// How the previews play. Measured on a test window (tests\t43\REPORT.md): see the note there for the numbers.
// LETITEDIT_LOOK_PREVIEWS=hover|all overrides it (used for the measurements).
LookCard::Playback NewVideoDialog::lookPlayback(int cards)
{
    const QString choice = qEnvironmentVariable("LETITEDIT_LOOK_PREVIEWS");
    if (choice == QLatin1String("hover"))
        return LookCard::WhenHovered;
    if (choice == QLatin1String("all"))
        return LookCard::Always;
    // many Looks at once (the 32 drawn styles): never all at once
    if (cards > 5)
        return LookCard::WhenHovered;
    // measured on a test window: all four at 30 fps use about 40% of one core, the hovered one about a tenth of
    // that; a PC with fewer than four threads plays only the one under the pointer or chosen
    return QThread::idealThreadCount() >= 4 ? LookCard::Always : LookCard::WhenHovered;
}

// ---- the Look page: the Style's Looks, Match a video I like, Adjust -----------------------------------------------
namespace {
// T176: every Look card's picture is the video's own shape. A Short's row is 9:16 pictures, a YouTube video's 16:9; a
// preview of the other shape keeps its own shape, centred in the row (never cropped, never with bars).
QSize lookBox(bool tall) { return tall ? QSize(117, 208) : QSize(240, 135); }

QSize lookPictureSize(const QString &poster, bool tall)
{
    const QSize box = lookBox(tall);
    const QSize own = poster.isEmpty() ? QSize() : QImageReader(poster).size();
    if (!own.isValid() || own.isEmpty())
        return box;
    return own.scaled(box, Qt::KeepAspectRatio).expandedTo(QSize(24, 24));
}

// a name on a calm block that fills the whole picture (a Look with no preview, a learned Look)
QPixmap namePicture(const QString &label, const QSize &size)
{
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    static const QList<QColor> shades{QColor("#144F5F"), QColor("#3A2A22"), QColor("#2E363B"), QColor("#1F3A33")};
    p.setPen(Qt::NoPen);
    p.setBrush(shades[qHash(label) % shades.size()]);
    p.drawRoundedRect(QRectF(QPointF(0, 0), QSizeF(size)), 8, 8);
    QFont f = p.font();
    f.setPixelSize(qBound(14, size.width() / 7, 19));
    f.setBold(true);
    p.setFont(f);
    p.setPen(QColor(LetItEditColors::cream));
    p.drawText(QRect(10, 8, size.width() - 20, size.height() - 16), Qt::AlignCenter | Qt::TextWordWrap, label);
    return pixmap;
}

// Match a video I like (and a Look still learning): a dashed frame with film frames and a plus, filling the picture
QPixmap matchPicture(const QSize &size)
{
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(QPen(QColor(LetItEditColors::teal), 2, Qt::DashLine));
    p.setBrush(Qt::NoBrush);
    p.drawRoundedRect(QRectF(1, 1, size.width() - 2, size.height() - 2), 8, 8);
    const qreal frame = qMin(size.width() / 4.2, 34.0);
    const qreal top = size.height() * 0.32;
    for (int i = 0; i < 3; ++i) {
        const QRectF one(size.width() / 2.0 - frame * 1.6 + i * frame * 1.1, top, frame * 0.9, frame * 0.66);
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(LetItEditColors::tealDeep));
        p.drawRoundedRect(one, 3, 3);
    }
    QFont f = p.font();
    f.setPixelSize(30);
    f.setBold(true);
    p.setFont(f);
    p.setPen(QColor(LetItEditColors::tealLight));
    p.drawText(QRectF(0, top + frame * 0.66, size.width(), 44), Qt::AlignCenter, QStringLiteral("+"));
    return pixmap;
}
} // namespace

void NewVideoDialog::updateModernSummary()
{
    const auto style = lookStyle(m_style);
    const auto look = style ? findLook(*style, m_look) : nullptr;
    const QString format = m_kind == QLatin1String("long") ? tr("YouTube video") : tr("Short");
    const LookStyle *filmed = lookStyle(filmedStyle());
    m_styleNote->setText(tr("%1  ·  %2  ·  %3")
                            .arg(format, filmed ? filmed->label : tr("All kinds"),
                                 look ? look->label
                                 : m_look == QLatin1String("pending-learn") ? m_pendingLearnName
                                 : m_look == QLatin1String("freestyle") ? tr("Freestyle")
                                 : editMyself() ? tr("Edit with the AI myself: opens the editor")
                                                : tr("AI picks the Look")));
    (void) style;
    m_styleNote->show();
}

void NewVideoDialog::showLearnPanel(bool shown)
{
    m_learnShown = shown;
    m_learnHolder->setVisible(shown || (m_learnPanel && m_learnPanel->isLearning()));
}

void NewVideoDialog::fillModernBrowser()
{
    if (!m_lookCardsLayout)
        return;
    m_styleSlides->setCurrentIndex(2);
    detectFilmed();
    settleTab();
    const LookStyle *style = lookStyle(m_style);
    m_styleHeading->setText(tr("Pick a Look"));
    m_styleLead->setText(m_noFootage ? tr("The layout of your video: where things go and how it moves. Your AI draws all of it.")
                                     : tr("The layout of your video: where things go and how it moves. The tabs are kinds of video; "
                                          "the one your clips look like is chosen."));
    m_filtersScroll->hide();
    m_chosenLine->setText(m_lookNote);
    m_chosenLine->setVisible(!m_lookNote.isEmpty());
    m_filling = true;
    m_lookCards.clear();
    clearLayout(m_lookCardsLayout, [this](QWidget *widget) {
        if (auto button = qobject_cast<QAbstractButton *>(widget))
            m_styles->removeButton(button);
    });
    auto lookScroll = new QScrollArea(m_lookCardsHolder);
    lookScroll->setObjectName(QStringLiteral("newVideoLooksScroll"));
    lookScroll->setFrameShape(QFrame::NoFrame);
    lookScroll->setWidgetResizable(true);
    lookScroll->setFixedHeight(m_review ? 266 : 232);
    lookScroll->setVerticalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    auto lookBody = new QWidget(lookScroll);
    auto cardRow = new QHBoxLayout(lookBody);
    cardRow->setContentsMargins(0, 0, 0, 0);
    cardRow->setSpacing(10);
    lookScroll->setWidget(lookBody);
    buildLookTabs();
    m_lookCardsLayout->addWidget(lookScroll);
    fillLookCards(style, lookScroll, lookBody, cardRow);
    const LookChoice *chosen = style ? findLook(*style, m_look) : nullptr;
    m_adjustButton->setEnabled(chosen != nullptr);
    m_adjustButton->setText(chosen ? tr("Adjust %1...").arg(chosen->label) : tr("Adjust..."));
    m_adjustButton->setToolTip(chosen ? tr("Change how much of each ingredient goes in, and keep it as your own Look")
                                      : tr("Pick one of the Looks first"));
    for (auto card : std::as_const(m_lookCards))
        if (card && card->isChecked())
            QTimer::singleShot(0, lookScroll, [lookScroll, shown = QPointer<LookCard>(card)]() {
                if (shown)
                    lookScroll->ensureWidgetVisible(shown);
            });
    showLearnPanel(m_learnShown);
    updateModernSummary();
    if (m_review)
        for (const auto &value : m_reviewItems) {
            const auto item = value.toObject();
            if (!item.value("cut").toBool())
                continue;
            auto row = new QHBoxLayout;
            row->addWidget(new QLabel(tr("Cut: %1").arg(item.value("title").toString()), m_lookCardsHolder));
            addReviewButtons(row, item.value("entry_kind").toString(), item.value("id").toString(), item.value("review").toString(), true);
            row->addStretch(1);
            m_lookCardsLayout->addLayout(row);
        }
    m_filling = false;
    checkFit();
}

void NewVideoDialog::buildLookTabs()
{
    // T179: the kinds of video as tabs, the one the clips look like chosen; All shows every Look
    {
        auto tabs = new QWidget(m_lookCardsHolder);
        tabs->setObjectName(QStringLiteral("newVideoStyleTabs"));
        auto tabRow = new QHBoxLayout(tabs);
        tabRow->setContentsMargins(0, 0, 0, 0);
        tabRow->setSpacing(6);
        const auto addTab = [&](const QString &id, const QString &label, const QString &tip) {
            auto tab = new QPushButton(label, tabs);
            tab->setObjectName(QStringLiteral("newVideoStyleTab_%1").arg(id));
            tab->setProperty("newVideoFilter", true);
            tab->setCheckable(true);
            tab->setChecked(m_tab == id);
            tab->setAutoDefault(false);
            tab->setCursor(Qt::PointingHandCursor);
            tab->setToolTip(tip);
            connect(tab, &QPushButton::clicked, this, [this, id]() {
                chooseTab(id);
                QTimer::singleShot(0, this, [this]() { go(PLook); });
            });
            tabRow->addWidget(tab);
        };
        addTab(QStringLiteral("all"), tr("All"), tr("Every Look"));
        for (const LookStyle *kind : tabStyles())
            addTab(kind->id, kind->label, kind->filmed.isEmpty() ? kind->line : tr("For %1").arg(kind->filmed));
        tabRow->addSpacing(10);
        auto said = new QLabel(tabs);
        said->setObjectName(QStringLiteral("newVideoFilmedNote"));
        said->setProperty("studioMuted", true);
        const LookStyle *found = lookStyle(m_detected);
        said->setText(m_noFootage ? QString()
                      : m_detected.isEmpty() ? tr("Looking at your clips...")
                      : found ? tr("Your clips look like: %1").arg(found->filmed.isEmpty() ? found->label : found->filmed)
                              : tr("Your clips could be more than one kind of video."));
        said->setToolTip(m_detectedWhy);
        tabRow->addWidget(said);
        // owner review only (review mode): Keep or Cut the chosen tab's Style here, now there is no Style step; a cut
        // Style is listed with Restore under the cards
        if (const LookStyle *reviewed = m_tab != QLatin1String("all") ? lookStyle(m_tab) : nullptr)
            addReviewButtons(tabRow, QStringLiteral("style"), reviewed->id, reviewed->review, reviewed->cut);
        tabRow->addStretch(1);
        m_lookCardsLayout->insertWidget(0, tabs);
    }
}

void NewVideoDialog::fillLookCards(const LookStyle *style, QScrollArea *lookScroll, QWidget *lookBody, QHBoxLayout *cardRow)
{
    const QString tabStyle = tabStyleFor();
    const auto shownLooks = tabLooks(m_tab);
    QList<LookChoice> choices;
    QStringList homes; // each card's own Style (where the Look lives), in the order of choices
    { // every tab starts with Let the AI pick, the default, even a tab with no Look of its own (it then picks from All)
        LookChoice automatic;
        automatic.id = QStringLiteral("auto");
        automatic.label = tr("Let the AI pick");
        automatic.line = shownLooks.isEmpty() ? tr("No Looks for this kind of video yet. It picks the closest one for your content.")
                                              : tr("It looks at your content and picks one of these.");
        choices << automatic;
        homes << tabStyle;
    }
    for (const auto &shown : shownLooks) {
        choices << *shown.second;
        homes << shown.first->id;
    }
    const QString freeLine = tr("No set Look. Your AI edits it the way it thinks suits your clips.");
    const QString editLine = m_noFootage ? tr("An empty timeline and the chat. Nothing starts until you ask.")
                                         : tr("Your clips on the timeline and the chat. Nothing starts until you ask.");
    const bool tall = m_kind != QLatin1String("long");
    const QSize pictureSize = lookBox(tall); // the row's height, and the shape of a card with no preview
    const int textWidth = qMax(pictureSize.width(), LookCard::kMinTextWidth);
    const QString learningLine = tr("Learning now. It joins Your Looks when it's done.");
    const QString matchLine = tr("Show it one to three videos you like.");
    int descriptionHeight = qMax(cardTextHeight(matchLine, textWidth),
                                 m_look == QLatin1String("pending-learn") ? cardTextHeight(learningLine, textWidth) : 18);
    descriptionHeight = qMax(descriptionHeight, qMax(cardTextHeight(freeLine, textWidth), cardTextHeight(editLine, LookCard::kMinTextWidth)));
    for (const auto &look : std::as_const(choices))
        descriptionHeight = qMax(descriptionHeight, cardTextHeight(look.line, textWidth));
    const int cardHeight = 86 + pictureSize.height() + descriptionHeight;
    // T189: the person's own Looks have a Rename button under the card
    const bool renameRow = std::any_of(choices.cbegin(), choices.cend(), [](const LookChoice &look) { return look.personal; });
    lookScroll->setFixedHeight(cardHeight + (m_review ? 34 : 24) + (renameRow && !m_review ? 26 : 0));
    const auto sizeCard = [&](LookCard *card, const QString &) {
        card->setFixedHeight(cardHeight);
        if (auto title = card->findChild<QLabel *>(QStringLiteral("newVideoCardTitle")))
            title->setFixedHeight(36);
        if (auto description = card->findChild<QLabel *>(QStringLiteral("newVideoCardText"))) {
            description->setWordWrap(true);
            description->setFixedHeight(descriptionHeight);
        }
    };
    const int cardCount = choices.size(); // the Looks and Let the AI pick play by themselves in a short row, as before
    for (int index = 0; index < choices.size(); ++index) {
        const LookChoice &look = choices[index];
        auto card = createLookCard(look, pictureSize, cardCount, tall, lookBody);
        sizeCard(card, look.line);
        const bool automaticCard = look.id == QLatin1String("auto");
        card->setObjectName(automaticCard ? QStringLiteral("newVideoStyle_none") : QStringLiteral("newVideoLook_%1").arg(look.id));
        card->setProperty("style", homes.value(index));
        card->setProperty("look", look.id);
        card->setEnabled(!look.cut);
        if (automaticCard)
            card->setBadge(tr("Default"));
        else if (look.personal)
            card->setBadge(tr("Yours"));
        else if (look.review == QLatin1String("new"))
            card->setBadge(tr("New"));
        m_styles->addButton(card);
        auto tile = new QWidget(lookBody);
        auto tileColumn = new QVBoxLayout(tile);
        tileColumn->setContentsMargins(0, 0, 0, 0);
        tileColumn->addWidget(card);
        if (!automaticCard && !look.personal) {
            auto reviewRow = new QHBoxLayout;
            tileColumn->addLayout(reviewRow);
            addReviewButtons(reviewRow, QStringLiteral("look"), look.id, look.review, look.cut);
        }
        if (look.personal)
            addRenameButton(tileColumn, card, look.id, look.label);
        cardRow->addWidget(tile, 0, Qt::AlignTop);
        m_lookCards << card;
        card->setChecked(m_look == look.id);
        card->onSound([this](LookCard *loud, bool on) {
            if (on)
                for (auto other : std::as_const(m_lookCards))
                    if (other && other != loud)
                        other->silence();
        });
    }
    if (m_look == QLatin1String("pending-learn")) {
        auto card = new LookCard(QStringLiteral("pending-learn"), m_pendingLearnName, learningLine,
                                 QString(), QString(), matchPicture(pictureSize), pictureSize, LookCard::WhenHovered, lookBody);
        sizeCard(card, learningLine);
        card->setObjectName(QStringLiteral("newVideoLook_pending"));
        card->setProperty("style", style ? style->id : tabStyle);
        card->setProperty("look", QStringLiteral("pending-learn"));
        card->setBadge(tr("Learning"));
        m_styles->addButton(card);
        cardRow->addWidget(card, 0, Qt::AlignTop);
        card->setChecked(true);
    }
    { // Match a video I like, on every tab
        auto match = new LookCard(QStringLiteral("match"), tr("Match a video I like"), matchLine,
                                  QString(), QString(), matchPicture(pictureSize), pictureSize,
                                  LookCard::WhenHovered, lookBody);
        sizeCard(match, matchLine);
        match->setObjectName(QStringLiteral("newVideoMatchLook"));
        match->setCheckable(false);
        connect(match, &QPushButton::clicked, this, [this]() { showLearnPanel(true); });
        cardRow->addWidget(match, 0, Qt::AlignTop);
    }
    // T179: the end of every row: Freestyle, and a smaller Edit with the AI myself
    {
        auto free = new LookCard(QStringLiteral("freestyle"), tr("Freestyle"), freeLine, QString(), QString(),
                                 freestylePicture(pictureSize), pictureSize, LookCard::WhenHovered, lookBody);
        sizeCard(free, freeLine);
        free->setObjectName(QStringLiteral("newVideoLook_freestyle"));
        free->setProperty("style", tabStyle);
        free->setProperty("look", QStringLiteral("freestyle"));
        m_styles->addButton(free);
        cardRow->addWidget(free, 0, Qt::AlignTop);
        free->setChecked(m_look == QLatin1String("freestyle"));
        const QSize small(qRound(pictureSize.width() * 0.6), qRound(pictureSize.height() * 0.6));
        auto myself = new LookCard(QStringLiteral("edit-myself"), tr("Edit with the AI myself"), editLine, QString(), QString(),
                                   editorPicture(small), small, LookCard::WhenHovered, lookBody);
        myself->setPictureHeight(pictureSize.height());
        sizeCard(myself, editLine);
        myself->setObjectName(QStringLiteral("newVideoLook_edit-myself"));
        myself->setProperty("style", tabStyle);
        myself->setProperty("look", QStringLiteral("edit-myself"));
        myself->setToolTip(tr("Opens the editor with %1 and the chat ready. Theme and Go are skipped; no AI run starts.")
                               .arg(m_noFootage ? tr("an empty timeline") : tr("your clips")));
        m_styles->addButton(myself);
        cardRow->addWidget(myself, 0, Qt::AlignTop);
        myself->setChecked(editMyself());
        m_lookCards << free << myself;
    }
    cardRow->addStretch(1);
}

LookCard *NewVideoDialog::createLookCard(const LookChoice &look, const QSize &pictureSize, int cardCount, bool tall, QWidget *lookBody)
{
    // a YouTube video plays the Look's wide preview where it has one (T175's preview_long)
    const bool wide = !tall && !look.previewLong.isEmpty() && QFileInfo::exists(look.previewLong);
    const QString clipPath = wide ? look.previewLong : look.preview;
    const QString posterPath = wide ? look.posterLong : look.poster;
    bool clip = !clipPath.isEmpty() && QFileInfo::exists(clipPath);
    QSize shown = pictureSize;
    if (clip) {
        // a preview of the other shape (a vertical clip for a YouTube video) would sit small with space around it, or need
        // cropping into the face: a clean placeholder of the right shape instead, until the Look has a preview of that shape
        const QSize own = lookPictureSize(posterPath, tall);
        const double want = double(pictureSize.width()) / pictureSize.height();
        clip = qAbs(double(own.width()) / own.height() - want) <= 0.04 * want;
    }
    auto card = new LookCard(look.id, look.label, look.line, clip ? clipPath : QString(), clip ? posterPath : QString(),
                             look.id == QLatin1String("auto") ? aiPickPicture(pictureSize, false) : namePicture(look.label, shown),
                             shown, lookPlayback(cardCount), lookBody);
    card->setPictureHeight(pictureSize.height());
    if (clip)
        if (auto preview = card->preview())
            preview->setStartAt(qRound64((wide ? look.posterLongAt : look.posterAt) * 1000));
    return card;
}

// ---- T179: the Style is what was filmed: tabs on the Look stage, set from the clips -----------------------------
// the clips the answer is for: the files chosen, else the folder ("" with no footage)
QString NewVideoDialog::detectKey() const
{
    if (m_noFootage || !m_folder)
        return QString();
    return m_selectedFiles.isEmpty() ? m_folder->text().trimmed() : m_selectedFiles.join(QLatin1Char('|'));
}

// What was filmed, worked out on this PC from the clips (bridge\what_was_filmed.py, a few seconds). Never waited on: the
// tabs show All until it answers, then the tab it names unless the person has picked one.
void NewVideoDialog::detectFilmed()
{
    const QString key = detectKey();
    if (key.isEmpty() || key == m_detectedFor)
        return;
    if (m_tabChosen && key != m_tabFor)
        m_tabChosen = false; // other clips than the tab was picked for: what they are decides the tab again
    m_detectedFor = key;
    m_detected.clear();
    m_detectedWhy.clear();
    m_detectedAngles = false;
    if (m_detect) {
        m_detect->disconnect(this);
        m_detect->kill();
        m_detect->deleteLater();
        m_detect = nullptr;
    }
    auto process = new QProcess(this);
    m_detect = process;
    const auto answered = [this, process, key](const QJsonObject &answer) {
        if (m_detect != process || key != m_detectedFor || !m_detected.isEmpty())
            return;
        m_detected = answer.value(QStringLiteral("style")).toString();
        if (!lookStyle(m_detected))
            m_detected = QStringLiteral("all");
        m_detectedWhy = answer.value(QStringLiteral("why")).toString();
        m_detectedAngles = answer.value(QStringLiteral("angles")).toBool();
        // the tab follows the clips, unless the person picked one or a Look they chose isn't under it
        const QString tab = m_detected;
        bool lookStays = m_look == QLatin1String("auto") || m_look == QLatin1String("freestyle") || editMyself();
        for (const auto &shown : tabLooks(tab))
            lookStays = lookStays || shown.second->id == m_look;
        if (!m_tabChosen && lookStays)
            chooseTab(tab, false);
        if (m_pages->currentIndex() == PLook && !m_customStylePage)
            go(PLook);
    };
    connect(process, &QProcess::readyReadStandardOutput, this, [process, answered]() {
        while (process->canReadLine()) {
            const QJsonObject answer = QJsonDocument::fromJson(process->readLine().trimmed()).object();
            if (answer.contains(QStringLiteral("style")))
                answered(answer);
        }
    });
    connect(process, &QProcess::finished, this, [this, process, answered]() {
        if (m_detect == process) {
            answered(QJsonObject{{"style", "all"}, {"why", tr("Couldn't look at the clips.")}});
            m_detect = nullptr;
        }
        process->deleteLater();
    });
    QStringList args{aiRootPath(QStringLiteral("bridge/what_was_filmed.py"))};
    args << (m_selectedFiles.isEmpty() ? QStringList{m_folder->text().trimmed()} : m_selectedFiles);
    process->start(aiChatSettings().value(QStringLiteral("python")).toString(), args);
}

// ---- T174: does the chosen clips' content fit the chosen learned Look's format? ---------------------------------------
// A learned Look with a saved place (its format and what it needs) is checked against the chosen clips on this PC
// (bridge\look_place.py fit: their words and what was filmed, a few seconds). The answer is a plain line under the
// Looks; when the clips don't fit, the person may make it with only the look, or choose another Look. Never waited on.
void NewVideoDialog::checkFit()
{
    if (!m_fitHolder)
        return;
    const LookChoice *card = chosenLookCard();
    const QString clips = detectKey();
    if (!m_modern || m_noFootage || !card || card->place.isEmpty() || clips.isEmpty()) {
        m_fitFor.clear();
        m_fitVerdict.clear();
        m_fitLine.clear();
        if (m_fitWaitingToSend) {
            m_fitWaitingToSend = false;
            m_problem->hide();
        }
        if (m_fit) {
            m_fit->disconnect(this);
            m_fit->kill();
            m_fit->deleteLater();
            m_fit = nullptr;
        }
        m_fitHolder->hide();
        if (m_goFitNote)
            m_goFitNote->hide();
        return;
    }
    const QString key = card->place + QLatin1Char('#') + clips + QLatin1Char('#') + m_kind;
    if (key == m_fitFor) {
        showFit();
        return;
    }
    m_fitFor = key;
    m_fitVerdict.clear();
    m_fitLine.clear();
    m_lookOnly->setChecked(false);
    if (m_fit) {
        m_fit->disconnect(this);
        m_fit->kill();
        m_fit->deleteLater();
        m_fit = nullptr;
    }
    auto process = new QProcess(this);
    m_fit = process;
    const auto answered = [this, process, key]() {
        if (m_fit != process)
            return process->deleteLater();
        m_fit = nullptr;
        QJsonObject answer;
        const QList<QByteArray> lines = process->readAllStandardOutput().split('\n');
        for (const QByteArray &line : lines)
            if (line.trimmed().startsWith('{'))
                answer = QJsonDocument::fromJson(line.trimmed()).object();
        process->deleteLater();
        if (key != m_fitFor)
            return;
        m_fitVerdict = answer.value(QStringLiteral("fit")).toString();
        m_fitLine = answer.value(QStringLiteral("line")).toString();
        if (m_fitVerdict.isEmpty() || m_fitLine.isEmpty()) {
            m_fitVerdict = QStringLiteral("unknown");
            m_fitLine = tr("Couldn't check whether your clips fit this Look. The AI checks while it cuts.");
        }
        showFit();
    };
    connect(process, &QProcess::finished, this, answered);
    connect(process, &QProcess::errorOccurred, this, [answered](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            answered();
    });
    QTimer::singleShot(15000, process, [this, process, answered]() {
        if (m_fit == process) {
            process->kill();
            answered();
        }
    });
    QStringList args{aiRootPath(QStringLiteral("bridge/look_place.py")), QStringLiteral("fit"), QStringLiteral("--look"), card->place};
    if (m_kind == QLatin1String("short") || m_kind == QLatin1String("long"))
        args << QStringLiteral("--format") << m_kind;
    args << (m_selectedFiles.isEmpty() ? QStringList{m_folder->text().trimmed()} : m_selectedFiles);
    process->start(aiChatSettings().value(QStringLiteral("python")).toString(), args);
    showFit();
}

void NewVideoDialog::showFit()
{
    if (!m_fitHolder)
        return;
    m_fitNote->setText(m_fitVerdict.isEmpty() ? tr("Checking whether your clips fit this Look...") : m_fitLine);
    m_fitNote->setProperty("fit", m_fitVerdict);
    if (m_fitWaitingToSend && !m_fitVerdict.isEmpty()) {
        m_fitWaitingToSend = false;
        m_problem->hide();
    }
    if (m_goFitNote) {
        m_goFitNote->setText(m_fitNote->text());
        m_goFitNote->setProperty("fit", m_fitVerdict);
        m_goFitNote->show();
    }
    m_lookOnly->setVisible(m_fitVerdict == QLatin1String("no"));
    m_fitHolder->show();
}

// the tabs after All: the kinds of video that have Looks for this route and format, and the one the clips look like even
// when it has none (Let the AI pick then picks from every Look)
QList<const LookStyle *> NewVideoDialog::tabStyles() const
{
    QList<const LookStyle *> list;
    for (const auto &style : m_lookStyles) {
        const bool ai = style.footage == QLatin1String("no");
        if (ai != m_noFootage || style.hidden || (style.cut && !m_review))
            continue;
        if (tabLooks(style.id).isEmpty() && style.id != m_detected && style.id != m_tab)
            continue;
        list << &style;
    }
    return list;
}

// the Looks under a tab, each with the Style it lives in: All is every one; a kind of video is every Look that fits it
// (its own, another Style's that lists it in fits, the person's own placed under it). The catalogue's own first.
QList<QPair<const LookStyle *, const LookChoice *>> NewVideoDialog::tabLooks(const QString &tab) const
{
    QList<QPair<const LookStyle *, const LookChoice *>> list;
    QSet<QString> seen;
    for (int pass = 0; pass < 2; ++pass)
        for (const auto &style : m_lookStyles) {
            const bool ai = style.footage == QLatin1String("no");
            if (ai != m_noFootage || style.hidden || (style.cut && !m_review))
                continue;
            for (const auto &look : style.looks) {
                if (look.personal != (pass == 1) || seen.contains(look.id) || (look.cut && !m_review) || !routeFits(look)
                    || !kindFits(look.kind))
                    continue;
                if (tab != QLatin1String("all") && style.id != tab && !look.fits.contains(tab))
                    continue;
                seen << look.id;
                list << qMakePair(&style, &look);
            }
        }
    return list;
}

// the Looks Let the AI pick chooses from: the tab's, or every Look when the tab has none (the same as under All)
QList<QPair<const LookStyle *, const LookChoice *>> NewVideoDialog::pickLooks() const
{
    const auto shown = tabLooks(m_tab);
    return shown.isEmpty() ? tabLooks(QStringLiteral("all")) : shown;
}

// what was filmed, for the request's Style line: the tab, or what the clips look like under All ("" when unknown)
QString NewVideoDialog::filmedStyle() const
{
    const QString kind = m_tab != QLatin1String("all") ? m_tab : m_detected;
    return lookStyle(kind) && kind != QLatin1String("all") ? kind : QString();
}

// the Style that Let the AI pick, Freestyle and Edit with the AI myself go under
QString NewVideoDialog::tabStyleFor() const
{
    const QString filmed = filmedStyle();
    if (!filmed.isEmpty())
        return filmed;
    const auto looks = tabLooks(QStringLiteral("all"));
    if (!looks.isEmpty())
        return looks.first().first->id;
    const auto styles = tabStyles();
    return styles.isEmpty() ? QStringLiteral("none") : styles.first()->id;
}

// a tab pressed (or set from the clips): a Look chosen that isn't under it goes back to Let the AI pick
void NewVideoDialog::chooseTab(const QString &tab, bool byPerson)
{
    m_tab = tab == QLatin1String("all") || !lookStyle(tab) ? QStringLiteral("all") : tab;
    if (byPerson) {
        m_tabChosen = true;
        m_tabFor = detectKey();
        m_styleExplicit = true;
        m_personChose = true;
    }
    const auto shown = tabLooks(m_tab);
    for (const auto &look : shown)
        if (look.second->id == m_look) {
            m_style = look.first->id;
            return;
        }
    if (m_look == QLatin1String("pending-learn")) {
        if (!lookStyle(m_style))
            m_style = tabStyleFor();
        return;
    }
    // a Freestyle chosen only because a tab had no Looks (older drafts) is Let the AI pick, which every tab now has
    if (m_look == QLatin1String("freestyle") && m_freestyleByDefault)
        m_look = QStringLiteral("auto");
    m_freestyleByDefault = false;
    if (m_look != QLatin1String("freestyle") && !editMyself()) {
        if (m_look != QLatin1String("auto")) {
            m_theme = QStringLiteral("freestyle");
            m_themeChosen = false;
        }
        m_look = QStringLiteral("auto");
    }
    m_style = tabStyleFor();
}

// before the Look stage is drawn: a tab that is gone is All, and a chosen Look still offered keeps its own Style (a Look
// just learned shows under All when its tab doesn't list it)
void NewVideoDialog::settleTab()
{
    if (m_tab != QLatin1String("all")) {
        bool known = false;
        for (const LookStyle *kind : tabStyles())
            known = known || kind->id == m_tab;
        if (!known)
            m_tab = QStringLiteral("all");
    }
    const bool special = m_look == QLatin1String("auto") || m_look == QLatin1String("freestyle") || editMyself()
                         || m_look == QLatin1String("pending-learn");
    if (!special) {
        bool here = false;
        for (const auto &look : tabLooks(m_tab))
            here = here || look.second->id == m_look;
        if (!here)
            for (const auto &look : tabLooks(QStringLiteral("all")))
                if (look.second->id == m_look) {
                    m_tab = QStringLiteral("all");
                    break;
                }
    }
    chooseTab(m_tab, false);
}

// Freestyle: a free brush stroke and two sparks on the calm teal block
QPixmap NewVideoDialog::freestylePicture(const QSize &size)
{
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(LetItEditColors::tealDeep));
    p.drawRoundedRect(QRectF(QPointF(0, 0), QSizeF(size)), 8, 8);
    const qreal w = size.width(), h = size.height();
    QPainterPath stroke;
    stroke.moveTo(w * 0.16, h * 0.62);
    stroke.cubicTo(w * 0.32, h * 0.22, w * 0.46, h * 0.86, w * 0.6, h * 0.46);
    stroke.cubicTo(w * 0.7, h * 0.2, w * 0.82, h * 0.42, w * 0.86, h * 0.34);
    p.setBrush(Qt::NoBrush);
    p.setPen(QPen(QColor(LetItEditColors::rust), qMax(4.0, qMin(w, h) * 0.07), Qt::SolidLine, Qt::RoundCap));
    p.drawPath(stroke);
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(LetItEditColors::cream));
    for (const QPointF &c : {QPointF(w * 0.78, h * 0.2), QPointF(w * 0.24, h * 0.8)}) {
        const qreal r = qMin(w, h) * 0.07;
        QPainterPath spark;
        spark.moveTo(c.x(), c.y() - r);
        spark.quadTo(c.x(), c.y(), c.x() + r, c.y());
        spark.quadTo(c.x(), c.y(), c.x(), c.y() + r);
        spark.quadTo(c.x(), c.y(), c.x() - r, c.y());
        spark.quadTo(c.x(), c.y(), c.x(), c.y() - r);
        p.drawPath(spark);
    }
    return pixmap;
}

// Edit with the AI myself: a small timeline (two tracks of clips and the playhead) and a chat bubble
QPixmap NewVideoDialog::editorPicture(const QSize &size)
{
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    const qreal w = size.width(), h = size.height();
    p.setPen(QPen(QColor(LetItEditColors::teal), 1.5));
    p.setBrush(QColor(LetItEditColors::deep));
    p.drawRoundedRect(QRectF(1, 1, w - 2, h - 2), 7, 7);
    const qreal lane = h * 0.12;
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(LetItEditColors::tealDeep));
    p.drawRoundedRect(QRectF(w * 0.1, h * 0.56, w * 0.36, lane), 3, 3);
    p.drawRoundedRect(QRectF(w * 0.5, h * 0.56, w * 0.4, lane), 3, 3);
    p.setBrush(QColor(QStringLiteral("#3A4247")));
    p.drawRoundedRect(QRectF(w * 0.1, h * 0.72, w * 0.8, lane * 0.8), 3, 3);
    p.setPen(QPen(QColor(LetItEditColors::rust), 2));
    p.drawLine(QPointF(w * 0.42, h * 0.5), QPointF(w * 0.42, h * 0.9));
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(LetItEditColors::cream));
    const QRectF bubble(w * 0.24, h * 0.12, w * 0.52, h * 0.26);
    p.drawRoundedRect(bubble, 6, 6);
    QPolygonF tail;
    tail << QPointF(bubble.left() + bubble.width() * 0.25, bubble.bottom() - 1) << QPointF(bubble.left() + bubble.width() * 0.2, bubble.bottom() + h * 0.07)
         << QPointF(bubble.left() + bubble.width() * 0.42, bubble.bottom() - 1);
    p.drawPolygon(tail);
    p.setBrush(QColor(LetItEditColors::tealDeep));
    for (int i = 0; i < 3; ++i)
        p.drawEllipse(QPointF(bubble.left() + bubble.width() * (0.3 + 0.2 * i), bubble.center().y()), 2.2, 2.2);
    return pixmap;
}

// the clips in the order chosen: the files ticked, else the folder's media as listed (none with no footage)
QStringList NewVideoDialog::clipsInOrder() const
{
    if (m_noFootage)
        return {};
    if (!m_selectedFiles.isEmpty())
        return m_selectedFiles;
    QStringList clips;
    for (int i = 0; m_media && i < m_media->topLevelItemCount(); ++i) {
        const QString path = m_media->topLevelItem(i)->data(0, Qt::UserRole).toString();
        if (QFileInfo(path).isFile())
            clips << path;
    }
    return clips;
}

// Edit with the AI myself: the editor opens with the clips and the chat ready (MainWindow::openEditorWithClips). No AI
// run starts; Theme and Go are skipped.
void NewVideoDialog::openEditorMyself()
{
    const QStringList clips = clipsInOrder();
    QString name;
    if (!m_noFootage)
        name = clips.size() == 1 ? QFileInfo(clips.first()).completeBaseName() : QFileInfo(m_folder->text().trimmed()).fileName();
    m_look = QStringLiteral("auto"); // the next New video starts at Let the AI pick, not at this way out
    remember();
    m_window->openEditorWithClips(m_kind == QLatin1String("long") ? QStringLiteral("long") : QStringLiteral("short"), clips, name);
    QDialog::accept();
}

} // namespace NewVideo
