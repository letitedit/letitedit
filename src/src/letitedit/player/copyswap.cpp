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

#include "letitedit/player/copyswap.h"

#include "Logger.h"
#include "docks/timelinedock.h"
#include "letitedit/player/playbackquality.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "player.h"
#include "proxymanager.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"

#include <QCoreApplication>
#include <QFileInfo>
#include <QGuiApplication>
#include <QThread>

#include <utility>

#include <MltProducer.h>
#include <MltProfile.h>

namespace {
constexpr int kBudgetMs = 20;           // the window's thread works on copies at most this long at a time
constexpr int kGapMs = 8;               // and then handles its own events for at least this long
constexpr int kHeldPollMs = 250;        // while playing, how often it looks whether it may go on
constexpr qint64 kPlayingWaitMs = 20000; // a copy ready this long while playing goes in (one batch, playing paused)
constexpr int kRounds = 3;              // clips added or changed meanwhile: planned again at most this often
constexpr qint64 kReleaseMs = 3000;     // clips taken out are let go this long after their run of edits ended (T366b)
} // namespace

struct CopySwap::Entry
{
    // Opened: the copy is open; the clips playing its original are looked up by the next tick, inside its budget
    enum State { Opening, Opened, Planning, Making, Applying };
    quint64 id = 0;
    QString source;
    QString copy;
    State state = Opening;
    std::shared_ptr<Mlt::Producer> configured;
    QList<QUuid> toPlan;
    QList<TimelineDock::CopySwapClip> plan;
    std::shared_ptr<QList<Mlt::Producer>> made;
    int next = 0;
    int rounds = 0;
    int replaced = 0;
    int busy = 0; // edits put off a turn because the player was building a frame from the timeline (T366b)
    bool othersDone = false;
    QElapsedTimer clock; // since it was added
    qint64 readyAt = -1; // clock time its clips were made
    qint64 openMs = 0, planMs = 0, makeMs = 0, applyMs = 0, longestMs = 0;
};

CopySwap &CopySwap::instance()
{
    static CopySwap *swap = new CopySwap(&MAIN);
    return *swap;
}

bool CopySwap::enabled()
{
    // on unless LETITEDIT_COPY_SWAP=0 or LETITEDIT_COPY_SWAP_OLD=1 (replaceClipsWithHash's way)
    static const bool on = [] {
        bool set = false;
        const int value = qEnvironmentVariableIntValue("LETITEDIT_COPY_SWAP", &set);
        return !(set && value <= 0) && qEnvironmentVariableIntValue("LETITEDIT_COPY_SWAP_OLD") <= 0;
    }();
    return on;
}

CopySwap::CopySwap(QObject *parent)
    : QObject(parent)
{
    m_pool.setMaxThreadCount(2);
    m_pool.setThreadPriority(QThread::LowPriority);
    m_timer.setSingleShot(true);
    connect(&m_timer, &QTimer::timeout, this, &CopySwap::tick);
    // the person playing, pausing or stopping during a batch takes over: playing isn't resumed for them
    if (MAIN.player()) {
        connect(MAIN.player(), &Player::played, this, [this]() { m_batch = false; });
        connect(MAIN.player(), &Player::paused, this, [this]() { m_batch = false; });
        connect(MAIN.player(), &Player::stopped, this, [this]() { m_batch = false; });
    }
    connect(qApp, &QCoreApplication::aboutToQuit, this, [this]() {
        clear();
        releaseRemoved(true);
        m_pool.clear();
        m_pool.waitForDone(5000);
    });
}

std::shared_ptr<CopySwap::Entry> CopySwap::find(quint64 id) const
{
    for (const auto &entry : m_entries)
        if (entry->id == id)
            return entry;
    return nullptr;
}

void CopySwap::add(const QString &source, const QString &copy)
{
    auto entry = std::make_shared<Entry>();
    entry->id = ++m_nextId;
    entry->source = source;
    entry->copy = copy;
    entry->clock.start();
    m_entries.append(entry);
    const quint64 generation = m_generation;
    const quint64 id = entry->id;
    // opening and probing the copy: off the window's thread
    m_pool.start([this, generation, id, source, copy]() {
        QElapsedTimer clock;
        clock.start();
        std::shared_ptr<Mlt::Producer> configured;
        if (generation == m_generation) {
            Mlt::Producer proxy(MLT.profile(), copy.toUtf8().constData());
            if (proxy.is_valid()) {
                configured.reset(MLT.setupNewProducer(&proxy));
                configured->set(kIsProxyProperty, 1);
                configured->set(kOriginalResourceProperty, source.toUtf8().constData());
            }
        }
        const qint64 ms = clock.elapsed();
        QMetaObject::invokeMethod(
            this, [this, generation, id, configured, ms]() { opened(generation, id, configured, ms); },
            Qt::QueuedConnection);
    });
}

void CopySwap::clear()
{
    ++m_generation;
    if (!m_entries.isEmpty())
        MAIN.setProperty("automaticProxyWorkers",
                         MAIN.property("automaticProxyWorkers").toInt() - m_entries.size());
    m_entries.clear();
    m_timer.stop();
    if (m_batch && MLT.producer()) {
        m_batch = false;
        MLT.play(m_batchSpeed);
    }
    if (m_removed && !m_removed->isEmpty())
        schedule(int(kReleaseMs)); // a tick ends the run (if one was going) and lets the clips taken out go after
}

void CopySwap::endRun()
{
    m_swapping = false;
    m_runEnded.start();
}

void CopySwap::releaseRemoved(bool now)
{
    if (!m_removed || m_removed->isEmpty())
        return;
    auto held = std::move(m_removed);
    m_removed.reset();
    LOG_INFO() << "copy swap: letting go of" << held->size() << "clips taken out";
    if (now) {
        held->clear();
        return;
    }
    // closing a clip can take a while (its decoder): a worker thread does it, after the copies waiting to be opened
    m_pool.start([held]() { held->clear(); }, -1);
}

void CopySwap::opened(quint64 generation, quint64 id, std::shared_ptr<Mlt::Producer> configured, qint64 ms)
{
    if (generation != m_generation)
        return;
    auto entry = find(id);
    if (!entry)
        return;
    entry->openMs = ms;
    if (!configured || !configured->is_valid()) {
        LOG_WARNING() << "copy swap: the copy did not open" << entry->copy;
        m_entries.removeAll(entry);
        MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() - 1);
        return;
    }
    entry->configured = configured;
    // T366b: not looked up here. The lookup walks the whole timeline (tens of ms on a heavy project), and on a warm
    // open every copy opens within a second or two: run from each `opened`, the lookups piled up back to back on the
    // window's thread, outside the tick's budget
    entry->state = Entry::Opened;
    schedule();
}

void CopySwap::startPlanning(Entry &entry)
{
    QElapsedTimer clock;
    clock.start();
    entry.toPlan = MAIN.isMultitrackValid() && MAIN.timelineDock()
                       ? MAIN.timelineDock()->copySwapClips(entry.source, *entry.configured)
                       : QList<QUuid>();
    entry.plan.clear();
    entry.made.reset();
    entry.next = 0;
    entry.rounds++;
    entry.state = Entry::Planning;
    entry.planMs += clock.elapsed();
}

void CopySwap::startMaking(Entry &entry)
{
    if (entry.plan.isEmpty()) {
        entry.made = std::make_shared<QList<Mlt::Producer>>();
        entry.state = Entry::Applying;
        if (entry.readyAt < 0)
            entry.readyAt = entry.clock.elapsed();
        return;
    }
    entry.state = Entry::Making;
    QStringList xmls;
    for (const auto &clip : std::as_const(entry.plan))
        xmls << clip.xml;
    const quint64 generation = m_generation;
    const quint64 id = entry.id;
    // each clip's replacement opened from its XML, as replaceClipsWithHash does on the window's thread
    m_pool.start(
        [this, generation, id, xmls]() {
            QElapsedTimer clock;
            clock.start();
            auto producers = std::make_shared<QList<Mlt::Producer>>();
            producers->reserve(xmls.size());
            for (const QString &xml : xmls) {
                if (generation != m_generation)
                    break;
                producers->append(Mlt::Producer(MLT.profile(), "xml-string", xml.toUtf8().constData()));
            }
            const qint64 ms = clock.elapsed();
            QMetaObject::invokeMethod(
                this, [this, generation, id, producers, ms]() { made(generation, id, producers, ms); },
                Qt::QueuedConnection);
        },
        1); // ahead of copies still waiting to be opened, so the first copies go in early
}

void CopySwap::made(quint64 generation, quint64 id, std::shared_ptr<QList<Mlt::Producer>> producers, qint64 ms)
{
    if (generation != m_generation)
        return;
    auto entry = find(id);
    if (!entry || entry->state != Entry::Making)
        return;
    entry->makeMs += ms;
    entry->made = producers;
    entry->state = Entry::Applying;
    if (entry->readyAt < 0)
        entry->readyAt = entry->clock.elapsed();
    schedule();
}

void CopySwap::finish(const std::shared_ptr<Entry> &entry)
{
    m_entries.removeAll(entry);
    MAIN.setProperty("automaticProxyWorkers", MAIN.property("automaticProxyWorkers").toInt() - 1);
    MAIN.setProperty("automaticProxyReady", MAIN.property("automaticProxyReady").toInt() + 1);
    LOG_INFO() << "copy swap:" << QFileInfo(entry->source).fileName() << "in on" << entry->replaced << "clips in"
               << entry->clock.elapsed() << "ms; off the window's thread: opened" << entry->openMs << "ms, made"
               << entry->makeMs << "ms; on it: planned" << entry->planMs << "ms, put in" << entry->applyMs
               << "ms, longest stretch" << entry->longestMs << "ms;" << entry->rounds << "round(s);" << entry->busy
               << "edit(s) put off a turn while the player built a frame";
}

bool CopySwap::playing() const
{
    return MLT.producer() && !MLT.isPaused();
}

bool CopySwap::held() const
{
    if (!MLT.producer())
        return true;
    if (ProxyManager::slowPlaying())
        return true; // a swap would stop the stepped frames
    if (playing())
        return true; // a swap stops playing for a moment: copies wait for a pause (or 20 s, see tick)
    // a drag or a trim in the timeline holds the clips it moves
    return QGuiApplication::mouseButtons() != Qt::NoButton;
}

void CopySwap::schedule(int ms)
{
    if (!m_timer.isActive() || m_timer.remainingTime() > ms)
        m_timer.start(ms);
}

void CopySwap::tick()
{
    QElapsedTimer clock;
    clock.start();
    TimelineDock *dock = MAIN.isMultitrackValid() ? MAIN.timelineDock() : nullptr;
    // 1. what each clip's replacement is made from (reads the clips; needs no pause)
    for (const auto &entry : std::as_const(m_entries)) {
        if (clock.elapsed() >= kBudgetMs)
            break;
        if (entry->state == Entry::Opened)
            startPlanning(*entry); // which of the timeline's clips play its original (one walk, then those clips)
        if (entry->state != Entry::Planning)
            continue;
        const qint64 started = clock.elapsed();
        while (!entry->toPlan.isEmpty() && clock.elapsed() < kBudgetMs) {
            const QUuid uuid = entry->toPlan.takeFirst();
            TimelineDock::CopySwapClip planned;
            if (dock && dock->planCopySwapClip(uuid, *entry->configured, planned))
                entry->plan << planned;
        }
        entry->planMs += clock.elapsed() - started;
        if (entry->toPlan.isEmpty())
            startMaking(*entry);
    }
    // 2. a batch for copies that waited while playing: playing pauses for it and resumes after
    bool waiting = false;
    for (const auto &entry : std::as_const(m_entries))
        waiting = waiting || entry->state == Entry::Applying;
    // T366b: the wait counts only playing at normal speed or faster, without a stop. A copy ready while paused or at
    // quarter or half speed (both hold copies) used to go in, playing paused, the moment Play was pressed. A copy
    // waiting has a tick at least every kHeldPollMs, so a stop between ticks is seen.
    if (playing() && !ProxyManager::slowPlaying()) {
        if (!m_playingFor.isValid())
            m_playingFor.start();
    } else {
        m_playingFor.invalidate();
    }
    if (waiting && m_playingFor.isValid() && m_playingFor.elapsed() >= kPlayingWaitMs && !m_batch
        && (!m_lastBatch.isValid() || m_lastBatch.elapsed() >= kPlayingWaitMs)) {
        for (const auto &entry : std::as_const(m_entries)) {
            if (entry->state == Entry::Applying && entry->clock.elapsed() - entry->readyAt >= kPlayingWaitMs) {
                m_batch = true;
                m_batchSpeed = MLT.producer()->get_speed();
                LOG_INFO() << "copy swap: copies waited" << kPlayingWaitMs / 1000
                           << "s while playing; playing pauses while they go in";
                MLT.pause();
                break;
            }
        }
    }
    // 3. the replacements go in, a few at a time; the player is paused for the run of steps and refreshed once after
    bool began = false;
    bool modified = false;
    bool any = false;
    if (m_swapping && playing()) {
        endRun(); // the person pressed play meanwhile: theirs
    }
    if (!held()) {
        const auto entries = m_entries;
        for (const auto &entry : entries) {
            if (clock.elapsed() >= kBudgetMs)
                break;
            if (entry->state != Entry::Applying)
                continue;
            if (!began) {
                began = true;
                modified = MAIN.isWindowModified();
                const bool starting = !m_swapping;
                if (starting) {
                    m_swapping = true;
                    m_swapPosition = MLT.producer()->position();
                }
                MLT.pause();
                if (starting)
                    m_pausedAt = MLT.producer()->position(); // a seek from here on is the person's: the run keeps it
                // T220: a copy going in for its original changes no picture: the rendered preview keeps what it drew
                qApp->setProperty("letitedit_copy_swap", true);
            }
            const qint64 started = clock.elapsed();
            if (!entry->othersDone) {
                // the player's own clip, the clip kept for the source player and the bin's items (few)
                entry->othersDone = true;
                MAIN.replaceAllByHash(entry->source, *entry->configured, true, true, false);
                any = true;
            }
            bool busy = false;
            while (entry->next < entry->plan.size() && clock.elapsed() < kBudgetMs) {
                const int index = entry->next++;
                if (!dock || index >= entry->made->size())
                    continue;
                if (!m_removed)
                    m_removed = std::make_shared<QList<Mlt::Producer>>();
                const int done = dock->applyCopySwap(entry->source, entry->plan.at(index), *entry->configured,
                                                     (*entry->made)[index], m_removed.get());
                if (done == 2) {
                    // the player is building a frame from the timeline (T366b): this clip again on the next turn
                    entry->next = index;
                    ++entry->busy;
                    busy = true;
                    break;
                }
                (*entry->made)[index] = Mlt::Producer(); // the timeline holds it now (or it isn't needed)
                if (done == 1) {
                    ++entry->replaced;
                    any = true;
                }
            }
            entry->applyMs += clock.elapsed() - started;
            if (busy)
                break;
            if (entry->next >= entry->plan.size()) {
                // clips changed or added since it was planned: plan those again
                const QList<QUuid> left = dock ? dock->copySwapClips(entry->source, *entry->configured)
                                               : QList<QUuid>();
                if (!left.isEmpty() && entry->rounds < kRounds) {
                    entry->toPlan = left;
                    entry->plan.clear();
                    entry->made.reset();
                    entry->next = 0;
                    entry->rounds++;
                    entry->state = Entry::Planning;
                } else {
                    entry->longestMs = qMax(entry->longestMs, clock.elapsed());
                    finish(entry);
                    MLT.setPreviewScale(PlaybackQuality::previewScale(MLT.profile().width(),
                                                                      MLT.profile().height(),
                                                                      Settings.playerPreviewScale()));
                }
            }
        }
    }
    if (began) {
        qApp->setProperty("letitedit_copy_swap", false);
        MAIN.setWindowModified(modified);
    }
    bool applying = false;
    bool planning = false;
    for (const auto &entry : std::as_const(m_entries)) {
        applying = applying || entry->state == Entry::Applying;
        planning = planning || entry->state == Entry::Planning || entry->state == Entry::Opened;
    }
    if (m_swapping && (!applying || held())) {
        // the run of steps is over: the frame on screen drawn again from the clips now in (it was paused), where the
        // run began, or where the person has since moved the playhead
        endRun();
        // Quarter or half speed started during the run: its steps draw each frame from the clips now in, and
        // MLT.play(0.0) would stop them (the video widget's play(0) emits paused, and the player stops stepping)
        if (MLT.producer() && !ProxyManager::slowPlaying()) {
            const int now = MLT.producer()->position();
            MLT.producer()->seek(now != m_pausedAt ? now : m_swapPosition);
            MLT.play(0.0);
        }
    }
    if (m_batch && !applying && !planning) {
        // the batch is in: playing resumes where it paused
        m_batch = false;
        m_lastBatch.start();
        if (MLT.producer())
            MLT.play(m_batchSpeed);
    }
    const qint64 took = clock.elapsed();
    for (const auto &entry : std::as_const(m_entries))
        entry->longestMs = qMax(entry->longestMs, took);
    if (took > 100 && any)
        LOG_INFO() << "copy swap: the window's thread took" << took << "ms for one step";
    if (planning || (applying && !held()))
        schedule(kGapMs);
    else if (applying)
        schedule(kHeldPollMs);
    // rule 2 (copyswap.h): the clips taken out go kReleaseMs after their run of edits ended
    if (m_removed && !m_removed->isEmpty() && !m_swapping) {
        const qint64 since = m_runEnded.isValid() ? m_runEnded.elapsed() : 0;
        if (since >= kReleaseMs)
            releaseRemoved(false);
        else
            schedule(int(kReleaseMs - since));
    }
}
