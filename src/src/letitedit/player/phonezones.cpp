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

#include "letitedit/player/phonezones.h"

#include "letitedit/airoot.h"

#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QVariantMap>

namespace {

const QStringList kApps{"tiktok", "youtube_shorts", "instagram_reels"};

QString shortLabel(const QString &name)
{
    const QString n = name.toLower();
    if (n.startsWith("right"))
        return QObject::tr("buttons");
    if (n.startsWith("bottom"))
        return QObject::tr("caption area");
    if (n.startsWith("top"))
        return QObject::tr("top bar");
    return QObject::tr("edge");
}

QList<PhoneZones::Zone> builtIn(const QString &app)
{
    // Copies of platforms/*.json (checked 2026-10-19) for an install without the platforms folder.
    if (app == "tiktok")
        return {{"TikTok", QObject::tr("top bar"), {0, 0, 1, 0.068}},
                {"TikTok", QObject::tr("caption area"), {0, 0.809, 1, 0.191}},
                {"TikTok", QObject::tr("buttons"), {0.889, 0, 0.111, 1}}};
    if (app == "youtube_shorts")
        return {{"YouTube Shorts", QObject::tr("top bar"), {0, 0, 1, 0.0625}},
                {"YouTube Shorts", QObject::tr("caption area"), {0, 0.844, 1, 0.156}},
                {"YouTube Shorts", QObject::tr("buttons"), {0.911, 0, 0.089, 1}}};
    return {{"Instagram Reels", QObject::tr("top bar"), {0, 0, 1, 0.14}},
            {"Instagram Reels", QObject::tr("caption area"), {0, 0.65, 1, 0.35}},
            {"Instagram Reels", QObject::tr("edge"), {0, 0, 0.06, 1}},
            {"Instagram Reels", QObject::tr("buttons"), {0.94, 0, 0.06, 1}}};
}

QList<PhoneZones::Zone> load(const QString &app)
{
    static QHash<QString, QList<PhoneZones::Zone>> cache;
    if (cache.contains(app))
        return cache.value(app);
    QList<PhoneZones::Zone> zones;
    QFile file(aiRootPath(QStringLiteral("platforms/%1.json").arg(app)));
    if (file.open(QIODevice::ReadOnly)) {
        const QJsonObject profile = QJsonDocument::fromJson(file.readAll()).object();
        const QString name = profile.value("name").toString();
        for (const auto &value : profile.value("safe_zones").toObject().value("value").toArray()) {
            const QJsonObject z = value.toObject();
            const QRectF rect(z.value("x").toDouble(), z.value("y").toDouble(), z.value("w").toDouble(),
                              z.value("h").toDouble());
            if (!name.isEmpty() && rect.isValid())
                zones.append({name, shortLabel(z.value("name").toString()), rect});
        }
    }
    if (zones.isEmpty())
        zones = builtIn(app);
    cache.insert(app, zones);
    return zones;
}

} // namespace

PhoneZones::PhoneZones(QObject *parent)
    : QObject(parent)
{}

QList<PhoneZones::Zone> PhoneZones::zones(const QString &app)
{
    if (!app.isEmpty())
        return load(app);
    QList<Zone> all;
    for (const auto &a : kApps)
        all += load(a);
    return all;
}

QStringList PhoneZones::appsCovering(const QRectF &box)
{
    QStringList apps;
    const double area = box.width() * box.height();
    if (area <= 0.0)
        return apps;
    for (const auto &zone : zones()) {
        const QRectF overlap = zone.rect.intersected(box);
        if (overlap.width() * overlap.height() > area / 6.0 && !apps.contains(zone.app))
            apps.append(zone.app);
    }
    return apps;
}

QVariantList PhoneZones::forGrid(int grid) const
{
    QVariantList list;
    const QString app = grid >= 30001 && grid <= 30003 ? kApps[grid - 30001] : QString();
    for (const auto &zone : zones(app)) {
        list << QVariantMap{{"app", zone.app},
                            {"label", zone.label},
                            {"x", zone.rect.x()},
                            {"y", zone.rect.y()},
                            {"w", zone.rect.width()},
                            {"h", zone.rect.height()}};
    }
    return list;
}

QStringList PhoneZones::coveringApps(double x, double y, double w, double h) const
{
    return appsCovering(QRectF(x, y, w, h));
}
