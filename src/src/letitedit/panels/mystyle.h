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

#ifndef MYSTYLE_H
#define MYSTYLE_H

#include <QJsonObject>
#include <QString>
#include <QStringList>

class MainWindow;
class QUndoCommand;

// Personal Look preferences share Learn's revision store and the Look-library resolver.
namespace MyStyle {

QString folder();
// The person's own styles (packs with letitedit.json), by name.
QStringList styles();
QString active();
QString legacyLook(const QString &name);
// The caption look of the video's shown captions (or the chosen look) and the app's pause and music settings, merged
// into the style (made when new). Empty on success, else why not.
QString save(MainWindow *window, const QString &name);
// Makes it the look for new captions and the settings for Remove pauses and Add music, restyles the shown captions
// and sets the project's style, as one undo step. Returns the line for the status bar, or empty if the style could
// not be read.
QString apply(MainWindow *window, const QString &name);
// The project's style (letitedit_ai:style on the timeline), set as an undo step; empty name clears it.
void setProjectStyle(MainWindow *window, const QString &name);
QString projectStyle(MainWindow *window);
// An undo command that sets properties of the project itself (the timeline's tractor; a null value removes one), for
// the bridge's apply_transaction project_properties (STYLES.md 5.4).
QUndoCommand *projectPropertiesCommand(const QJsonObject &properties, const QString &label);

void show(MainWindow *window);
// The open My style panel, for checks (the bridge's my_style_state): its style, unsaved changes, status line.
QJsonObject panelState();
// Checks: choose another style in the open panel's list, as a person would (queued, so its question can come up).
void selectInPanel(const QString &name);

} // namespace MyStyle

#endif // MYSTYLE_H
