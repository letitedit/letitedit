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

// letitedit (T214): a rendered preview of the timeline for smooth playback. A worker (bridge/playback_preview.py)
// draws the timeline once at a light size in cached chunks; a filter on the player's output shows a ready chunk's
// frame instead of drawing the timeline live, while it plays. Paused frames, and every stretch not ready yet, are
// drawn live as before. The sound is always the timeline's own, from the same frame. An edit makes the preview
// unusable at once; the worker then says which chunks still draw the same pictures, and draws again the others.
#ifndef RENDEREDPREVIEW_H
#define RENDEREDPREVIEW_H

#include <QJsonObject>

class MainWindow;
namespace Mlt {
class FilteredConsumer;
}

namespace RenderedPreview {

// The player's output: put the filter on it (once per output).
void attach(Mlt::FilteredConsumer &consumer);
// Review opened (chunks are drawn while it is open) or closed (the preview is kept and checked, nothing more drawn).
void reviewOpened(MainWindow *window, int position);
// T220: a heavy timeline open in the main window gets its preview drawn too, Review or not
void watchMain(MainWindow *window);
// how much of the timeline the main player's preview has drawn, 0-100; -1 when there is none to draw (a light
// timeline, Playback Quality Off, the worker not running)
int drawnPercent();
// T220: whether the preview being drawn is sharper than live frames play (Balanced, Sharpest or Automatic over lighter
// live frames): the drawn part shows at the choice's own size
bool drawsSharper();
void reviewClosed();
// Review's slower-than-normal speeds step paused frames: while on, those come from the preview too.
void setStepping(bool on);
// Where playing starts: the chunks from here on are drawn first.
void setFocus(int frame);
// Playing dropped frames: draw a preview even for a timeline that didn't look heavy.
void liveCannotKeepUp();
// Ready stretches for the timeline as it is now.
bool inUse();
// A preview is wanted for this timeline and not all of it is ready.
bool preparing();
// QA: what the preview and the player are doing (and with reset, counting afresh).
QJsonObject state(bool reset = false);

} // namespace RenderedPreview

#endif // RENDEREDPREVIEW_H
