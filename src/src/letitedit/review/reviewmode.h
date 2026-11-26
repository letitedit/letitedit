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

#ifndef REVIEWMODE_H
#define REVIEWMODE_H

#include <QJsonObject>

class MainWindow;

// letitedit "Review": the video full screen, played by the real player (with sound). Pause anywhere, draw on the frame
// and type or say what should change; each note sticks to its moment. Live Review (livereview.h): just talk and draw while it
// plays; a pause ends a note and the AI works on a copy, one note at a time. Submit for re-edit keeps
// the video as it is now as an earlier version (<name> vN.mlt, listed in Versions of This Video), writes the notes and
// the marked frames to <name>.letitedit/review/<time>/ and hands them to the person's AI in the chat panel, which makes
// the changes in the open project as Undo steps. Notes not yet sent are kept in <name>.letitedit/review/notes.json.
// Frames are made into pictures off the screen thread at the size shown, only the part of the picture a stroke
// touches is painted again, and PNGs are written on their own thread, so drawing keeps up with the pen over the
// playing video and opening and closing are quick.
namespace ReviewMode {

void show(MainWindow *window);
void initializeQueue(MainWindow *window);
// What Review shows (open, notes, recording, the picture's size) and, for QA, its drawing measurements.
QJsonObject state();
// QA actions (LETITEDIT_QA): synthetic pen strokes over the playing video or a still frame, measured; the old drawing
// code for a before/after measurement.
void installQaActions(MainWindow *window);

} // namespace ReviewMode

#endif // REVIEWMODE_H
