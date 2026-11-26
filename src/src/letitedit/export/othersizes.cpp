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

#include "letitedit/export/othersizes.h"

#include "letitedit/dialogs/lejobs.h"
#include "letitedit/dialogs/lefeatures.h"
#include "mainwindow.h"

#include "Logger.h"
#include "letitedit/letitedit.h"
#include "util.h"

#include <QButtonGroup>
#include <QCheckBox>
#include <QCoreApplication>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QMessageBox>
#include <QPushButton>
#include <QRadioButton>
#include <QVBoxLayout>

#include <cmath>

namespace OtherSizes {

namespace {

QString tool(const QString &name)
{
    return QDir(qApp->applicationDirPath()).filePath(name);
}

int even(double v)
{
    return qMax(2, int(std::lround(v / 2.0)) * 2);
}

struct Probe
{
    QSize size; // as shown, after any rotation
    double seconds = 0.0;
};

Probe probe(const QString &video)
{
    Probe result;
    QByteArray printed;
    if (!leRun(tool("ffprobe"),
               {"-v", "error", "-select_streams", "v:0", "-show_entries",
                "stream=width,height:stream_side_data=rotation:stream_tags=rotate:format=duration", "-of", "json", video},
               nullptr,
               &printed,
               20000))
        return result;
    const QJsonObject json = QJsonDocument::fromJson(printed).object();
    const QJsonObject stream = json.value("streams").toArray().first().toObject();
    int width = stream.value("width").toInt(), height = stream.value("height").toInt();
    int rotation = stream.value("tags").toObject().value("rotate").toString().toInt();
    for (const auto &side : stream.value("side_data_list").toArray()) {
        if (side.toObject().contains("rotation"))
            rotation = side.toObject().value("rotation").toInt();
    }
    if (std::abs(rotation) % 180 == 90)
        std::swap(width, height);
    result.size = QSize(width, height);
    result.seconds = json.value("format").toObject().value("duration").toString().toDouble();
    return result;
}

bool sameShape(const Shape &shape, const QSize &video)
{
    if (video.isEmpty())
        return false;
    const double a = double(shape.across) / shape.down, b = double(video.width()) / video.height();
    return std::abs(a - b) / a < 0.03;
}

} // namespace

QList<Shape> shapes()
{
    return {{"9x16", QObject::tr("Vertical 9:16 (TikTok, Shorts, Reels)"), 9, 16},
            {"1x1", QObject::tr("Square 1:1 (Instagram and Facebook feed)"), 1, 1},
            {"4x5", QObject::tr("Portrait 4:5 (Instagram feed)"), 4, 5},
            {"16x9", QObject::tr("Wide 16:9 (YouTube)"), 16, 9}};
}

QSize sizeFor(const Shape &shape, const QSize &video)
{
    const int shortSide = qBound(720, qMin(video.width(), video.height()), 1080);
    if (shape.across >= shape.down)
        return QSize(even(double(shortSide) * shape.across / shape.down), even(shortSide));
    return QSize(even(shortSide), even(double(shortSide) * shape.down / shape.across));
}

QString make(const QString &video, const Shape &shape, bool fill, QProgressDialog *progress)
{
    const Probe info = probe(video);
    if (info.size.isEmpty())
        return QString();
    const QSize out = sizeFor(shape, info.size);
    const int w = out.width(), h = out.height();
    QString graph;
    if (fill) {
        graph = QStringLiteral("[0:v]scale=%1:%2:force_original_aspect_ratio=increase,crop=%1:%2,setsar=1[v]").arg(w).arg(h);
    } else {
        // The whole picture over a blurred, slightly darker copy of itself (blurred small, then enlarged: quick).
        graph = QStringLiteral("[0:v]split=2[a][b];[a]scale=%3:%4:force_original_aspect_ratio=increase,crop=%3:%4,"
                               "gblur=sigma=6,scale=%1:%2,eq=brightness=-0.07[bg];[b]scale=%1:%2:force_original_"
                               "aspect_ratio=decrease[fg];[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
                    .arg(w)
                    .arg(h)
                    .arg(even(w / 8.0))
                    .arg(even(h / 8.0));
    }
    const QFileInfo source(video);
    QString target = source.dir().filePath(QStringLiteral("%1 %2.mp4").arg(source.completeBaseName(), shape.key));
    for (int n = 2; QFileInfo::exists(target); ++n)
        target = source.dir().filePath(QStringLiteral("%1 %2 %3.mp4").arg(source.completeBaseName(), shape.key).arg(n));

    // one heavy job at a time on this PC (the render lock, first come first served), at most 4 threads
    const QString threads = QString::number(leThreads());
    const QStringList args{"-hide_banner", "-nostats", "-loglevel", "error", "-y", "-threads", threads, "-i", video,
                           "-filter_complex_threads", threads, "-filter_complex", graph, "-map", "[v]", "-map", "0:a?",
                           "-c:v", "libx264", "-preset", "fast", "-crf", "19", "-pix_fmt", "yuv420p", "-threads",
                           threads, "-c:a", "copy", "-movflags", "+faststart", "-progress", "pipe:1", target};
    QByteArray printed;
    const bool ok = leRunHeavy(QStringLiteral("letitedit Other sizes %1").arg(QFileInfo(target).fileName()),
                               tool("ffmpeg"), args, progress, &printed, -1, [&](const QByteArray &line) {
                                   if (progress && info.seconds > 0.0 && line.startsWith("out_time_us=")) {
                                       const double done = line.mid(12).toDouble() / 1e6;
                                       progress->setValue(qBound(0, int(done / info.seconds * 1000.0), 999));
                                   }
                               });
    if (!ok) {
        if (!(progress && progress->wasCanceled()))
            LOG_WARNING() << "other size failed:" << printed.right(600);
        QFile::remove(target);
        return QString();
    }
    return target;
}

void show(QWidget *parent, const QString &video)
{
    const Probe info = probe(video);
    if (info.size.isEmpty()) {
        QMessageBox::warning(parent, QObject::tr("Other Sizes"), QObject::tr("That video could not be read."));
        return;
    }
    QDialog dialog(parent);
    dialog.setObjectName(QStringLiteral("otherSizesDialog"));
    dialog.setWindowTitle(QObject::tr("Other Sizes"));
    auto *layout = new QVBoxLayout(&dialog);
    auto *intro = new QLabel(QObject::tr("Copies of <b>%1</b> in other shapes, for other places. They are saved next to "
                                         "it.")
                                 .arg(QFileInfo(video).fileName().toHtmlEscaped()));
    intro->setWordWrap(true);
    layout->addWidget(intro);
    const bool wide = info.size.width() > info.size.height();
    QList<QPair<Shape, QCheckBox *>> boxes;
    for (const auto &shape : shapes()) {
        if (sameShape(shape, info.size))
            continue;
        const QSize size = sizeFor(shape, info.size);
        auto *box = new QCheckBox(QStringLiteral("%1, %2×%3").arg(shape.label).arg(size.width()).arg(size.height()));
        box->setObjectName(QStringLiteral("otherSize_") + shape.key);
        const bool usual = wide ? shape.key == QLatin1String("9x16") : shape.key == QLatin1String("1x1");
        box->setChecked(leSettings().value(QStringLiteral("sizes/") + shape.key, usual).toBool());
        layout->addWidget(box);
        boxes.append({shape, box});
    }
    layout->addSpacing(6);
    layout->addWidget(new QLabel(QObject::tr("How the picture fits:")));
    auto *whole = new QRadioButton(QObject::tr("Whole picture, with a blurred copy behind it (nothing is cut off)"));
    whole->setObjectName(QStringLiteral("otherSizesWhole"));
    auto *fill = new QRadioButton(QObject::tr("Fill the frame (the edges are cropped)"));
    fill->setObjectName(QStringLiteral("otherSizesFill"));
    (leSettings().value("sizes/fill", false).toBool() ? fill : whole)->setChecked(true);
    layout->addWidget(whole);
    layout->addWidget(fill);
    // letitedit_reframe through the person's AI: a crop that follows the people (and splits or insets where two can't
    // share one), made from the project, not the exported file
    auto *people = new QRadioButton(QObject::tr("Keep the people in frame: your AI reframes each shot from the project "
                                                "(a few minutes)"));
    people->setObjectName(QStringLiteral("otherSizesPeople"));
    const bool saved = !MAIN.fileName().isEmpty();
    people->setEnabled(saved);
    people->setToolTip(saved ? QObject::tr("Smart framing that follows faces, hands and what's being shown; your AI "
                                           "also re-fits the captions")
                             : QObject::tr("Save your video first: your AI reframes the saved project"));
    layout->addWidget(people);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel);
    auto *go = buttons->addButton(QObject::tr("Make Copies"), QDialogButtonBox::AcceptRole);
    go->setObjectName(QStringLiteral("otherSizesGo"));
    go->setDefault(true);
    QObject::connect(people, &QRadioButton::toggled, go, [go](bool on) {
        go->setText(on ? QObject::tr("Ask My AI to Make Them") : QObject::tr("Make Copies"));
    });
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted)
        return;

    QList<Shape> chosen;
    for (const auto &pair : boxes) {
        leSettings().setValue(QStringLiteral("sizes/") + pair.first.key, pair.second->isChecked());
        if (pair.second->isChecked())
            chosen.append(pair.first);
    }
    if (!people->isChecked())
        leSettings().setValue("sizes/fill", fill->isChecked());
    if (chosen.isEmpty())
        return;
    if (people->isChecked()) {
        QStringList keys;
        for (const auto &shape : chosen)
            keys << shape.key;
        LeFeatures::askReframe(&MAIN, video, keys);
        return;
    }
    QStringList made;
    for (int i = 0; i < chosen.size(); ++i) {
        QProgressDialog progress(QObject::tr("Making the %1 copy (%2 of %3)...")
                                     .arg(chosen[i].label.section(QLatin1Char(' '), 0, 1))
                                     .arg(i + 1)
                                     .arg(chosen.size()),
                                 QObject::tr("Cancel"),
                                 0,
                                 1000,
                                 parent);
        progress.setWindowTitle(QObject::tr("Other Sizes"));
        progress.setWindowModality(Qt::WindowModal);
        progress.setMinimumDuration(0);
        progress.setValue(0);
        const QString path = make(video, chosen[i], fill->isChecked(), &progress);
        if (progress.wasCanceled())
            break;
        if (!path.isEmpty())
            made << path;
    }
    if (made.isEmpty())
        return;
    QMessageBox box(QMessageBox::Information,
                    QObject::tr("Other Sizes"),
                    QObject::tr("Made %1 of %2.").arg(made.size()).arg(chosen.size()),
                    QMessageBox::Close,
                    parent);
    QStringList names;
    for (const auto &path : made)
        names << QFileInfo(path).fileName();
    box.setInformativeText(names.join('\n'));
    auto *folder = box.addButton(QObject::tr("Show in Folder"), QMessageBox::ActionRole);
    box.exec();
    if (box.clickedButton() == folder)
        Util::showInFolder(made.first());
}

} // namespace OtherSizes
