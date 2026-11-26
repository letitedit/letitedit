/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit "Opening" panel: the video's hook (its first seconds) and a big New hook button. Hook candidates come from
 * bridge/hooks.py (the file <project>.letitedit/hooks.json and its command line, STYLES.md "Hooks"), fetched and
 * previewed in the background so the next one shows at once; each swap goes into the open video as one native Undo
 * step (hooks.py apply -> the live edit). Previous, Other words and Back to my original opening; the first cut's
 * Opening panel shows itself when the AI finishes a New video request.
 */
#ifndef HOOKPANEL_H
#define HOOKPANEL_H

#include <QJsonObject>
#include <QString>

class MainWindow;
class QDockWidget;

namespace HookPanel {

// The panel's dock (hidden until shown); safe to call more than once.
QDockWidget *install(MainWindow *window);
// Shows the Opening panel for the open project (fetching candidates if needed).
void show(MainWindow *window);
// What the panel shows and does, for the bridge (hook_state) and checks.
QJsonObject state();
// The opening in the open video, from its timeline: the id the last swap wrote on it in the same Undo step
// (letitedit_ai:hook), "h0" when no swapped-in opening is on the timeline, empty when that can't be told (an opening
// swapped in by an older build).
QString openingInVideo(MainWindow *window);

} // namespace HookPanel

#endif // HOOKPANEL_H
