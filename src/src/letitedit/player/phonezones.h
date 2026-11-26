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

#ifndef PHONEZONES_H
#define PHONEZONES_H

#include <QList>
#include <QObject>
#include <QRectF>
#include <QVariantList>

// letitedit: where TikTok, YouTube Shorts and Instagram Reels draw their own buttons, captions and bars over a
// vertical video, as fractions of the frame. The numbers come from the platforms folder the AI tools use (one place
// to update), with built-in copies if it is missing. The player shows them from its grid menu (values 30000-30003)
// and while text is dragged; the export checklist tests text and captions against them.
class PhoneZones : public QObject
{
    Q_OBJECT
public:
    struct Zone
    {
        QString app;   // display name, e.g. "TikTok"
        QString label; // "buttons", "caption area", "top bar", "edge"
        QRectF rect;
    };

    explicit PhoneZones(QObject *parent = nullptr);

    // app: "tiktok", "youtube_shorts" or "instagram_reels"; empty for all three.
    static QList<Zone> zones(const QString &app = QString());
    // Apps whose zones cover more than a sixth of the box (fractions of the frame).
    static QStringList appsCovering(const QRectF &box);

    // For the player overlay: 30000 all apps, 30001 TikTok, 30002 YouTube Shorts, 30003 Instagram Reels.
    Q_INVOKABLE QVariantList forGrid(int grid) const;
    Q_INVOKABLE QStringList coveringApps(double x, double y, double w, double h) const;
};

#endif // PHONEZONES_H
