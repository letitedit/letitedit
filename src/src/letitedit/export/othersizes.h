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

#ifndef OTHERSIZES_H
#define OTHERSIZES_H

#include <QList>
#include <QSize>
#include <QString>
#include <QStringList>

class QProgressDialog;
class QWidget;

// letitedit "Other sizes": copies of an exported video in other shapes for other places - vertical 9:16, square 1:1,
// portrait 4:5, wide 16:9 - either the whole picture over a blurred copy of itself (nothing is cut off, so captions
// and text stay readable) or filling the frame (the edges are cropped). Made with ffmpeg next to the video.
namespace OtherSizes {

struct Shape
{
    QString key;   // "9x16", "1x1", "4x5", "16x9"
    QString label; // shown in the dialog
    int across;    // aspect, e.g. 9
    int down;      // e.g. 16
};

QList<Shape> shapes();
// The frame size for a shape, from the video's own short side (720 to 1080 pixels).
QSize sizeFor(const Shape &shape, const QSize &video);
// Makes one copy; the file written, or empty if it failed or was cancelled.
QString make(const QString &video, const Shape &shape, bool fill, QProgressDialog *progress = nullptr);

// The dialog: pick shapes and how the picture fits, then make the copies.
void show(QWidget *parent, const QString &video);

} // namespace OtherSizes

#endif // OTHERSIZES_H
