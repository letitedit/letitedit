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

#ifndef SHORTSMAKER_H
#define SHORTSMAKER_H

#include <QString>

class MainWindow;

// letitedit "Make shorts from this video": the person's own AI (the chat panel, with the letitedit-shorts skill)
// finds the moments of the open long video that stand on their own and makes each a vertical short in its own
// project next to it (exported too, if asked), leaving the long video as it is.
void showShortsDialog(MainWindow *window);

// The message the chat panel receives (also used by tests).
QString shortsRequest(const QString &project, double seconds, int count, int length, const QString &about,
                      bool exportThem);

#endif // SHORTSMAKER_H
