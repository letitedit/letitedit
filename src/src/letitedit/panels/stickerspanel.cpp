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

#include "letitedit/panels/stickerspanel.h"

#include "letitedit/workspace/focusworkspace.h"
#include "letitedit/chat/aichatpanel.h"
#include "docks/timelinedock.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/dialogs/letools.h"
#include "mainwindow.h"
#include "mltcontroller.h"

#include <QApplication>
#include <QAudioOutput>
#include <QBuffer>
#include <QClipboard>
#include <QComboBox>
#include <QDrag>
#include <QCursor>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QImageReader>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMediaPlayer>
#include <QMimeData>
#include <QMouseEvent>
#include <QMovie>
#include <QPainter>
#include <QPainterPath>
#include <QPointer>
#include <QPushButton>
#include <QTimer>
#include <QUrl>
#include <QVBoxLayout>

namespace {

const int kIcon = 64;

// The panel's choices: {label, kinds, animated}
struct KindChoice
{
    const char *label;
    const char *kinds;
    const char *animated;
    const char *groups;
};
const KindChoice kKinds[] = {{QT_TR_NOOP("Everything"), "emoji,sticker,icon,graphic,transition,sfx", "", ""},
                             {QT_TR_NOOP("Emoji"), "emoji", "no", ""},
                             {QT_TR_NOOP("Animated stickers"), "emoji,sticker", "yes", ""},
                             {QT_TR_NOOP("Icons"), "icon", "", ""},
                             {QT_TR_NOOP("Titles & motion graphics"), "graphic", "", "text,motion"},
                             {QT_TR_NOOP("Transitions"), "transition", "", "transitions"},
                             {QT_TR_NOOP("Overlays & frames"), "graphic,sticker", "", "overlays"},
                             {QT_TR_NOOP("Sound effects"), "sfx", "", ""},
                             {QT_TR_NOOP("My scenes"), "my_scene", "", ""}};

QString myScenesFolder()
{
    return QDir(qEnvironmentVariable("APPDATA")).filePath(QStringLiteral("letitedit/my-scenes"));
}

QImage readPicture(const QString &path)
{
    if (path.isEmpty())
        return {};
    if (path.endsWith(QLatin1String(".svg"), Qt::CaseInsensitive)) {
        // Tabler icons draw in currentColor (black): drawn here in cream, like the rest of the panel
        QFile f(path);
        if (!f.open(QIODevice::ReadOnly))
            return {};
        QByteArray svg = f.readAll();
        svg.replace("currentColor", LetItEditColors::cream);
        QBuffer buffer(&svg);
        buffer.open(QIODevice::ReadOnly);
        QImageReader reader(&buffer, "svg");
        reader.setScaledSize(QSize(kIcon - 12, kIcon - 12));
        return reader.read();
    }
    QImageReader reader(path);
    const QSize size = reader.size();
    if (size.isValid())
        reader.setScaledSize(size.scaled(kIcon, kIcon, Qt::KeepAspectRatio));
    return reader.read();
}

QIcon iconFor(const QJsonObject &e)
{
    using namespace LetItEditColors;
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(QSize(kIcon, kIcon) * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    p.setRenderHint(QPainter::SmoothPixmapTransform);
    const bool sound = e.value("kind").toString() == QLatin1String("sfx");
    const QImage picture = sound ? QImage() : readPicture(e.value("thumb").toString());
    if (!picture.isNull()) {
        const QSize s = picture.size().scaled(kIcon, kIcon, Qt::KeepAspectRatio);
        p.drawImage(QRect((kIcon - s.width()) / 2, (kIcon - s.height()) / 2, s.width(), s.height()), picture);
    } else {
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(sound ? tealDeep : lifted));
        p.drawRoundedRect(QRectF(2, 2, kIcon - 4, kIcon - 4), 9, 9);
        QFont f = p.font();
        p.setPen(QColor(cream));
        if (sound) {
            f.setPixelSize(22);
            p.setFont(f);
            p.drawText(QRect(0, 4, kIcon, 32), Qt::AlignCenter, QStringLiteral("♪"));
            f.setPixelSize(11);
            p.setFont(f);
            const double s = e.value("duration_s").toDouble();
            p.drawText(QRect(0, 34, kIcon, 16), Qt::AlignCenter,
                       s > 0 ? QStringLiteral("%1 s").arg(s, 0, 'f', s < 10 ? 1 : 0) : QString());
        } else {
            const QString glyph = e.value("glyph").toString();
            f.setPixelSize(glyph.isEmpty() ? 12 : 28);
            p.setFont(f);
            p.drawText(QRect(4, 4, kIcon - 8, kIcon - 8), Qt::AlignCenter | Qt::TextWordWrap,
                       glyph.isEmpty() ? e.value("name").toString() : glyph);
        }
    }
    // marks: it moves (bottom left), it needs a credit line (top right)
    QFont small = p.font();
    small.setPixelSize(10);
    small.setBold(true);
    p.setFont(small);
    if (e.value("animated").toBool()) {
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(teal));
        p.drawEllipse(QRectF(1, kIcon - 17, 16, 16));
        QPainterPath tri;
        tri.moveTo(6.5, kIcon - 13);
        tri.lineTo(13, kIcon - 9);
        tri.lineTo(6.5, kIcon - 5);
        tri.closeSubpath();
        p.setBrush(QColor(cream));
        p.drawPath(tri);
    }
    if (!e.value("credit").toString().isEmpty()) {
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(rust));
        p.drawEllipse(QRectF(kIcon - 17, 1, 16, 16));
        p.setPen(QColor(cream));
        p.drawText(QRectF(kIcon - 17, 1, 16, 16), Qt::AlignCenter, QStringLiteral("©"));
    }
    p.end();
    return QIcon(pixmap);
}

QString trackFor(const QJsonObject &e)
{
    return e.value("kind").toString() == QLatin1String("sfx") ? QObject::tr("Sound effects") : QObject::tr("Stickers");
}

} // namespace

StickersPanel::StickersPanel(MainWindow *window)
    : QDockWidget(tr("Elements"), window)
    , m_window(window)
{
    using namespace LetItEditColors;
    setObjectName(QStringLiteral("stickersDock"));
    toggleViewAction()->setObjectName(QStringLiteral("stickersDockAction"));
    auto body = new QWidget(this);
    auto column = new QVBoxLayout(body);
    column->setContentsMargins(12, 12, 12, 12);
    column->setSpacing(8);
    auto intro = new QLabel(tr("Browse open-source elements. Drag to the timeline or use Add at playhead."),
                            body);
    intro->setWordWrap(true);
    intro->setProperty("studioMuted", true);
    column->addWidget(intro);
    auto row = new QHBoxLayout;
    m_search = new QLineEdit(body);
    m_search->setObjectName(QStringLiteral("stickersSearch"));
    m_search->setPlaceholderText(tr("Search: fire, arrow, money, whoosh..."));
    m_search->setAccessibleName(tr("Search elements"));
    m_search->setClearButtonEnabled(true);
    row->addWidget(m_search, 1);
    m_kind = new QComboBox(body);
    m_kind->setObjectName(QStringLiteral("stickersKind"));
    for (const auto &k : kKinds)
        m_kind->addItem(tr(k.label), QString::fromLatin1(k.kinds) + QLatin1Char('|')
                                         + QString::fromLatin1(k.animated) + QLatin1Char('|')
                                         + QString::fromLatin1(k.groups));
    row->addWidget(m_kind);
    column->addLayout(row);
    m_list = new QListWidget(body);
    m_list->setObjectName(QStringLiteral("stickersList"));
    m_list->setViewMode(QListView::IconMode);
    m_list->setIconSize(QSize(kIcon, kIcon));
    m_list->setGridSize(QSize(kIcon + 50, kIcon + 42));
    m_list->setResizeMode(QListView::Adjust);
    m_list->setMovement(QListView::Static);
    m_list->setWordWrap(true);
    m_list->setUniformItemSizes(true);
    m_list->setSelectionMode(QAbstractItemView::SingleSelection);
    m_list->setDragEnabled(false); // our own drag: the clip as the timeline takes it
    m_list->viewport()->installEventFilter(this);
    window->installEventFilter(this);
    m_list->setAccessibleName(tr("Elements found. Drag one to the timeline."));
    column->addWidget(m_list, 1);
    m_title = new QPushButton(tr("Make an animated title..."), body);
    m_title->setObjectName(QStringLiteral("elementsAnimatedTitle"));
    m_title->hide();
    connect(m_title, &QPushButton::clicked, this, [this]() { LeFeatures::showAnimatedTitle(m_window); });
    column->addWidget(m_title);
    m_more = new QPushButton(tr("Show more"), body);
    m_more->setObjectName(QStringLiteral("stickersMore"));
    m_more->hide();
    connect(m_more, &QPushButton::clicked, this, [this]() { search(true); });
    column->addWidget(m_more);
    m_creditBox = new QWidget(body);
    m_creditBox->setObjectName(QStringLiteral("stickersCreditBox"));
    m_creditBox->setStyleSheet(QStringLiteral("#stickersCreditBox { background: %1; border: 1px solid %2; border-radius: 8px; }")
                                   .arg(raised, rustDeep));
    auto creditRow = new QHBoxLayout(m_creditBox);
    creditRow->setContentsMargins(10, 8, 10, 8);
    m_credit = new QLabel(m_creditBox);
    m_credit->setObjectName(QStringLiteral("stickersCredit"));
    m_credit->setWordWrap(true);
    m_credit->setTextInteractionFlags(Qt::TextSelectableByMouse);
    creditRow->addWidget(m_credit, 1);
    auto copy = new QPushButton(tr("Copy"), m_creditBox);
    copy->setObjectName(QStringLiteral("stickersCopy"));
    copy->setToolTip(tr("Copy the credit line for your video's description"));
    connect(copy, &QPushButton::clicked, this, [this]() {
        if (auto item = m_list->currentItem()) {
            QApplication::clipboard()->setText(item->data(Qt::UserRole).toJsonObject().value("credit").toString());
            m_status->setText(tr("Copied. Paste it into your video's description."));
        }
    });
    creditRow->addWidget(copy, 0, Qt::AlignTop);
    m_creditBox->hide();
    column->addWidget(m_creditBox);
    m_status = new QLabel(body);
    m_status->setObjectName(QStringLiteral("stickersStatus"));
    m_status->setWordWrap(true);
    m_status->setProperty("studioMuted", true);
    column->addWidget(m_status);
    auto buttons = new QHBoxLayout;
    m_play = new QPushButton(tr("Play"), body);
    m_play->setObjectName(QStringLiteral("stickersPlay"));
    m_play->setToolTip(tr("Hear the sound here"));
    m_play->setEnabled(false);
    connect(m_play, &QPushButton::clicked, this, [this]() { play(); });
    m_add = new QPushButton(tr("Add at playhead"), body);
    m_add->setObjectName(QStringLiteral("stickersAdd"));
    m_add->setProperty("studioPrimary", true);
    m_add->setEnabled(false);
    connect(m_add, &QPushButton::clicked, this, [this]() { add(); });
    buttons->addWidget(m_play);
    buttons->addWidget(m_add, 1);
    column->addLayout(buttons);
    setWidget(body);

    m_searchRun = new LeToolRun(this);
    m_placeRun = new LeToolRun(this);
    m_previewRun = new LeToolRun(this);
    m_player = new QMediaPlayer(this);
    m_movie = new QMovie(this);
    m_movie->setScaledSize(QSize(kIcon, kIcon));
    connect(m_movie, &QMovie::frameChanged, this, [this]() {
        auto *item = m_list->currentItem();
        if (item && item->data(Qt::UserRole).toJsonObject().value("id").toString() == m_previewId)
            item->setIcon(QIcon(m_movie->currentPixmap()));
    });
    m_output = new QAudioOutput(this);
    m_player->setAudioOutput(m_output);
    connect(m_player, &QMediaPlayer::playbackStateChanged, this, [this](QMediaPlayer::PlaybackState s) {
        m_play->setText(s == QMediaPlayer::PlayingState ? tr("Stop") : tr("Play"));
    });
    m_debounce = new QTimer(this);
    m_debounce->setSingleShot(true);
    m_debounce->setInterval(280);
    connect(m_debounce, &QTimer::timeout, this, [this]() { search(); });
    connect(m_search, &QLineEdit::textChanged, m_debounce, qOverload<>(&QTimer::start));
    connect(m_kind, &QComboBox::currentIndexChanged, this, [this]() { search(); });
    connect(m_kind, &QComboBox::currentIndexChanged, this, [this]() {
        m_title->setVisible(m_kind->currentText() == tr("Titles & motion graphics"));
    });
    connect(m_list, &QListWidget::currentItemChanged, this, [this]() { chosen(); });
    connect(m_list, &QListWidget::itemDoubleClicked, this, [this]() { add(); });
    connect(m_list, &QListWidget::itemClicked, this, [this](QListWidgetItem *item) {
        if (item->data(Qt::UserRole).toJsonObject().value("kind").toString() == QLatin1String("sfx"))
            play();
    });
    connect(this, &QDockWidget::visibilityChanged, this, [this](bool shown) {
        if (shown && (!m_list->count() || m_kind->currentData().toString().startsWith(
                                            QStringLiteral("my_scene|"))) && !m_searchRun->running())
            search();
        if (!shown) {
            m_player->stop();
            m_movie->stop();
        }
    });
}

void StickersPanel::showKinds(const QString &kinds)
{
    int index = 0;
    for (int i = 0; i < m_kind->count(); ++i)
        if (!kinds.isEmpty() && m_kind->itemData(i).toString().section(QLatin1Char('|'), 0, 0) == kinds)
            index = i;
    if (index != m_kind->currentIndex())
        m_kind->setCurrentIndex(index); // searches again
    else if (!m_list->count() || m_kind->currentData().toString().startsWith(QStringLiteral("my_scene|")))
        search();
    m_search->setFocus();
}

void StickersPanel::search(bool more)
{
    m_debounce->stop();
    if (m_searchRun->running())
        m_searchRun->cancel();
    const QStringList choice = m_kind->currentData().toString().split(QLatin1Char('|'));
    if (choice.value(0) == QLatin1String("my_scene")) {
        QJsonArray rows;
        const QString query = m_search->text().trimmed();
        const QDir shelf(myScenesFolder());
        for (const QFileInfo &folder : shelf.entryInfoList(QDir::Dirs | QDir::NoDotAndDotDot,
                                                           QDir::Time)) {
            QFile manifest(QDir(folder.absoluteFilePath()).filePath(QStringLiteral("manifest.json")));
            if (!manifest.open(QIODevice::ReadOnly))
                continue;
            const QJsonObject saved = QJsonDocument::fromJson(manifest.readAll()).object();
            const QString name = saved.value(QStringLiteral("name")).toString();
            if (saved.value(QStringLiteral("format")).toString() != QLatin1String("letitedit-my-scene/1")
                || (!query.isEmpty() && !name.contains(query, Qt::CaseInsensitive)))
                continue;
            rows.append(QJsonObject{{"kind", "my_scene"}, {"id", saved.value("id")},
                                    {"name", name}, {"animated", true},
                                    {"thumb", QDir(folder.absoluteFilePath()).filePath(
                                         saved.value(QStringLiteral("thumbnail")).toString())},
                                    {"source", QDir(folder.absoluteFilePath()).filePath("scene.json")}});
        }
        fill(QJsonObject{{"results", rows}, {"total", rows.size()}}, false);
        if (rows.isEmpty())
            m_status->setText(tr("Scenes you save from the timeline appear here."));
        m_resultsFor = QStringLiteral("%1|%2").arg(query, m_kind->currentText());
        return;
    }
    QStringList args{QStringLiteral("--query"), m_search->text().trimmed(), QStringLiteral("--kinds"), choice.value(0),
                     QStringLiteral("--limit"), QStringLiteral("60"), QStringLiteral("--offset"),
                     QString::number(more ? m_shown : 0)};
    if (!choice.value(1).isEmpty())
        args << QStringLiteral("--animated") << choice.value(1);
    if (!choice.value(2).isEmpty())
        args << QStringLiteral("--group") << choice.value(2);
    m_status->setText(tr("Looking..."));
    m_searchRun->done = [this, more](bool ok, const QJsonObject &result, const QString &why) {
        if (!ok) {
            if (!why.isEmpty())
                m_status->setText(tr("The library couldn't be searched: %1").arg(why));
            return;
        }
        m_resultsFor = QStringLiteral("%1|%2").arg(m_search->text().trimmed(), m_kind->currentText());
        fill(result, more);
    };
    m_searchRun->start(QStringLiteral("library-search"), args);
}

void StickersPanel::fill(const QJsonObject &result, bool more)
{
    if (!more)
        m_list->clear();
    const QJsonArray rows = result.value("results").toArray();
    for (const auto &v : rows) {
        const QJsonObject e = v.toObject();
        auto item = new QListWidgetItem(iconFor(e), e.value("name").toString(), m_list);
        QString tip = e.value("name").toString();
        if (e.value("kind").toString() == QLatin1String("sfx"))
            tip += tr(" (sound, %1 s)").arg(e.value("duration_s").toDouble(), 0, 'f', 1);
        else if (e.value("animated").toBool())
            tip += tr(" (moves)");
        if (!e.value("credit").toString().isEmpty())
            tip += QLatin1Char('\n') + tr("Needs a credit line in your video's description (CC BY 4.0)");
        item->setToolTip(tip);
        item->setData(Qt::UserRole, e);
        item->setData(Qt::UserRole + 1, e.value("file").toString()); // ready to place (empty: drawn first)
    }
    m_total = result.value("total").toInt();
    m_shown = m_list->count();
    m_more->setVisible(m_shown < m_total);
    QString words;
    if (!m_total) {
        QStringList similar; // not "near": windows.h defines near as a macro
        for (const auto &s : result.value("suggestions").toArray())
            similar << s.toString();
        if (m_search->text().trimmed().isEmpty() && m_kind->currentText() == tr("Titles & motion graphics"))
            words = tr("Use Make an animated title to choose a title or motion graphic.");
        else if (m_search->text().trimmed().isEmpty() && m_kind->currentText() == tr("Transitions"))
            words = tr("New transitions are being added to this library.");
        else if (m_search->text().trimmed().isEmpty() && m_kind->currentText() == tr("Overlays & frames"))
            words = tr("No open-source overlays or frames are ready here yet.");
        else
            words = similar.isEmpty() ? tr("Nothing found in this category. Try another word or category.")
                                      : tr("Nothing found. Did you mean: %1?").arg(similar.mid(0, 4).join(QStringLiteral(", ")));
    } else if (result.value("partial").toBool()) {
        words = tr("Nothing has all of those words; these come closest.");
    } else {
        words = m_shown < m_total ? tr("Showing %1 of %2.").arg(m_shown).arg(m_total) : tr("%1 found.").arg(m_total);
    }
    m_status->setText(words);
    if (!more && m_list->count())
        m_list->setCurrentRow(0);
}

void StickersPanel::chosen()
{
    auto item = m_list->currentItem();
    const QJsonObject e = item ? item->data(Qt::UserRole).toJsonObject() : QJsonObject();
    const bool sound = e.value("kind").toString() == QLatin1String("sfx");
    m_play->setEnabled(sound);
    m_add->setEnabled(item && !m_adding);
    if (!sound)
        m_player->stop();
    m_movie->stop();
    for (int i = 0; i < m_list->count(); ++i) {
        auto *old = m_list->item(i);
        if (old->data(Qt::UserRole).toJsonObject().value("id").toString() == m_previewId)
            old->setIcon(iconFor(old->data(Qt::UserRole).toJsonObject()));
    }
    if (m_previewRun->running())
        m_previewRun->cancel();
    m_previewId = e.value("id").toString();
    if (e.value("animated").toBool()) {
        if (e.value("kind").toString() == QLatin1String("my_scene")) {
            m_movie->setFileName(e.value("thumb").toString());
            if (m_movie->isValid())
                m_movie->start();
            m_creditBox->hide();
            m_status->setText(tr("Your AI adapts this saved scene to the words at the playhead."));
            return;
        }
        const QString id = m_previewId;
        QTimer::singleShot(350, this, [this, id]() {
            if (id != m_previewId || !isVisible())
                return;
            m_previewRun->done = [this, id](bool ok, const QJsonObject &result, const QString &) {
                if (id != m_previewId)
                    return;
                if (!ok)
                    return;
                m_movie->setFileName(result.value("file").toString());
                if (m_movie->isValid()) m_movie->start();
            };
            m_previewRun->start(QStringLiteral("library-preview"), {QStringLiteral("--id"), id});
        });
    }
    const QString credit = e.value("credit").toString();
    m_creditBox->setVisible(!credit.isEmpty());
    if (!credit.isEmpty())
        m_credit->setText(tr("<b>Needs a credit line in your video's description:</b><br>%1")
                              .arg(credit.toHtmlEscaped()));
    // a picture drawn from an icon file is made ready now, so it can be dragged
    if (item && item->data(Qt::UserRole + 1).toString().isEmpty() && !m_placeRun->running() && !m_adding)
        ready(item, nullptr);
}

void StickersPanel::ready(QListWidgetItem *item, const std::function<void(const QString &)> &then)
{
    const QString id = item->data(Qt::UserRole).toJsonObject().value("id").toString();
    const QString file = item->data(Qt::UserRole + 1).toString();
    if (!file.isEmpty()) {
        if (then)
            then(file);
        return;
    }
    if (m_placeRun->running())
        m_placeRun->cancel();
    QPointer<QListWidget> list(m_list);
    m_placeRun->done = [this, id, then, list](bool ok, const QJsonObject &result, const QString &why) {
        if (!list)
            return;
        if (!ok) {
            if (!why.isEmpty())
                m_status->setText(tr("That one couldn't be made ready: %1").arg(why));
            if (then)
                then(QString());
            return;
        }
        const QString made = result.value("file").toString();
        for (int i = 0; i < m_list->count(); ++i)
            if (m_list->item(i)->data(Qt::UserRole).toJsonObject().value("id").toString() == id)
                m_list->item(i)->setData(Qt::UserRole + 1, made);
        if (then)
            then(made);
    };
    m_placeRun->start(QStringLiteral("library-place"), {QStringLiteral("--id"), id, QStringLiteral("--px"),
                                                       QStringLiteral("512")});
}

QString StickersPanel::xmlFor(const QJsonObject &e, const QString &file, QString *why)
{
    const QString kind = e.value("kind").toString();
    const bool sound = kind == QLatin1String("sfx");
    const QString group = e.value("group").toString();
    const double size = sound || kind == QLatin1String("transition") || group == QLatin1String("overlays")
                            || group == QLatin1String("motion") ? 0.0
                         : kind == QLatin1String("graphic") ? 0.6 : 0.35;
    const QString name = e.value("name").toString();
    return LeFeatures::producerXml(LeFeatures::projectCopy(m_window, file, name), sound, e.value("id").toString(),
                                   sound || e.value("animated").toBool() ? 0.0 : 3.0, size, why, name);
}

void StickersPanel::place(const QJsonObject &e, const QString &file)
{
    m_adding = false;
    chosen();
    if (file.isEmpty())
        return;
    QString why;
    const QString xml = xmlFor(e, file, &why);
    const bool sound = e.value("kind").toString() == QLatin1String("sfx");
    const QString label = sound ? tr("Add a sound: %1").arg(e.value("name").toString())
                                : tr("Add a sticker: %1").arg(e.value("name").toString());
    if (xml.isEmpty() || !LeFeatures::placeAtPlayhead(m_window, xml, sound, trackFor(e), label, &why)) {
        m_status->setText(why);
        return;
    }
    m_status->setText(e.value("credit").toString().isEmpty()
                          ? tr("Added at the playhead on the %1 track. Undo takes it back.").arg(trackFor(e))
                          : tr("Added at the playhead on the %1 track. It needs the credit line above in your video's "
                               "description.")
                                .arg(trackFor(e)));
    m_window->showStatusMessage(label + tr(" (one Undo step)"), 6);
}

void StickersPanel::add()
{
    auto item = m_list->currentItem();
    if (!item || m_adding)
        return;
    if (!m_window->multitrack()) {
        m_status->setText(tr("Put a video on the timeline first, then add stickers and sounds."));
        return;
    }
    const QJsonObject e = item->data(Qt::UserRole).toJsonObject();
    if (e.value("kind").toString() == QLatin1String("my_scene")) {
        if (MAIN.fileName().isEmpty() || !m_window->timelineDock()) {
            m_status->setText(tr("Open or save your video first."));
            return;
        }
        const int frame = qMax(0, m_window->timelineDock()->position());
        const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
        const QString request = QStringLiteral(
            "The person selected their saved My scene %1 (source: %2) for project %3 at playhead %4 seconds. "
            "Read that scene's scene.json and the words at this moment. Adapt its source to these new words, "
            "writing new custom scene code for this video, then use letitedit_code_scene(create) to put it "
            "on the Code scene track. Keep the scene's recognizable idea, but fit the entrance, exit, timing "
            "and any accompanying sound to this line. Check the result live.")
            .arg(e.value("name").toString(), e.value("source").toString(), MAIN.fileName())
            .arg(frame / fps, 0, 'f', 3);
        if (!aiChatRequest(m_window, request, tr("Use my scene: %1").arg(e.value("name").toString()))) {
            m_status->setText(tr("Your AI is busy. Try again when it has answered."));
            return;
        }
        if (auto chat = m_window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
            chat->show();
            chat->raise();
        }
        m_status->setText(tr("Your AI is adapting this scene to the words here…"));
        return;
    }
    m_adding = true;
    m_add->setEnabled(false);
    m_status->setText(tr("Getting it ready..."));
    ready(item, [this, e](const QString &file) { place(e, file); });
}

void StickersPanel::play()
{
    auto item = m_list->currentItem();
    if (!item)
        return;
    const QJsonObject e = item->data(Qt::UserRole).toJsonObject();
    if (e.value("kind").toString() != QLatin1String("sfx"))
        return;
    const QUrl url = QUrl::fromLocalFile(e.value("file").toString());
    if (m_player->playbackState() == QMediaPlayer::PlayingState && m_player->source() == url) {
        m_player->stop();
        return;
    }
    m_player->setSource(url);
    m_player->play();
}

void StickersPanel::startDrag(QListWidgetItem *item)
{
    const QString file = item->data(Qt::UserRole + 1).toString();
    const QJsonObject e = item->data(Qt::UserRole).toJsonObject();
    if (e.value("kind").toString() == QLatin1String("my_scene")) {
        auto mime = new QMimeData;
        mime->setData("application/x-letitedit-my-scene", e.value("id").toString().toUtf8());
        auto drag = new QDrag(m_list);
        drag->setMimeData(mime);
        drag->setPixmap(item->icon().pixmap(kIcon, kIcon));
        drag->exec(Qt::CopyAction);
        if (auto timeline = m_window->timelineDock()) {
            if (timeline->isVisible() && timeline->rect().contains(timeline->mapFromGlobal(QCursor::pos()))) {
                m_list->setCurrentItem(item);
                add();
            }
        }
        return;
    }
    if (file.isEmpty()) {
        m_status->setText(tr("One moment: getting it ready to drag. Or press Add at playhead."));
        return;
    }
    QString why;
    const QString xml = xmlFor(e, file, &why);
    if (xml.isEmpty()) {
        m_status->setText(why);
        return;
    }
    auto mime = new QMimeData;
    mime->setData(Mlt::XmlMimeType, xml.toUtf8());
    auto drag = new QDrag(m_list);
    drag->setMimeData(mime);
    drag->setPixmap(item->icon().pixmap(kIcon, kIcon));
    m_player->stop();
    drag->exec(Qt::CopyAction);
}

bool StickersPanel::eventFilter(QObject *watched, QEvent *event)
{
    if (watched == m_window && event->type() == QEvent::Resize && isFloating() && isVisible()) {
        // A floating library should leave a timeline drop area visible when the
        // editor is made smaller. Preserve the person's size when they enlarge it.
        const int maxWidth = qMin(1260, qMax(700, m_window->width() * 72 / 100));
        const int maxHeight = qMin(820, qMax(440, m_window->height() * 72 / 100));
        if (width() > maxWidth || height() > maxHeight)
            resize(qMin(width(), maxWidth), qMin(height(), maxHeight));
    }
    if (watched == m_list->viewport()) {
        if (event->type() == QEvent::MouseButtonPress) {
            auto me = static_cast<QMouseEvent *>(event);
            if (me->button() == Qt::LeftButton)
                m_pressAt = me->pos();
        } else if (event->type() == QEvent::MouseMove) {
            auto me = static_cast<QMouseEvent *>(event);
            if ((me->buttons() & Qt::LeftButton) && !m_pressAt.isNull()
                && (me->pos() - m_pressAt).manhattanLength() >= QApplication::startDragDistance()) {
                if (auto item = m_list->itemAt(m_pressAt)) {
                    m_pressAt = QPoint();
                    startDrag(item);
                    return true;
                }
                m_pressAt = QPoint();
            }
        } else if (event->type() == QEvent::MouseButtonRelease) {
            m_pressAt = QPoint();
        }
    }
    return QDockWidget::eventFilter(watched, event);
}

QJsonObject StickersPanel::qaState() const
{
    auto item = m_list->currentItem();
    const QJsonObject e = item ? item->data(Qt::UserRole).toJsonObject() : QJsonObject();
    return QJsonObject{{"visible", isVisible()},
                       {"query", m_search->text()},
                       {"kind", m_kind->currentText()},
                       {"shown", m_list->count()},
                       {"total", m_total},
                       {"current", e.value("id").toString()},
                       {"current_kind", e.value("kind").toString()},
                       {"current_group", e.value("group").toString()},
                       {"current_file", item ? item->data(Qt::UserRole + 1).toString() : QString()},
                       {"credit_shown", m_creditBox->isVisible()},
                       {"credit", m_creditBox->isVisible() ? m_credit->text() : QString()},
                       {"status", m_status->text()},
                       {"searching", m_searchRun->running() || m_debounce->isActive()},
                       {"preview_playing", m_movie->state() == QMovie::Running},
                       {"results_for", m_resultsFor},
                       {"adding", m_adding}};
}
