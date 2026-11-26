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

// New video (letitedit): the dialog and its widgets, declared for the files of letitedit/newvideo/ (one per
// step; the file beside each method group names it). The rest of the editor sees only firstcut.h.
#ifndef NEWVIDEODIALOG_H
#define NEWVIDEODIALOG_H

#include "letitedit/newvideo/firstcut.h"

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "letitedit/workspace/focusworkspace.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/letitedit.h"
#include "letitedit/workspace/leside.h"
#include "mainwindow.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/newvideo/learnlooks.h"
#include "settings.h"
#include "letitedit/home/videoprojects.h"
#include "util.h"

#include <QAudioOutput>
#include <QButtonGroup>
#include <QComboBox>
#include <QCheckBox>
#include <QDialog>
#include <QDir>
#include <QDrag>
#include <QDragEnterEvent>
#include <QDragMoveEvent>
#include <QDropEvent>
#include <QFileDialog>
#include <QFileInfo>
#include <QFile>
#include <QFileSystemModel>
#include <QGridLayout>
#include <QHeaderView>
#include <QHBoxLayout>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonValue>
#include <QIcon>
#include <QLabel>
#include <QLineEdit>
#include <QMediaPlayer>
#include <QMimeData>
#include <QMouseEvent>
#include <QListWidget>
#include <QMenu>
#include <QActionGroup>
#include <QPaintEvent>
#include <QPainter>
#include <QPainterPath>
#include <QPlainTextEdit>
#include <QSet>
#include <QPointer>
#include <QProcess>
#include <QPushButton>
#include <QRegularExpression>
#include <QResizeEvent>
#include <QScreen>
#include <QScrollArea>
#include <QSettings>
#include <QSignalBlocker>
#include <QSlider>
#include <QStandardPaths>
#include <QStorageInfo>
#include <QStackedWidget>
#include <QTemporaryFile>
#include <QThread>
#include <QTimer>
#include <QToolButton>
#include <QUrl>
#include <QTreeView>
#include <QTreeWidget>
#include <QVBoxLayout>
#include <QVideoFrame>
#include <QVideoSink>
#include <QWheelEvent>
#include <functional>
#include <memory>
#include <utility>

namespace NewVideo {

class CustomSlider : public QSlider
{
public:
    explicit CustomSlider(QWidget *parent);
    void onTouch(std::function<void()> action);

protected:
    void wheelEvent(QWheelEvent *event) override;
    void mousePressEvent(QMouseEvent *event) override;
private:
    std::function<void()> m_onTouch;
};

// A small, drawn indicator beside each preference. It changes with the slider without loading assets.
class SliderToy : public QWidget
{
public:
    SliderToy(const QString &kind, QWidget *parent);
    void setLevel(int level);

protected:
    void paintEvent(QPaintEvent *) override;
private:
    QString m_kind;
    int m_level = 0;
    bool m_automatic = false;
};

// A big choice button: a title, a line under it, and optionally a picture and a badge (a style card).
class ChoiceCard : public QPushButton
{
public:
    ChoiceCard(const QString &title, const QString &text, QWidget *parent, const QString &badge = QString(),
               const QPixmap &picture = QPixmap(), const QString &tags = QString());
    QSize sizeHint() const override;
    QSize minimumSizeHint() const override;
};

QPixmap placeholderPicture(const QString &label, bool ai);

QPixmap importPicture();

// A Look's preview clip (looks\<look>\preview.mp4): its poster until it plays, then the video muted and looping.
// Sound is the person's to switch on and never starts by itself.
class LookPreview : public QLabel
{
public:
    LookPreview(const QString &clip, const QString &poster, const QSize &size, QWidget *parent);
    bool hasClip() const;
    bool playing() const;
    bool sound() const;
    int frames() const;
    void setPlaying(bool on);
    void setSound(bool on);
    void setStartAt(qint64 ms) { m_startMs = ms; }
    bool exactShape() const { return m_exact; }

private:
    void ensurePlayer();
    void showPoster();
    QImage fitted(const QImage &image) const;

    QString m_clip;
    QSize m_size;
    bool m_exact = false; // the picture is the clip's own shape: it fills it, centred, with no bars and no crop (T176)
    QPixmap m_poster;
    QVideoSink *m_sink = nullptr;
    QAudioOutput *m_audio = nullptr;
    QMediaPlayer *m_player = nullptr;
    int m_frames = 0;
    qint64 m_startMs = 0; // the first play starts where the poster is, so the card opens on its finished picture
};

// One Look in the picker: its preview, name and one line, a sound switch, and a card the person clicks to choose.
// Previews play according to the card's policy (see NewVideoDialog::lookPlayback).
class LookCard : public QPushButton
{
public:
    enum Playback { WhenHovered, Always };
    LookCard(const QString &id, const QString &title, const QString &text, const QString &clip, const QString &poster,
             const QPixmap &placeholder, const QSize &pictureSize, Playback playback, QWidget *parent);
    void onSound(std::function<void(LookCard *, bool)> action);
    void silence();
    LookPreview *preview() const { return m_preview; }
    QSize sizeHint() const override;
    QSize minimumSizeHint() const override;
    void setBadge(const QString &text);
    void setPictureHeight(int height); // pictures of other shapes sit centred in a row of the same height (T176)

    static constexpr int kCardMargin = 12;
    static constexpr int kMinTextWidth = 150; // a narrow (9:16) picture never squeezes the card's words

protected:
    void enterEvent(QEnterEvent *event) override;
    void leaveEvent(QEvent *event) override;
    void showEvent(QShowEvent *event) override;
    void hideEvent(QHideEvent *event) override;

private:
    void applyPlayback();
    static QString soundOffText();
    static QString soundOnText();

    Playback m_playback;
    LookPreview *m_preview = nullptr;
    QWidget *m_picture = nullptr;
    QToolButton *m_sound = nullptr;
    QLabel *m_state = nullptr;
    std::function<void(LookCard *, bool)> m_onSound;
};

// One box a Look asks for up front (looks\manifest.json `asks`; bridge\looks.py resolves the folder's defaults)
struct LookAsk
{
    QString id;
    QString kind;    // text | files | audio
    QString label;
    QString hint;
    QString need;    // required | recommended | optional
    QString role;    // about | show | style | voiceover | product | person ...
    QString instead; // what they get if a recommended box stays empty
};

// One Look as the Look page lists it (from bridge\looks.py --list-json, which reads looks\manifest.json)
struct LookChoice
{
    QString id;
    QString label;
    QString line;
    QString needs;
    QString preview;
    QString poster;
    QString previewLong; // a 16:9 preview for a YouTube video (T175), shown when Format is YouTube
    QString posterLong;
    double posterAt = 0;     // where in the preview its poster was taken (seconds): playing starts there (T179)
    double posterLongAt = 0;
    QString folder;
    QString worksWith; // footage | no-footage | both
    QList<LookAsk> asks;
    QString themes;
    QString review;
    QString kind = QStringLiteral("both"); // short | long | both: the formats it suits
    bool personal = false; // one of the person's own (learned or adjusted)
    QString basedOn;       // an adjusted Look: the Look it was adjusted from
    bool cut = false;
    QStringList fits;      // the kinds of video (Style ids) it suits, its own Style first (T179)
    QString place;         // a learned Look's saved place (place.json: its format and needs), for the fit check (T174)
};

// A folder of a Style's Looks (a genre), shown before the Looks
struct LookFolder
{
    QString id;
    QString label;
    QString line;
    QString poster;
    QStringList looks; // ids
};

// A Style that has Looks (Talking head) and its approved Looks
struct LookStyle
{
    QString id;
    QString label;
    QString line;
    QString kind;                            // short | long | both
    QString footage = QStringLiteral("yes"); // yes | no | optional: whether its Looks need footage
    QString filterLabel;                     // its name as a filter in the Look browser
    QString group;                           // footage | ai
    bool hidden = false;                     // a group kept for old projects, never shown
    QString filmed;                          // what was filmed, in plain words (T179)
    QStringList fitting;                     // every Look that fits this kind of video, its own or another Style's (T179)
    QList<LookFolder> folders;
    QList<LookChoice> looks;
    QString review;
    bool cut = false;
};

// The files of one of a Look's boxes: a tile for each (a small picture, its name and length where it has one), files
// dropped in from Explorer, a tile dragged to another box, or moved or removed with its own buttons. The person's files
// are only named here, never opened for writing, copied or moved on disk. letitedit does not sort files itself: a mistake
// there could put someone else's picture in a video, so the person moves a tile that is in the wrong box.
class AskFiles : public QListWidget
{
public:
    static QString mime();
    AskFiles(const QString &askId, bool single, QWidget *parent);
    QStringList files() const;

    static constexpr int kEmptyHeight = 44;
    static constexpr int kFilledHeight = 164;
    void fitHeight();
    void addFiles(const QStringList &paths);
    void removeFile(const QString &path);
    void clearFiles();
    void setFacts(const QString &path, const QString &length, const QPixmap &picture);
    void setCanMove(bool can, const QString &destinationLabel);
    void onChanged(std::function<void()> f);
    void onAdded(std::function<void(const QStringList &)> f);
    void onMove(std::function<void(AskFiles *, const QString &)> f);
    QString askId() const;
    static QString tileName(const QString &path);

protected:
    void paintEvent(QPaintEvent *event) override;
    void startDrag(Qt::DropActions) override;
    void dragEnterEvent(QDragEnterEvent *event) override;
    void dragMoveEvent(QDragMoveEvent *event) override;
    void dropEvent(QDropEvent *event) override;

private:
    void acceptIfFiles(QDropEvent *event);
    void addTile(const QString &path);
    static QPixmap placeholder(const QString &path);

    QString m_ask;
    bool m_single = false;
    bool m_canMove = false;
    QString m_destination;
    std::function<void()> m_onChanged;
    std::function<void(const QStringList &)> m_onAdded;
    std::function<void(AskFiles *, const QString &)> m_onMove;
};

struct StyleChoice
{
    QString name; // "none" for Let the AI decide
    QString label;
    QString summary;
    QString kind; // short | long | both
    QStringList tags;
    QString preview;
    QString recipe;
    bool mine = false;
};

class NewVideoDialog : public QDialog
{
public:

    // newvideodialog.cpp
    explicit NewVideoDialog(MainWindow *window, bool shortEntry);
    void remember();
    ~NewVideoDialog() override;
    void reject() override;

protected:

    // newvideodialog.cpp
    void resizeEvent(QResizeEvent *event) override;

private:
    void setupDialogAppearance(MainWindow *window);
    void buildStageNavigation(QVBoxLayout *outer);
    void buildStepNotices(QVBoxLayout *outer);
    void buildNavigationButtons(QVBoxLayout *outer);
    enum Step { PFormat, PContent, PStyle, PLook, PTheme, PGo };

    // "This PC (C:)", "Google Drive (G:)": the drive's own name where it has one
    struct SliderField
    {
        QString key;
        QString title;
        QStringList labels;
        QStringList descriptions;
    };

    struct Place
    {
        QString label;
        QString path;
        QString id;
    };

    // One card of the Look browser
    struct BrowserEntry
    {
        QString style;
        QString look;     // a Look's id, "auto", or empty for a card that is only a style
        QString category; // the filter it belongs to
        bool onlyInCategory = false; // not listed under All
        QString label;
        QString line;
        const LookChoice *choice = nullptr;
        QString name;  // its object name
        QString badge;
        QPixmap picture;
    };

    // newvideodialog.cpp
    QWidget *page(const QString &heading, const QString &lead, QVBoxLayout **body);
    static QHBoxLayout *fieldTitle(const QString &title, const QString &need, QWidget *parent);
    void makeParts(QWidget *w);
    void restore();
    static void clearLayout(QLayout *layout, const std::function<void(QWidget *)> &forget = nullptr);
    int cardTextHeight(const QString &text, int width);
    void refreshChoicePages();
    bool check(int step);
    void back();
    void next();
    void jump(int to);
    void go(int step);

    // formatstep.cpp
    static QPixmap formatPicture(bool vertical);
    QWidget *formatPage();

    // contentstep.cpp
    QWidget *contentPage();
    QList<Place> places() const;
    QWidget *footageBrowser(QWidget *parent);
    void markDrive();
    void fillFolders(const QString &path);
    void countMedia();
    void updateShapeNote(); // a YouTube video from vertical clips: say so plainly
    void scanMedia();

    // stylestep.cpp
    bool kindFits(const QString &lookKind) const;
    bool routeFits(const LookChoice &look) const;
    QList<const LookChoice *> offeredLooks(const LookStyle &style) const;
    QSet<QString> styleFormats(const LookStyle &style) const;
    void dropLookForFormat();
    QWidget *styleChoicePage();
    void chooseStyle(const QString &id);
    void fillStyleChoices();

    // lookstep.cpp
    QWidget *stylePage();
    void buildMasterSlider(QWidget *customBody, QVBoxLayout *sliders);
    void buildStyleSliders(QWidget *customBody, QVBoxLayout *sliders);
    void buildLookFilters(QWidget *w, QVBoxLayout *column);
    void buildLookFitChoice(QWidget *w, QVBoxLayout *column);
    void buildLegacyLookBrowser(QWidget *w);
    void buildCustomLookPage(QWidget *w);
    void buildModernLookPage(QWidget *w);
    void connectLookChoices();
    void saveAdjusted();
    void showStylePageTexts();
    QString currentLookLabel(const LookStyle &style) const;
    static QPixmap aiPickPicture(const QSize &size, bool showLabel = true);
    static QPixmap framedPicture(const QPixmap &source, const QSize &size);
    static LookCard::Playback lookPlayback(int cards = 0);
    void updateModernSummary();
    void showLearnPanel(bool shown);
    void fillModernBrowser();
    void buildLookTabs();
    void fillLookCards(const LookStyle *style, QScrollArea *lookScroll, QWidget *lookBody, QHBoxLayout *cardRow);
    LookCard *createLookCard(const LookChoice &look, const QSize &pictureSize, int cardCount, bool tall, QWidget *lookBody);
    // T179: the Style tabs, Freestyle and Edit with the AI myself (lookstep.cpp)
    QString detectKey() const;
    void detectFilmed();
    void checkFit();       // T174: do the chosen clips fit the chosen learned Look's format? (bridge\look_place.py fit)
    void showFit();
    QList<const LookStyle *> tabStyles() const;
    QList<QPair<const LookStyle *, const LookChoice *>> tabLooks(const QString &tab) const;
    QList<QPair<const LookStyle *, const LookChoice *>> pickLooks() const;
    QString filmedStyle() const;
    QString tabStyleFor() const;
    void chooseTab(const QString &tab, bool byPerson = true);
    void settleTab();
    static QPixmap freestylePicture(const QSize &size);
    static QPixmap editorPicture(const QSize &size);
    bool editMyself() const { return m_look == QLatin1String("edit-myself"); }
    void openEditorMyself();
    QStringList clipsInOrder() const;

    // lookbrowser.cpp
    QList<BrowserEntry> browserEntries(QList<QPair<QString, QString>> *filters) const;
    void reviewEntry(const QString &kind, const QString &id, const QString &action);
    void addReviewButtons(QBoxLayout *row, const QString &kind, const QString &id, const QString &review, bool cut);
    void addRenameButton(QBoxLayout *column, QWidget *card, const QString &id, const QString &label);
    bool entryChosen(const BrowserEntry &e) const;
    void fillBrowser();
    QList<const BrowserEntry *> buildBrowserCards(const QList<BrowserEntry> &entries);

    // presets.cpp
    QJsonArray storedPresets() const;
    void storePresets(const QJsonArray &presets);
    QJsonArray allPresets() const;
    QJsonObject selectedPreset() const;
    void fillPresets(const QString &select = QString());
    void resetCustom(bool clearPreset = true);
    void loadSelectedPreset();
    void saveCurrentPreset();
    void renameSelectedPreset();
    void deleteSelectedPreset();
    void starSelectedPreset();
    static QString mineByDefault();
    void importStyle();

    // themestep.cpp
    void settleTheme();
    bool themeFits(const QJsonObject &theme, const LookStyle *style, const LookChoice *look) const;
    QJsonObject ownTheme(const LookChoice *look) const;
    QString themeRequest(const LookChoice *look) const;
    QJsonObject themeChoice(const LookChoice *look) const; // T331 P4: the Theme as resolved, the typed request's `theme`
    QWidget *themePage();
    void fillThemePage();

    // gostep.cpp
    static QString musicChoice(const QString &saved);
    QWidget *musicRow(QWidget *parent);
    QString summaryLine() const;
    QString chosenLookName() const;
    bool aboutRequired() const;
    QWidget *readyPage();
    void buildReadyInputs(QWidget *w, QHBoxLayout *body);
    void refreshAi();
    void prepareReady();
    const LookChoice *chosenLookCard() const;
    const StyleChoice *chosenCatalogCard() const;
    QString chosenName() const;
    QString chosenLine() const;
    QPixmap chosenPicture(const QSize &size) const;
    void updateSummary();
    bool noFootageForSummary() const;

    // lookinputs.cpp
    static QString needWords(const QString &need);
    static QString roleMeaning(const QString &role);
    static QString mediaKind(const QString &path);
    bool askEmpty(const QString &id) const;
    const LookChoice *askingLook() const;
    QString missingInputsLine() const;
    void captureInputsDraft();
    void updateInputsState();
    void refreshMoveTargets();
    void moveTile(AskFiles *from, const QString &path);
    void applyFacts(const QString &path);
    void requestFacts(const QStringList &paths);
    void showInputsFor(const LookChoice *look);
    void clearInputs();
    QFrame *inputBox(const LookAsk &ask, const QJsonObject &draft);
    void fillInputs(const LookChoice &look);
    QJsonObject inputsRecord(const LookChoice &look) const;
    QString inputsRequestText(const QJsonObject &record, const QString &recordPath) const;
    QString writeInputsRecord(const QJsonObject &record) const;
    void keepInputsBesideProject(const QString &recordPath);

    // catalog.cpp
    void loadStyles();
    void loadLooks();
    void mergePersonalLooks();
    const LookChoice *findLook(const LookStyle &style, const QString &id) const;
    const LookFolder *lookFolder(const LookStyle &style, const QString &id) const;
    const LookStyle *lookStyle(const QString &id) const;

    // request.cpp
    void send();
    bool prepareRequest();
    void appendLookRequest(QString &request, const LookStyle *looks, bool noFootage, bool waitingForLook,
                           const QString &look, const QString &lookLabel);
    void clearSentRequest();
    QStringList lookArtifacts() const;
    // T331 P4: the same request as typed fields (bridge/letitedit/app/new_video_request.py renders the same text)
    QJsonObject typedRequest(const QString &path, const LookStyle *looks, const QString &label, bool mine,
                             const QString &look, const QString &lookLabel, const QString &styleKindLabel, bool noFootage,
                             bool waitingForLook, const QJsonObject &inputs, const QString &recordPath,
                             const QString &song, const QString &saveFolder) const;
    QString normalizedLength() const;
    bool writeCustomStyle();

    MainWindow *m_window;
    bool m_shortEntry = false;
    QStackedWidget *m_pages = nullptr;
    QList<QPushButton *> m_dots;
    QLabel *m_stepLabel = nullptr;
    QLabel *m_problem = nullptr;
    QPushButton *m_back = nullptr;
    QPushButton *m_next = nullptr;
    QPushButton *m_go = nullptr;
    QLineEdit *m_folder = nullptr;
    QButtonGroup *m_drives = nullptr;
    QStringList m_recentFolders;
    QStringList m_selectedFiles;
    QListWidget *m_folders = nullptr;
    QTreeWidget *m_media = nullptr;
    QPushButton *m_useOneNow = nullptr;
    QButtonGroup *m_routes = nullptr;
    QPushButton *m_useFootageButton = nullptr;
    QPushButton *m_noFootageButton = nullptr;
    QStackedWidget *m_footageStack = nullptr;
    bool m_routeRemembered = false;
    bool m_noFootage = false; // Create from an idea: the Look stage offers only Looks that draw everything
    QTimer *m_scanTimer = nullptr;
    QTimer *m_resizeTimer = nullptr;
    QProcess *m_scan = nullptr;
    QByteArray m_scanBuffer;
    QLabel *m_found = nullptr;
    QLabel *m_shapeNote = nullptr;
    QButtonGroup *m_kinds = nullptr;
    QString m_kind = QStringLiteral("short");
    QLabel *m_customLabel = nullptr;
    QPlainTextEdit *m_custom = nullptr;
    QWidget *m_styleHolder = nullptr;
    QStackedWidget *m_styleSlides = nullptr;
    QScrollArea *m_styleScroll = nullptr;
    bool m_customStylePage = false;
    // Styles that have Looks (bridge\looks.py)
    bool m_modern = false;
    bool m_restoringRoute = false;
    bool m_review = false;
    bool m_styleExplicit = false;
    bool m_reviewBusy = false;
    QString m_browseStyle;
    QString m_theme = QStringLiteral("freestyle"); // "freestyle" (no set Theme, the default), "pick" (Let the AI pick), "none" or a Theme id
    QString m_caption = QStringLiteral("auto");
    QString m_music = QStringLiteral("auto");
    QString m_musicFile;
    QJsonArray m_themes;
    QJsonArray m_reviewItems;
    bool m_themeChosen = false; // the person picked a Theme (else a Look's own Theme starts chosen)
    QString m_selectLook;       // a Look just learned or adjusted: chosen once the catalogue is read again
    QWidget *m_lookCardsHolder = nullptr;
    QVBoxLayout *m_lookCardsLayout = nullptr;
    QPushButton *m_adjustButton = nullptr;
    QLineEdit *m_adjustName = nullptr;
    QWidget *m_learnHolder = nullptr;
    LearnLooks::Panel *m_learnPanel = nullptr;
    bool m_learnShown = false;
    QString m_pendingLearnJob;
    QString m_pendingLearnName;
    QWidget *m_styleChoiceBody = nullptr;
    QGridLayout *m_styleChoiceGrid = nullptr;
    QButtonGroup *m_styleChoiceGroup = nullptr;
    QLabel *m_stylePickLead = nullptr;
    QButtonGroup *m_themeGroup = nullptr;
    QWidget *m_themeDeck = nullptr; // the trading cards (themestep.cpp, T176)
    QLabel *m_themeLead = nullptr;
    QWidget *m_aboutBox = nullptr;
    QLabel *m_aboutTitle = nullptr;
    QLabel *m_aboutNeed = nullptr;
    QWidget *m_referencesBox = nullptr;
    AskFiles *m_references = nullptr;
    QLineEdit *m_musicFileEdit = nullptr;
    QList<SliderField> m_sliderFields;
    QWidget *m_modernBody = nullptr;
    QVBoxLayout *m_modernColumn = nullptr;
    QList<LookStyle> m_lookStyles;
    int m_looksState = 0; // 0 loading, 1 loaded, -1 failed
    bool m_libraryStyles = false; // picker.library_styles in looks\manifest.json: show every library style pack too
    QStringList m_alsoShow;       // picker.also_show: pack names shown even when the library styles are not
    bool m_freestyleByDefault = false; // a draft's Freestyle chosen only because its tab had no Looks (T179); read once, then false
    QString m_look = QStringLiteral("auto"); // a Look's id, "auto" (Let the AI pick), "freestyle" or "edit-myself" (T179)
    // T179: the Style is what was filmed, a row of tabs on the Look step, set from the clips (bridge\what_was_filmed.py)
    QString m_tab = QStringLiteral("all"); // the tab shown: "all" or a Style's id
    bool m_tabChosen = false;              // the person picked the tab: what the clips say no longer moves it
    QString m_tabFor;                      // the clips the person picked it for: other clips decide the tab again
    QString m_detected;                    // what the clips are ("" while it is worked out, "all" when unsure)
    QString m_detectedWhy;
    bool m_detectedAngles = false;         // T188: the clips look like several cameras on one conversation
    QString m_detectedFor;                 // the clips that answer is for
    QProcess *m_detect = nullptr;
    // T174: the fit check of a learned Look's format against the chosen clips, shown under the Looks
    QWidget *m_fitHolder = nullptr;
    QLabel *m_fitNote = nullptr;
    QLabel *m_goFitNote = nullptr;
    bool m_fitWaitingToSend = false;
    QCheckBox *m_lookOnly = nullptr; // "Make it with only the look", offered when the clips don't fit
    QProcess *m_fit = nullptr;
    QString m_fitFor;                // the Look's place and the clips the answer is for
    QString m_fitVerdict;            // fits | maybe | partly | no | unknown ("" while it is worked out)
    QString m_fitLine;
    QString m_filter;          // the Look browser's filter: "all", "mine", a folder's or a Style's id
    QString m_lookNote;        // the chosen Look was let go: why
    QHBoxLayout *m_filterRow = nullptr;
    QScrollArea *m_filtersScroll = nullptr;
    QLabel *m_chosenLine = nullptr;
    QWidget *m_inputsHolder = nullptr;
    QVBoxLayout *m_inputsColumn = nullptr;
    QLabel *m_inputsNote = nullptr;
    QLabel *m_inputsGone = nullptr;
    QString m_inputsLookId;                       // the Look the boxes were built for
    QString m_inputsLookLabel;
    QStringList m_askOrder;                       // the shown boxes' ids, in order
    QMap<QString, LookAsk> m_askDefs;
    QMap<QString, QPlainTextEdit *> m_askText;
    QMap<QString, AskFiles *> m_askFiles;
    QMap<QString, QLabel *> m_askStatus;
    QMap<QString, QPair<QString, QString>> m_askFacts; // path -> (length, thumbnail image)
    QJsonObject m_inputsDraft;                    // look id -> box id -> text, or a list of paths (kept for next time)
    QList<LookCard *> m_lookCards;
    QLabel *m_styleHeading = nullptr;
    QLabel *m_styleLead = nullptr;
    QMap<QString, QSlider *> m_sliders;
    QMap<QString, QCheckBox *> m_aiSwitches;
    QSlider *m_master = nullptr;
    QCheckBox *m_masterAi = nullptr;
    QComboBox *m_presetList = nullptr;
    QLineEdit *m_presetName = nullptr;
    QLabel *m_presetNote = nullptr;
    QPushButton *m_defaultPresetButton = nullptr;
    bool m_loadingPreset = false;
    QString m_legacyStyle;
    QMap<QString, QStringList> m_customArtifacts;
    QGridLayout *m_styleGrid = nullptr;
    QLabel *m_styleNote = nullptr;
    QButtonGroup *m_styles = nullptr;
    QString m_style = QStringLiteral("none");
    bool m_personChose = false; // the person picked a card (else m_style is the default: their own style or none)
    bool m_filling = false;
    QList<StyleChoice> m_catalog;
    int m_catalogState = 0; // 0 loading, 1 loaded, -1 failed
    QPlainTextEdit *m_about = nullptr;
    QCheckBox *m_aiLength = nullptr;
    QCheckBox *m_turbo = nullptr;
    QWidget *m_turboRow = nullptr;
    QLabel *m_turboNote = nullptr;
    QLabel *m_goHint = nullptr;
    QLabel *m_readyHeading = nullptr;
    QLabel *m_readyLead = nullptr;
    QLabel *m_readyPicture = nullptr;
    QLabel *m_readyLook = nullptr;
    QLabel *m_readyLine = nullptr;
    QLabel *m_readyAi = nullptr;
    QLabel *m_readyModel = nullptr;
    QMenu *m_aiMenu = nullptr;
    QLineEdit *m_song = nullptr;
    QWidget *m_songPanel = nullptr;
    QLineEdit *m_length = nullptr;
    QLabel *m_summary = nullptr;
};

} // namespace NewVideo

#endif // NEWVIDEODIALOG_H
