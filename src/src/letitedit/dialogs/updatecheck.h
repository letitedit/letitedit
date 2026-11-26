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

#ifndef UPDATECHECK_H
#define UPDATECHECK_H

// T368: the update check. At most once a day it reads one small public file naming the newest build
// ({"format": "letitedit-latest/1", "build": "20261201.1", "version": "...", "url": "https://letitedit.app/...",
// "notes": "..."}); if it is newer than this build, a quiet note in the status bar and the Help menu link to the
// download page. Nothing is downloaded or installed by letitedit. Help > Check for updates automatically turns it off.
// The setting and the last check are in <appdata>/update-check.json.
//
// The file's address: LETITEDIT_UPDATE_URL when set ("off": none), else the built-in address, used only by the main
// profile. The built-in address is empty until its hosting is approved: until then nothing is checked.

#include <QString>

class QWidget;
class QMenu;

namespace UpdateCheck {

QString updateUrl();
// "20261201.1" newer than "20261124.3"; false when either isn't a build name
bool isNewer(const QString &latest, const QString &mine);
// Help menu: Check for updates, Check for updates automatically
void addMenuItems(QWidget *window, QMenu *help);
// 30 s after start (then hourly while open): checks when the setting is on and a day has passed since the last check
void startDaily(QWidget *window);

} // namespace UpdateCheck

#endif // UPDATECHECK_H
