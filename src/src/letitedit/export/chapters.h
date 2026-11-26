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

#ifndef CHAPTERS_H
#define CHAPTERS_H

#include <QList>
#include <QString>
#include <QStringList>

class MainWindow;

// letitedit "YouTube chapters": the timeline's chapter:<title> markers (the AI skills write the same) as the lines
// YouTube reads from a description - "0:00 Intro" - checked against YouTube's rules (a chapter at 0:00, at least three,
// each at least 10 seconds) and copied in one click. The person's AI can find the chapters.
namespace Chapters {

struct Chapter
{
    int frame;
    QString title;
    int marker; // index in the markers model; -1 for the 0:00 line added for YouTube
};

QList<Chapter> fromTimeline(MainWindow *window);
// With a 0:00 "Intro" line in front when the first chapter starts later, as YouTube requires.
QList<Chapter> forYouTube(const QList<Chapter> &chapters);
QString youtubeText(const QList<Chapter> &chapters, double fps);
// Plain-language problems with YouTube's rules; empty when the chapters will show.
QStringList problems(const QList<Chapter> &chapters, double fps, double seconds);

void show(MainWindow *window);

} // namespace Chapters

#endif // CHAPTERS_H
