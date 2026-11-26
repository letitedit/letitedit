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

#ifndef FIRSTCUT_H
#define FIRSTCUT_H

#include <QString>
#include <QStringList>

class MainWindow;

// letitedit "New video" (it was "Make a first cut"): three stages, with Back always possible (T97). Video: footage or an
// idea, what you are making, how long, an optional song. Look: one browser of Looks and styles, "Let the AI choose" first
// and chosen by default. Ready: the Look's boxes, anything to keep or avoid, which AI, Turbo, and the one big action. The
// person's own AI (the chat panel's Claude Code or Codex, with the letitedit skills) builds the cut and takes fixes in plain
// words.
void showFirstCutDialog(MainWindow *window, bool shortEntry = false);

// The message the chat panel receives (also used by tests). kind: "short", "long", "both" or "custom" (custom: what
// the person typed). style: "" or "none" for no style (the brief's `style: none`), else the pack's name; label is its
// name on the card, mine: the person's own style (My style). look: for a Style with Looks (Talking head), the Look's id
// or "auto" (Let the AI pick) - the brief's `look` line, with the style line `none`; lookLabel and styleKindLabel are
// their names on the cards. inputs: what the person gave the Look up front, already worded by role (T64); noFootage: the
// Look draws everything, so there is no footage folder to name. turbo (T70): the person ticked Turbo, which "sacrifices
// quality for speed" on this first run through only; it adds the brief's `turbo: on` line and never touches the AI, model
// or effort.
QString firstCutRequest(const QString &folder,
                        const QString &kind,
                        const QString &length,
                        const QString &about,
                        const QString &style = QString(),
                        const QString &styleLabel = QString(),
                        bool mine = false,
                        const QString &custom = QString(),
                        const QStringList &files = QStringList(),
                        const QString &look = QString(),
                        const QString &lookLabel = QString(),
                        const QString &styleKindLabel = QString(),
                        const QString &inputs = QString(),
                        bool noFootage = false,
                        bool turbo = false);

#endif // FIRSTCUT_H
