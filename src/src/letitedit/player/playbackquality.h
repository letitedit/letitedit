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

// letitedit (T214): Settings > Playback Quality, the size heavy footage plays at while editing. Heavy clips (HEVC,
// over 30 fps, over 1080p, on a cloud drive) play from light working copies made in the background
// (ProxyManager::watchAutomatic, bridge/playback_copies.py), and Review plays heavy timelines from a rendered preview
// (RenderedPreview); both are made at this size. Exports, checks and note pictures always read the originals.
//   Automatic  the sharpest size this PC decodes fast enough: a short test the copy worker runs once and keeps in the
//              copies' folder (pc-test.json); 540 until it has answered. While it plays copies above 540 at 1x, two
//              8 s stretches in a row that each skip four frames or more step it down a size for this PC (kept;
//              choosing Automatic again forgets it)
//   Smoothest  540 on the shorter side
//   Balanced   720
//   Sharpest   1080, or the original's own size when that is smaller
//   Off        the originals play; no copies are made and Review draws the timeline live
// T220: with the rendered preview on (sharpAhead), live frames never play above Automatic's size, so they play every
// frame; the preview draws the timeline at the choice's own size (Automatic: 1080) in the background and shows it
// wherever it is drawn, paused too.
// Each size keeps copies of its own. A change puts the originals back at once, then the new size's copies take their
// place as each is ready, in the background; nothing waits.
#ifndef PLAYBACKQUALITY_H
#define PLAYBACKQUALITY_H

#include <QJsonObject>
#include <QObject>
#include <QString>

class QAction;
class QMenu;

namespace PlaybackQuality {

enum class Choice { Automatic, Smoothest, Balanced, Sharpest, Off };

class Notifier : public QObject
{
    Q_OBJECT
signals:
    // Another choice was made: copy runs and queued copies of the old size stop (before the originals go back).
    void changing();
    // The new choice is in force (after the clips playing copies of another size have their originals back).
    void changed();
};

Choice choice();
void setChoice(Choice choice);
// The shorter side live frames play at, and the copies' size: 540, 720 or 1080 (Automatic: the PC test's pick, 540
// until it has answered; Balanced and Sharpest: their own size, never above Automatic's while sharpAhead()); 0 when Off.
int size();
// T220: the shorter side shown wherever the rendered preview has drawn the timeline (playing, stepping and paused):
// the choice's own size (Automatic: 1080) while sharpAhead(), else size(). Undrawn stretches play live at size(), so
// they play every frame while the preview draws.
int displaySize();
// Whether sharper choices show the rendered preview at their own size over lighter live frames (off with
// LETITEDIT_PLAYBACK_SHARP=off, LETITEDIT_MAIN_PREVIEW=off or LETITEDIT_PLAYBACK_PREVIEW=off: each choice then plays
// copies of its own size live, as before T220).
bool sharpAhead();
// The copy worker's --size: "540", "720", "1080" or "auto".
QString workerSize();
// The player's preview scale that goes with the copies, for this profile: the size above, never above the person's
// own Settings > Preview Scaling when one is set (selected > 0). Off: their own setting.
int previewScale(int profileWidth, int profileHeight, int selected);
Notifier *notifier();
// Settings > Playback Quality, placed before `before` in the Settings menu.
void addMenu(QMenu *settings, QAction *before);
// QA: the choice, the size, Automatic's PC test and the clips on copies now.
QJsonObject state();

} // namespace PlaybackQuality

#endif // PLAYBACKQUALITY_H
