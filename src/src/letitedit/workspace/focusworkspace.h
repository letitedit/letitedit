/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit workspace: the brand look and the simple layout over the engine's docks, actions, models and AI commands,
 * which all stay native. One header row (wordmark, menus, project, undo/redo, Ask the AI, Export), steps down the
 * left in the order a video gets made (Media, Cut, Captions, Music, Effects, AI; Export video in the header), plain panel names, a welcome
 * screen instead of the engine's New Project form, and a timeline bar with the few commands people use.
 */
#ifndef FOCUSWORKSPACE_H
#define FOCUSWORKSPACE_H

#include <QIcon>
#include <QString>

class MainWindow;

// LETITEDIT_WORKSPACE=classic turns the workspace off (the engine's own layout).
bool focusWorkspaceEnabled();
// letitedit's own line icons first (icons/letitedit/ui), the engine's theme icons for everything else.
QIcon focusWorkspaceIcon(const QString &name);

// The letitedit colours: ink for the window, cream for words, rust for the one action that matters on a screen,
// teal for where you are and what is selected.
namespace LetItEditColors {
constexpr const char *ink = "#161A1D";
constexpr const char *panel = "#1E2428";
constexpr const char *raised = "#262D32";
constexpr const char *lifted = "#2E363B";
constexpr const char *line = "#343B40";
constexpr const char *deep = "#0E1113";
constexpr const char *cream = "#F4EFE6";
constexpr const char *muted = "#AFA9A0";
constexpr const char *dim = "#6E6A62";
constexpr const char *rust = "#C8653B";
constexpr const char *rustLight = "#D4744A";
constexpr const char *rustDeep = "#A95431";
constexpr const char *teal = "#2A8597";
constexpr const char *tealDeep = "#144F5F";
constexpr const char *tealLight = "#9ED6E2";
constexpr const char *ok = "#7FBF8A";
} // namespace LetItEditColors

// The dark palette, before any window is made; then the workspace over the main window (focusworkspace.cpp).
void applyFocusPalette();
void installFocusWorkspace(MainWindow *window);

#endif // FOCUSWORKSPACE_H
