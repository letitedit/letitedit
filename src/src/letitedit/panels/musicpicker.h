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

#ifndef MUSICPICKER_H
#define MUSICPICKER_H

#include <QList>
#include <QString>
#include <QStringList>

class MainWindow;
class QWidget;

// letitedit "Add music": the best-fitting song from the person's music folder and the free library goes straight in;
// the Music & sound panel lists every song, best fit first, each playable beside the video. The song goes on
// its own "Music" track under the whole video, set against the talking (quieter while someone talks, up in the
// gaps), with a fade in and out. When the video is longer than the song, other songs follow it (the best fit for the
// time left, another artist, the same feel), each at its own level. One Undo removes it.
namespace MusicPicker {

struct Song
{
    QString path;
    QString title;
    QString artist;
    QString genre;
    QString mood;
    double seconds = 0.0; // 0 until known
    int bpm = 0;          // 0 means no reliable steady beat or not indexed
};

struct Options
{
    QString song;
    int volume = 1;      // 0 low, 1 medium, 2 high
    bool duck = true;    // quieter while someone talks
    bool replace = true; // put it on the existing music track, replacing what is there
    int track = -1;      // the music track to replace; -1 for the first one
    QStringList chain;   // the songs after the first, in order (fitted() fills it, so a refit keeps them); Add music
                         // picks more when the video is longer than these cover
};

void addMusic(MainWindow *window);
// The music list as a panel (the "Music" tab of the Music & sound dock): every song best fit first, Play to hear it,
// Use This Song to put it in (or change the one there and its volume). showMusicPanel brings it up, refreshed.
QWidget *createMusicPanel(MainWindow *window, QWidget *parent);
void showMusicPanel(MainWindow *window);
// The work behind the dialog's Add button. Returns the line for the status bar, or an empty string if nothing changed.
QString apply(MainWindow *window, const Options &options);
// Track names taken as music (and never as talking): Music, Song, Score, Bed.
bool isMusicName(const QString &trackName);
// The songs and settings Add music used on this track, if the track holds just its pieces. Remove pauses uses it to
// fit the music again to the shorter video, so it still ends with a fade and dips under the talking where it now is.
bool fitted(MainWindow *window, int track, Options &options);

QString musicFolder();
// letitedit's own free library: songs dedicated to the public domain (CC0), usable in any video with no credit.
QString freeLibraryFolder();
// The person's folder and the free library together, by title.
QList<Song> allSongs(const QString &folder);
// Every song in the folder, with titles, artists and lengths from any list (CSV) kept beside the music.
QList<Song> library(const QString &folder);
QList<Song> suggest(const QList<Song> &songs, double videoSeconds, quint32 seed);
// Every song, best fit for this video first: long enough not to repeat, not used lately, the style's music taste
// (My style), calm under talking and livelier for a video nobody talks in.
QList<Song> ranked(const QList<Song> &songs, double videoSeconds, bool talking);

} // namespace MusicPicker

#endif // MUSICPICKER_H
