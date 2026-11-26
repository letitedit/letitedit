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

#include "letitedit/player/renderedpreview.h"

#include "Logger.h"
#include "controllers/filtercontroller.h"
#include "docks/timelinedock.h"
#include "letitedit/airoot.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/player/playbackquality.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/attachedfiltersmodel.h"
#include "models/multitrackmodel.h"
#include "proxymanager.h"
#include "sharedframe.h"
#include "videowidget.h"

#include <Mlt.h>
#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QMutex>
#include <QPointer>
#include <QProcess>
#include <QRunnable>
#include <QThreadPool>
#include <QTimer>
#include <QUndoStack>

#include <algorithm>
#include <atomic>
#include <cstring>
#include <memory>

namespace RenderedPreview {
namespace {

constexpr int kDecoders = 4;        // open chunk files, the most recently used kept
constexpr int kPlanDelayMs = 700;   // after an edit, the plan is sent once the edits stop for this long
// T220: without Review the plan waits longer and never goes while playing: writing a heavy timeline out takes the
// window a third of a second (Rat), which would show as a hitch in the main player
constexpr int kMainPlanDelayMs = 2500;
constexpr char kAttached[] = "letitedit.rendered_preview";
constexpr char kPreviewFrame[] = "letitedit.preview";
constexpr char kPreviewPosition[] = "letitedit.preview_position";

struct Chunk
{
    int a = 0;
    int b = 0; // exclusive
    QString file;
    int width = 0; // the preview's own size
    int height = 0;
};

struct Decoder
{
    QString file;
    std::unique_ptr<Mlt::Producer> producer;
};

// What the player's threads read: the chunks ready for the timeline as it is now, and their decoders.
class Store
{
public:
    QMutex mutex;
    QVector<Chunk> ready; // by start
    std::atomic<bool> stepping{false};
    std::atomic<bool> disabled{false};
    // T220: the preview is drawn sharper than live frames play (PlaybackQuality::displaySize() > size()): drawn frames
    // show at the preview's own size, paused ones too
    std::atomic<bool> sharp{false};
    // QA (T220): where playing went from live frames to the preview's and back, newest last
    QMutex switchMutex;
    QJsonArray switches;
    int lastSource = -1; // 0 live, 1 preview
    QElapsedTimer switchClock;
    // QA (T220): the frame the screen showed last and its picture's size
    std::atomic<int> shownFrame{-1};
    std::atomic<int> shownWidth{0};
    std::atomic<int> shownHeight{0};

    // whether the frames playing now are drawn live (not from the preview)
    bool playingLive()
    {
        QMutexLocker lock(&switchMutex);
        return lastSource == 0;
    }

    void source(int position, int which)
    {
        QMutexLocker lock(&switchMutex);
        if (which == lastSource)
            return;
        lastSource = which;
        if (!switchClock.isValid())
            switchClock.start();
        switches.append(QJsonObject{{"frame", position}, {"to", which ? "preview" : "live"},
                                    {"ms", switchClock.elapsed()}});
        while (switches.size() > 40)
            switches.removeFirst();
    }
    std::atomic<int> previewFrames{0};
    std::atomic<int> liveFrames{0};
    std::atomic<int> failures{0};
    std::atomic<qint64> decodeUs{0};
    std::atomic<qint64> decodeMaxUs{0};
    QMutex decodeMutex;
    QList<Decoder *> decoders; // most recently used first
    QThreadPool opener;
    QMutex openingMutex;
    QSet<QString> opening;

    Store() { opener.setMaxThreadCount(1); }

    bool find(int position, Chunk *out)
    {
        QMutexLocker lock(&mutex);
        auto it = std::upper_bound(ready.cbegin(), ready.cend(), position,
                                   [](int p, const Chunk &c) { return p < c.a; });
        if (it == ready.cbegin())
            return false;
        --it;
        if (position < it->a || position >= it->b)
            return false;
        if (out)
            *out = *it;
        return true;
    }

    bool next(int b, Chunk *out)
    {
        QMutexLocker lock(&mutex);
        for (const auto &c : std::as_const(ready))
            if (c.a == b) {
                *out = c;
                return true;
            }
        return false;
    }

    void clear()
    {
        QMutexLocker lock(&mutex);
        ready.clear();
    }

    // Before the program exits (T220): no chunk decoder is left for this static store's destructor, which runs during
    // the program's exit, after the engine and the graphics driver's own threads are gone (every T214 journey left its
    // test window stuck closing, its main thread waiting forever).
    void release()
    {
        disabled = true;
        clear();
        opener.waitForDone(2000);
        QMutexLocker lock(&decodeMutex);
        qDeleteAll(decoders);
        decoders.clear();
    }

    static std::unique_ptr<Mlt::Producer> open(const QString &file)
    {
        auto producer = std::make_unique<Mlt::Producer>(MLT.profile(), file.toUtf8().constData());
        if (!producer->is_valid())
            return nullptr;
        producer->set("audio_index", -1);
        producer->set("force_colorspace", MLT.profile().colorspace());
        producer->set("force_progressive", 1);
        return producer;
    }

    // Under decodeMutex.
    Decoder *decoder(const QString &file)
    {
        for (int i = 0; i < decoders.size(); ++i)
            if (decoders[i]->file == file) {
                if (i)
                    decoders.move(i, 0);
                return decoders.first();
            }
        auto producer = open(file);
        if (!producer)
            return nullptr;
        return keep(file, std::move(producer));
    }

    Decoder *keep(const QString &file, std::unique_ptr<Mlt::Producer> producer)
    {
        auto *d = new Decoder{file, std::move(producer)};
        decoders.prepend(d);
        while (decoders.size() > kDecoders)
            delete decoders.takeLast();
        return d;
    }

    // The next chunk is opened and its first frame decoded off the player's threads, before playing reaches it.
    void prefetch(const QString &file)
    {
        {
            QMutexLocker lock(&decodeMutex);
            for (auto *d : std::as_const(decoders))
                if (d->file == file)
                    return;
        }
        {
            QMutexLocker lock(&openingMutex);
            if (opening.contains(file))
                return;
            opening.insert(file);
        }
        opener.start(QRunnable::create([this, file]() {
            auto producer = open(file);
            if (producer) {
                producer->seek(0);
                std::unique_ptr<Mlt::Frame> frame(producer->get_frame());
                if (frame && frame->is_valid()) {
                    mlt_image_format format = mlt_image_yuv420p;
                    int width = 0, height = 0;
                    uint8_t *image = nullptr;
                    mlt_frame_get_image(frame->get_frame(), &image, &format, &width, &height, 0);
                }
                QMutexLocker lock(&decodeMutex);
                bool have = false;
                for (auto *d : std::as_const(decoders))
                    have = have || d->file == file;
                if (!have)
                    keep(file, std::move(producer));
            }
            QMutexLocker lock(&openingMutex);
            opening.remove(file);
        }));
    }

    bool decode(int position, mlt_frame target, uint8_t **image, mlt_image_format *format, int *width, int *height)
    {
        Chunk chunk;
        if (disabled || !find(position, &chunk))
            return false;
        QElapsedTimer clock;
        clock.start();
        bool prefetchNext = false;
        {
            QMutexLocker lock(&decodeMutex);
            Decoder *d = decoder(chunk.file);
            if (!d)
                return false;
            const int local = position - chunk.a;
            d->producer->seek(local);
            std::unique_ptr<Mlt::Frame> frame(d->producer->get_frame());
            if (!frame || !frame->is_valid())
                return false;
            mlt_image_format wanted = *format;
            if (wanted == mlt_image_none || wanted == mlt_image_movit || wanted == mlt_image_opengl_texture)
                wanted = mlt_image_yuv420p;
            // the preview's own size, or smaller when the player asks for less (the picture is never enlarged here:
            // the screen scales it, as it does the light preview of heavy footage). Sharper than live frames
            // (T220): always its own size, so a drawn stretch shows sharp while undrawn ones play light
            int w = *width, h = *height;
            if (chunk.width > 0 && chunk.height > 0
                && (sharp || w <= 0 || h <= 0 || w > chunk.width || h > chunk.height)) {
                w = chunk.width;
                h = chunk.height;
            }
            uint8_t *source = nullptr;
            mlt_frame decoded = frame->get_frame();
            if (mlt_frame_get_image(decoded, &source, &wanted, &w, &h, 0) || !source || w <= 0 || h <= 0)
                return false;
            mlt_image_s info = {};
            mlt_image_set_values(&info, nullptr, wanted, w, h);
            const int size = mlt_image_calculate_size(&info);
            auto *copy = static_cast<uint8_t *>(mlt_pool_alloc(size));
            if (!copy)
                return false;
            std::memcpy(copy, source, size);
            mlt_frame_set_image(target, copy, size, mlt_pool_release);
            // the timeline's own drawing steps are left undone, as for a frame the player drops: a later request for
            // this frame's picture (the screen, a note) reads the picture set here and never draws it live
            mlt_deque steps = MLT_FRAME_IMAGE_STACK(target);
            while (mlt_deque_count(steps) > 0)
                mlt_deque_pop_back(steps);
            mlt_properties to = MLT_FRAME_PROPERTIES(target), from = MLT_FRAME_PROPERTIES(decoded);
            for (const char *name : {"colorspace", "color_trc", "color_primaries", "full_range", "aspect_ratio"})
                if (mlt_properties_get(from, name))
                    mlt_properties_set(to, name, mlt_properties_get(from, name));
            mlt_properties_set_int(to, "progressive", 1);
            mlt_properties_set_int(to, "format", wanted);
            mlt_properties_set_int(to, "width", w);
            mlt_properties_set_int(to, "height", h);
            *image = copy;
            *format = wanted;
            *width = w;
            *height = h;
            prefetchNext = local * 2 >= chunk.b - chunk.a;
        }
        const qint64 us = clock.nsecsElapsed() / 1000;
        decodeUs += us;
        qint64 worst = decodeMaxUs.load();
        while (us > worst && !decodeMaxUs.compare_exchange_weak(worst, us)) {
        }
        Chunk following;
        if (prefetchNext && next(chunk.b, &following))
            prefetch(following.file);
        return true;
    }
};

Store &store()
{
    static Store s;
    return s;
}

int previewGetImage(mlt_frame frame, uint8_t **image, mlt_image_format *format, int *width, int *height, int writable)
{
    mlt_frame_pop_service(frame);
    mlt_properties properties = MLT_FRAME_PROPERTIES(frame);
    const int position = mlt_properties_get_int(properties, kPreviewPosition);
    if (store().decode(position, frame, image, format, width, height)) {
        ++store().previewFrames;
        store().source(position, 1);
        return 0;
    }
    store().source(position, 0);
    // not ready after all (an edit came in meanwhile): drawn live
    mlt_properties_set_int(properties, kPreviewFrame, 0);
    ++store().failures;
    ++store().liveFrames;
    return mlt_frame_get_image(frame, image, format, width, height, writable);
}

mlt_frame previewProcess(mlt_filter filter, mlt_frame frame)
{
    Store &s = store();
    if (s.disabled)
        return frame;
    mlt_properties properties = MLT_FRAME_PROPERTIES(frame);
    const bool playing = mlt_properties_get_double(properties, "_speed") != 0.0;
    if (!playing && !s.stepping && !s.sharp)
        return frame; // paused: drawn live at full quality, for drawing on and judging
    // (T220: when the preview is sharper than live frames, a paused frame of a drawn stretch is the sharp one)
    const int position = mlt_frame_get_position(frame);
    if (!s.find(position, nullptr)) {
        if (playing || s.stepping) {
            ++s.liveFrames;
            s.source(position, 0);
        }
        return frame;
    }
    mlt_properties_set_int(properties, kPreviewFrame, 1);
    mlt_properties_set_int(properties, kPreviewPosition, position);
    mlt_frame_push_service(frame, filter);
    mlt_frame_push_get_image(frame, previewGetImage);
    return frame;
}

// The window's side: the worker, the plan of the timeline as it is now, and what the worker said.
class Link : public QObject
{
public:
    QPointer<MainWindow> window;
    QPointer<QProcess> process;
    QByteArray buffer;
    QTimer delay;
    int generation = 0;      // every change to the timeline makes a new one
    int sentGeneration = -1; // the newest sent to the worker
    int planGeneration = -1; // the newest the worker answered
    bool review = false;
    bool main = false;       // T220: a heavy timeline in the main window is drawn too
    bool forced = false;
    bool light = true;
    bool done = false;
    int focus = 0;
    int chunksTotal = 0;
    int chunksReady = 0;
    int readyFrames = 0;
    int totalFrames = 0;
    QTimer follow;           // the main player's playhead, for which chunks are drawn first
    // T220: while the player plays (or steps) frames it draws live, the drawing gives way: the worker starts no chunk and
    // pauses a running one, so an undrawn stretch plays as it does without the preview
    QTimer yieldWatch;
    bool yielded = false;
    bool sentSharp = false;  // the worker was told to draw this timeline sharp even if it is light
    QJsonObject weight;
    QJsonObject lastDone;
    int width = 0; // the preview's size in the newest plan
    int height = 0;
    QJsonArray events;
    QString cache;
    QElapsedTimer changed;   // since the last change (or the plan sent at opening)
    qint64 planMs = -1;      // from the change to the worker's plan
    qint64 doneMs = -1;      // from the plan sent to the whole preview ready
    QElapsedTimer sent;
    QElapsedTimer opened;    // since Review opened, for the time to a ready preview
    qint64 openedToDoneMs = -1;

    explicit Link(MainWindow *w)
        : QObject(w)
        , window(w)
    {
        delay.setSingleShot(true);
        delay.setInterval(kPlanDelayMs);
        connect(&delay, &QTimer::timeout, this, [this]() {
            if (!review && main && !MLT.isPaused()) {
                delay.start(kMainPlanDelayMs);
                return;
            }
            sendPlan();
        });
        yieldWatch.setInterval(100);
        connect(&yieldWatch, &QTimer::timeout, this, [this]() {
            const bool playing = MLT.producer() && (!MLT.isPaused() || store().stepping);
            if (process && !review && !sentSharp && sharpWanted()) {
                sentSharp = true;
                send(QJsonObject{{"force", true}});
            }
            const bool want = process && playing && store().playingLive();
            if (want == yielded)
                return;
            yielded = want;
            send(QJsonObject{{"yield", want}});
        });
        yieldWatch.start();
        follow.setInterval(2000);
        connect(&follow, &QTimer::timeout, this, [this]() {
            if (!main || review || !process || !MLT.producer())
                return;
            const int position = MLT.producer()->position();
            if (qAbs(position - focus) > 30) {
                focus = position;
                send(QJsonObject{{"focus", focus}});
            }
        });
        connect(w->undoStack(), &QUndoStack::indexChanged, this, [this]() { timelineChanged(); });
        connect(w, &MainWindow::producerOpened, this, [this]() { timelineChanged(); });
        if (auto *dock = w->timelineDock())
            if (auto *model = dock->model())
                connect(model, &MultitrackModel::modified, this, [this]() { timelineChanged(); });
        if (auto *filters = w->filterController()) {
            connect(filters, &FilterController::filterChanged, this, [this](Mlt::Service *) { timelineChanged(); });
            connect(filters->attachedModel(), &AttachedFiltersModel::changed, this, [this]() { timelineChanged(); });
        }
        connect(qApp, &QCoreApplication::aboutToQuit, this, [this]() {
            stop();
            store().release();
        });
        // a normal close ends in MainWindow::closeEvent's _Exit(0) right after aboutToShutDown: aboutToQuit never
        // comes then, so the worker is told to stop and the chunk decoders are closed here (T220)
        connect(w, &MainWindow::aboutToShutDown, this, [this]() {
            stop();
            store().release();
        });
        // Settings > Playback Quality: a new size draws the preview again at that size; Off draws live
        connect(PlaybackQuality::notifier(), &PlaybackQuality::Notifier::changed, this, [this]() {
            if (!PlaybackQuality::size()) {
                store().clear();
                stop();
                return;
            }
            // the worker first (after Off it isn't running), then the timeline again at the new size
            const bool running = (review || main) && start();
            timelineChanged();
            if (running)
                send(QJsonObject{{"render", true}, {"focus", focus}});
        });
    }

    ~Link() override { stop(); }

    // The worker is asked to stop and left to finish on its own (killed if it hasn't in 2 s): nothing waits for it.
    // (Waiting here ran its finished handler, which cleared `process` under this function.)
    void stop()
    {
        if (!process)
            return;
        QPointer<QProcess> worker = process;
        process = nullptr;
        sentGeneration = -1;
        worker->disconnect(this);
        connect(worker.data(), &QProcess::finished, worker.data(), &QObject::deleteLater);
        worker->write("{\"stop\": true}\n");
        worker->closeWriteChannel();
        QTimer::singleShot(2000, worker.data(), [worker]() {
            if (worker && worker->state() != QProcess::NotRunning)
                worker->kill();
        });
    }

    void note(const QJsonObject &event)
    {
        events.append(event);
        while (events.size() > 40)
            events.removeFirst();
    }

    // Any change to the timeline: the preview no longer matches it until the worker says which chunks still do.
    void timelineChanged()
    {
        // a playback copy swapped in for its original, or back (ProxyManager, PlaybackQuality): the same pictures, and
        // the chunks are keyed by the originals, so what is drawn stays (T220: Rat's 51 swaps cleared it 51 times)
        if (qApp->property("letitedit_copy_swap").toBool())
            return;
        replan();
        // the timeline is written out for the worker only while Review is open or the main window has a heavy timeline
        if (process && (review || main))
            delay.start(review ? kPlanDelayMs : kMainPlanDelayMs);
    }

    // a new plan: after an edit, or when the preview's size changes (Review opened or closed with sharp ahead)
    void replan()
    {
        ++generation;
        store().clear();
        done = false;
        chunksReady = 0;
        readyFrames = 0;
        changed.start();
    }

    // T220: Review keeps the light preview it was made with (sharp drawing there held the window up while drawing on
    // the playing video); the main player draws sharp
    bool sharpNow() const { return sharpAhead() && !review; }

    void send(const QJsonObject &command)
    {
        if (!process || process->state() == QProcess::NotRunning)
            return;
        process->write(QJsonDocument(command).toJson(QJsonDocument::Compact) + '\n');
    }

    bool start()
    {
        if (process && process->state() != QProcess::NotRunning)
            return true;
        if (qEnvironmentVariable("LETITEDIT_PLAYBACK_PREVIEW") == QLatin1String("off") || !PlaybackQuality::size())
            return false;
        const QString worker = qEnvironmentVariable("LETITEDIT_PREVIEW_WORKER", aiRootPath("bridge/playback_preview.py"));
        const QString python = aiChatSettings().value("python").toString();
        if (!QFileInfo::exists(worker) || python.isEmpty())
            return false;
        process = new QProcess(this);
#ifdef Q_OS_WIN
        process->setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *arguments) {
            arguments->flags |= 0x08004000; // no console window, below-normal priority
        });
#endif
        connect(process, &QProcess::readyReadStandardOutput, this, [this]() { read(); });
        connect(process, &QProcess::finished, this, [this](int code, QProcess::ExitStatus) {
            note(QJsonObject{{"event", "exited"}, {"code", code}});
            if (process)
                process->deleteLater();
            process = nullptr;
            sentGeneration = -1;
        });
        QStringList arguments{worker, QStringLiteral("--owner-pid"), QString::number(QCoreApplication::applicationPid()),
                              QStringLiteral("--app"), QDir::toNativeSeparators(qApp->applicationDirPath())};
        if (qEnvironmentVariableIsSet("LETITEDIT_PREVIEW_CACHE"))
            arguments << QStringLiteral("--cache") << qEnvironmentVariable("LETITEDIT_PREVIEW_CACHE");
        if (qEnvironmentVariableIsSet("LETITEDIT_PREVIEW_EXPORT_CHUNKS"))
            arguments << QStringLiteral("--chunks") << qEnvironmentVariable("LETITEDIT_PREVIEW_EXPORT_CHUNKS");
        process->setProcessChannelMode(QProcess::SeparateChannels);
        process->setStandardErrorFile(qEnvironmentVariableIsSet("LETITEDIT_PREVIEW_LOG")
                                          ? qEnvironmentVariable("LETITEDIT_PREVIEW_LOG")
                                          : QProcess::nullDevice());
        process->start(python, arguments);
        sentGeneration = -1;
        yielded = false;
        sentSharp = false;
        return true;
    }

    // T220: the preview draws sharper than live frames play, at the choice's own size
    static bool sharpAhead()
    {
        return PlaybackQuality::sharpAhead() && PlaybackQuality::displaySize() > PlaybackQuality::size();
    }

    // A light timeline is drawn sharp only while its live frames play smaller than the chosen size (on playback
    // copies): at the person's own full size, drawing it would spend the PC on nothing better (a heavy one is drawn
    // anyway)
    static bool sharpWanted()
    {
        if (!sharpAhead())
            return false;
        const int live = qMin(MLT.previewProfile().width(), MLT.previewProfile().height());
        const int full = qMin(MLT.profile().width(), MLT.profile().height());
        return live > 0 && live < qMin(full, PlaybackQuality::displaySize());
    }

    // A paused frame on a stretch just drawn is shown again, sharp.
    void refreshPaused(int a, int b)
    {
        if (!store().sharp || !MLT.producer() || !MLT.isPaused() || store().stepping)
            return;
        const int position = MLT.producer()->position();
        if (position >= a && position < b)
            MLT.refreshConsumer();
    }

    void sendPlan()
    {
        store().sharp = sharpNow();
        if (!window || !window->multitrack() || !process)
            return;
        sentSharp = sentSharp || (sharpNow() && sharpWanted());
        const QString xml = ProxyManager::originalXML(window->multitrack());
        if (xml.isEmpty())
            return;
        sent.start();
        sentGeneration = generation;
        // the saved file and whether the window has unsaved changes: an export made from the file can be reused
        send(QJsonObject{{"plan", QJsonObject{{"xml", xml},
                                              {"generation", generation},
                                              {"render", review || main},
                                              {"force", forced || (sentSharp && !review)},
                                              {"focus", focus},
                                              {"project", window->fileName()},
                                              {"short_side", sharpNow() ? PlaybackQuality::displaySize() : PlaybackQuality::size()},
                                              {"modified", window->isWindowModified()}}}});
    }

    void read()
    {
        buffer.append(process->readAllStandardOutput());
        while (true) {
            const int end = buffer.indexOf('\n');
            if (end < 0)
                break;
            const QJsonObject event = QJsonDocument::fromJson(buffer.left(end)).object();
            buffer.remove(0, end + 1);
            handle(event);
        }
    }

    void handle(const QJsonObject &event)
    {
        const QString kind = event.value("event").toString();
        const int g = event.value("generation").toInt(-1);
        if (kind == QLatin1String("hello")) {
            cache = event.value("cache").toString();
            note(event);
            return;
        }
        if (kind == QLatin1String("plan")) {
            if (g != generation)
                return;
            planGeneration = g;
            light = event.value("light").toBool();
            weight = event.value("weight").toObject();
            width = event.value("size").toArray().at(0).toInt();
            height = event.value("size").toArray().at(1).toInt();
            const QJsonArray chunks = event.value("chunks").toArray();
            chunksTotal = chunks.size();
            totalFrames = 0;
            for (const auto &value : chunks)
                totalFrames += value.toObject().value("b").toInt() - value.toObject().value("a").toInt();
            QVector<Chunk> ready;
            for (const auto &value : chunks) {
                const QJsonObject c = value.toObject();
                if (c.value("ready").toBool())
                    ready.append(Chunk{c.value("a").toInt(), c.value("b").toInt(), c.value("file").toString(), width,
                                       height});
            }
            set(ready);
            for (const auto &c : std::as_const(ready))
                refreshPaused(c.a, c.b);
            planMs = changed.isValid() ? changed.elapsed() : -1;
            note(QJsonObject{{"event", "plan"}, {"generation", g}, {"chunks", chunksTotal}, {"ready", chunksReady},
                             {"light", light}, {"ms", planMs}, {"exports", event.value("exports")}});
            return;
        }
        if (kind == QLatin1String("ready")) {
            if (g != generation)
                return;
            QVector<Chunk> ready;
            {
                QMutexLocker lock(&store().mutex);
                ready = store().ready;
            }
            ready.append(Chunk{event.value("a").toInt(), event.value("b").toInt(), event.value("file").toString(),
                               width, height});
            set(ready);
            refreshPaused(event.value("a").toInt(), event.value("b").toInt());
            note(event);
            return;
        }
        if (kind == QLatin1String("done")) {
            if (g != generation)
                return;
            done = true;
            lastDone = event;
            doneMs = sent.isValid() ? sent.elapsed() : -1;
            if (opened.isValid() && openedToDoneMs < 0)
                openedToDoneMs = opened.elapsed();
            note(event);
            return;
        }
        note(event);
    }

    void set(QVector<Chunk> ready)
    {
        std::sort(ready.begin(), ready.end(), [](const Chunk &x, const Chunk &y) { return x.a < y.a; });
        ready.erase(std::unique(ready.begin(), ready.end(), [](const Chunk &x, const Chunk &y) { return x.a == y.a; }),
                    ready.end());
        chunksReady = ready.size();
        readyFrames = 0;
        for (const auto &c : std::as_const(ready))
            readyFrames += c.b - c.a;
        QMutexLocker lock(&store().mutex);
        store().ready = ready;
    }
};

QPointer<Link> &link()
{
    static QPointer<Link> l;
    return l;
}

} // namespace

void attach(Mlt::FilteredConsumer &consumer)
{
    if (!consumer.is_valid() || consumer.get_int(kAttached))
        return;
    if (qEnvironmentVariable("LETITEDIT_PLAYBACK_PREVIEW") == QLatin1String("off"))
        return;
    mlt_filter filter = mlt_filter_new();
    if (!filter)
        return;
    filter->process = previewProcess;
    Mlt::Filter wrapped(filter);
    mlt_filter_close(filter); // the wrapper and the output's chain hold it now
    if (!consumer.attach(wrapped))
        consumer.set(kAttached, 1);
}

void reviewOpened(MainWindow *window, int position)
{
    if (!window)
        return;
    auto &l = link();
    if (!l)
        l = new Link(window);
    const bool wasSharp = store().sharp;
    l->review = true;
    if (wasSharp) {
        store().sharp = false;
        l->replan();
    }
    l->focus = qMax(0, position);
    l->opened.start();
    l->openedToDoneMs = -1;
    if (!l->start())
        return;
    l->send(QJsonObject{{"render", true}, {"focus", l->focus}});
    if (l->sentGeneration != l->generation) {
        l->changed.start();
        // after Review has shown: the timeline is written out on the screen thread
        QTimer::singleShot(250, l, [lp = QPointer<Link>(l)]() {
            if (lp && lp->sentGeneration != lp->generation)
                lp->sendPlan();
        });
    }
}

// QA (T220): the frame the screen shows and its picture's size (the player's widget is made after the main window)
static void watchShown()
{
    auto *video = qobject_cast<Mlt::VideoWidget *>(MLT.videoWidget());
    if (!video) {
        QTimer::singleShot(1000, qApp, watchShown);
        return;
    }
    QObject::connect(video, &Mlt::VideoWidget::frameDisplayed, video, [](const SharedFrame &frame) {
        store().shownFrame = frame.get_position();
        store().shownWidth = frame.get_image_width();
        store().shownHeight = frame.get_image_height();
    });
}

void watchMain(MainWindow *window)
{
    QTimer::singleShot(2000, qApp, watchShown);
    if (!window || qEnvironmentVariable("LETITEDIT_MAIN_PREVIEW") == QLatin1String("off")
        || qEnvironmentVariable("LETITEDIT_PLAYBACK_PREVIEW") == QLatin1String("off"))
        return;
    QObject::connect(window, &MainWindow::producerOpened, window, [window]() {
        // after the opening has settled; the worker says whether the timeline is heavy enough to draw
        QTimer::singleShot(1500, window, [window]() {
            if (!window->multitrack() || !PlaybackQuality::size())
                return;
            auto &l = link();
            if (!l)
                l = new Link(window);
            l->main = true;
            l->focus = MLT.producer() ? qMax(0, MLT.producer()->position()) : 0;
            if (!l->start())
                return;
            l->follow.start();
            if (l->sentGeneration != l->generation) {
                l->changed.start();
                l->sendPlan();
            }
            l->send(QJsonObject{{"render", true}, {"focus", l->focus}});
        });
    });
}

int drawnPercent()
{
    auto &l = link();
    if (!l || !l->main || !l->process || l->light || l->planGeneration != l->generation || l->totalFrames <= 0)
        return -1;
    return qBound(0, int(qint64(l->readyFrames) * 100 / l->totalFrames), 100);
}

bool drawsSharper()
{
    return store().sharp;
}

void reviewClosed()
{
    if (auto &l = link()) {
        l->review = false;
        if (!l->main)
            l->delay.stop();
        l->send(QJsonObject{{"render", l->main}});
        if (l->main && l->process && l->sharpNow() && !store().sharp) {
            l->replan();
            l->delay.start(kMainPlanDelayMs);
        }
    }
}

void setStepping(bool on)
{
    store().stepping = on;
}

void setFocus(int frame)
{
    if (auto &l = link()) {
        l->focus = qMax(0, frame);
        l->send(QJsonObject{{"focus", l->focus}});
    }
}

void liveCannotKeepUp()
{
    if (auto &l = link()) {
        if (l->forced)
            return;
        l->forced = true;
        l->send(QJsonObject{{"force", true}});
        l->note(QJsonObject{{"event", "live_cannot_keep_up"}});
    }
}

bool inUse()
{
    QMutexLocker lock(&store().mutex);
    return !store().ready.isEmpty();
}

bool preparing()
{
    auto &l = link();
    return l && l->process && l->review && l->planGeneration == l->generation && !l->light && !l->done;
}

QJsonObject state(bool reset)
{
    Store &s = store();
    QJsonObject out{{"preview_frames", s.previewFrames.load()},
                    {"live_frames", s.liveFrames.load()},
                    {"failures", s.failures.load()},
                    {"decode_ms_max", s.decodeMaxUs.load() / 1000.0},
                    {"decode_ms_mean", s.previewFrames.load() ? s.decodeUs.load() / 1000.0 / s.previewFrames.load() : 0.0},
                    {"stepping", s.stepping.load()},
                    {"sharp", s.sharp.load()},
                    {"shown", QJsonObject{{"frame", s.shownFrame.load()},
                                          {"width", s.shownWidth.load()},
                                          {"height", s.shownHeight.load()}}},
                    {"in_use", inUse()},
                    {"preparing", preparing()}};
    if (auto &l = link()) {
        out["running"] = bool(l->process);
        out["review"] = l->review;
        out["main"] = l->main;
        out["total_frames"] = l->totalFrames;
        out["drawn_percent"] = drawnPercent();
        out["generation"] = l->generation;
        out["sent_generation"] = l->sentGeneration;
        out["plan_generation"] = l->planGeneration;
        out["light"] = l->light;
        out["forced"] = l->forced;
        out["weight"] = l->weight;
        out["size"] = QJsonArray{l->width, l->height};
        out["chunks_total"] = l->chunksTotal;
        out["chunks_ready"] = l->chunksReady;
        out["ready_frames"] = l->readyFrames;
        out["done"] = l->done;
        out["done_event"] = l->lastDone;
        out["plan_ms"] = l->planMs;
        out["plan_to_done_ms"] = l->doneMs;
        out["opened_to_done_ms"] = l->openedToDoneMs;
        out["cache"] = l->cache;
        out["events"] = l->events;
    }
    {
        QMutexLocker lock(&s.switchMutex);
        out["switches"] = s.switches;
        if (reset) {
            s.switches = QJsonArray();
            s.lastSource = -1;
        }
    }
    if (reset) {
        s.previewFrames = 0;
        s.liveFrames = 0;
        s.failures = 0;
        s.decodeUs = 0;
        s.decodeMaxUs = 0;
    }
    return out;
}

} // namespace RenderedPreview
