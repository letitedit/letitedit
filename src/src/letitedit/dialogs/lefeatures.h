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

#ifndef LEFEATURES_H
#define LEFEATURES_H

#include <QJsonArray>
#include <QJsonObject>
#include <QString>
#include <QStringList>

class MainWindow;
class QWidget;

// letitedit's AI features as buttons where a beginner looks for them. Some run the tools directly on this PC, with
// progress, Cancel and the PC render lock (bridge/app_tools.py: Import a style, Stickers & sounds, Animated title,
// Line up separate sound, Check my video); the ones that need judgement send a short request to the person's own AI
// in the chat panel, shown there as a one-line summary (Clean up the voice, Dub this video, people-in-frame Other
// sizes).
namespace LeFeatures {

// The actions (Menu > File, Edit and AI) and the Stickers & sounds panel. After the AI menu exists, before the
// workspace gives the panels their headers.
void install(MainWindow *window);

void showLearn(MainWindow *window);

// The Stickers & sounds panel on the left. kinds: "" (everything) or a kind ("sfx": sound effects).
void showStickers(MainWindow *window, const QString &kinds = QString());
void showAnimatedTitle(MainWindow *window);
void showSyncSound(MainWindow *window);
// video: the file to check (default the last export of this window).
void showCheckVideo(MainWindow *window, const QString &video = QString());

// Requests to the person's AI (false when it couldn't take one; the reason is on the status bar).
bool askCleanVoice(MainWindow *window);
void showDub(MainWindow *window);
bool askReframe(MainWindow *window, const QString &video, const QStringList &shapes);

// The MLT XML of a file made ready for the timeline (a picture sized as a sticker in the middle of the frame, an
// animation, or a sound), named after the library asset it came from (asset, for the credit lines). seconds: how long
// a still picture stays (0: the default). size: the picture's box as a share of the frame's short side (0: as it is).
// caption: the clip's name on the timeline (default the file's).
QString producerXml(const QString &file, bool audio, const QString &asset, double seconds, double size, QString *why,
                    const QString &caption = QString());
// Puts that at the playhead on a free track named trackName (a new one when none is free there), as one undo step
// named label. False (why) when there is no timeline or the file can't be read.
bool placeAtPlayhead(MainWindow *window, const QString &xml, bool audio, const QString &trackName, const QString &label,
                     QString *why);
// A copy of a library file in the project's folder (<project folder>/Stickers & sounds, named `name` when given), or
// the file itself while the project isn't saved.
QString projectCopy(MainWindow *window, const QString &file, const QString &name = QString());

// The credit lines the video owes for library assets on its timeline as it is now ([{line, assets}]).
QJsonArray credits(MainWindow *window, int timeoutMs = 30000);
// Those lines as text for a video's description.
QString creditText(const QJsonArray &credits);

// The last export this window finished (Check my video's default).
void rememberExport(const QString &video);
QString lastExport();

// For checks (the bridge's features_state): the open feature dialogs and the Stickers & sounds panel.
QJsonObject state();

} // namespace LeFeatures

#endif // LEFEATURES_H
