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

#include "letitedit/player/previewobjects.h"

#include "actions.h"
#include "letitedit/chat/aichatpanel.h"
#include "commands/timelinecommands.h"
#include "docks/subtitlesdock.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/multitrackmodel.h"
#include "models/subtitlesmodel.h"
#include "shotcut_mlt_properties.h"

#include <QAbstractSpinBox>
#include <QAction>
#include <QApplication>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QImage>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QMenu>
#include <QPlainTextEdit>
#include <QRegularExpression>
#include <QSet>
#include <QTextEdit>
#include <QToolButton>
#include <QUndoCommand>
#include <QUndoStack>

#include <algorithm>
#include <memory>

namespace {

const char *kAffineName = "affineSizePosition";

std::unique_ptr<Mlt::Filter> findFilter(Mlt::Producer *producer, const char *shotcutName)
{
    for (int i = 0; producer && i < producer->filter_count(); ++i) {
        std::unique_ptr<Mlt::Filter> filter(producer->filter(i));
        if (filter && QString::fromUtf8(filter->get(kShotcutFilterProperty)) == QLatin1String(shotcutName))
            return filter;
    }
    return nullptr;
}

std::unique_ptr<Mlt::Filter> textFilter(Mlt::Producer *producer)
{
    return findFilter(producer, "dynamicText");
}

std::unique_ptr<Mlt::Filter> captionFilter(const QString &feed)
{
    auto tractor = MAIN.multitrack();
    for (int i = 0; tractor && i < tractor->filter_count(); ++i) {
        std::unique_ptr<Mlt::Filter> filter(tractor->filter(i));
        if (filter && filter->is_valid() && QString(filter->get("mlt_service")) == "subtitle"
            && QString::fromUtf8(filter->get("feed")) == feed)
            return filter;
    }
    return nullptr;
}

QString percentGeometry(double x, double y, double w, double h)
{
    return QStringLiteral("%1%/%2%:%3%x%4%")
        .arg(x * 100.0, 0, 'f', 2)
        .arg(y * 100.0, 0, 'f', 2)
        .arg(w * 100.0, 0, 'f', 2)
        .arg(h * 100.0, 0, 'f', 2);
}

QString pixels(double x, double y, double w, double h)
{
    return QStringLiteral("%1 %2 %3 %4 1").arg(qRound(x)).arg(qRound(y)).arg(qMax(1, qRound(w))).arg(qMax(1, qRound(h)));
}

// Places a letitedit text clip: box (fractions of the frame), text size and rotation in degrees.
// Unrotated text keeps the plain layout (the text filter's own box). Rotated text is drawn centred
// in the clip's frame and that frame is moved and turned by a Size, Position & Rotate filter, so
// the text turns around its own centre.
void placeText(Mlt::Producer &producer, double x, double y, double w, double h, int size, double angle,
               bool forPreview = false)
{
    auto text = textFilter(&producer);
    if (!text)
        return;
    const double W = MLT.profile().width(), H = MLT.profile().height();
    const double bw = w * W, bh = h * H;
    auto affine = findFilter(&producer, kAffineName);
    if (qAbs(angle) < 0.05 && !affine) {
        text->set("geometry", pixels(x * W, y * H, bw, bh).toUtf8().constData());
    } else {
        if (!affine) {
            Mlt::Filter filter(MLT.profile(), "affine");
            filter.set(kShotcutFilterProperty, kAffineName);
            filter.set("transition.fill", 0);
            filter.set("transition.distort", 0);
            filter.set("transition.halign", "center");
            filter.set("transition.valign", "middle");
            filter.set("transition.threads", 0);
            if (forPreview)
                filter.set("letitedit:preview", 1);
            producer.attach(filter);
            affine = findFilter(&producer, kAffineName);
        }
        text->set("geometry", pixels((W - bw) / 2, (H - bh) / 2, bw, bh).toUtf8().constData());
        const double cx = x * W + bw / 2, cy = y * H + bh / 2;
        if (affine) {
            affine->set("transition.rect", pixels(cx - W / 2, cy - H / 2, W, H).toUtf8().constData());
            affine->set("transition.fix_rotate_x", angle);
        }
    }
    if (size > 0)
        text->set("size", size);
}

SubtitlesDock *subtitlesDock()
{
    return MAIN.findChild<SubtitlesDock *>(QStringLiteral("SubtitlesDock"));
}

// Moving or resizing the caption box changes the caption track's burn-in filter: one undo step.
class CaptionPlaceCommand : public QUndoCommand
{
public:
    CaptionPlaceCommand(const QString &feed, const QString &geometryBefore, int sizeBefore,
                        const QString &geometryAfter, int sizeAfter)
        : m_feed(feed)
        , m_before(geometryBefore)
        , m_after(geometryAfter)
        , m_sizeBefore(sizeBefore)
        , m_sizeAfter(sizeAfter)
    {
        setText(QObject::tr("Move captions"));
    }
    void redo() override { apply(m_after, m_sizeAfter); }
    void undo() override { apply(m_before, m_sizeBefore); }

private:
    void apply(const QString &geometry, int size)
    {
        if (auto filter = captionFilter(m_feed)) {
            filter->set("geometry", geometry.toUtf8().constData());
            if (size > 0)
                filter->set("size", size);
            MLT.refreshConsumer();
        }
    }
    QString m_feed, m_before, m_after;
    int m_sizeBefore, m_sizeAfter;
};

// T99: what a click in the picture lands on

const char *kIdProp = "letitedit_ai:id";

inline quint64 clipKey(int track, int clip)
{
    return (quint64(uint(track)) << 32) | uint(clip);
}

QString clockText(int frames, bool exact = false)
{
    const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
    const double seconds = frames / fps;
    const int m = int(seconds / 60);
    return QStringLiteral("%1:%2").arg(m).arg(seconds - m * 60, exact ? 6 : 4, 'f', exact ? 3 : 1, QLatin1Char('0'));
}

QString rangeText(int start, int end)
{
    return clockText(start) + QChar(0x2013) + clockText(end);
}

QString slug(const QString &name)
{
    static const QRegularExpression other(QStringLiteral("[^a-z0-9]+"));
    QString s = name.toLower().replace(other, QStringLiteral("-"));
    while (s.startsWith(QLatin1Char('-')))
        s.remove(0, 1);
    while (s.endsWith(QLatin1Char('-')))
        s.chop(1);
    return s.isEmpty() ? QStringLiteral("t") : s;
}

bool formatHasAlpha(const QByteArray &format)
{
    return format.startsWith("yuva") || format.startsWith("rgba") || format.startsWith("bgra")
           || format.startsWith("argb") || format.startsWith("abgr") || format.startsWith("gbra")
           || format.startsWith("ya");
}

// Whether a clip can cover only part of the frame, so that its picture has to be looked at to know where it is.
bool partOfFrame(Mlt::Producer &producer, const QString &kind)
{
    if (kind != QLatin1String("video"))
        return true;
    const int index = producer.get_int("video_index");
    if (formatHasAlpha(producer.get(QStringLiteral("meta.media.%1.codec.pix_fmt").arg(index).toUtf8().constData())))
        return true;
    static const QRegularExpression moves(QStringLiteral("affine|mask|crop|alpha|shape|matte|rotoscop|lift"),
                                          QRegularExpression::CaseInsensitiveOption);
    for (int i = 0; i < producer.filter_count(); ++i) {
        std::unique_ptr<Mlt::Filter> filter(producer.filter(i));
        if (!filter || !filter->is_valid() || filter->get_int("disable"))
            continue;
        if (moves.match(QString::fromUtf8(filter->get("mlt_service"))).hasMatch()
            || moves.match(QString::fromUtf8(filter->get(kShotcutFilterProperty))).hasMatch())
            return true;
    }
    return false;
}

// The clip alone at a timeline frame, in a small picture that is transparent where the clip doesn't cover the frame.
// A fresh copy, so the player's own producers aren't touched.
QImage clipPicture(Mlt::ClipInfo &info, int position)
{
    Mlt::Producer copy(MLT.profile(), "xml-string", MLT.XML(info.producer).toUtf8().constData());
    if (!copy.is_valid())
        return QImage();
    copy.set_in_and_out(info.frame_in, info.frame_out);
    const int height = 240;
    int width = qMax(2, qRound(height * MLT.profile().dar()));
    width += width % 2;
    return MLT.image(copy, qBound(0, position - info.start, info.frame_count - 1), width, height);
}

// Where the picture isn't transparent, as fractions of the frame.
QRectF coveredArea(const QImage &image)
{
    const QImage rgba = image.convertToFormat(QImage::Format_ARGB32);
    int left = rgba.width(), right = -1, top = rgba.height(), bottom = -1;
    for (int y = 0; y < rgba.height(); ++y) {
        const QRgb *row = reinterpret_cast<const QRgb *>(rgba.constScanLine(y));
        for (int x = 0; x < rgba.width(); ++x)
            if (qAlpha(row[x]) > 16) {
                left = qMin(left, x);
                right = qMax(right, x);
                top = qMin(top, y);
                bottom = y;
            }
    }
    if (right < 0)
        return QRectF();
    return QRectF(double(left) / rgba.width(), double(top) / rgba.height(), double(right - left + 1) / rgba.width(),
                  double(bottom - top + 1) / rgba.height());
}

// A click near what's drawn counts: thin strokes and the gaps between them shouldn't need a steady hand.
bool coveredNear(const QImage &image, double x, double y)
{
    const QImage rgba = image.convertToFormat(QImage::Format_ARGB32);
    const int cx = qRound(x * rgba.width()), cy = qRound(y * rgba.height());
    const int reach = qMax(2, rgba.height() / 40);
    for (int py = qMax(0, cy - reach); py <= qMin(rgba.height() - 1, cy + reach); ++py) {
        const QRgb *row = reinterpret_cast<const QRgb *>(rgba.constScanLine(py));
        for (int px = qMax(0, cx - reach); px <= qMin(rgba.width() - 1, cx + reach); ++px)
            if (qAlpha(row[px]) > 16)
                return true;
    }
    return false;
}

void setBox(QVariantMap &item, const QRectF &box)
{
    item["x"] = box.x();
    item["y"] = box.y();
    item["w"] = box.width();
    item["h"] = box.height();
}

QRectF boxOf(const QVariantMap &item)
{
    return QRectF(item.value("x").toDouble(), item.value("y").toDouble(), item.value("w").toDouble(), item.value("h").toDouble());
}

// The words of a word-by-word caption graphic, from its recipe.
QString captionWords(const QJsonObject &recipe)
{
    QStringList words;
    for (const QJsonValue &word : recipe.value(QStringLiteral("params")).toObject().value(QStringLiteral("words")).toArray())
        words << word.toArray().at(0).toString();
    return words.join(QLatin1Char(' '));
}

QString quotedLabel(const QVariantMap &item)
{
    QString label = item.value("label").toString().simplified();
    if (label.size() > 40)
        label = label.left(39) + QChar(0x2026);
    return label.isEmpty() ? QString() : QStringLiteral(" \"%1\"").arg(label);
}

bool sameItem(const QVariantMap &a, const QVariantMap &b)
{
    return !a.isEmpty() && !b.isEmpty() && a.value("kind") == b.value("kind") && a.value("track") == b.value("track")
           && a.value("clip") == b.value("clip") && a.value("start") == b.value("start");
}

} // namespace

PreviewObjects::PreviewObjects(MainWindow *window)
    : QObject(window)
    , m_window(window)
{
    m_boxTimer.setSingleShot(true);
    m_boxTimer.setInterval(120);
    connect(&m_boxTimer, &QTimer::timeout, this, &PreviewObjects::updateBox);
    m_refreshTimer.setSingleShot(true);
    m_refreshTimer.setInterval(60);
    connect(&m_refreshTimer, &QTimer::timeout, this, &PreviewObjects::refreshTargets);
    connect(window->undoStack(), &QUndoStack::indexChanged, this, [this]() {
        if (!m_targets.isEmpty())
            m_refreshTimer.start();
    });
    connect(window, &MainWindow::producerOpened, this, [this]() {
        if (!m_targets.isEmpty())
            m_refreshTimer.start();
    });
    if (auto tl = window->timelineDock()) {
        connect(tl, &TimelineDock::selectionChanged, this, &PreviewObjects::onTimelineSelection);
        connect(tl, &TimelineDock::positionChanged, this, [this](int position) {
            if (m_targets.isEmpty() || position == m_boxPosition)
                return;
            // The box isn't drawn while the picture moves; it comes back when the playhead rests on the item.
            if (m_targets.first().value("atPlayhead").toBool()) {
                m_targets.first()["atPlayhead"] = false;
                emit targetChanged();
            }
            m_boxTimer.start();
        });
    }
    connect(qApp, &QApplication::focusChanged, this, [this](QWidget *old, QWidget *now) {
        if (!now)
            return;
        const bool aiBox = old && (old->objectName() == QLatin1String("aiTerminal") || old->objectName() == QLatin1String("aiChatInput"));
        m_returnFocus = aiBox && now->inherits("Mlt::VideoWidget") ? old : nullptr;
    });
    setupBar();
}

// A row for the player's top line, where a live scene can't cover it and a filter's overlay can't replace it. It says
// what's selected and offers what goes with it.
void PreviewObjects::setupBar()
{
    m_bar = new QWidget;
    m_bar->setObjectName(QStringLiteral("playerSelectionBar"));
    auto layout = new QHBoxLayout(m_bar);
    layout->setContentsMargins(0, 0, 0, 0);
    layout->setSpacing(6);
    m_barLabel = new QLabel(m_bar);
    m_barLabel->setObjectName(QStringLiteral("playerSelectionLabel"));
    layout->addWidget(m_barLabel);
    m_barChoose = new QToolButton(m_bar);
    m_barChoose->setObjectName(QStringLiteral("playerSelectionChoose"));
    m_barChoose->setText(tr("Choose item here"));
    m_barChoose->setToolTip(tr("Everything at the point you clicked, topmost first"));
    m_barChoose->setPopupMode(QToolButton::InstantPopup);
    m_barChoose->setFocusPolicy(Qt::NoFocus);
    auto menu = new QMenu(m_barChoose);
    m_barChoose->setMenu(menu);
    connect(menu, &QMenu::aboutToShow, this, [this, menu]() {
        menu->clear();
        const QVariantMap now = target();
        for (int i = 0; i < m_choices.size(); ++i) {
            const QVariantMap item = m_choices[i].toMap();
            auto action = menu->addAction(item.value("kindLabel").toString() + quotedLabel(item));
            action->setCheckable(true);
            action->setChecked(sameItem(item, now));
            connect(action, &QAction::triggered, this, [this, i]() { choose(i); });
        }
    });
    layout->addWidget(m_barChoose);
    auto ask = new QToolButton(m_bar);
    ask->setObjectName(QStringLiteral("playerSelectionAsk"));
    ask->setText(tr("Ask AI"));
    ask->setToolTip(tr("Open your AI with this selected, so the request is about it"));
    ask->setFocusPolicy(Qt::NoFocus);
    connect(ask, &QToolButton::clicked, this, &PreviewObjects::askAiRequested);
    layout->addWidget(ask);
    auto clear = new QToolButton(m_bar);
    clear->setObjectName(QStringLiteral("playerSelectionClear"));
    clear->setText(tr("Clear"));
    clear->setToolTip(tr("Clear the selection (Esc)"));
    clear->setFocusPolicy(Qt::NoFocus);
    connect(clear, &QToolButton::clicked, this, &PreviewObjects::clearTarget);
    layout->addWidget(clear);
    m_bar->hide();
}

void PreviewObjects::updateBar()
{
    if (!m_bar)
        return;
    m_bar->setVisible(!m_targets.isEmpty());
    const QString words = chipText();
    m_barLabel->setText(m_barLabel->fontMetrics().elidedText(words, Qt::ElideMiddle, 340)); // never wider than a laptop has room for
    m_barLabel->setToolTip(words);
    m_barChoose->setVisible(m_choices.size() > 1);
}

QString PreviewObjects::chipText() const
{
    if (m_targets.isEmpty())
        return QString();
    const QVariantMap first = m_targets.first();
    if (first.value("gone").toBool())
        return tr("%1 is gone. Select it again").arg(first.value("kindLabel").toString());
    if (m_targets.size() > 1)
        return tr("%1 items selected").arg(m_targets.size());
    return first.value("kindLabel").toString() + quotedLabel(first) + QStringLiteral(" ") + QChar(0x00b7) + QStringLiteral(" ")
           + first.value("range").toString();
}

// The same ids letitedit_timeline_read gives (edit_script._ids_for): the stored id, else a positional one.
QHash<quint64, QString> PreviewObjects::stableIds() const
{
    QHash<quint64, QString> ids;
    auto tl = m_window->timelineDock();
    if (!tl || !tl->model() || !tl->model()->tractor())
        return ids;
    auto model = tl->model();
    // The file's order is the engine's, not the timeline's.
    QList<QPair<int, int>> order;
    for (int t = 0; t < model->trackList().size(); ++t)
        order << qMakePair(model->trackList()[t].mlt_index, t);
    std::sort(order.begin(), order.end());
    QSet<QString> stored, used;
    QHash<QString, int> seen;
    for (const auto &entry : order) {
        std::unique_ptr<Mlt::Producer> track(model->tractor()->track(entry.first));
        Mlt::Playlist playlist(*track);
        for (int c = 0; c < playlist.count(); ++c) {
            std::unique_ptr<Mlt::ClipInfo> info(playlist.clip_info(c));
            if (info && info->producer && !info->cut->is_blank()) {
                Mlt::Producer parent(info->producer->parent());
                const QString id = QString::fromUtf8(parent.get(kIdProp));
                if (!id.isEmpty())
                    stored << id;
            }
        }
    }
    for (const auto &entry : order) {
        std::unique_ptr<Mlt::Producer> track(model->tractor()->track(entry.first));
        Mlt::Playlist playlist(*track);
        QString name = QString::fromUtf8(playlist.get(kTrackNameProperty));
        if (name.isEmpty())
            name = QString::fromUtf8(playlist.get("id"));
        const int repeat = ++seen[name];
        if (repeat > 1)
            name = QStringLiteral("%1 (%2)").arg(name).arg(repeat);
        int n = 0;
        for (int c = 0; c < playlist.count(); ++c) {
            std::unique_ptr<Mlt::ClipInfo> info(playlist.clip_info(c));
            if (!info || !info->producer || info->cut->is_blank())
                continue;
            if (info->producer->get(kShotcutTransitionProperty)) {
                ids.insert(clipKey(entry.second, c), QStringLiteral("%1-transition-%2").arg(slug(name)).arg(c));
                continue;
            }
            ++n;
            Mlt::Producer parent(info->producer->parent());
            const QString own = QString::fromUtf8(parent.get(kIdProp));
            const QString base = !own.isEmpty() ? own : QStringLiteral("%1-%2").arg(slug(name)).arg(n, 3, 10, QLatin1Char('0'));
            QString id = base;
            int suffix = 1;
            while (used.contains(id) || (own.isEmpty() && stored.contains(id))) {
                ++suffix;
                id = suffix <= 26 ? base + QChar(96 + suffix) : QStringLiteral("%1-%2").arg(base).arg(suffix);
            }
            used << id;
            ids.insert(clipKey(entry.second, c), id);
        }
    }
    return ids;
}

// A clip as a selectable item, without its place in the picture. Empty for what can't be selected.
QVariantMap PreviewObjects::clipItem(int track, int clip, const QHash<quint64, QString> &ids) const
{
    auto model = m_window->timelineDock()->model();
    auto info = model->getClipInfo(track, clip);
    if (!info || !info->producer || !info->producer->is_valid() || info->cut->is_blank()
        || info->producer->get(kShotcutTransitionProperty) || info->producer->get_int("meta.fx_cut"))
        return QVariantMap();
    Mlt::Producer parent(info->producer->parent());
    const QString resource = QString::fromUtf8(info->resource ? info->resource : parent.get("resource"));
    QString kind = QStringLiteral("video"), kindLabel = tr("Video clip");
    QString label = QString::fromUtf8(parent.get(kShotcutCaptionProperty));
    const char *graphic = info->producer->get("letitedit_ai:graphic");
    const char *scene = info->producer->get("letitedit_ai:code_scene");
    const QString service = QString::fromUtf8(parent.get("mlt_service"));
    static const QRegularExpression stills(QStringLiteral(R"(\.(png|jpe?g|bmp|gif|tiff?|webp|heic)$)"),
                                           QRegularExpression::CaseInsensitiveOption);
    if (scene && *scene) {
        kind = QStringLiteral("scene");
        kindLabel = tr("Scene");
    } else if (info->producer->get_int("shotcut:studioText")) {
        kind = QStringLiteral("text");
        kindLabel = tr("Text");
    } else if (graphic && *graphic) {
        const QJsonObject recipe = QJsonDocument::fromJson(graphic).object();
        if (recipe.value(QStringLiteral("template")).toString() == QLatin1String("word_captions")) {
            kind = QStringLiteral("caption");
            kindLabel = tr("Caption");
            label = captionWords(recipe);
        } else {
            kind = QStringLiteral("graphic");
            kindLabel = tr("Graphic");
        }
    } else if (service.startsWith(QLatin1String("qimage")) || service.startsWith(QLatin1String("pixbuf"))
               || stills.match(resource).hasMatch()) {
        kind = QStringLiteral("picture");
        kindLabel = tr("Picture");
    }
    if (label.isEmpty() && !resource.isEmpty())
        label = QFileInfo(resource).fileName();
    const QString id = ids.value(clipKey(track, clip));
    return QVariantMap{{"kind", kind},
                       {"kindLabel", kindLabel},
                       {"label", label},
                       {"id", id},
                       {"storedId", QString::fromUtf8(parent.get(kIdProp)) == id},
                       {"uuid", MLT.ensureHasUuid(*info->producer).toString()},
                       {"resource", resource},
                       {"track", track},
                       {"clip", clip},
                       {"trackName", model->index(track).data(MultitrackModel::NameRole).toString()},
                       {"start", info->start},
                       {"end", info->start + info->frame_count},
                       {"range", rangeText(info->start, info->start + info->frame_count)},
                       {"grab", false}};
}

QVariantList PreviewObjects::itemsAt(double x, double y)
{
    QVariantList list;
    auto tl = m_window->timelineDock();
    if (!tl || !m_window->isMultitrackValid() || !MLT.isMultitrack() || x < 0 || y < 0 || x > 1 || y > 1)
        return list;
    auto model = tl->model();
    const int position = tl->position();
    const auto ids = stableIds();
    const QVariantList grabbable = objectsAtPlayhead();
    const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
    // Burned-in captions are drawn over the finished picture, so they come first.
    for (const QVariant &v : grabbable) {
        QVariantMap o = v.toMap();
        if (o.value("kind") != QLatin1String("caption") || !boxOf(o).contains(x, y))
            continue;
        const auto &cue = tl->subtitlesModel()->getItem(o.value("track").toInt(), o.value("item").toInt());
        const int start = qRound(cue.start * fps / 1000.0), end = qRound(cue.end * fps / 1000.0);
        o["kindLabel"] = tr("Caption");
        o["cue"] = true;
        o["grab"] = true;
        o["start"] = start;
        o["end"] = end;
        o["cueStartMs"] = qint64(cue.start);
        o["cueText"] = o.value("text");
        o["id"] = QStringLiteral("cue on caption track \"%1\"").arg(o.value("trackName").toString());
        o["range"] = rangeText(start, end);
        list << o;
    }
    for (int t = 0; t < model->trackList().size(); ++t) {
        if (model->trackList()[t].type != VideoTrackType)
            continue;
        const QModelIndex track = model->index(t);
        if (track.data(MultitrackModel::IsHiddenRole).toBool() || track.data(MultitrackModel::IsLockedRole).toBool())
            continue;
        int clip = model->clipIndex(t, position);
        if (clip < 0)
            continue;
        auto info = model->getClipInfo(t, clip);
        if (info && info->producer && info->producer->get(kShotcutTransitionProperty)) // a dissolve: the clip coming in
            info = model->getClipInfo(t, ++clip);
        if (!info)
            continue;
        QVariantMap item = clipItem(t, clip, ids);
        if (item.isEmpty())
            continue;
        const QString kind = item.value("kind").toString();
        if (kind == QLatin1String("text")) {
            for (const QVariant &v : grabbable) {
                const QVariantMap o = v.toMap();
                if (o.value("kind") == QLatin1String("text") && o.value("track").toInt() == t
                    && o.value("clip").toInt() == clip && boxOf(o).contains(x, y)) {
                    for (auto it = o.constBegin(); it != o.constEnd(); ++it)
                        if (it.key() != QLatin1String("label") || !it.value().toString().isEmpty())
                            item[it.key()] = it.value();
                    item["grab"] = true;
                    list << item;
                }
            }
            continue;
        }
        QRectF box(0, 0, 1, 1);
        if (kind != QLatin1String("scene") && partOfFrame(*info->producer, kind)) {
            const QImage picture = clipPicture(*info, position);
            if (!picture.isNull()) {
                box = coveredArea(picture);
                if (box.isEmpty())
                    continue;
                if (kind == QLatin1String("caption") ? !box.contains(x, y) : !coveredNear(picture, x, y))
                    continue;
            }
        }
        setBox(item, box);
        list << item;
    }
    return list;
}

QVariantMap PreviewObjects::pickAt(double x, double y)
{
    if (!m_window->isMultitrackValid() || !MLT.isMultitrack())
        return QVariantMap();
    if (m_returnFocus) { // queued: the press is still being delivered
        QPointer<QWidget> box = m_returnFocus;
        m_returnFocus = nullptr;
        QTimer::singleShot(0, this, [box]() {
            if (box)
                box->setFocus();
        });
    }
    const QVariantList items = itemsAt(x, y);
    if (items.isEmpty()) {
        clearTarget();
        return QVariantMap();
    }
    QVariantMap top = items.first().toMap();
    const bool same = sameItem(top, target());
    if (!MLT.isPaused())
        if (auto pause = Actions["playerPauseAction"])
            pause->trigger();
    top["atPlayhead"] = true;
    setTargets({top}, items);
    selectInTimeline(top);
    top["wasTarget"] = same;
    return top;
}

void PreviewObjects::choose(int index)
{
    if (index < 0 || index >= m_choices.size())
        return;
    QVariantMap item = m_choices[index].toMap();
    item["atPlayhead"] = true;
    setTargets({item}, m_choices);
    selectInTimeline(item);
}

void PreviewObjects::clearTarget()
{
    const bool had = !m_targets.isEmpty();
    setTargets({}, {});
    if (!had)
        return;
    m_syncing = true;
    if (auto tl = m_window->timelineDock())
        if (!tl->selection().isEmpty())
            tl->setSelection();
    m_syncing = false;
}

bool PreviewObjects::escapePressed()
{
    if (m_targets.isEmpty())
        return false;
    auto focus = QApplication::focusWidget();
    auto focusObject = QApplication::focusObject();
    auto plain = qobject_cast<QPlainTextEdit *>(focus);
    // The AI's own box with nothing in it isn't typing: the chip Esc clears is right above it.
    const bool emptyAiBox = plain && plain->objectName() == QLatin1String("aiChatInput") && plain->toPlainText().isEmpty();
    const bool typing = qobject_cast<QLineEdit *>(focus) || (plain && !emptyAiBox) || qobject_cast<QTextEdit *>(focus)
                        || qobject_cast<QAbstractSpinBox *>(focus)
                        || (focusObject && (focusObject->inherits("QQuickTextInput") || focusObject->inherits("QQuickTextEdit")));
    if (typing)
        return false;
    clearTarget();
    return true;
}

void PreviewObjects::setTargets(const QList<QVariantMap> &targets, const QVariantList &choices)
{
    m_targets = targets;
    m_choices = choices;
    m_project = m_window->fileName();
    if (auto tl = m_window->timelineDock())
        m_boxPosition = tl->position();
    updateBar();
    emit targetChanged();
}

void PreviewObjects::selectInTimeline(const QVariantMap &item)
{
    m_syncing = true;
    if (item.value("cue").toBool()) {
        select(item);
    } else if (auto tl = m_window->timelineDock()) {
        const QList<QPoint> wanted{QPoint(item.value("clip").toInt(), item.value("track").toInt())};
        if (tl->selection() != wanted)
            tl->setSelection(wanted);
    }
    m_syncing = false;
}

// The other way round: a clip chosen on the timeline is the selection too. Nothing selected there says nothing: the
// timeline clears its selection for its own reasons, and a request must never lose its target by accident.
void PreviewObjects::onTimelineSelection()
{
    if (m_syncing)
        return;
    auto tl = m_window->timelineDock();
    if (!tl || tl->selection().isEmpty())
        return;
    const auto ids = stableIds();
    QList<QVariantMap> items;
    for (const QPoint &p : tl->selection()) {
        const QVariantMap item = clipItem(p.y(), p.x(), ids);
        if (!item.isEmpty())
            items << item;
    }
    if (items.isEmpty())
        return;
    if (items.size() == m_targets.size()) {
        bool same = true;
        for (int i = 0; i < items.size(); ++i)
            same = same && items[i].value("id") == m_targets[i].value("id");
        if (same)
            return;
    }
    setTargets(items, {});
    m_boxPosition = -1;
    m_boxTimer.start();
}

// Finds the item again after a change: by its stored id, else the clip it was, else (a clip that never had a stored id)
// by the positional id still naming the same file. A caption cue is found by its words, nearest to where it was.
// False: it's gone.
bool PreviewObjects::resolve(QVariantMap &item, const QHash<quint64, QString> &ids) const
{
    auto tl = m_window->timelineDock();
    if (!tl || !tl->model())
        return false;
    auto model = tl->model();
    if (item.value("cue").toBool()) {
        auto subtitles = tl->subtitlesModel();
        const QString name = item.value("trackName").toString();
        const QString text = item.value("cueText").toString();
        const qint64 was = item.value("cueStartMs").toLongLong();
        const double fps = MLT.profile().fps() > 0 ? MLT.profile().fps() : 30.0;
        for (int t = 0; t < subtitles->trackCount(); ++t) {
            if (subtitles->trackName(t) != name)
                continue;
            int best = -1;
            qint64 bestGap = 0;
            for (int i = 0; i < subtitles->itemCount(t); ++i) {
                const auto &cue = subtitles->getItem(t, i);
                const qint64 gap = qAbs(qint64(cue.start) - was);
                if (QString::fromStdString(cue.text) == text && (best < 0 || gap < bestGap)) {
                    best = i;
                    bestGap = gap;
                }
            }
            if (best < 0)
                return false;
            const auto &cue = subtitles->getItem(t, best);
            const int start = qRound(cue.start * fps / 1000.0), end = qRound(cue.end * fps / 1000.0);
            item["track"] = t;
            item["clip"] = best;
            item["item"] = best;
            item["start"] = start;
            item["end"] = end;
            item["cueStartMs"] = qint64(cue.start);
            item["range"] = rangeText(start, end);
            return true;
        }
        return false;
    }
    const QString id = item.value("id").toString();
    const QString uuid = item.value("uuid").toString();
    int foundTrack = -1, foundClip = -1;
    for (auto it = ids.constBegin(); it != ids.constEnd() && foundTrack < 0; ++it) {
        if (it.value() != id)
            continue;
        const int t = int(it.key() >> 32), c = int(it.key() & 0xffffffffu);
        auto info = model->getClipInfo(t, c);
        if (item.value("storedId").toBool()
            || (info && info->resource && QString::fromUtf8(info->resource) == item.value("resource").toString())) {
            foundTrack = t;
            foundClip = c;
        }
    }
    for (auto it = ids.constBegin(); it != ids.constEnd() && foundTrack < 0; ++it) {
        const int t = int(it.key() >> 32), c = int(it.key() & 0xffffffffu);
        auto info = model->getClipInfo(t, c);
        if (info && info->producer && MLT.uuid(*info->producer).toString() == uuid) {
            foundTrack = t;
            foundClip = c;
        }
    }
    if (foundTrack < 0)
        return false;
    const QVariantMap fresh = clipItem(foundTrack, foundClip, ids);
    if (fresh.isEmpty() || fresh.value("kind") != item.value("kind")) // the same place, but a different thing now
        return false;
    for (auto it = fresh.constBegin(); it != fresh.constEnd(); ++it)
        if (it.key() != QLatin1String("grab"))
            item[it.key()] = it.value();
    return true;
}

void PreviewObjects::refreshTargets()
{
    if (m_targets.isEmpty())
        return;
    if (m_window->fileName() != m_project) { // another project: that selection means nothing here
        setTargets({}, {});
        return;
    }
    const auto ids = stableIds();
    for (QVariantMap &item : m_targets)
        item["gone"] = !resolve(item, ids);
    m_choices.clear();
    updateBar();
    updateBox();
    emit targetChanged();
}

// Where the selected item is in the picture now. Only at rest, since looking can mean drawing the clip's frame.
void PreviewObjects::updateBox()
{
    if (m_targets.isEmpty())
        return;
    auto tl = m_window->timelineDock();
    if (!tl || !MLT.isMultitrack())
        return;
    if (!MLT.isPaused()) {
        m_boxTimer.start();
        return;
    }
    QVariantMap &item = m_targets.first();
    const int position = tl->position();
    m_boxPosition = position;
    bool here = m_targets.size() == 1 && !item.value("gone").toBool() && position >= item.value("start").toInt()
                && position < item.value("end").toInt();
    if (here) {
        const QString kind = item.value("kind").toString();
        if (item.value("cue").toBool() || kind == QLatin1String("text")) {
            here = false;
            for (const QVariant &v : objectsAtPlayhead()) {
                const QVariantMap o = v.toMap();
                if (o.value("kind") == kind && o.value("track") == item.value("track") && o.value("clip") == item.value("clip")) {
                    for (const char *key : {"x", "y", "w", "h", "size", "angle", "geometry"})
                        if (o.contains(key))
                            item[key] = o.value(key);
                    here = true;
                }
            }
        } else if (kind == QLatin1String("scene")) {
            setBox(item, QRectF(0, 0, 1, 1));
        } else if (auto info = tl->model()->getClipInfo(item.value("track").toInt(), item.value("clip").toInt())) {
            QRectF box(0, 0, 1, 1);
            if (info->producer && partOfFrame(*info->producer, kind)) {
                const QImage picture = clipPicture(*info, position);
                if (!picture.isNull())
                    box = coveredArea(picture);
            }
            here = !box.isEmpty();
            setBox(item, box);
        }
    }
    item["atPlayhead"] = here;
    emit targetChanged();
}

QString PreviewObjects::requestLine(QString *problem)
{
    if (m_targets.isEmpty())
        return QString();
    refreshTargets();
    if (m_targets.isEmpty())
        return QString();
    QStringList parts;
    for (const QVariantMap &item : m_targets) {
        if (item.value("gone").toBool()) {
            if (problem)
                *problem = tr("The %1 you selected isn't there any more. Click it again in the video, or press Clear to "
                              "ask about the whole video.").arg(item.value("kindLabel").toString().toLower());
            return QString();
        }
        const QString range = clockText(item.value("start").toInt(), true) + QStringLiteral(" to ")
                              + clockText(item.value("end").toInt(), true);
        QString words = item.value("kindLabel").toString().toLower();
        const QString label = item.value("label").toString().simplified();
        if (!label.isEmpty())
            words += QStringLiteral(" \"%1\"").arg(label);
        if (item.value("cue").toBool())
            words += QStringLiteral(" (a %1, %2; every cue on that track shares one style)").arg(item.value("id").toString(), range);
        else
            words += QStringLiteral(" (id %1 on track %2, %3)").arg(item.value("id").toString(), item.value("trackName").toString(), range);
        parts << words;
    }
    const QString which = m_targets.size() > 1 ? QStringLiteral("these") : QStringLiteral("it");
    return QStringLiteral("target: on this project's timeline the person selected %1, and this request is about %2. Project "
                          "revision %3. Use the letitedit tools on that id (letitedit_timeline_read, letitedit_timeline_apply); "
                          "change only %2 unless they say otherwise.")
        .arg(parts.join(QStringLiteral("; ")), which, aiBridgeRevision());
}

QVariantList PreviewObjects::objectsAtPlayhead()
{
    QVariantList list;
    auto tl = m_window->timelineDock();
    if (!tl || !m_window->isMultitrackValid())
        return list;
    auto model = tl->model();
    const double W = MLT.profile().width(), H = MLT.profile().height();
    const int position = tl->position();
    for (int t = 0; t < model->trackList().size(); ++t) {
        if (model->trackList()[t].type != VideoTrackType)
            continue;
        const int clip = model->clipIndex(t, position);
        if (clip < 0)
            continue;
        auto info = model->getClipInfo(t, clip);
        if (!info || !info->producer || !info->producer->get_int("shotcut:studioText"))
            continue;
        auto filter = textFilter(info->producer);
        if (!filter)
            continue;
        mlt_rect r = filter->anim_get_rect("geometry", 0);
        double angle = 0.0;
        auto affine = findFilter(info->producer, kAffineName);
        if (affine) {
            const mlt_rect a = affine->anim_get_rect("transition.rect", 0);
            r.x += a.x;
            r.y += a.y;
            angle = affine->get_double("transition.fix_rotate_x");
        }
        list << QVariantMap{{"kind", "text"},
                            {"track", t},
                            {"clip", clip},
                            {"x", r.x / W},
                            {"y", r.y / H},
                            {"w", r.w / W},
                            {"h", r.h / H},
                            {"angle", angle},
                            {"size", filter->get_int("size")},
                            {"label", QString::fromUtf8(info->producer->get(kShotcutCaptionProperty))}};
    }
    if (auto dock = subtitlesDock()) {
        for (const auto &v : dock->captionsAtPlayhead()) {
            auto c = v.toMap();
            if (!c.value("burnedIn").toBool())
                continue;
            auto filter = captionFilter(c.value("trackName").toString());
            c["kind"] = "caption";
            c["clip"] = c.value("item");
            c["angle"] = 0.0;
            c["size"] = filter ? filter->get_int("size") : 0;
            c["geometry"] = filter ? QString::fromUtf8(filter->get("geometry")) : QString();
            c["label"] = c.value("text");
            list << c;
        }
    }
    return list;
}

QVariantList PreviewObjects::allObjects() const
{
    QVariantList list;
    auto tl = m_window->timelineDock();
    if (!tl || !m_window->isMultitrackValid())
        return list;
    auto model = tl->model();
    const double W = MLT.profile().width(), H = MLT.profile().height();
    for (int t = 0; t < model->trackList().size(); ++t) {
        if (model->trackList()[t].type != VideoTrackType)
            continue;
        std::unique_ptr<Mlt::Producer> track(model->tractor()->track(model->trackList()[t].mlt_index));
        if (!track || !track->is_valid())
            continue;
        Mlt::Playlist playlist(*track);
        for (int c = 0; c < playlist.count(); ++c) {
            auto info = model->getClipInfo(t, c);
            if (!info || !info->producer || !info->producer->get_int("shotcut:studioText"))
                continue;
            auto filter = textFilter(info->producer);
            if (!filter)
                continue;
            mlt_rect r = filter->anim_get_rect("geometry", 0);
            if (auto affine = findFilter(info->producer, kAffineName)) {
                const mlt_rect a = affine->anim_get_rect("transition.rect", 0);
                r.x += a.x;
                r.y += a.y;
            }
            list << QVariantMap{{"kind", "text"},
                                {"track", t},
                                {"clip", c},
                                {"x", r.x / W},
                                {"y", r.y / H},
                                {"w", r.w / W},
                                {"h", r.h / H},
                                {"start", info->start},
                                {"label", QString::fromUtf8(info->producer->get(kShotcutCaptionProperty))}};
        }
    }
    auto tractor = MAIN.multitrack();
    for (int i = 0; tractor && i < tractor->filter_count(); ++i) {
        std::unique_ptr<Mlt::Filter> filter(tractor->filter(i));
        if (!filter || !filter->is_valid() || QString(filter->get("mlt_service")) != "subtitle")
            continue;
        list << QVariantMap{{"kind", "caption"},
                            {"feed", QString::fromUtf8(filter->get("feed"))},
                            {"geometry", QString::fromUtf8(filter->get("geometry"))},
                            {"valign", QString::fromUtf8(filter->get("valign"))},
                            {"size", filter->get_int("size")},
                            {"label", tr("Captions")}};
    }
    return list;
}

void PreviewObjects::select(const QVariantMap &object)
{
    const int track = object.value("track").toInt();
    const int clip = object.value("clip").toInt();
    if (object.value("kind") == "text") {
        m_window->timelineDock()->setSelection({QPoint(clip, track)});
    } else if (auto dock = subtitlesDock()) {
        if (!m_window->timelineDock()->selection().isEmpty())
            m_window->timelineDock()->setSelection();
        dock->selectCaption(track, clip);
    }
}

void PreviewObjects::preview(const QVariantMap &object, double x, double y, double w, double h, double scale,
                             double angle)
{
    const int size = qRound(object.value("size").toInt() * scale);
    if (object.value("kind") == "text") {
        auto info = m_window->timelineDock()->model()->getClipInfo(object.value("track").toInt(),
                                                                  object.value("clip").toInt());
        if (!info || !info->producer)
            return;
        placeText(*info->producer, x, y, w, h, size, angle, true);
    } else if (auto filter = captionFilter(object.value("trackName").toString())) {
        filter->set("geometry", percentGeometry(x, y, w, h).toUtf8().constData());
        if (size > 0)
            filter->set("size", size);
    }
    MLT.refreshConsumer();
}

void PreviewObjects::commit(const QVariantMap &object, double x, double y, double w, double h, double scale,
                            double angle)
{
    const int sizeBefore = object.value("size").toInt();
    const int sizeAfter = qRound(sizeBefore * scale);
    if (object.value("kind") == "text") {
        auto tl = m_window->timelineDock();
        const int track = object.value("track").toInt();
        const int clip = object.value("clip").toInt();
        if (tl->isTrackLocked(track))
            return;
        auto info = tl->model()->getClipInfo(track, clip);
        if (!info || !info->producer)
            return;
        // Put the live preview back so the undo step records the real "before". A rotate filter
        // added only for the preview is taken off again.
        auto affine = findFilter(info->producer, kAffineName);
        if (affine && affine->get_int("letitedit:preview"))
            info->producer->detach(*affine);
        placeText(*info->producer, object.value("x").toDouble(), object.value("y").toDouble(),
                  object.value("w").toDouble(), object.value("h").toDouble(), sizeBefore,
                  object.value("angle").toDouble());
        Mlt::Producer clone(MLT.profile(), "xml-string", MLT.XML(info->producer).toUtf8().constData());
        clone.set_in_and_out(info->frame_in, info->frame_out);
        placeText(clone, x, y, w, h, sizeAfter, angle);
        auto command = new Timeline::UpdateCommand(*tl, track, clip, info->start);
        command->setXmlAfter(MLT.XML(&clone));
        command->setText(qAbs(angle - object.value("angle").toDouble()) > 0.05 ? tr("Rotate text") : tr("Move text"));
        tl->setSelection();
        m_window->undoStack()->push(command);
        tl->setSelection({QPoint(clip, track)});
    } else {
        const QString feed = object.value("trackName").toString();
        const QByteArray geometryBefore = object.value("geometry").toString().toUtf8();
        if (auto live = captionFilter(feed)) {
            live->set("geometry", geometryBefore.constData());
            if (sizeBefore > 0)
                live->set("size", sizeBefore);
        }
        m_window->undoStack()->push(new CaptionPlaceCommand(feed, QString::fromUtf8(geometryBefore), sizeBefore,
                                                            percentGeometry(x, y, w, h), sizeAfter));
    }
}

void PreviewObjects::edit(const QVariantMap &object)
{
    select(object);
    if (object.value("kind") == "text") {
        if (auto action = m_window->findChild<QAction *>(QStringLiteral("focuscaptionsAction")))
            action->trigger();
    } else if (auto dock = subtitlesDock()) {
        dock->editCaption(object.value("track").toInt(), object.value("clip").toInt());
    }
}

void PreviewObjects::remove(const QVariantMap &object)
{
    if (object.value("kind") == "text") {
        auto tl = m_window->timelineDock();
        const int track = object.value("track").toInt();
        if (!tl->isTrackLocked(track)) {
            tl->setSelection();
            tl->lift(track, object.value("clip").toInt());
        }
    } else {
        select(object);
        if (auto action = Actions["subtitleRemoveItemAction"])
            action->trigger();
    }
}
