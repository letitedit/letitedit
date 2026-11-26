/*
 * Copyright (c) 2020-2026 Meltytech, LLC
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

#include "proxymanager.h"

#include "Logger.h"
#include "dialogs/longuitask.h"
#include "jobqueue.h"
#include "jobs/ffmpegjob.h"
#include "jobs/qimagejob.h"
#include "mltcontroller.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"
#include "util.h"
#include "mainwindow.h"
#include "player.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/player/copyswap.h"
#include "letitedit/player/playbackquality.h"
#include "letitedit/player/renderedpreview.h"

#include <QDomDocument>
#include <QJsonDocument>
#include <QJsonArray>
#include <QProcess>
#include <QTimer>
#include <QTemporaryFile>
#include <QUndoStack>

#include <QFile>
#include <QImageReader>
#include <QObject>
#include <QVector>
#include <QXmlStreamReader>
#include <QXmlStreamWriter>

#include <utime.h>

static constexpr char kProxySubfolder[] = "proxies";

QString ProxyManager::originalXML(Mlt::Service *producer)
{
    QString xml = MLT.XML(producer, true);
    filterXML(xml, {});
    return xml;
}

void ProxyManager::preserveAutomaticProperties(Mlt::Producer &destination, Mlt::Producer &source)
{
    for (int index = 0; index < source.count(); ++index) {
        const QString name = QString::fromUtf8(source.get_name(index));
        // shotcut_ai:* is letitedit_ai:* in projects saved before the 29 Oct rename (the tools read both): a clip's
        // id and notes stay on it when its copy goes in (T356b)
        if ((name.startsWith("letitedit_ai:") || name.startsWith("shotcut_ai:") || name.startsWith("shotcut:")
             || name == kUuidProperty)
            && name != kIsProxyProperty && name != kOriginalResourceProperty)
            destination.set(source.get_name(index), source.get(index));
    }
}

bool ProxyManager::slowPlaying()
{
    if (!MAIN.player())
        return false;
    const double speed = MAIN.player()->playbackSpeed(); // the stepped speed while it steps, else the engine's
    return speed > 0.0 && speed < 1.0 && MLT.isPaused();
}

void ProxyManager::watchAutomatic(MainWindow *window)
{
    RenderedPreview::watchMain(window); // T220: heavy timelines get a rendered preview in the main player too
    if (qEnvironmentVariableIsSet("LETITEDIT_DISABLE_AUTOMATIC_PROXIES"))
        return;
    auto *timer = new QTimer(window);
    timer->setSingleShot(true);
    timer->setInterval(750);
    auto attempted = std::make_shared<QSet<QString>>();
    auto ready = std::make_shared<QList<QPair<QString, QString>>>();
    auto *applyTimer = new QTimer(window);
    applyTimer->setInterval(50);
    QObject::connect(applyTimer, &QTimer::timeout, window, [ready, applyTimer]() {
        if (ready->isEmpty()) {
            applyTimer->stop();
            return;
        }
        if (slowPlaying())
            return; // a swap would stop the stepped frames: the copy goes in once the person pauses or plays at 1x or 2x
        const auto pending = ready->takeFirst();
        const QString source = pending.first;
        const QString copy = pending.second;
        MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() - 1);
        if (!MLT.producer())
            return;
        const int position = MLT.producer()->position();
        const double speed = MLT.producer()->get_speed();
        const bool modified = MAIN.isWindowModified();
        Mlt::Producer proxy(MLT.profile(), copy.toUtf8().constData());
        if (!proxy.is_valid())
            return;
        std::unique_ptr<Mlt::Producer> configured(MLT.setupNewProducer(&proxy));
        configured->set(kIsProxyProperty, 1);
        configured->set(kOriginalResourceProperty, source.toUtf8().constData());
        MLT.pause();
        // T220: a copy going in for its original (or back) changes no picture: the rendered preview keeps what it drew
        qApp->setProperty("letitedit_copy_swap", true);
        MAIN.replaceAllByHash(source, *configured, true, true);
        qApp->setProperty("letitedit_copy_swap", false);
        const auto &profile = MLT.profile();
        MLT.setPreviewScale(PlaybackQuality::previewScale(profile.width(), profile.height(), Settings.playerPreviewScale()));
        if (MLT.producer()) {
            MLT.producer()->seek(position);
            MLT.play(speed);
        }
        MAIN.setWindowModified(modified);
        MAIN.setProperty("automaticProxyReady", MAIN.property("automaticProxyReady").toInt() + 1);
    });
    QObject::connect(window, &MainWindow::producerOpened, timer, [timer, attempted]() {
        attempted->clear();
        MAIN.setProperty("automaticProxyReady", 0);
        timer->start();
    });
    QObject::connect(window->undoStack(), &QUndoStack::indexChanged, timer, [timer]() { timer->start(); });
    // Settings > Playback Quality: copies of the old size still queued are dropped; once the originals are back, the
    // clips are looked at again for copies of the new size
    QObject::connect(PlaybackQuality::notifier(), &PlaybackQuality::Notifier::changing, timer, [ready]() {
        MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() - ready->size());
        ready->clear();
        if (CopySwap::enabled())
            CopySwap::instance().clear();
    });
    QObject::connect(PlaybackQuality::notifier(), &PlaybackQuality::Notifier::changed, timer, [timer, attempted]() {
        attempted->clear();
        timer->start();
    });
    QObject::connect(timer, &QTimer::timeout, window, [attempted, ready, applyTimer]() {
        if (!MLT.producer() || !PlaybackQuality::size())
            return;
        QDomDocument document;
        if (!document.setContent(MLT.XML()))
            return;
        QHash<QString, QStringList> hashes;
        QSet<QString> slowed; // T220: a source played slower than 1x somewhere keeps its own frame rate in its copy
        for (const QString &tag : {QStringLiteral("producer"), QStringLiteral("chain")}) {
            const auto nodes = document.elementsByTagName(tag);
            for (int index = 0; index < nodes.size(); ++index) {
                const auto node = nodes.at(index).toElement();
                QHash<QString, QString> props;
                for (auto property = node.firstChildElement("property"); !property.isNull();
                     property = property.nextSiblingElement("property"))
                    props.insert(property.attribute("name"), property.text());
                const QString service = props.value("mlt_service");
                if ((!service.startsWith("avformat") && service != "timewarp") || props.contains(kIsProxyProperty))
                    continue;
                const QString source = QDir::fromNativeSeparators(props.value(service == "timewarp" ? "warp_resource" : "resource"));
                if (service == "timewarp" && qAbs(props.value("warp_speed", "1").toDouble()) < 0.999)
                    slowed.insert(source);
                const QString hash = source;
                if (!source.isEmpty() && !hash.isEmpty() && !attempted->contains(source) && !hashes[source].contains(hash))
                    hashes[source].append(hash);
            }
        }
        if (hashes.isEmpty())
            return;
        const QString worker = qEnvironmentVariable("LETITEDIT_PLAYBACK_WORKER", aiRootPath("bridge/playback_copies.py"));
        if (!QFileInfo::exists(worker))
            return;
        auto *process = new QProcess(&MAIN);
        MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() + 1);
#ifdef Q_OS_WIN
        process->setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *arguments) {
            arguments->flags |= 0x08004000;
        });
#endif
        auto *manifest = new QTemporaryFile(process);
        if (!manifest->open()) {
            MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() - 1);
            process->deleteLater();
            return;
        }
        QJsonArray sources;
        for (auto iterator = hashes.cbegin(); iterator != hashes.cend(); ++iterator) {
            sources.append(QJsonObject{{"path", iterator.key()}, {"keep_rate", slowed.contains(iterator.key())}});
            attempted->insert(iterator.key());
        }
        manifest->write(QJsonDocument(sources).toJson());
        manifest->flush();
        auto buffer = std::make_shared<QByteArray>();
        QObject::connect(process, &QProcess::readyReadStandardOutput, &MAIN, [process, buffer, ready, applyTimer]() {
            buffer->append(process->readAllStandardOutput());
            while (buffer->contains('\n')) {
                const int end = buffer->indexOf('\n');
                const auto record = QJsonDocument::fromJson(buffer->left(end)).object();
                buffer->remove(0, end + 1);
                if (record.value("state") != "ready"
                    || (record.contains("size") && record.value("size").toInt() != PlaybackQuality::size()))
                    continue;
                const auto identity = record.value("source").toObject();
                const QString source = QDir::fromNativeSeparators(identity.value("path").toString());
                const QFileInfo original(source);
                const QString copy = record.value("copy").toString();
                if (original.size() != qint64(identity.value("size").toDouble())
                    || qAbs(original.lastModified().toMSecsSinceEpoch() - qint64(identity.value("mtime_ns").toDouble() / 1000000)) > 1
                    || !QFileInfo::exists(copy))
                    continue;
                MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() + 1);
                // T366: the copy and its clips' replacements are made off the window's thread, and go in while paused
                if (CopySwap::enabled()) {
                    CopySwap::instance().add(source, copy);
                    continue;
                }
                ready->append(qMakePair(source, copy));
                if (!applyTimer->isActive())
                    applyTimer->start();
            }
        });
        auto finish = [process]() {
            if (!process->property("automaticFinished").toBool()) {
                process->setProperty("automaticFinished", true);
                MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() - 1);
            }
            process->deleteLater();
        };
        QObject::connect(process, &QProcess::finished, process, finish);
        QObject::connect(process, &QProcess::errorOccurred, process, finish);
        QStringList arguments{worker, "--manifest", manifest->fileName(), "--owner-pid",
                              QString::number(QCoreApplication::applicationPid()),
                              "--ffmpeg", QDir(qApp->applicationDirPath()).filePath("ffmpeg.exe"),
                              "--ffprobe", QDir(qApp->applicationDirPath()).filePath("ffprobe.exe"),
                              "--size", PlaybackQuality::workerSize(), "--stop-file", manifest->fileName() + ".stop",
                              // T220: copies at the timeline's frame rate (Rat's 60 fps cameras on a 30 fps timeline)
                              "--fps", QStringLiteral("%1/%2").arg(MLT.profile().frame_rate_num()).arg(MLT.profile().frame_rate_den())};
        // another Playback Quality: this run stops (the worker stops its encoder and removes the file)
        QObject::connect(PlaybackQuality::notifier(), &PlaybackQuality::Notifier::changing, process, [manifest]() {
            QFile(manifest->fileName() + ".stop").open(QIODevice::WriteOnly);
        });
        // T366 (T315's finding): another project opened (or the window's project closed): this run stops; it kept
        // checking or copying the closed project's sources, and taking PC-lock turns, for about three rounds
        const QString project = MAIN.fileName();
        QObject::connect(&MAIN, &MainWindow::producerOpened, process, [manifest, project]() {
            QTimer::singleShot(0, manifest, [manifest, project]() {
                if (MAIN.fileName() != project) {
                    LOG_INFO() << "playback copies: the project closed; its copy maker stops";
                    QFile(manifest->fileName() + ".stop").open(QIODevice::WriteOnly);
                }
            });
        });
        if (qEnvironmentVariableIsSet("LETITEDIT_PLAYBACK_CACHE"))
            arguments << "--cache" << qEnvironmentVariable("LETITEDIT_PLAYBACK_CACHE");
        process->start(aiChatSettings().value("python").toString(), arguments);
    });
}
static constexpr char kProxyVideoExtension[] = ".mp4";
static constexpr char kGoProProxyVideoExtension[] = ".LRV";
static constexpr char kDJIProxyVideoExtension[] = ".LRF";
static constexpr char kProxyPendingVideoExtension[] = ".pending.mp4";
static constexpr char kProxyImageExtension[] = ".jpg";
static constexpr char kProxyPendingImageExtension[] = ".pending.jpg";
static constexpr float kProxyResolutionRatio = 1.3f;
static constexpr int kFallbackProxyResolution = 540;
static const QStringList kPixFmtsWithAlpha
    = {"pal8",         "argb",         "rgba",         "abgr",         "bgra",
       "yuva420p",     "yuva422p",     "yuva444p",     "yuva420p9be",  "yuva420p9le",
       "yuva422p9be",  "yuva422p9le",  "yuva444p9be",  "yuva444p9le",  "yuva420p10be",
       "yuva420p10le", "yuva422p10be", "yuva422p10le", "yuva444p10be", "yuva444p10le",
       "yuva420p16be", "yuva420p16le", "yuva422p16be", "yuva422p16le", "yuva444p16be",
       "yuva444p16le", "rgba64be",     "rgba64le",     "bgra64be",     "bgra64le",
       "ya8",          "ya16le",       "ya16be",       "gbrap",        "gbrap16le",
       "gbrap16be",    "ayuv64le",     "ayuv64be",     "gbrap12le",    "gbrap12be",
       "gbrap10le",    "gbrap10be",    "gbrapf32be",   "gbrapf32le",   "yuva422p12be",
       "yuva422p12le", "yuva444p12be", "yuva444p12le"};

QDir ProxyManager::dir()
{
    // Use project folder + "/proxies" if using project folder and enabled
    QDir dir(MLT.projectFolder());
    if (!MLT.projectFolder().isEmpty() && dir.exists() && Settings.proxyUseProjectFolder()) {
        if (!dir.cd(kProxySubfolder)) {
            if (dir.mkdir(kProxySubfolder))
                dir.cd(kProxySubfolder);
        }
    } else {
        // Otherwise, use app setting
        dir = QDir(Settings.proxyFolder());
    }
    return dir;
}

QString ProxyManager::resource(Mlt::Service &producer)
{
    QString resource = QString::fromUtf8(producer.get("resource"));
    if (producer.get_int(kIsProxyProperty) && producer.get(kOriginalResourceProperty)) {
        resource = QString::fromUtf8(producer.get(kOriginalResourceProperty));
    } else if (!::qstrcmp(producer.get("mlt_service"), "timewarp")) {
        resource = QString::fromUtf8(producer.get("warp_resource"));
    }
    return resource;
}

void ProxyManager::generateVideoProxy(Mlt::Producer &producer,
                                      bool fullRange,
                                      ScanMode scanMode,
                                      const QPoint &aspectRatio,
                                      bool replace)
{
    // Always regenerate per preview scaling or 540 if not specified
    QString resource = ProxyManager::resource(producer);
    QStringList args;
    QString hash = Util::getHash(producer);
    QString fileName = ProxyManager::dir().filePath(hash + kProxyPendingVideoExtension);
    QString filters;
    auto hwCodecs = Settings.encodeHardware();
    QString hwFilters;

    if (JOBS.targetIsInProgress(fileName)) {
        LOG_ERROR() << "A job is already in progress for" << fileName;
        return;
    }

    // Touch file to make it in progress
    QFile file(fileName);
    if (!file.open(QIODevice::WriteOnly)) {
        LOG_ERROR() << "Failed to open file for writing:" << fileName;
        return;
    }
    file.resize(0);
    file.close();

    args << "-loglevel"
         << "verbose";
    args << "-noautorotate";
    args << "-i" << resource;
    args << "-max_muxing_queue_size"
         << "9999";
    // transcode all streams except data, subtitles, and attachments
    auto audioIndex = producer.property_exists(kDefaultAudioIndexProperty)
                          ? producer.get_int(kDefaultAudioIndexProperty)
                          : producer.get_int("audio_index");
    if (producer.get_int("video_index") < audioIndex) {
        if (Util::hasiPhoneAmbisonic(&producer))
            args << "-map"
                 << "0:V?"
                 << "-map"
                 << "0:a:0";
        else
            args << "-map"
                 << "0:V?"
                 << "-map"
                 << "0:a?";
    } else {
        args << "-map"
             << "0:a?"
             << "-map"
             << "0:V?";
    }
    args << "-map_metadata"
         << "0"
         << "-ignore_unknown";
    args << "-vf";

    // Detect rotation from either an explicit "rotate" property (user override)
    // or from the stream's codec metadata. If non-zero the rotation will be
    // injected into the proxy file after transcoding via a fast -c copy pass so
    // that media players and MLT read it automatically from the proxy.
    auto videoIndex = producer.get_int("video_index");
    QString rotateKey = QStringLiteral("meta.media.%1.codec.rotate").arg(videoIndex);
    int rotation = producer.property_exists("rotate")
                       ? producer.get_int("rotate")
                       : producer.get_int(rotateKey.toLatin1().constData());
    rotation = ((rotation % 360) + 360) % 360;

    if (scanMode == Automatic) {
        filters = QStringLiteral("yadif=deint=interlaced,");
    } else if (scanMode != Progressive) {
        filters = QStringLiteral("yadif=parity=%1,")
                      .arg(scanMode == InterlacedTopFieldFirst ? "tff" : "bff");
    }
    filters += QStringLiteral("scale=width=-2:height=%1").arg(resolution());
    if (Settings.proxyUseHardware()
        && (hwCodecs.contains("hevc_vaapi") || hwCodecs.contains("h264_vaapi"))) {
        hwFilters = ",format=nv12,hwupload";
    }
    if (fullRange) {
        args << filters + ":in_range=full:out_range=full" + hwFilters;
        args << "-color_range"
             << "jpeg";
    } else {
        args << filters + ":in_range=mpeg:out_range=mpeg" + hwFilters;
        args << "-color_range"
             << "mpeg";
    }
    switch (producer.get_int("meta.media.colorspace")) {
    case 601:
        if (producer.get_int("meta.media.height") == 576) {
            args << "-color_primaries"
                 << "bt470bg";
            args << "-color_trc"
                 << "smpte170m";
            args << "-colorspace"
                 << "bt470bg";
        } else {
            args << "-color_primaries"
                 << "smpte170m";
            args << "-color_trc"
                 << "smpte170m";
            args << "-colorspace"
                 << "smpte170m";
        }
        break;
    case 170:
        args << "-color_primaries"
             << "smpte170m";
        args << "-color_trc"
             << "smpte170m";
        args << "-colorspace"
             << "smpte170m";
        break;
    case 240:
        args << "-color_primaries"
             << "smpte240m";
        args << "-color_trc"
             << "smpte240m";
        args << "-colorspace"
             << "smpte240m";
        break;
    case 470:
        args << "-color_primaries"
             << "bt470bg";
        args << "-color_trc"
             << "bt470bg";
        args << "-colorspace"
             << "bt470bg";
        break;
    case 2020:
        args << "-color_primaries"
             << "bt2020";
        args << "-colorspace"
             << "bt2020nc";
        break;
    default:
        args << "-color_primaries"
             << "bt709";
        args << "-color_trc"
             << "bt709";
        args << "-colorspace"
             << "bt709";
        break;
    }
    if (!aspectRatio.isNull()) {
        args << "-aspect" << QStringLiteral("%1:%2").arg(aspectRatio.x()).arg(aspectRatio.y());
    }
    args << "-f"
         << "mp4"
         << "-codec:a"
         << "ac3"
         << "-b:a"
         << "256k";
    args << "-pix_fmt"
         << "yuv420p";
    if (Settings.proxyUseHardware()) {
        if (hwCodecs.contains("hevc_nvenc")) {
            args << "-codec:v"
                 << "hevc_nvenc";
            args << "-rc"
                 << "constqp";
            args << "-qp:v"
                 << "37";
            args << "-b_ref_mode"
                 << "0";
        } else if (hwCodecs.contains("hevc_qsv")) {
            args << "-load_plugin"
                 << "hevc_hw";
            args << "-codec:v"
                 << "hevc_qsv";
            args << "-q:v"
                 << "36";
        } else if (hwCodecs.contains("hevc_amf")) {
            args << "-codec:v"
                 << "hevc_amf";
            args << "-rc"
                 << "1";
            args << "-qp_i"
                 << "32"
                 << "-qp_p"
                 << "32";
        } else if (hwCodecs.contains("hevc_vaapi")) {
            args << "-init_hw_device"
                 << "vaapi=vaapi0:"
                 << "-filter_hw_device"
                 << "vaapi0";
            args << "-codec:v"
                 << "hevc_vaapi";
            args << "-qp"
                 << "37";
        } else if (hwCodecs.contains("hevc_mf")) {
            args << "-codec:v"
                 << "hevc_mf";
            args << "-rate_control"
                 << "quality";
            args << "-quality"
                 << "27";
            args << "-hw_encoding"
                 << "true"
                 << "-pix_fmt"
                 << "nv12";
        } else if (hwCodecs.contains("h264_nvenc")) {
            args << "-codec:v"
                 << "h264_nvenc";
            args << "-rc"
                 << "constqp";
            args << "-qp:v"
                 << "37";
            args << "-b_ref_mode"
                 << "0";
        } else if (hwCodecs.contains("h264_vaapi")) {
            args << "-init_hw_device"
                 << "vaapi=vaapi0:"
                 << "-filter_hw_device"
                 << "vaapi0";
            args << "-codec:v"
                 << "h264_vaapi";
            args << "-qp"
                 << "30";
#if (defined(Q_OS_MAC) && defined(Q_PROCESSOR_ARM))
        } else if (!fullRange && hwCodecs.contains("hevc_videotoolbox")) {
            args << "-codec:v"
                 << "hevc_videotoolbox";
            args << "-q:v"
                 << "45";
        } else if (!fullRange && hwCodecs.contains("h264_videotoolbox")) {
            args << "-codec:v"
                 << "h264_videotoolbox";
            args << "-q:v"
                 << "45";
#else
        } else if (hwCodecs.contains("hevc_videotoolbox")) {
            args << "-codec:v"
                 << "hevc_videotoolbox";
            args << "-b:v"
                 << "5M";
        } else if (hwCodecs.contains("h264_videotoolbox")) {
            args << "-codec:v"
                 << "h264_videotoolbox";
            args << "-b:v"
                 << "8M";
#endif
        } else if (hwCodecs.contains("h264_qsv")) {
            args << "-codec:v"
                 << "h264_qsv";
            args << "-q:v"
                 << "36";
        } else if (hwCodecs.contains("h264_amf")) {
            args << "-codec:v"
                 << "h264_amf";
            args << "-rc"
                 << "1";
            args << "-qp_i"
                 << "32"
                 << "-qp_p"
                 << "32";
        } else if (hwCodecs.contains("h264_mf")) {
            args << "-codec:v"
                 << "h264_mf";
            args << "-rate_control"
                 << "quality";
            args << "-quality"
                 << "41";
            args << "-hw_encoding"
                 << "true"
                 << "-pix_fmt"
                 << "nv12";
        }
    }
    if (!args.contains("-codec:v")) {
        args << "-codec:v"
             << "libx264";
        args << "-preset"
             << "veryfast";
        args << "-crf"
             << "23";
    }
    args << "-g"
         << QString::fromLatin1(hwCodecs.contains("hevc_nvenc")   ? "0"
                                : hwCodecs.contains("h264_nvenc") ? "2"
                                                                  : "1");
    args << "-bf"
         << "0";
    args << "-y" << fileName;

    FfmpegJob *job = new FfmpegJob(fileName, args, true);
    job->setLabel(QObject::tr("Make proxy for %1").arg(Util::baseName(resource)));
    job->setTarget(fileName);
    // letitedit: one heavy job at a time on the PC (lejobs.h)
    job->setRenderLock(QStringLiteral("letitedit proxy %1").arg(Util::baseName(resource)));
    if (replace) {
        job->setPostJobAction(new ProxyReplacePostJobAction(resource, fileName, hash, rotation));
    } else {
        job->setPostJobAction(new ProxyFinalizePostJobAction(resource, fileName, rotation));
    }
    JOBS.add(job);
}

void ProxyManager::generateImageProxy(Mlt::Producer &producer, bool replace)
{
    // Always regenerate per preview scaling or 540 if not specified
    QString resource = ProxyManager::resource(producer);
    QString hash = Util::getHash(producer);
    QString fileName = ProxyManager::dir().filePath(hash + kProxyPendingImageExtension);

    // Touch file to make it in progress
    QFile file(fileName);
    if (!file.open(QIODevice::WriteOnly)) {
        LOG_ERROR() << "Failed to open file for writing:" << fileName;
        return;
    }
    file.resize(0);
    file.close();

    AbstractJob *job = new QImageJob(fileName, resource, resolution());
    if (replace) {
        job->setPostJobAction(new ProxyReplacePostJobAction(resource, fileName, hash));
    } else {
        job->setPostJobAction(new ProxyFinalizePostJobAction(resource, fileName));
    }
    JOBS.add(job);
}

typedef QPair<QString, QString> MltProperty;

static void processProperties(QXmlStreamWriter &newXml,
                              QVector<MltProperty> &properties,
                              const QString &root)
{
    // Determine if this is a proxy resource
    bool isProxy = false;
    QString newResource;
    QString service;
    QString speed = "1";
    for (const auto &p : properties) {
        if (p.first == kIsProxyProperty) {
            isProxy = true;
        } else if (p.first == kOriginalResourceProperty) {
            newResource = p.second;
        } else if (newResource.isEmpty() && p.first == "resource") {
            newResource = p.second;
        } else if (p.first == "mlt_service") {
            service = p.second;
        } else if (p.first == "warp_speed") {
            speed = p.second;
        }
    }
    QVector<MltProperty> newProperties;
    QVector<MltProperty> &propertiesRef = properties;
    if (isProxy) {
        // Filter the properties
        for (const auto &p : properties) {
            // Replace the resource property if proxy
            if (p.first == "resource") {
                // Convert to relative
                if (!root.isEmpty() && newResource.startsWith(root)) {
                    newResource = newResource.mid(root.size());
                }
                if (service == "timewarp") {
                    newProperties << MltProperty(p.first,
                                                 QStringLiteral("%1:%2").arg(speed, newResource));
                } else {
                    newProperties << MltProperty(p.first, newResource);
                }
            } else if (p.first == "warp_resource") {
                newProperties << MltProperty(p.first, newResource);
            } else if (p.first != kIsProxyProperty && p.first != kOriginalResourceProperty) {
                // Remove special proxy and original resource properties
                newProperties << MltProperty(p.first, p.second);
            }
        }
        propertiesRef = newProperties;
    }
    // Write all of the property elements
    for (auto &p : propertiesRef) {
        newXml.writeStartElement("property");
        newXml.writeAttribute("name", p.first);
        newXml.writeCharacters(p.second);
        newXml.writeEndElement();
    }
    // Reset the saved properties
    properties.clear();
}

bool ProxyManager::filterXML(QString &xmlString, QString root)
{
    QString output;
    QXmlStreamReader xml(xmlString);
    QXmlStreamWriter newXml(&output);
    bool isPropertyElement = false;
    QVector<MltProperty> properties;

    // This prevents processProperties() from mis-matching a resource path that begins with root
    // when it is converting to relative paths.
    if (!root.isEmpty() && !root.endsWith('/')) {
        root.append('/');
    }

    newXml.setAutoFormatting(true);
    newXml.setAutoFormattingIndent(2);

    while (!xml.atEnd()) {
        switch (xml.readNext()) {
        case QXmlStreamReader::Characters:
            if (!isPropertyElement)
                newXml.writeCharacters(xml.text().toString());
            break;
        case QXmlStreamReader::Comment:
            newXml.writeComment(xml.text().toString());
            break;
        case QXmlStreamReader::DTD:
            newXml.writeDTD(xml.text().toString());
            break;
        case QXmlStreamReader::EntityReference:
            newXml.writeEntityReference(xml.name().toString());
            break;
        case QXmlStreamReader::ProcessingInstruction:
            newXml.writeProcessingInstruction(xml.processingInstructionTarget().toString(),
                                              xml.processingInstructionData().toString());
            break;
        case QXmlStreamReader::StartDocument:
            newXml.writeStartDocument(xml.documentVersion().toString(), xml.isStandaloneDocument());
            break;
        case QXmlStreamReader::EndDocument:
            newXml.writeEndDocument();
            break;
        case QXmlStreamReader::StartElement: {
            const QString element = xml.name().toString();
            if (element == "property") {
                // Save each property element but do not output yet
                const QString name = xml.attributes().value("name").toString();
                properties << MltProperty(name, xml.readElementText());
                isPropertyElement = true;
            } else {
                // At the start of a non-property element
                isPropertyElement = false;
                processProperties(newXml, properties, root);
                // Write the new start element
                newXml.writeStartElement(xml.namespaceUri().toString(), element);
                for (const auto &a : xml.attributes()) {
                    newXml.writeAttribute(a);
                }
            }
            break;
        }
        case QXmlStreamReader::EndElement:
            // At the end of a non-property element
            if (xml.name().toString() != "property") {
                processProperties(newXml, properties, root);
                newXml.writeEndElement();
            }
            break;
        default:
            break;
        }
    }

    // Useful for debugging
    //    LOG_DEBUG() << output;

    if (!xml.hasError()) {
        xmlString = output;
        return true;
    }
    return false;
}

bool ProxyManager::fileExists(Mlt::Producer &producer)
{
    QDir proxyDir(Settings.proxyFolder());
    QDir projectDir(MLT.projectFolder());
    QString service = QString::fromLatin1(producer.get("mlt_service"));
    QString fileName;
    if (service.startsWith("avformat")) {
        if (QFile::exists(GoProProxyFilePath(producer.get("resource")))) {
            return true;
        }
        if (QFile::exists(DJIProxyFilePath(producer.get("resource")))) {
            return true;
        }
        fileName = Util::getHash(producer) + kProxyVideoExtension;
    } else if (isValidImage(producer)) {
        fileName = Util::getHash(producer) + kProxyImageExtension;
    } else {
        return false;
    }
    return (projectDir.cd(kProxySubfolder) && projectDir.exists(fileName))
           || proxyDir.exists(fileName);
}

bool ProxyManager::filePending(Mlt::Producer &producer)
{
    QDir proxyDir(Settings.proxyFolder());
    QDir projectDir(MLT.projectFolder());
    QString service = QString::fromLatin1(producer.get("mlt_service"));
    QString fileName;
    if (service.startsWith("avformat")) {
        fileName = Util::getHash(producer) + kProxyPendingVideoExtension;
    } else if (isValidImage(producer)) {
        fileName = Util::getHash(producer) + kProxyPendingImageExtension;
    } else {
        return false;
    }
    return (projectDir.cd(kProxySubfolder) && projectDir.exists(fileName))
           || proxyDir.exists(fileName);
}

bool ProxyManager::isValidImage(Mlt::Producer &producer)
{
    QString service = QString::fromLatin1(producer.get("mlt_service"));
    if ((service == "qimage" || service == "pixbuf")
        && !producer.get_int(kShotcutSequenceProperty)) {
        QImageReader reader;
        reader.setDecideFormatFromContent(true);
        reader.setFileName(ProxyManager::resource(producer));
        return reader.imageCount() == 1 && !reader.read().hasAlphaChannel();
    }
    return false;
}

bool ProxyManager::isValidVideo(Mlt::Producer producer)
{
    QString service = QString::fromLatin1(producer.get("mlt_service"));
    int video_index = producer.get_int("video_index");
    // video_index -1 means no video
    if (video_index < 0)
        return false;
    if (service == "avformat-novalidate") {
        producer = Mlt::Producer(MLT.profile(), resource(producer).toUtf8().constData());
        service = QString::fromLatin1(producer.get("mlt_service"));
        producer.set("video_index", video_index);
    }
    if (service == "avformat") {
        QString key = QStringLiteral("meta.media.%1.codec.pix_fmt").arg(video_index);
        QString pix_fmt = QString::fromLatin1(producer.get(key.toLatin1().constData()));
        // Cover art is usually 90000 fps and should not be proxied
        key = QStringLiteral("meta.media.%1.codec.frame_rate").arg(video_index);
        QString frame_rate = producer.get(key.toLatin1().constData());
        key = QStringLiteral("meta.media.%1.codec.name").arg(video_index);
        QString codec_name = producer.get(key.toLatin1().constData());
        bool coverArt = codec_name == "mjpeg" && frame_rate == "90000";
        key = QStringLiteral("meta.attr.%1.stream.alpha_mode.markup").arg(video_index);
        bool alpha_mode = producer.get_int(key.toLatin1().constData());
        LOG_DEBUG() << "pix_fmt =" << pix_fmt << " codec.frame_rate =" << frame_rate
                    << " alpha_mode =" << alpha_mode;
        return !kPixFmtsWithAlpha.contains(pix_fmt) && !alpha_mode && !coverArt;
    }
    return false;
}

// Returns true if the producer exists and was updated with proxy info
bool ProxyManager::generateIfNotExists(Mlt::Producer &producer, bool replace)
{
    if (Settings.proxyEnabled() && producer.is_valid() && !producer.get_int(kDisableProxyProperty)
        && !producer.get_int(kIsProxyProperty)) {
        if (ProxyManager::fileExists(producer)) {
            QString service = QString::fromLatin1(producer.get("mlt_service"));
            QDir projectDir(MLT.projectFolder());
            QString fileName = Util::getHash(producer) + kProxyVideoExtension;
            QDir proxyDir(Settings.proxyFolder());

            if (service.startsWith("avformat")) {
                auto gopro = GoProProxyFilePath(producer.get("resource"));
                auto dji = DJIProxyFilePath(producer.get("resource"));
                if (!projectDir.exists(fileName) && !proxyDir.exists(fileName)) {
                    if (QFile::exists(gopro)) {
                        producer.set(kIsProxyProperty, 1);
                        producer.set(kMetaProxyProperty, 1);
                        producer.set(kOriginalResourceProperty, producer.get("resource"));
                        producer.set("resource", gopro.toUtf8().constData());
                        return true;
                    } else if (QFile::exists(dji)) {
                        producer.set(kIsProxyProperty, 1);
                        producer.set(kMetaProxyProperty, 1);
                        producer.set(kOriginalResourceProperty, producer.get("resource"));
                        producer.set("resource", dji.toUtf8().constData());
                        return true;
                    }
                }
            } else if (isValidImage(producer)) {
                fileName = Util::getHash(producer) + kProxyImageExtension;
            } else {
                return false;
            }
            producer.set(kIsProxyProperty, 1);
            producer.set(kMetaProxyProperty, 1);
            producer.set(kOriginalResourceProperty, producer.get("resource"));
            if (projectDir.exists(fileName)) {
                ::utime(projectDir.filePath(fileName).toUtf8().constData(), nullptr);
                producer.set("resource", projectDir.filePath(fileName).toUtf8().constData());
            } else {
                ::utime(proxyDir.filePath(fileName).toUtf8().constData(), nullptr);
                producer.set("resource", proxyDir.filePath(fileName).toUtf8().constData());
            }
            return true;
        } else if (!filePending(producer)) {
            if (isValidVideo(producer)) {
                // Tag this producer so we do not try to generate proxy again in this session
                delete producer.get_frame();
                auto threshold = qRound(kProxyResolutionRatio * resolution());
                LOG_DEBUG() << producer.get_int("meta.media.width") << "x"
                            << producer.get_int("meta.media.height") << "threshold" << threshold;
                if (producer.get_int("meta.media.width") > threshold
                    && producer.get_int("meta.media.height") > threshold) {
                    ProxyManager::generateVideoProxy(producer,
                                                     MLT.fullRange(producer),
                                                     Automatic,
                                                     QPoint(),
                                                     replace);
                }
            } else if (isValidImage(producer)) {
                // Tag this producer so we do not try to generate proxy again in this session
                delete producer.get_frame();
                auto threshold = qRound(kProxyResolutionRatio * resolution());
                LOG_DEBUG() << producer.get_int("meta.media.width") << "x"
                            << producer.get_int("meta.media.height") << "threshold" << threshold;
                if (producer.get_int("meta.media.width") > threshold
                    && producer.get_int("meta.media.height") > threshold) {
                    ProxyManager::generateImageProxy(producer, replace);
                }
            }
        }
    }
    return false;
}

const char *ProxyManager::videoFilenameExtension()
{
    return kProxyVideoExtension;
}

const char *ProxyManager::pendingVideoExtension()
{
    return kProxyPendingVideoExtension;
}

const char *ProxyManager::imageFilenameExtension()
{
    return kProxyImageExtension;
}

const char *ProxyManager::pendingImageExtension()
{
    return kProxyImageExtension;
}

int ProxyManager::resolution()
{
    return Settings.playerPreviewScale() ? Settings.playerPreviewScale() : kFallbackProxyResolution;
}

class FindNonProxyProducersParser : public Mlt::Parser
{
private:
    QString m_hash;
    QList<Mlt::Producer> m_producers;

public:
    FindNonProxyProducersParser()
        : Mlt::Parser()
    {}

    QList<Mlt::Producer> &producers() { return m_producers; }

    int on_start_filter(Mlt::Filter *) { return 0; }
    int on_start_producer(Mlt::Producer *producer)
    {
        if (!producer->parent().get_int(kIsProxyProperty))
            m_producers << Mlt::Producer(producer);
        return 0;
    }
    int on_end_producer(Mlt::Producer *) { return 0; }
    int on_start_playlist(Mlt::Playlist *) { return 0; }
    int on_end_playlist(Mlt::Playlist *) { return 0; }
    int on_start_tractor(Mlt::Tractor *) { return 0; }
    int on_end_tractor(Mlt::Tractor *) { return 0; }
    int on_start_multitrack(Mlt::Multitrack *) { return 0; }
    int on_end_multitrack(Mlt::Multitrack *) { return 0; }
    int on_start_track() { return 0; }
    int on_end_track() { return 0; }
    int on_end_filter(Mlt::Filter *) { return 0; }
    int on_start_transition(Mlt::Transition *) { return 0; }
    int on_end_transition(Mlt::Transition *) { return 0; }
    int on_start_chain(Mlt::Chain *chain)
    {
        if (!chain->parent().get_int(kIsProxyProperty))
            m_producers << Mlt::Producer(chain);
        return 0;
    }
    int on_end_chain(Mlt::Chain *) { return 0; }
    int on_start_link(Mlt::Link *) { return 0; }
    int on_end_link(Mlt::Link *) { return 0; }
};

void ProxyManager::generateIfNotExistsAll(Mlt::Producer &producer)
{
    FindNonProxyProducersParser parser;
    LongUiTask longTask(QObject::tr("Generating Proxies"));
    parser.start(producer);
    auto n = parser.producers().size();
    auto i = 0;
    for (auto &clip : parser.producers()) {
        longTask.reportProgress(QFileInfo(ProxyManager::resource(clip)).fileName(), i++, n);
        generateIfNotExists(clip, true /* replace */);
    }
}

bool ProxyManager::removePending()
{
    bool foundAny = false;
    QDir dir(MLT.projectFolder());
    if (!MLT.projectFolder().isEmpty() && dir.exists()) {
        dir.cd(kProxySubfolder);
    } else {
        dir = QDir(Settings.proxyFolder());
    }
    if (dir.exists()) {
        dir.setNameFilters(QStringList() << "*.pending.*");
        dir.setFilter(QDir::Files | QDir::NoDotAndDotDot | QDir::Writable);
        for (const auto &s : dir.entryList()) {
            LOG_INFO() << "removing" << dir.filePath(s);
            foundAny |= QFile::remove(dir.filePath(s));
        }
    }
    //TODO if any pending remove, let user know and offer to regenerate?
    return foundAny;
}

QString ProxyManager::GoProProxyFilePath(const QString &resource)
{
    auto fi = QFileInfo(resource);
    auto base = fi.baseName();
    base = "GL" + base.mid(2);
    auto result = fi.absoluteDir().filePath(base + kGoProProxyVideoExtension);
    LOG_DEBUG() << result;
    return result;
}

QString ProxyManager::DJIProxyFilePath(const QString &resource)
{
    auto fi = QFileInfo(resource);
    auto base = fi.baseName();
    auto result = fi.absoluteDir().filePath(base + kDJIProxyVideoExtension);
    LOG_DEBUG() << result;
    return result;
}
