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

#ifndef EXPORTCHECKS_H
#define EXPORTCHECKS_H

#include <QList>
#include <QString>

#include <functional>

class MainWindow;

// letitedit: the quick look before an export - length for each phone app, text and captions out from under the apps'
// buttons, captions there at all, black gaps between clips, a slow first second, even volume. Each problem says what
// it means in plain words and offers the fix or shows the spot.
namespace ExportChecks {

struct Check
{
    enum Level { Good, Note, Warning };
    Level level;
    QString text;
    QString button;           // empty: nothing to press
    std::function<void()> act; // what the button does (after the list closes)
    bool keepOpen = false;     // the button does its job and the list stays (Copy)
};

QList<Check> run(MainWindow *window, bool evenVolume);
// True to go ahead: at once when nothing needs a look, else when the person presses Export Anyway.
bool confirm(MainWindow *window, bool evenVolume);

} // namespace ExportChecks

#endif // EXPORTCHECKS_H
