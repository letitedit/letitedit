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

#include "letitedit/player/playbackquality.h"
#include "Logger.h"
#include "letitedit/letitedit.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "settings.h"
#include "sharedframe.h"
#include "shotcut_mlt_properties.h"
#include "videowidget.h"

#include <QActionGroup>
#include <QCoreApplication>
#include <QDir>
#include <QDateTime>
#include <QDomDocument>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMenu>
#include <QPointer>
#include <QRegularExpression>
#include <QSet>
#include <QTimer>

#include <functional>
#include <memory>

namespace PlaybackQuality {
namespace {

const char kSetting[] = "playback/quality";
// Automatic's own measurement: playing at 1x dropped frames at a size, so Automatic stays below it on this PC
const char kCap[] = "playback/automaticCap";
const char kCapEvidence[] = "playback/automaticCapEvidence";

struct Entry
{
    Choice choice;
    const char *key;
    const char *object;
    const char *label;
    const char *tip;
};

const Entry kEntries[] = {
    {Choice::Automatic,
     "automatic",
     "playbackQualityAutomatic",
     QT_TRANSLATE_NOOP("PlaybackQuality", "Automatic"),
     QT_TRANSLATE_NOOP("PlaybackQuality", "The sharpest size this PC plays smoothly, from a short test it runs once")},
    {Choice::Smoothest,
     "smoothest",
     "playbackQualitySmoothest",
     QT_TRANSLATE_NOOP("PlaybackQuality", "Smoothest (540)"),
     QT_TRANSLATE_NOOP("PlaybackQuality", "Heavy footage plays at 540 on the shorter side: the lightest for a slower PC")},
    {Choice::Balanced,
     "balanced",
     "playbackQualityBalanced",
     QT_TRANSLATE_NOOP("PlaybackQuality", "Balanced (720)"),
     QT_TRANSLATE_NOOP("PlaybackQuality", "Heavy footage plays at 720 on the shorter side")},
    {Choice::Sharpest,
     "sharpest",
     "playbackQualitySharpest",
     QT_TRANSLATE_NOOP("PlaybackQuality", "Sharpest (1080)"),
     QT_TRANSLATE_NOOP("PlaybackQuality",
                       "Heavy footage plays at 1080 on the shorter side, or its own size when that is smaller")},
    {Choice::Off,
     "off",
     "playbackQualityOff",
     QT_TRANSLATE_NOOP("PlaybackQuality", "Off (play the originals)"),
     QT_TRANSLATE_NOOP("PlaybackQuality", "No working copies: every clip plays from its original file")},
};

Choice fromKey(const QString &key, Choice fallback)
{
    for (const auto &entry : kEntries)
        if (key == QLatin1String(entry.key))
            return entry.choice;
    return fallback;
}

QString keyOf(Choice choice)
{
    for (const auto &entry : kEntries)
        if (entry.choice == choice)
            return QString::fromLatin1(entry.key);
    return QStringLiteral("automatic");
}

int sizeOf(Choice choice)
{
    switch (choice) {
    case Choice::Smoothest:
        return 540;
    case Choice::Balanced:
        return 720;
    case Choice::Sharpest:
        return 1080;
    case Choice::Off:
        return 0;
    case Choice::Automatic:
        break;
    }
    return 0;
}

QString cacheFolder()
{
    if (qEnvironmentVariableIsSet("LETITEDIT_PLAYBACK_CACHE"))
        return QDir::fromNativeSeparators(qEnvironmentVariable("LETITEDIT_PLAYBACK_CACHE"));
    return QDir::fromNativeSeparators(qEnvironmentVariable("LOCALAPPDATA")) + QStringLiteral("/letitedit/playback-copies");
}

// The copy worker's PC test (--size auto), when it has run on this PC (read again at most every 2 s).
QJsonObject pcTest()
{
    static QJsonObject record;
    static QElapsedTimer read;
    if (read.isValid() && read.elapsed() < 2000)
        return record;
    read.start();
    record = {};
    QFile file(cacheFolder() + QStringLiteral("/pc-test.json"));
    if (!file.open(QIODevice::ReadOnly))
        return record;
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    record = QJsonDocument::fromJson(data).object();
    return record;
}

bool tested()
{
    const int size = pcTest().value("size").toInt();
    return size == 540 || size == 720 || size == 1080;
}

// The PC test's pick, never above a size this PC's own playback dropped frames at.
int automaticSize()
{
    const int size = tested() ? pcTest().value("size").toInt() : 540;
    const int cap = leSettings().value(kCap).toInt();
    return cap >= 540 ? qMin(size, cap) : size;
}

// The clips playing an automatic working copy now: each copy's original and the copy's size (from its receipt).
QList<QPair<QString, int>> sourcesOnCopies()
{
    QList<QPair<QString, int>> out;
    QSet<QString> seen;
    QStringList documents;
    if (MLT.producer() && MLT.producer()->is_valid())
        documents << MLT.XML();
    if (MAIN.multitrack() && MAIN.multitrack()->is_valid())
        documents << MLT.XML(MAIN.multitrack());
    if (MAIN.playlist() && MAIN.playlist()->is_valid())
        documents << MLT.XML(MAIN.playlist());
    static const QRegularExpression copyName(QStringLiteral("^[0-9a-f]{64}$"));
    for (const QString &xml : documents) {
        QDomDocument document;
        if (!document.setContent(xml))
            continue;
        for (const QString &tag : {QStringLiteral("producer"), QStringLiteral("chain")}) {
            const auto nodes = document.elementsByTagName(tag);
            for (int index = 0; index < nodes.size(); ++index) {
                QHash<QString, QString> props;
                for (auto property = nodes.at(index).firstChildElement("property"); !property.isNull();
                     property = property.nextSiblingElement("property"))
                    props.insert(property.attribute("name"), property.text());
                if (props.value(kIsProxyProperty) != QLatin1String("1"))
                    continue;
                const bool warp = props.value("mlt_service") == QLatin1String("timewarp");
                const QFileInfo copy(props.value(warp ? "warp_resource" : "resource"));
                const QString source = QDir::fromNativeSeparators(props.value(kOriginalResourceProperty));
                if (source.isEmpty() || seen.contains(source) || !copyName.match(copy.completeBaseName()).hasMatch())
                    continue;
                QFile receipt(copy.absolutePath() + QLatin1Char('/') + copy.completeBaseName() + QStringLiteral(".json"));
                if (!receipt.open(QIODevice::ReadOnly))
                    continue;
                QByteArray data = receipt.readAll();
                if (data.startsWith("\xEF\xBB\xBF"))
                    data.remove(0, 3);
                const auto record = QJsonDocument::fromJson(data).object();
                const QString recipe = record.value("recipe").toString();
                if (!recipe.startsWith(QStringLiteral("h264-gop15-")))
                    continue;
                // the receipt's own size, or the one in its recipe's name (h264-gop15-540-v3)
                int size = record.value("size").toInt();
                if (!size)
                    size = recipe.section(QLatin1Char('-'), 2, 2).toInt();
                seen.insert(source);
                out.append({source, size});
            }
        }
    }
    return out;
}

// The originals back on every clip of these sources, one source a tick so the window keeps painting; then done().
void putOriginalsBack(const QStringList &sources, std::function<void()> done)
{
    auto pending = std::make_shared<QStringList>(sources);
    auto *timer = new QTimer(&MAIN);
    timer->setInterval(50);
    QObject::connect(timer, &QTimer::timeout, &MAIN, [pending, timer, done]() {
        if (pending->isEmpty()) {
            timer->stop();
            timer->deleteLater();
            done();
            return;
        }
        const QString source = pending->takeFirst();
        if (!MLT.producer() || !QFileInfo::exists(source))
            return;
        const int position = MLT.producer()->position();
        const double speed = MLT.producer()->get_speed();
        const bool modified = MAIN.isWindowModified();
        Mlt::Producer original(MLT.profile(), source.toUtf8().constData());
        if (!original.is_valid())
            return;
        std::unique_ptr<Mlt::Producer> configured(MLT.setupNewProducer(&original));
        MLT.pause();
        // T220: a copy going in for its original (or back) changes no picture: the rendered preview keeps what it drew
        qApp->setProperty("letitedit_copy_swap", true);
        MAIN.replaceAllByHash(source, *configured, true, true);
        qApp->setProperty("letitedit_copy_swap", false);
        if (MLT.producer()) {
            MLT.producer()->seek(position);
            MLT.play(speed);
        }
        MAIN.setWindowModified(modified);
        LOG_INFO() << "playback quality: original back for" << source;
    });
    timer->start();
}

QPointer<QMenu> &menu()
{
    static QPointer<QMenu> m;
    return m;
}

void updateLabels()
{
    if (!menu())
        return;
    for (QAction *action : menu()->actions()) {
        if (action->objectName() != QLatin1String("playbackQualityAutomatic"))
            continue;
        if (sharpAhead() && displaySize() > automaticSize())
            action->setText(QCoreApplication::translate("PlaybackQuality", "Automatic (%1, sharp once drawn)")
                                .arg(automaticSize()));
        else
            action->setText(tested() ? QCoreApplication::translate("PlaybackQuality", "Automatic (%1 on this PC)")
                                           .arg(automaticSize())
                                     : QCoreApplication::translate("PlaybackQuality", "Automatic"));
    }
}

// Another size is in force: copy runs and queued copies of the old size stop, clips on copies of another size play
// their originals, then the new size's copies are looked for (watchAutomatic) and the preview is drawn again.
void apply(int newSize)
{
    emit notifier()->changing();
    QStringList sources;
    for (const auto &entry : sourcesOnCopies())
        if (newSize == 0 || entry.second != newSize)
            sources << entry.first;
    putOriginalsBack(sources, [newSize]() {
        if (newSize == 0) {
            MLT.setPreviewScale(Settings.playerPreviewScale());
            MLT.refreshConsumer();
        }
        emit notifier()->changed();
    });
}

// Automatic, measured: while it plays copies above 540 at 1x, two 8 s stretches in a row that each skip four frames
// or more step it down a size, kept for this PC (choosing Automatic again forgets it).
void watchPlayback()
{
    auto *video = qobject_cast<Mlt::VideoWidget *>(MLT.videoWidget());
    if (!video) {
        QTimer::singleShot(1000, qApp, watchPlayback);
        return;
    }
    struct Watch
    {
        int last = -1;
        int shown = 0;
        int skipped = 0;
        int bad = 0;
        QElapsedTimer clock;
    };
    static Watch watch;
    QObject::connect(video, &Mlt::VideoWidget::frameDisplayed, video, [](const SharedFrame &frame) {
        if (choice() != Choice::Automatic || automaticSize() <= 540 || !MLT.producer()
            || qAbs(MLT.producer()->get_speed() - 1.0) > 0.01 || MAIN.property("automaticProxyReady").toInt() <= 0) {
            watch.last = -1;
            return;
        }
        const int position = frame.get_position();
        if (position == watch.last)
            return;
        if (watch.last < 0 || position < watch.last || position - watch.last > 30) {
            watch.last = position;
            watch.shown = watch.skipped = 0;
            watch.clock.start();
            return;
        }
        watch.skipped += position - watch.last - 1;
        ++watch.shown;
        watch.last = position;
        if (watch.clock.elapsed() < 8000)
            return;
        watch.bad = watch.skipped >= 4 ? watch.bad + 1 : 0;
        const int shown = watch.shown, skipped = watch.skipped;
        watch.shown = watch.skipped = 0;
        watch.clock.start();
        if (watch.bad < 2)
            return;
        watch.bad = 0;
        watch.last = -1;
        const int current = automaticSize();
        const int lower = current > 720 ? 720 : 540;
        leSettings().setValue(kCap, lower);
        leSettings().setValue(kCapEvidence,
                              QStringLiteral("%1 on %2: %3 frames shown, %4 skipped in 8 s at 1x")
                                  .arg(current)
                                  .arg(QDateTime::currentDateTime().toString(Qt::ISODate))
                                  .arg(shown)
                                  .arg(skipped));
        leSettings().sync();
        LOG_INFO() << "playback quality: Automatic dropped frames at" << current << "(" << shown << "shown," << skipped
                   << "skipped in 8 s); now" << lower;
        updateLabels();
        apply(lower);
    });
}

} // namespace

Notifier *notifier()
{
    static Notifier n;
    return &n;
}

Choice choice()
{
    return fromKey(leSettings().value(kSetting).toString(), Choice::Automatic);
}

bool sharpAhead()
{
    for (const char *name : {"LETITEDIT_PLAYBACK_SHARP", "LETITEDIT_MAIN_PREVIEW", "LETITEDIT_PLAYBACK_PREVIEW"})
        if (qEnvironmentVariable(name) == QLatin1String("off"))
            return false;
    return true;
}

int size()
{
    const Choice current = choice();
    if (current == Choice::Automatic)
        return automaticSize();
    // T220: a sharper choice plays its live frames at the size this PC plays every frame of (Automatic's), and shows
    // its own size wherever the rendered preview has drawn the timeline
    return sharpAhead() && current != Choice::Off ? qMin(sizeOf(current), automaticSize()) : sizeOf(current);
}

int displaySize()
{
    const Choice current = choice();
    if (current == Choice::Off || !sharpAhead())
        return size();
    return current == Choice::Automatic ? 1080 : sizeOf(current);
}

QString workerSize()
{
    // Automatic before the PC test has run: the worker runs it; afterwards the editor's own pick (below its cap)
    return choice() == Choice::Automatic && !tested() ? QStringLiteral("auto") : QString::number(size());
}

int previewScale(int profileWidth, int profileHeight, int selected)
{
    const int shortSide = size();
    if (shortSide <= 0 || profileWidth <= 0 || profileHeight <= 0)
        return selected;
    const int scale = profileHeight > profileWidth ? qRound(double(shortSide) * profileHeight / profileWidth)
                                                   : shortSide;
    if (scale >= profileHeight) // the project's own size: no scaling but the person's own
        return selected;
    return selected > 0 ? qMin(selected, scale) : scale;
}

void setChoice(Choice wanted)
{
    const Choice before = choice();
    const int beforeSize = size();
    leSettings().setValue(kSetting, keyOf(wanted));
    leSettings().sync();
    const int newSize = size();
    LOG_INFO() << "playback quality:" << keyOf(before) << "->" << keyOf(wanted) << "size" << newSize;
    if (before == wanted && beforeSize == newSize)
        return;
    // clips on copies of another size (all of them, for Off) play their originals until the new copies are ready
    apply(newSize);
    // T220: the graphics card decodes only when the originals play (Off), and then only by the person's own setting
    MLT.configureHardwareDecoder(Settings.playerPreviewHardwareDecoder());
}

void addMenu(QMenu *settings, QAction *before)
{
    // a test window may start with a choice of its own (it keeps its own app data folder)
    if (qEnvironmentVariableIsSet("LETITEDIT_PLAYBACK_QUALITY"))
        leSettings().setValue(kSetting, keyOf(fromKey(qEnvironmentVariable("LETITEDIT_PLAYBACK_QUALITY"), Choice::Automatic)));
    auto *m = new QMenu(QCoreApplication::translate("PlaybackQuality", "Playback Quality"), settings);
    m->setObjectName(QStringLiteral("menuPlaybackQuality"));
    m->setToolTipsVisible(true);
    m->setToolTip(QCoreApplication::translate("PlaybackQuality",
                                              "How sharp heavy footage looks while it plays. Exports always use the originals."));
    auto *group = new QActionGroup(m);
    for (const auto &entry : kEntries) {
        QAction *action = m->addAction(QCoreApplication::translate("PlaybackQuality", entry.label));
        action->setObjectName(QString::fromLatin1(entry.object));
        action->setToolTip(QCoreApplication::translate("PlaybackQuality", entry.tip));
        action->setCheckable(true);
        action->setData(int(entry.choice));
        action->setChecked(choice() == entry.choice);
        group->addAction(action);
    }
    QObject::connect(group, &QActionGroup::triggered, m, [](QAction *action) {
        // choosing Automatic again forgets what this PC's playback measured: it starts from the PC test's pick
        if (Choice(action->data().toInt()) == Choice::Automatic)
            leSettings().remove(kCap);
        setChoice(Choice(action->data().toInt()));
    });
    QObject::connect(m, &QMenu::aboutToShow, m, []() { updateLabels(); });
    menu() = m;
    updateLabels();
    settings->insertMenu(before, m);
    // later: this runs while the main window is still being made (MAIN isn't there yet)
    QTimer::singleShot(2000, m, watchPlayback);
}

QJsonObject state()
{
    QJsonArray clips;
    for (const auto &entry : sourcesOnCopies())
        clips.append(QJsonObject{{"source", entry.first}, {"size", entry.second}});
    return QJsonObject{{"choice", keyOf(choice())},
                       {"size", size()},
                       {"display_size", displaySize()},
                       {"sharp_ahead", sharpAhead()},
                       {"worker_size", workerSize()},
                       {"pc_test", pcTest()},
                       {"automatic_cap", leSettings().value(kCap).toInt()},
                       {"automatic_cap_evidence", leSettings().value(kCapEvidence).toString()},
                       {"preview_size", QJsonArray{MLT.previewProfile().width(), MLT.previewProfile().height()}},
                       {"on_copies", clips}};
}

} // namespace PlaybackQuality
