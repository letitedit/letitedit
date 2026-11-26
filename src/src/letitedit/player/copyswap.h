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

// letitedit (T366): playback copies go in without holding the window. A heavy project's copies used to go in one clip
// at a time on the window's thread, each clip's replacement opened and probed there (0.4-1 s a copy, 15-24 s in all
// on a 130-clip project, T315). Now each ready copy is opened on a worker thread, the window's thread writes what each
// clip's replacement is made from (a few milliseconds a clip), the worker makes the replacements, and the window's
// thread only puts them in, a few at a time, while the player is paused (or, after a copy has waited 20 s of playing,
// in one batch with playing paused for it). The steps are the ones TimelineDock::replaceClipsWithHash takes, so the
// clips that come out are the same.
// On by default; LETITEDIT_COPY_SWAP=0 (or LETITEDIT_COPY_SWAP_OLD=1) goes back to replaceClipsWithHash's way.
//
// Who owns a clip taken out (T366b, tests/t366/REPORT.md). The engine counts references: the track holds one on each
// clip, and every frame the player builds holds one on each clip (and filter) that made it, taken while the player's
// thread builds the frame holding the timeline's lock. A clip is closed when the last reference goes. Two rules keep
// that count true while copies go in:
//  1. Each edit holds the same timeline lock (TimelineDock::applyCopySwap), so the player never finds a clip in its
//     track, has it closed by the edit, and then counts a reference on the closed clip. That happened once (24 Nov): the
//     player's audio thread, dropping its queued frames on a pause, closed such a clip a second time and crashed.
//     The window never waits on that lock: an edit takes it only if it is free (while the player builds a frame, which
//     can take a few hundred ms when it opens a clip's file, the edit goes on the next turn), and an edit asks for no
//     redraw of its own (the run redraws once at its end), so the player is seldom building one.
//  2. The clips taken out (each cut and the clip under it) are kept here, not closed on the spot, until kReleaseMs
//     after the run of edits has ended (paused, its frame drawn again from the new clips, so frames from before are
//     dropped); then a worker thread lets them go. Whatever still holds one (a frame on screen, the filter panel)
//     closes it when it lets go, as always.

#ifndef COPYSWAP_H
#define COPYSWAP_H

#include <QElapsedTimer>
#include <QList>
#include <QObject>
#include <QString>
#include <QThreadPool>
#include <QTimer>

#include <atomic>
#include <memory>

namespace Mlt {
class Producer;
}

class CopySwap : public QObject
{
    Q_OBJECT
public:
    static CopySwap &instance();
    static bool enabled();
    // a copy is ready for `source`: it goes in on every clip playing the original (the caller has counted it in
    // MainWindow's automaticProxyWorkers; it is counted out, and automaticProxyReady counts it, once it is in)
    void add(const QString &source, const QString &copy);
    // Settings > Playback Quality is changing: copies not yet in are dropped
    void clear();

private:
    explicit CopySwap(QObject *parent);
    struct Entry;
    std::shared_ptr<Entry> find(quint64 id) const;
    void opened(quint64 generation, quint64 id, std::shared_ptr<Mlt::Producer> configured, qint64 ms);
    void startPlanning(Entry &entry);
    void startMaking(Entry &entry);
    void made(quint64 generation, quint64 id, std::shared_ptr<QList<Mlt::Producer>> producers, qint64 ms);
    void finish(const std::shared_ptr<Entry> &entry);
    bool playing() const;
    bool held() const;
    void tick();
    void schedule(int ms = 0);
    void endRun();
    void releaseRemoved(bool now);

    QList<std::shared_ptr<Entry>> m_entries;
    QThreadPool m_pool;
    QTimer m_timer;
    quint64 m_nextId = 0;
    std::atomic<quint64> m_generation{0};
    bool m_swapping = false; // a run of steps that paused the player (refreshed once at its end)
    int m_swapPosition = 0;
    int m_pausedAt = -1; // the playhead right after the run paused the player (a move from it is the person's)
    bool m_batch = false; // playing paused for a batch of copies that waited (resumes after)
    double m_batchSpeed = 0.0;
    QElapsedTimer m_lastBatch;
    QElapsedTimer m_playingFor; // since the person's playing (at 1x or faster) was last seen to start (T366b)
    // rule 2 above: the clips taken out, kept until kReleaseMs after the run of edits that took them out has ended
    std::shared_ptr<QList<Mlt::Producer>> m_removed;
    QElapsedTimer m_runEnded;
};

#endif // COPYSWAP_H
