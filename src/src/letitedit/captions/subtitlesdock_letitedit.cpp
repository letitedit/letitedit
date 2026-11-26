/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * Captions: the caption looks and word lists, choosing and editing captions on the timeline, speech to text through the bridge, translating, burning in.
 * (letitedit's additions to subtitlesdock.cpp, moved out of Shotcut's file; the
 * declarations stay in its header.)
 */
#include "docks/subtitlesdock.h"
#include <QKeyEvent>
#include <QUndoStack>

#include "Logger.h"
#include "actions.h"
#include "dialogs/speechdialog.h"
#include "dialogs/subtitletrackdialog.h"
#include "dialogs/transcribeaudiodialog.h"
#include "jobqueue.h"
#include "jobs/kokorodokijob.h"
#include "jobs/meltjob.h"
#include "jobs/whisperjob.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/letitedit.h"
#include "letitedit/dialogs/letools.h"
#include "docks/timelinedock.h"
#include "models/multitrackmodel.h"
#include "mainwindow.h"
#include "models/subtitlesmodel.h"
#include "models/subtitlesselectionmodel.h"
#include "qmltypes/qmlapplication.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"
#include "util.h"
#include "widgets/docktoolbar.h"
#include "widgets/timespinbox.h"

#include <QButtonGroup>
#include <QFormLayout>
#include <QDockWidget>
#include <QDir>
#include <QDateTime>
#include <QDialog>
#include <QRegularExpression>
#include <QTableWidget>
#include <QUndoCommand>
#include <QDialogButtonBox>
#include <QPushButton>
#include <QVariantMap>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QFile>
#include <limits>
#include <algorithm>

#include <MltPlaylist.h>
#include <QAction>
#include <QApplication>
#include <QComboBox>
#include <QFileInfo>
#include <QGridLayout>
#include <QHBoxLayout>
#include <QHeaderView>
#include <QIcon>
#include <QInputDialog>
#include <QItemSelection>
#include <QItemSelectionModel>
#include <QLabel>
#include <QMenu>
#include <QMessageBox>
#include <QProcess>
#include <QStandardPaths>
#include <QTextDocumentFragment>
#include <QTextEdit>
#include <QToolButton>
#include <QTreeView>
#include <QVBoxLayout>
#include <QtWidgets/QScrollArea>

// letitedit: caption looks. Each is a set of burn-in filter properties; sizes follow the frame so a look
// reads the same at any resolution, and vertical videos sit a little below the middle, clear of the app buttons.
// Shotcut's own helper (docks/subtitlesdock.cpp)
int64_t positionToMs(mlt_position position);

namespace {

struct CaptionLook
{
    const char *key;
    const char *label;
    const char *family;
    int weight;
    const char *fg;
    const char *bg;
    const char *ol;
    double outline;  // outline width as a share of the frame height (0 = none)
    double sizeTall; // text size as a share of the frame height, vertical video
    double sizeWide; // and horizontal video
    double pad;      // background padding as a share of the frame height
};

const CaptionLook kCaptionLooks[] = {
    {"bold", QT_TRANSLATE_NOOP("SubtitlesDock", "Bold"), "Segoe UI Black", QFont::Black, "#ffffffff", "#00000000",
     "#ff000000", 1.0 / 240, 1.0 / 24, 1.0 / 18, 0},
    {"box", QT_TRANSLATE_NOOP("SubtitlesDock", "Box"), "Segoe UI", QFont::Bold, "#ffffffff", "#b4000000",
     "#00000000", 0, 1.0 / 26, 1.0 / 20, 1.0 / 120},
    {"yellow", QT_TRANSLATE_NOOP("SubtitlesDock", "Yellow"), "Segoe UI Black", QFont::Black, "#ffffd84a", "#00000000",
     "#ff000000", 1.0 / 200, 1.0 / 22, 1.0 / 17, 0},
    {"classic", QT_TRANSLATE_NOOP("SubtitlesDock", "Classic"), "Verdana", QFont::Bold, "#ffffffff", "#00000000",
     "#aa000000", 1.0 / 360, 1.0 / 30, 1.0 / 20, 0},
};

const CaptionLook &captionLook(const QString &key)
{
    for (const auto &look : kCaptionLooks) {
        if (key == QLatin1String(look.key))
            return look;
    }
    return kCaptionLooks[0];
}

QString savedCaptionLook()
{
    return leSettings().value(QStringLiteral("captions/look"), QStringLiteral("bold")).toString();
}

QMap<QString, QString> captionLookProperties(const CaptionLook &look)
{
    const double h = MLT.profile().height();
    const bool tall = MLT.profile().width() < MLT.profile().height();
    QMap<QString, QString> p;
#if defined(Q_OS_WIN)
    p["family"] = look.family;
#endif
    p["weight"] = QString::number(look.weight);
    p["style"] = QStringLiteral("normal");
    p["fgcolour"] = look.fg;
    p["bgcolour"] = look.bg;
    p["olcolour"] = look.ol;
    p["outline"] = QString::number(look.outline > 0 ? qMax(2, qRound(h * look.outline)) : 0);
    p["size"] = QString::number(qRound(h * (tall ? look.sizeTall : look.sizeWide)));
    p["pad"] = QString::number(qRound(h * look.pad));
    p["geometry"] = tall ? QStringLiteral("8%/50%:84%x20%") : QStringLiteral("10%/76%:80%x18%");
    p["valign"] = tall ? QStringLiteral("middle") : QStringLiteral("bottom");
    p["halign"] = QStringLiteral("center");
    p["shotcut:captionLook"] = look.key;
    return p;
}

Mlt::Filter *captionBurnIn(const QString &feed)
{
    auto tractor = MAIN.multitrack();
    for (int i = 0; tractor && i < tractor->filter_count(); ++i) {
        Mlt::Filter *filter = tractor->filter(i);
        if (filter && filter->is_valid() && QString(filter->get("mlt_service")) == "subtitle"
            && QString::fromUtf8(filter->get("feed")) == feed)
            return filter;
        delete filter;
    }
    return nullptr;
}

// Changing the look of the captions on the video: one undo step.
class CaptionLookCommand : public QUndoCommand
{
public:
    CaptionLookCommand(const QString &feed, const QMap<QString, QString> &before, const QMap<QString, QString> &after)
        : m_feed(feed)
        , m_before(before)
        , m_after(after)
    {
        setText(QObject::tr("Caption look"));
    }
    void redo() override { apply(m_after); }
    void undo() override { apply(m_before); }

private:
    void apply(const QMap<QString, QString> &props)
    {
        QScopedPointer<Mlt::Filter> filter(captionBurnIn(m_feed));
        if (!filter)
            return;
        for (auto it = props.cbegin(); it != props.cend(); ++it)
            filter->set(it.key().toUtf8().constData(), it.value().toUtf8().constData());
        MLT.refreshConsumer();
        emit MAIN.timelineDock()->model()->modified();
    }
    QString m_feed;
    QMap<QString, QString> m_before, m_after;
};

// Spelling fixes on a caption track (names, brands, part numbers): one undo step.
class CaptionWordsCommand : public QUndoCommand
{
public:
    CaptionWordsCommand(SubtitlesModel *model, int track, const QList<Subtitles::SubtitleItem> &before,
                        const QList<Subtitles::SubtitleItem> &after)
        : m_model(model)
        , m_track(track)
        , m_before(before)
        , m_after(after)
    {
        setText(QObject::tr("Fix caption words"));
    }
    void redo() override { m_model->doReplaceItems(m_track, m_after); }
    void undo() override { m_model->doReplaceItems(m_track, m_before); }

private:
    SubtitlesModel *m_model;
    int m_track;
    QList<Subtitles::SubtitleItem> m_before, m_after;
};

} // namespace

void SubtitlesDock::buildStudioCaptionChoices(QWidget *body, QVBoxLayout *column)
{
    auto intro = new QLabel(tr("Spoken captions"), body);
    intro->setProperty("studioHeading", true);
    column->addWidget(intro);
    auto help = new QLabel(tr("Make captions from speech, or add a caption at the playhead. Double-click a row to adjust timing."), body);
    help->setWordWrap(true);
    help->setProperty("studioMuted", true);
    column->addWidget(help);
    auto generate = new QPushButton(tr("Make captions from speech…"), body);
    generate->setProperty("studioPrimary", true);
    connect(generate, &QPushButton::clicked, Actions["subtitleSpeechToTextAction"], &QAction::trigger);
    connect(Actions["subtitleSpeechToTextAction"], &QAction::changed, generate, [generate]() {
        generate->setEnabled(Actions["subtitleSpeechToTextAction"]->isEnabled());
    });
    column->addWidget(generate);
    auto lookRow = new QHBoxLayout;
    lookRow->setSpacing(6);
    auto lookLabel = new QLabel(tr("Look"), body);
    lookRow->addWidget(lookLabel);
    auto looks = new QButtonGroup(body);
    looks->setExclusive(true);
    const QString current = savedCaptionLook();
    for (const auto &look : kCaptionLooks) {
        auto button = new QPushButton(tr(look.label), body);
        button->setObjectName(QStringLiteral("captionLook_%1").arg(look.key));
        button->setCheckable(true);
        button->setChecked(current == QLatin1String(look.key));
        button->setToolTip(tr("Captions in the video look like this (one undo step)"));
        looks->addButton(button);
        lookRow->addWidget(button, 1);
        connect(button, &QPushButton::clicked, this, [this, key = QString::fromLatin1(look.key)]() {
            applyCaptionLook(key);
        });
    }
    column->addLayout(lookRow);
    auto words = new QPushButton(tr("Fix words (names, brands, part numbers)…"), body);
    words->setObjectName(QStringLiteral("captionFixWords"));
    connect(words, &QPushButton::clicked, this, [this]() { editWordList(); });
    column->addWidget(words);
    auto translate = new QPushButton(tr("Translate captions…"), body);
    translate->setObjectName(QStringLiteral("captionTranslate"));
    translate->setToolTip(tr("Your AI translates the captions into another language as a new caption track"));
    connect(translate, &QPushButton::clicked, this, [this]() { translateCaptions(); });
    column->addWidget(translate);
    auto dub = new QPushButton(tr("Dub this video…"), body);
    dub->setObjectName(QStringLiteral("captionDub"));
    dub->setToolTip(tr("Your AI translates what's said and a voice speaks it in another language, on its own track"));
    connect(dub, &QPushButton::clicked, this, []() {
        if (auto a = Actions["dubVideoAction"])
            a->trigger();
    });
    column->addWidget(dub);
    auto style = new QPushButton(tr("My Looks (save or use)…"), body);
    style->setObjectName(QStringLiteral("captionMyStyle"));
    style->setToolTip(tr("Keep this caption look, with the music and pause settings, for every video in the series"));
    connect(style, &QPushButton::clicked, this, []() {
        if (auto a = Actions["myStyleAction"])
            a->trigger();
    });
    column->addWidget(style);
}

void SubtitlesDock::installStudioPresentation()
{
    auto legacy = widget();
    auto body = new QWidget(this);
    auto column = new QVBoxLayout(body);
    column->setContentsMargins(16, 14, 16, 14);
    column->setSpacing(10);
    buildStudioCaptionChoices(body, column);
    auto row = new QHBoxLayout;
    auto import = new QPushButton(tr("Import captions…"), body);
    connect(import, &QPushButton::clicked, Actions["SubtitleImportAction"], &QAction::trigger);
    row->addWidget(import);
    auto more = new QToolButton(body);
    more->setText(tr("More"));
    more->setPopupMode(QToolButton::InstantPopup);
    auto menu = new QMenu(more);
    for (const char *key : {"subtitleAddTrackAction", "subtitleRemoveTrackAction", "subtitleEditTrackAction",
                            "SubtitleImportAction", "SubtitleExportAction", "subtitleSetStartAction", "subtitleSetEndAction", "subtitleRemoveItemAction", "subtitleBurnInAction"})
        menu->addAction(Actions[key]);
    more->setMenu(menu);
    row->addWidget(more);
    column->addLayout(row);
    column->addWidget(m_addToTimelineLabel);
    column->addWidget(m_trackCombo);
    column->addWidget(m_treeView, 1);
    m_treeView->setMinimumHeight(90);
    m_treeView->setColumnHidden(2, true);
    m_treeView->setColumnHidden(3, true);
    m_treeView->setHeaderHidden(true);
    m_text->setObjectName(QStringLiteral("studioCaptionContent"));
    m_text->setLineWrapMode(QTextEdit::WidgetWidth);
    m_text->setPlaceholderText(tr("Select a caption above to edit its words"));
    m_text->setMinimumHeight(70);
    m_text->setMaximumHeight(105);
    column->addWidget(m_text);
    auto add = new QPushButton(tr("+ Caption at playhead"), body);
    auto addAction = new QAction(tr("Add caption at playhead"), this);
    addAction->setObjectName(QStringLiteral("studioAddCaptionAction"));
    Actions.add(QStringLiteral("studioAddCaptionAction"), addAction, tr("Captions"));
    MAIN.addAction(addAction);
    connect(addAction, &QAction::triggered, this, [this]() {
        if (!m_model || !m_model->isValid())
            return;
        const int track = m_trackCombo->currentIndex();
        if (track >= 0 && m_model->itemIndexAtTime(track, positionToMs(m_pos)) >= 0) {
            onCreateOrEditRequested();
            return;
        }
        MAIN.undoStack()->beginMacro(tr("Add caption"));
        onCreateOrEditRequested();
        if (m_trackCombo->currentIndex() >= 0 && m_model->itemCount(m_trackCombo->currentIndex()) > 0) {
            burnInOnTimeline();
            MAIN.findChild<QDockWidget *>(QStringLiteral("FiltersDock"))->hide();
            show();
            raise();
        }
        MAIN.undoStack()->endMacro();
    });
    connect(add, &QPushButton::clicked, addAction, &QAction::trigger);
    row->insertWidget(0, add, 1);
    import->hide();
    auto showVideo = new QPushButton(tr("Show captions in video"), body);
    showVideo->setEnabled(m_trackCombo->currentIndex() >= 0);
    connect(m_trackCombo, &QComboBox::currentIndexChanged, showVideo, [showVideo](int index) { showVideo->setEnabled(index >= 0); });
    connect(showVideo, &QPushButton::clicked, this, [this]() {
        if (m_trackCombo->currentIndex() >= 0) {
            burnInOnTimeline();
            MAIN.findChild<QDockWidget *>(QStringLiteral("FiltersDock"))->hide();
            show();
            raise();
        }
    });
    column->addWidget(showVideo);
    auto back = new QPushButton(tr("← Titles and text"), body);
    connect(back, &QPushButton::clicked, this, []() { Actions["focustextAction"]->trigger(); });
    column->addWidget(back);
    back->hide();
    // The old controls retain their signals and settings behind this presentation.
    legacy->hide();
    legacy->setParent(body);
    auto scroll = new QScrollArea(this);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setWidgetResizable(true);
    scroll->setWidget(body);
    setWidget(scroll);
    m_trackCombo->setVisible(m_model->trackCount() > 1);
    connect(m_model, &SubtitlesModel::tracksChanged, m_trackCombo, [this](int count) { m_trackCombo->setVisible(count > 1); });
    m_prev->hide();
    m_next->hide();
    m_prevLabel->hide();
    m_nextLabel->hide();
    m_textLabel->hide();
}

void SubtitlesDock::selectTrack(int trackIndex)
{
    if (!m_model || trackIndex < 0 || trackIndex >= m_model->trackCount())
        return;
    if (m_trackCombo->currentIndex() != trackIndex)
        m_trackCombo->setCurrentIndex(trackIndex); // -> setSelectedTrack via the combo connection
    else if (m_selectionModel->selectedTrack() != trackIndex)
        m_selectionModel->setSelectedTrack(trackIndex);
}

void SubtitlesDock::editTrackAt(int trackIndex)
{
    selectTrack(trackIndex);
    editSubtitleTrack();
}

bool SubtitlesDock::selectCaption(int trackIndex, int itemIndex)
{
    if (!m_model || trackIndex < 0 || trackIndex >= m_model->trackCount() || itemIndex < 0
        || itemIndex >= m_model->itemCount(trackIndex))
        return false;
    selectTrack(trackIndex);
    m_selectionModel->selectItem(itemIndex);
    return true;
}

bool SubtitlesDock::hasSelectedCaptions()
{
    return m_selectionModel && !m_selectionModel->selectedItems().isEmpty();
}

bool SubtitlesDock::removeSelectedCaptions()
{
    if (!hasSelectedCaptions())
        return false;
    onRemoveRequested();
    m_selectionModel->clearSelection();
    return true;
}

// Parses a Subtitle Burn In 'geometry' (first keyframe) into a normalized rect.
static QRectF captionArea(const QString &value)
{
    QString g = value.trimmed();
    if (g.contains('='))
        g = g.section('=', 1).section(';', 0, 0).trimmed();
    const bool percent = g.contains('%');
    QString s = g;
    s.replace('%', ' ').replace('/', ' ').replace(':', ' ').replace('x', ' ');
    const QStringList v = s.split(' ', Qt::SkipEmptyParts);
    if (v.size() < 4)
        return QRectF(0.2, 0.75, 0.6, 0.2);
    QRectF r(v[0].toDouble(), v[1].toDouble(), v[2].toDouble(), v[3].toDouble());
    if (percent)
        return QRectF(r.x() / 100.0, r.y() / 100.0, r.width() / 100.0, r.height() / 100.0);
    const double w = MLT.profile().width(), h = MLT.profile().height();
    return QRectF(r.x() / w, r.y() / h, r.width() / w, r.height() / h);
}

QVariantList SubtitlesDock::captionsAtPlayhead()
{
    QVariantList list;
    if (!m_model || !MAIN.multitrack())
        return list;
    const int64_t ms = positionToMs(m_pos);
    for (int t = 0; t < m_model->trackCount(); ++t) {
        const int item = m_model->itemIndexAtTime(t, ms);
        if (item < 0)
            continue;
        const QString name = m_model->trackName(t);
        bool burnedIn = false;
        QRectF area(0.2, 0.75, 0.6, 0.2);
        for (int i = 0; i < MAIN.multitrack()->filter_count(); ++i) {
            QScopedPointer<Mlt::Filter> f(MAIN.multitrack()->filter(i));
            if (f && f->is_valid() && QString(f->get("mlt_service")) == "subtitle"
                && QString::fromUtf8(f->get("feed")) == name && !f->get_int("disable")) {
                burnedIn = true;
                area = captionArea(QString::fromUtf8(f->get("geometry")));
                break;
            }
        }
        list << QVariantMap{{"track", t},
                            {"item", item},
                            {"trackName", name},
                            {"text", QString::fromStdString(m_model->getItem(t, item).text)},
                            {"burnedIn", burnedIn},
                            {"x", area.x()},
                            {"y", area.y()},
                            {"w", area.width()},
                            {"h", area.height()}};
    }
    return list;
}

bool SubtitlesDock::editCaption(int trackIndex, int itemIndex)
{
    if (!selectCaption(trackIndex, itemIndex))
        return false;
    const auto item = m_model->getItem(trackIndex, itemIndex);
    const double fps = MLT.profile().fps();
    auto toFrames = [fps](int64_t ms) { return int(qRound(ms * fps / 1000.0)); };
    auto toMs = [fps](int frames) { return int64_t(qRound64(frames * 1000.0 / fps)); };

    QDialog dialog(this);
    dialog.setWindowTitle(tr("Edit Caption"));
    dialog.setWindowModality(QmlApplication::dialogModality());
    auto layout = new QVBoxLayout(&dialog);
    auto trackLabel = new QLabel(tr("Subtitle track: %1").arg(m_model->trackName(trackIndex)));
    layout->addWidget(trackLabel);
    auto text = new QTextEdit;
    text->setAcceptRichText(false);
    text->setPlainText(QString::fromStdString(item.text));
    text->setMinimumSize(420, 90);
    layout->addWidget(text);
    auto times = new QGridLayout;
    auto start = new TimeSpinBox;
    auto end = new TimeSpinBox;
    start->setRange(0, std::numeric_limits<int>::max());
    end->setRange(0, std::numeric_limits<int>::max());
    start->setValue(toFrames(item.start));
    end->setValue(toFrames(item.end));
    times->addWidget(new QLabel(tr("Start")), 0, 0);
    times->addWidget(start, 0, 1);
    times->addWidget(new QLabel(tr("End")), 0, 2);
    times->addWidget(end, 0, 3);
    layout->addLayout(times);
    auto buttons = new QDialogButtonBox(QDialogButtonBox::Ok | QDialogButtonBox::Cancel);
    auto styleButton = buttons->addButton(tr("Style (font, color, position)..."),
                                          QDialogButtonBox::ActionRole);
    auto deleteButton = buttons->addButton(tr("Delete Caption"), QDialogButtonBox::DestructiveRole);
    layout->addWidget(buttons);
    enum { None, Style, Delete } extra = None;
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    connect(styleButton, &QPushButton::clicked, &dialog, [&]() {
        extra = Style;
        dialog.accept();
    });
    connect(deleteButton, &QPushButton::clicked, &dialog, [&]() {
        extra = Delete;
        dialog.accept();
    });
    text->setFocus();
    text->selectAll();
    if (dialog.exec() != QDialog::Accepted)
        return false;

    if (extra == Delete) {
        MAIN.undoStack()->beginMacro(tr("Remove captions only"));
        m_model->removeItems(trackIndex, itemIndex, itemIndex);
        MAIN.undoStack()->endMacro();
        return true;
    }
    const QString newText = text->toPlainText();
    int64_t newStart = toMs(start->value());
    int64_t newEnd = toMs(end->value());
    if (newEnd <= newStart) {
        MAIN.showStatusMessage(tr("The caption must end after it starts."));
        return false;
    }
    const int count = m_model->itemCount(trackIndex);
    if ((itemIndex > 0 && newStart < m_model->getItem(trackIndex, itemIndex - 1).end)
        || (itemIndex < count - 1 && newEnd > m_model->getItem(trackIndex, itemIndex + 1).start)) {
        MAIN.showStatusMessage(tr("Unable to change the time: it would overlap the next or previous caption."));
        newStart = item.start;
        newEnd = item.end;
    }
    MAIN.undoStack()->beginMacro(tr("Edit caption"));
    if (newText != QString::fromStdString(item.text))
        m_model->setText(trackIndex, itemIndex, newText);
    if (newStart != item.start || newEnd != item.end) {
        // order the two changes so neither is ever start >= end on the way
        if (newStart >= item.end) {
            m_model->setItemEnd(trackIndex, itemIndex, newEnd);
            m_model->setItemStart(trackIndex, itemIndex, newStart);
        } else {
            m_model->setItemStart(trackIndex, itemIndex, newStart);
            m_model->setItemEnd(trackIndex, itemIndex, newEnd);
        }
    }
    MAIN.undoStack()->endMacro();
    if (extra == Style) {
        selectTrack(trackIndex);
        burnInOnTimeline(); // creates the Subtitle Burn In filter or opens the existing one
    }
    return true;
}

QList<QPair<QString, QString>> SubtitlesDock::wordList()
{
    QList<QPair<QString, QString>> list;
    const auto rows = leSettings().value(QStringLiteral("captions/words")).toStringList();
    for (const auto &row : rows) {
        const int tab = row.indexOf(QLatin1Char('\t'));
        if (tab > 0)
            list.append({row.left(tab), row.mid(tab + 1)});
    }
    return list;
}

int SubtitlesDock::applyWordList(int trackIndex)
{
    const auto words = wordList();
    if (!m_model || trackIndex < 0 || trackIndex >= m_model->trackCount() || words.isEmpty())
        return 0;
    QList<Subtitles::SubtitleItem> before, after;
    int changes = 0;
    for (int i = 0; i < m_model->itemCount(trackIndex); ++i) {
        auto item = m_model->getItem(trackIndex, i);
        before.append(item);
        QString text = QString::fromStdString(item.text);
        for (const auto &pair : words) {
            QRegularExpression heard(QStringLiteral("(?<![\\w'])%1(?![\\w'])")
                                         .arg(QRegularExpression::escape(pair.first)),
                                     QRegularExpression::CaseInsensitiveOption);
            auto matches = heard.globalMatch(text);
            while (matches.hasNext()) {
                const auto m = matches.next();
                if (m.captured(0) != pair.second)
                    ++changes;
            }
            text.replace(heard, pair.second);
        }
        item.text = text.toStdString();
        after.append(item);
    }
    if (changes > 0)
        MAIN.undoStack()->push(new CaptionWordsCommand(m_model, trackIndex, before, after));
    return changes;
}

QMap<QString, QString> SubtitlesDock::chosenCaptionProperties()
{
    // A style saved with "My style" (its look for this frame shape), else one of the four looks.
    if (savedCaptionLook() == QLatin1String("style")) {
        const QVariantMap custom = leSettings().value(QStringLiteral("captions/custom")).toMap();
        if (!custom.isEmpty()) {
            const double w = MLT.profile().width(), h = MLT.profile().height();
            const double shortSide = qMin(w, h);
            const bool tall = w < h;
            QMap<QString, QString> p = captionLookProperties(captionLook(QStringLiteral("bold")));
            for (const char *key : {"family", "weight", "style", "fgcolour", "bgcolour", "olcolour", "halign"}) {
                if (custom.contains(key))
                    p[key] = custom.value(key).toString();
            }
            // Sizes follow the frame's height, as the AI's style packs do, so the app and the AI agree on any shape
            // (styles saved before kept shares of the short side only).
            const QVariantMap heights = custom.value("heights").toMap();
            for (const char *key : {"size", "outline", "pad"}) {
                if (heights.contains(key))
                    p[key] = QString::number(qRound(heights.value(key).toDouble() * h));
                else if (custom.contains(key))
                    p[key] = QString::number(qRound(custom.value(key).toDouble() * shortSide));
            }
            // The place on screen only carries over to a frame of the same shape.
            if (custom.value("tall").toBool() == tall && custom.contains("geometry")) {
                p["geometry"] = custom.value("geometry").toString();
                p["valign"] = custom.value("valign").toString();
            }
            p["shotcut:captionLook"] = QStringLiteral("style");
            return p;
        }
    }
    return captionLookProperties(captionLook(savedCaptionLook()));
}

QMap<QString, QString> SubtitlesDock::shownCaptionProperties() const
{
    QMap<QString, QString> p;
    const int trackIndex = m_trackCombo->currentIndex();
    if (!m_model || trackIndex < 0 || trackIndex >= m_model->trackCount())
        return p;
    QScopedPointer<Mlt::Filter> filter(captionBurnIn(m_model->getTrack(trackIndex).name));
    if (!filter)
        return p;
    for (const char *key : {"family", "weight", "style", "fgcolour", "bgcolour", "olcolour", "outline", "size", "pad",
                            "geometry", "valign", "halign"})
        p[key] = QString::fromUtf8(filter->get(key));
    return p;
}

bool SubtitlesDock::applyCaptionProperties(const QMap<QString, QString> &properties)
{
    const int trackIndex = m_trackCombo->currentIndex();
    if (!m_model || trackIndex < 0 || trackIndex >= m_model->trackCount())
        return false;
    const QString feed = m_model->getTrack(trackIndex).name;
    QScopedPointer<Mlt::Filter> filter(captionBurnIn(feed));
    if (!filter)
        return false;
    QMap<QString, QString> before;
    for (auto it = properties.cbegin(); it != properties.cend(); ++it)
        before[it.key()] = QString::fromUtf8(filter->get(it.key().toUtf8().constData()));
    MAIN.undoStack()->push(new CaptionLookCommand(feed, before, properties));
    return true;
}

void SubtitlesDock::applyCaptionLook(const QString &key)
{
    leSettings().setValue(QStringLiteral("captions/look"), key);
    const int trackIndex = m_trackCombo->currentIndex();
    if (!m_model || trackIndex < 0)
        return;
    const QString feed = m_model->getTrack(trackIndex).name;
    QScopedPointer<Mlt::Filter> filter(captionBurnIn(feed));
    if (!filter) {
        // Not shown in the video yet: showing them uses the chosen look.
        burnInOnTimeline();
        MAIN.findChild<QDockWidget *>(QStringLiteral("FiltersDock"))->hide();
        show();
        raise();
        return;
    }
    const auto after = captionLookProperties(captionLook(key));
    QMap<QString, QString> before;
    for (auto it = after.cbegin(); it != after.cend(); ++it)
        before[it.key()] = QString::fromUtf8(filter->get(it.key().toUtf8().constData()));
    MAIN.undoStack()->push(new CaptionLookCommand(feed, before, after));
}

// letitedit: the captions in another language, by the person's own AI (the chat panel). The track goes to a file the AI
// reads; it translates the words only (numbers and times stay exactly as they are) and loads the result as a new
// caption track named after the language. The original track is left alone.
void SubtitlesDock::translateCaptions()
{
    const int trackIndex = m_trackCombo->currentIndex();
    if (!m_model || trackIndex < 0 || trackIndex >= m_model->trackCount()) {
        MAIN.showStatusMessage(tr("Make captions first (Make captions from speech), then translate them."));
        return;
    }
    const auto track = m_model->getTrack(trackIndex);
    const QString folder = Settings.appDataLocation() + QStringLiteral("/captions");
    QDir().mkpath(folder);
    const QString srt = QStringLiteral("%1/%2 %3.srt")
                            .arg(folder, track.name, QDateTime::currentDateTime().toString("yyyyMMdd-HHmmss"));
    m_model->exportSubtitles(srt, trackIndex);
    if (QFileInfo(srt).size() < 10) {
        MAIN.showStatusMessage(tr("The %1 captions are empty.").arg(track.name));
        return;
    }

    // Common languages first; any other can be typed.
    const QList<QPair<QString, QString>> languages{{tr("Spanish"), "spa"},    {tr("French"), "fra"},
                                                   {tr("German"), "deu"},     {tr("Portuguese"), "por"},
                                                   {tr("Italian"), "ita"},    {tr("Dutch"), "nld"},
                                                   {tr("Polish"), "pol"},     {tr("Turkish"), "tur"},
                                                   {tr("Russian"), "rus"},    {tr("Ukrainian"), "ukr"},
                                                   {tr("Arabic"), "ara"},     {tr("Hindi"), "hin"},
                                                   {tr("Indonesian"), "ind"}, {tr("Vietnamese"), "vie"},
                                                   {tr("Japanese"), "jpn"},   {tr("Korean"), "kor"},
                                                   {tr("Chinese (Simplified)"), "zho"},
                                                   {tr("English"), "eng"}};
    QDialog dialog(this);
    dialog.setObjectName(QStringLiteral("translateCaptionsDialog"));
    dialog.setWindowTitle(tr("Translate Captions"));
    auto layout = new QVBoxLayout(&dialog);
    auto intro = new QLabel(tr("Your AI translates the <b>%1</b> captions (%2 of them) into a new caption track. The "
                               "original stays as it is; pick either track in Captions to show it on the video or "
                               "save it as an SRT file.")
                                .arg(track.name.toHtmlEscaped())
                                .arg(m_model->itemCount(trackIndex)));
    intro->setWordWrap(true);
    layout->addWidget(intro);
    auto language = new QComboBox(&dialog);
    language->setObjectName(QStringLiteral("translateLanguage"));
    language->setEditable(true);
    for (const auto &l : languages)
        language->addItem(l.first, l.second);
    language->setCurrentIndex(qMax(0, language->findText(leSettings().value("captions/translateTo").toString())));
    auto form = new QFormLayout;
    form->addRow(tr("Into"), language);
    layout->addLayout(form);
    auto buttons = new QDialogButtonBox(QDialogButtonBox::Cancel, &dialog);
    auto go = buttons->addButton(tr("Translate"), QDialogButtonBox::AcceptRole);
    go->setObjectName(QStringLiteral("translateGo"));
    go->setDefault(true);
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted)
        return;
    const QString name = language->currentText().trimmed();
    if (name.isEmpty())
        return;
    leSettings().setValue("captions/translateTo", name);
    const int known = language->findText(name);
    const QString code = known >= 0 ? language->itemData(known).toString() : QStringLiteral("und");
    QString trackName = name;
    for (int n = 2; trackNameExists(trackName); ++n)
        trackName = QStringLiteral("%1 %2").arg(name).arg(n);
    const QString request
        = tr("Translate the captions in \"%1\" into %2 for the open letitedit project. Keep every caption's number and "
             "time line exactly as they are and translate only the words; keep each caption about as short as the "
             "original so it still fits on screen, and leave names, brands and part numbers as they are. Then load the "
             "whole translated SRT with letitedit_import_srt(srt=<the translated SRT text>, track_name=\"%3\", "
             "lang=\"%4\"). Do not change the \"%5\" track. Reply in one line when it is done.")
              .arg(QDir::toNativeSeparators(srt), name, trackName, code, track.name);
    if (!aiChatRequest(&MAIN, request, tr("Translate the captions into %1").arg(name))) {
        MAIN.showStatusMessage(tr("Your AI is still busy with the last request. Try again when it has answered."));
        return;
    }
    if (auto chat = MAIN.findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
        chat->show();
        chat->raise();
    }
    MAIN.showStatusMessage(tr("Your AI is translating the captions; a %1 track appears in Captions when it is done.")
                               .arg(trackName),
                           15);
}

void SubtitlesDock::editWordList()
{
    QDialog dialog(this);
    dialog.setWindowTitle(tr("Fix words in captions"));
    dialog.setMinimumWidth(460);
    auto column = new QVBoxLayout(&dialog);
    auto help = new QLabel(tr("Names, brands and part numbers that speech recognition gets wrong. Each row: what it "
                              "hears, and how to write it. They are fixed in these captions now and in new ones "
                              "automatically."),
                           &dialog);
    help->setWordWrap(true);
    column->addWidget(help);
    auto table = new QTableWidget(&dialog);
    table->setObjectName(QStringLiteral("captionWordTable"));
    table->setColumnCount(2);
    table->setHorizontalHeaderLabels({tr("It hears"), tr("Write it as")});
    table->horizontalHeader()->setSectionResizeMode(QHeaderView::Stretch);
    table->verticalHeader()->hide();
    const auto words = wordList();
    table->setRowCount(words.size() + 3);
    for (int r = 0; r < words.size(); ++r) {
        table->setItem(r, 0, new QTableWidgetItem(words[r].first));
        table->setItem(r, 1, new QTableWidgetItem(words[r].second));
    }
    column->addWidget(table, 1);
    auto addRow = new QPushButton(tr("+ Row"), &dialog);
    connect(addRow, &QPushButton::clicked, table, [table]() { table->setRowCount(table->rowCount() + 1); });
    auto buttons = new QDialogButtonBox(QDialogButtonBox::Cancel, &dialog);
    buttons->addButton(addRow, QDialogButtonBox::ResetRole);
    auto ok = buttons->addButton(tr("Fix these words"), QDialogButtonBox::AcceptRole);
    ok->setObjectName(QStringLiteral("captionWordsApply"));
    connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    column->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted)
        return;
    QStringList rows;
    for (int r = 0; r < table->rowCount(); ++r) {
        const QString heard = table->item(r, 0) ? table->item(r, 0)->text().trimmed() : QString();
        const QString written = table->item(r, 1) ? table->item(r, 1)->text().trimmed() : QString();
        if (!heard.isEmpty() && !written.isEmpty())
            rows << heard + QLatin1Char('\t') + written;
    }
    leSettings().setValue(QStringLiteral("captions/words"), rows);
    const int fixed = applyWordList(m_trackCombo->currentIndex());
    MAIN.showStatusMessage(fixed ? tr("Fixed %n word(s) in the captions.", nullptr, fixed)
                                 : tr("Saved. Nothing to fix in these captions."));
}

void SubtitlesDock::burnInOnTimelineWithProperties(const QMap<QString, QString> &properties)
{
    int trackIndex = m_trackCombo->currentIndex();
    auto track = m_model->getTrack(trackIndex);
    Mlt::Filter filter(MLT.profile(), "subtitle");
    filter.set(kShotcutFilterProperty, "subtitles");
#if defined(Q_OS_WIN)
    filter.set("family", "Verdana");
#elif defined(Q_OS_MAC)
    filter.set("family", "Helvetica");
#endif
    filter.set("fgcolour", "#ffffffff");
    filter.set("bgcolour", "#00000000");
    filter.set("olcolour", "#aa000000");
    filter.set("outline", 3);
    filter.set("weight", QFont::Bold);
    filter.set("style", "normal");
    filter.set("shotcut:usePointSize", 1);
    filter.set("size", MLT.profile().height() / 20);
    filter.set("geometry", "20%/75%:60%x20%");
    filter.set("valign", "bottom");
    filter.set("halign", "center");
    // The chosen caption look (Bold by default): sized to the frame, placed for vertical or horizontal video.
    for (auto it = properties.cbegin(); it != properties.cend(); ++it)
        filter.set(it.key().toUtf8().constData(), it.value().toUtf8().constData());
    filter.set("feed", track.name.toUtf8().constData());
    filter.set("typewriter", 0);
    filter.set("typewriter.step_length", 15);
    filter.set("typewriter.step_sigma", 2);
    filter.set("typewriter.random_seed", 0);
    filter.set("typewriter.macro_type", 2);
    filter.set("typewriter.cursor", 0);
    filter.set("typewriter.cursor_blink_rate", 25);
    filter.set("typewriter.cursor_char", "|");
    emit createOrEditFilterOnOutput(&filter, QStringList() << "feed");
}

void SubtitlesDock::speechToTextWithBridge(const QString &trackName, const QString &language)
{
    const QString folder = MAIN.fileName().isEmpty()
                               ? QStandardPaths::writableLocation(QStandardPaths::AppDataLocation)
                               : QFileInfo(MAIN.fileName()).absolutePath();
    auto *copy = new QTemporaryFile(QDir(folder).filePath(QStringLiteral("letitedit-captions-XXXXXX.mlt")));
    if (!copy->open()) {
        delete copy;
        MAIN.showStatusMessage(tr("Could not make a working copy of the open video for captions."), 15);
        return;
    }
    QString xml = MLT.XML(MAIN.multitrack());
    // MLT.XML(tractor) omits the profile. The bridge reader needs the open window's exact frame shape and rate.
    if (!xml.contains(QLatin1String("<profile"))) {
        const auto &profile = MLT.profile();
        const QString profileXml = QStringLiteral("<profile width=\"%1\" height=\"%2\" progressive=\"1\" "
                                                  "sample_aspect_num=\"1\" sample_aspect_den=\"1\" "
                                                  "display_aspect_num=\"%1\" display_aspect_den=\"%2\" "
                                                  "frame_rate_num=\"%3\" frame_rate_den=\"%4\" colorspace=\"709\"/>")
                                       .arg(profile.width()).arg(profile.height())
                                       .arg(profile.frame_rate_num()).arg(profile.frame_rate_den());
        const int root = xml.indexOf(QLatin1Char('>'), xml.indexOf(QLatin1String("<mlt")));
        if (root >= 0) xml.insert(root + 1, profileXml);
    }
    copy->write(xml.toUtf8());
    copy->flush();
    copy->close();
    const QString path = copy->fileName();
    copy->setAutoRemove(false); // Python replaces this working file; no Qt file handle may remain open on Windows.
    delete copy;
    QJsonObject fixes;
    for (const auto &pair : wordList())
        fixes.insert(pair.first, pair.second);
    auto *run = new LeToolRun(this);
    run->progress = [](double, const QString &message) {
        if (!message.isEmpty()) MAIN.showStatusMessage(message, 5);
    };
    run->waiting = [](const QString &message) {
        if (!message.isEmpty()) MAIN.showStatusMessage(message, 5);
    };
    run->done = [this, run, path, trackName, language](bool ok, const QJsonObject &result, const QString &why) {
        QFile::remove(path);
        run->deleteLater();
        if (!ok) {
            if (!why.isEmpty()) MAIN.showStatusMessage(tr("Captions could not be made: %1").arg(why), 20);
            return;
        }
        if (trackNameExists(trackName)) {
            MAIN.showStatusMessage(tr("The caption track was added while captions were being made. Try again."), 15);
            return;
        }
        const QJsonArray tracks = result.value(QStringLiteral("captions")).toArray();
        if (tracks.isEmpty()) {
            MAIN.showStatusMessage(tr("No spoken captions were found."), 15);
            return;
        }
        int total = 0;
        MAIN.undoStack()->beginMacro(tr("Make captions"));
        for (const auto &value : tracks) {
            const QJsonObject planned = value.toObject();
            SubtitlesModel::SubtitleTrack track;
            track.name = planned.value(QStringLiteral("track")).toString();
            QLocale::Language lang = QLocale::codeToLanguage(language);
            track.lang = lang == QLocale::AnyLanguage ? language
                                                      : QLocale::languageToCode(lang, QLocale::ISO639Part2);
            QList<Subtitles::SubtitleItem> items;
            for (const auto &cueValue : planned.value(QStringLiteral("cues")).toArray()) {
                const auto cue = cueValue.toObject();
                items.append({(int64_t) cue.value(QStringLiteral("start_ms")).toDouble(),
                              (int64_t) cue.value(QStringLiteral("end_ms")).toDouble(),
                              cue.value(QStringLiteral("text")).toString().toStdString()});
            }
            total += items.size();
            m_model->importSubtitlesToNewTrack(track, items);
            m_trackCombo->setCurrentIndex(m_model->trackCount() - 1);
            QMap<QString, QString> style = chosenCaptionProperties();
            const QJsonObject plannedStyle = planned.value(QStringLiteral("style")).toObject();
            for (auto it = plannedStyle.begin(); it != plannedStyle.end(); ++it)
                if (it.value().isString() || it.value().isDouble())
                    style[it.key()] = it.value().toVariant().toString();
            burnInOnTimelineWithProperties(style);
        }
        MAIN.undoStack()->endMacro();
        if (auto filters = MAIN.findChild<QDockWidget *>(QStringLiteral("FiltersDock"))) filters->hide();
        show();
        raise();
        const QJsonArray models = result.value(QStringLiteral("models")).toArray();
        const bool smaller = std::any_of(models.begin(), models.end(), [](const QJsonValue &v) {
            return v.toString() != QLatin1String("large-v3-turbo");
        });
        MAIN.showStatusMessage(smaller ? tr("Made %n captions with the smaller speech engine; the larger one was unavailable.", nullptr, total)
                                      : tr("Made %n captions. One Undo removes them.", nullptr, total), 20);
    };
    run->start(QStringLiteral("captions-plan"),
               {QStringLiteral("--project"), path, QStringLiteral("--track"), trackName,
                QStringLiteral("--fixes"), QString::fromUtf8(QJsonDocument(fixes).toJson(QJsonDocument::Compact))},
               true, QStringLiteral("letitedit captions from speech"));
}

bool SubtitlesDock::eventFilter(QObject *watched, QEvent *event)
{
    if(watched==m_treeView && (event->type()==QEvent::ShortcutOverride || event->type()==QEvent::KeyPress)){
        auto *key=static_cast<QKeyEvent *>(event);
        if(key->key()==Qt::Key_Delete && key->modifiers()==Qt::NoModifier){
            if(event->type()==QEvent::KeyPress)onRemoveRequested();
            event->accept();return true;
        }
    }
    return QDockWidget::eventFilter(watched,event);
}
