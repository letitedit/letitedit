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

#ifndef MYASSETS_H
#define MYASSETS_H

#include <QJsonObject>
#include <QString>
#include <QStringList>

class MainWindow;

// letitedit "My assets" (T69): the person's own logo, intro, outro, colours, clips, sounds, pictures and fonts, in one
// folder that is the same for every video (Documents\letitedit\My assets, or my_assets_dir in settings.json) and stays
// when letitedit is reinstalled. The panel lists them, takes files dropped on it or added with a button, keeps a
// one-line note per item and lets the person take one out. All of it goes through bridge\my_assets.py, the code the
// AI's letitedit_my_assets tool uses, so both see the same folder, notes and measurements. The person's files are only
// read: adding copies a file in, taking out moves the copy to the folder's hidden .letitedit\removed.
namespace MyAssets {

void show(MainWindow *window);
// The open panel, for checks (the bridge's my_assets_state): its folder, items, selection, note, status.
QJsonObject panelState();
// Checks: do in the open panel what a person does (queued, so the panel's own code runs as it would for a click).
void addToPanel(const QStringList &paths);
void selectInPanel(const QString &id);

} // namespace MyAssets

#endif // MYASSETS_H
