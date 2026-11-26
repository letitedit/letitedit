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

#include "letitedit/export/exportchecks.h"

#include "actions.h"
#include "docks/timelinedock.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/letitedit.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/multitrackmodel.h"
#include "letitedit/export/pauseremover.h"
#include "letitedit/player/phonezones.h"
#include "letitedit/player/previewobjects.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"

#include <MltPlaylist.h>
#include <QAction>
#include <QApplication>
#include <QClipboard>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QGridLayout>
#include <QLabel>
#include <QPushButton>
#include <QRegularExpression>
#include <QTemporaryDir>
#include <QThread>
#include <QVBoxLayout>
#include <QtEndian>

#include <algorithm>

namespace ExportChecks {

namespace {

QString clock(double seconds)
{
    const int s = qRound(seconds);
    return QStringLiteral("%1:%2").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0'));
}

void showPhoneZones(MainWindow *window)
{
    if (auto action = window->findChild<QAction *>(QStringLiteral("phoneZonesAllAction"))) {
        if (!action->isChecked())
            action->trigger();
    }
}

// Where the caption text itself sits (about two lines) inside the caption box the look sets.
QRectF captionBlock(const QVariantMap &caption, double width, double height)
{
    const QString geometry = caption.value("geometry").toString();
    static const QRegularExpression percent(
        QStringLiteral("^\\s*(-?[0-9.]+)%/(-?[0-9.]+)%:(-?[0-9.]+)%x(-?[0-9.]+)%"));
    static const QRegularExpression pixels(QStringLiteral("^\\s*(-?[0-9.]+)[/ ](-?[0-9.]+)[: ](-?[0-9.]+)[x ](-?[0-9.]+)"));
    QRectF box(0.0, 0.75, 1.0, 0.2);
    if (const auto m = percent.match(geometry); m.hasMatch())
        box = QRectF(m.captured(1).toDouble() / 100.0,
                     m.captured(2).toDouble() / 100.0,
                     m.captured(3).toDouble() / 100.0,
                     m.captured(4).toDouble() / 100.0);
    else if (const auto p = pixels.match(geometry); p.hasMatch())
        box = QRectF(p.captured(1).toDouble() / width,
                     p.captured(2).toDouble() / height,
                     p.captured(3).toDouble() / width,
                     p.captured(4).toDouble() / height);
    const double size = caption.value("size").toDouble() > 0.0 ? caption.value("size").toDouble() : height / 20.0;
    const double block = qMin(box.height(), 2.0 * size * 1.3 / height);
    const QString valign = caption.value("valign").toString();
    const double top = valign == "top"      ? box.top()
                       : valign == "middle" ? box.center().y() - block / 2.0
                                            : box.bottom() - block;
    return QRectF(box.left() + box.width() * 0.05, top, box.width() * 0.9, block);
}

// Seconds until something is heard at the start of the main track, or -1 when it cannot tell.
double firstSound(const Mlt::ClipInfo &info, double fps)
{
    if (!info.producer)
        return -1.0;
    const QString resource = QString::fromUtf8(info.producer->get("resource"));
    if (!QFileInfo(resource).isFile() || info.producer->get_int("audio_index") < 0)
        return -1.0;
    QTemporaryDir temp;
    const QString wav = temp.filePath(QStringLiteral("start.wav"));
    const double length = qMin(15.0, info.frame_count / fps);
    if (!leRun(QDir(qApp->applicationDirPath()).filePath("ffmpeg"),
               {"-hide_banner", "-nostats", "-loglevel", "error", "-y", "-ss", QString::number(info.frame_in / fps, 'f', 3),
                "-t", QString::number(length, 'f', 3), "-i", resource, "-map", "0:a:0", "-ac", "1", "-ar", "16000",
                "-c:a", "pcm_s16le", wav},
               nullptr,
               nullptr,
               20000))
        return -1.0;
    const QVector<float> db = PauseRemover::loudness(wav);
    if (db.size() < 50)
        return -1.0;
    QVector<float> sorted = db;
    std::sort(sorted.begin(), sorted.end());
    const double speech = sorted[sorted.size() * 9 / 10];
    if (speech < -50.0)
        return -1.0; // nothing but quiet in the first seconds: the gap and caption checks speak for it
    const double level = qBound(-46.0, speech - 14.0, -28.0);
    for (int i = 0; i + 15 <= db.size(); ++i) {
        bool loud = true;
        for (int k = i; k < i + 15 && loud; ++k)
            loud = db[k] >= level;
        if (loud)
            return i * 0.01;
    }
    return -1.0;
}

// The parts of [from, to) that no picture on another shown video track covers: a title card or b-roll above a gap
// on the main track fills it.
QList<QPair<int, int>> uncovered(MultitrackModel *model, int mainMltIndex, int from, int to)
{
    QList<QPair<int, int>> open{{from, to}};
    for (const auto &track : model->trackList()) {
        if (track.type != VideoTrackType || track.mlt_index == mainMltIndex)
            continue;
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(track.mlt_index));
        if (!producer || !producer->is_valid() || (producer->get_int("hide") & 1))
            continue;
        Mlt::Playlist playlist(*producer);
        for (int i = 0; i < playlist.count() && !open.isEmpty(); ++i) {
            if (playlist.is_blank(i))
                continue;
            const int a = playlist.clip_start(i), b = a + playlist.clip_length(i);
            QList<QPair<int, int>> rest;
            for (const auto &span : std::as_const(open)) {
                if (b <= span.first || a >= span.second) {
                    rest.append(span);
                    continue;
                }
                if (a > span.first)
                    rest.append({span.first, a});
                if (b < span.second)
                    rest.append({b, span.second});
            }
            open = rest;
        }
    }
    return open;
}

// Whether someone talks in the video: the speech model listens to five short stretches spread over it (music and
// sound-effect tracks left out). -1 when it cannot tell, so the caption check still asks.
int talking(MultitrackModel *model, int mainMltIndex, double fps)
{
    if (!QFileInfo(Settings.whisperExe()).isExecutable() || !QFileInfo::exists(Settings.whisperModel()))
        return -1;
    static const QRegularExpression notTalk(QStringLiteral("music|song|score|bed|sfx|effect|sound|foley|ambien"),
                                            QRegularExpression::CaseInsensitiveOption);
    struct Sound
    {
        int start, length, in;
        QString resource;
    };
    QList<Sound> sounds; // the main track's first
    QList<Track> order = model->trackList();
    std::stable_sort(order.begin(), order.end(), [mainMltIndex](const Track &a, const Track &b) {
        return a.mlt_index == mainMltIndex && b.mlt_index != mainMltIndex;
    });
    for (const auto &track : std::as_const(order)) {
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(track.mlt_index));
        if (!producer || !producer->is_valid() || (producer->get_int("hide") & 2)
            || notTalk.match(QString::fromUtf8(producer->get(kTrackNameProperty))).hasMatch())
            continue;
        Mlt::Playlist playlist(*producer);
        for (int i = 0; i < playlist.count(); ++i) {
            QScopedPointer<Mlt::ClipInfo> info(playlist.clip_info(i));
            if (!info || playlist.is_blank(i) || !info->producer || info->producer->get_int("audio_index") < 0)
                continue;
            const QString resource = QString::fromUtf8(info->producer->get("resource"));
            if (QFileInfo(resource).isFile())
                sounds.append({info->start, info->frame_count, info->frame_in, resource});
        }
    }
    const int total = model->tractor()->get_playtime();
    QTemporaryDir temp;
    QByteArray pcm;
    for (int k = 0; k < 5; ++k) {
        const int at = int(qint64(total) * (2 * k + 1) / 10);
        for (const auto &sound : std::as_const(sounds)) {
            if (at < sound.start || at >= sound.start + sound.length)
                continue;
            const double from = (sound.in + at - sound.start) / fps;
            const double seconds = qMin(6.0, (sound.start + sound.length - at) / fps);
            const QString raw = temp.filePath(QStringLiteral("part%1.raw").arg(k));
            QByteArray data;
            if (leRun(QDir(qApp->applicationDirPath()).filePath("ffmpeg"),
                      {"-hide_banner", "-nostats", "-loglevel", "error", "-y", "-ss", QString::number(from, 'f', 3),
                       "-t", QString::number(seconds, 'f', 3), "-i", sound.resource, "-map", "0:a:0", "-ac", "1",
                       "-ar", "16000", "-f", "s16le", raw},
                      nullptr,
                      nullptr,
                      20000)) {
                QFile file(raw);
                if (file.open(QIODevice::ReadOnly))
                    pcm += file.readAll();
            }
            break;
        }
    }
    if (sounds.isEmpty())
        return 0;
    if (pcm.size() < 16000 * 2)
        return -1; // the sound could not be read
    const int words = PauseRemover::wordsHeard(pcm);
    // a lone "Thank you." is what the model hears in plain noise
    return words < 0 ? -1 : words >= 3 ? 1 : 0;
}

} // namespace

namespace {

void checkGuideSong(MultitrackModel *model, QList<Check> &checks)
{
    // T72: the song the person adds when posting
    {
        static const QRegularExpression songTrack(QStringLiteral("^\\s*song \\(not in the export\\)"),
                                                  QRegularExpression::CaseInsensitiveOption);
        for (const auto &track : model->trackList()) {
            QScopedPointer<Mlt::Producer> producer(model->tractor()->track(track.mlt_index));
            if (!producer || !producer->is_valid()
                || !songTrack.match(QString::fromUtf8(producer->get(kTrackNameProperty))).hasMatch())
                continue;
            const bool heard = !(producer->get_int("hide") & 2);
            checks.append({heard ? Check::Warning : Check::Note,
                           heard ? QObject::tr("You can hear the song in this window, but it stays out of this file. Add it "
                                               "in the phone app when you post.")
                                 : QObject::tr("The song stays out of this file. Add it in the phone app when you post."),
                           {},
                           {}});
            break;
        }
    }
}

void checkLength(bool vertical, double seconds, QList<Check> &checks)
{
    // 1. Length for the apps it is made for.
    if (!vertical) {
        checks.append({Check::Good, QObject::tr("Wide video (%1): made for YouTube and big screens.").arg(clock(seconds)), {}, {}});
    } else if (seconds <= 60.0) {
        checks.append({Check::Good, QObject::tr("Length %1: fits TikTok, Shorts and Reels.").arg(clock(seconds)), {}, {}});
    } else if (seconds <= 180.0) {
        checks.append({Check::Good,
                       QObject::tr("Length %1: fits TikTok, Shorts and Reels (up to 3 minutes).").arg(clock(seconds)),
                       {},
                       {}});
    } else if (seconds <= 600.0) {
        checks.append({Check::Warning,
                       QObject::tr("Length %1: over 3 minutes, so YouTube posts it as a regular video, not a Short, "
                                   "and Reels may not suggest it. TikTok takes up to 10 minutes.")
                           .arg(clock(seconds)),
                       {},
                       {}});
    } else {
        checks.append({Check::Warning,
                       QObject::tr("Length %1: over 10 minutes, too long for TikTok, Shorts and Reels.").arg(clock(seconds)),
                       {},
                       {}});
    }
}

bool checkTextPlacement(MainWindow *window, bool vertical, double width, double height, double fps, QList<Check> &checks)
{
    // 2. Text and captions out from under the apps' buttons and captions (vertical video).
    const QVariantList objects = PreviewObjects(window).allObjects();
    bool burnedCaptions = false;
    int covered = 0;
    for (const auto &value : objects) {
        const QVariantMap o = value.toMap();
        const bool caption = o.value("kind").toString() == QLatin1String("caption");
        burnedCaptions = burnedCaptions || caption;
        if (!vertical)
            continue;
        const QRectF box = caption ? captionBlock(o, width, height)
                                   : QRectF(o.value("x").toDouble(), o.value("y").toDouble(),
                                            o.value("w").toDouble(), o.value("h").toDouble());
        const QStringList apps = PhoneZones::appsCovering(box);
        if (apps.isEmpty())
            continue;
        if (++covered > 4)
            continue;
        if (caption) {
            checks.append({Check::Warning,
                           QObject::tr("The captions sit where %1 draw over the video. Drag one up or down on the "
                                       "player: it says when it is clear.")
                               .arg(apps.join(QStringLiteral(", "))),
                           QObject::tr("Show Me"),
                           [window]() { showPhoneZones(window); }});
        } else {
            const int start = o.value("start").toInt();
            const QString label = o.value("label").toString().simplified().left(40);
            checks.append({Check::Warning,
                           QObject::tr("“%1” at %2 is covered on %3.")
                               .arg(label, clock(start / fps), apps.join(QStringLiteral(", "))),
                           QObject::tr("Show Me"),
                           [window, start]() {
                               window->seekTimeline(start + 1);
                               showPhoneZones(window);
                           }});
        }
    }
    if (vertical && covered == 0 && !objects.isEmpty())
        checks.append({Check::Good, QObject::tr("Text and captions are clear of the apps' buttons and captions."), {}, {}});
    return burnedCaptions;
}

void checkMainTrack(MainWindow *window, MultitrackModel *model, bool vertical, bool burnedCaptions, double fps, QList<Check> &checks)
{
    // 3. The main track: black gaps, a slow start, sound to caption.
    int mltIndex = -1;
    for (const auto &track : model->trackList()) {
        if (track.type == VideoTrackType && (mltIndex < 0 || track.number == 0))
            mltIndex = track.mlt_index;
    }
    QScopedPointer<Mlt::Producer> main(model->tractor()->track(mltIndex));
    bool hasSound = false;
    if (main && main->is_valid()) {
        Mlt::Playlist playlist(*main);
        int gaps = 0;
        for (int i = 0; i < playlist.count(); ++i) {
            QScopedPointer<Mlt::ClipInfo> info(playlist.clip_info(i));
            if (!info)
                continue;
            if (!playlist.is_blank(i)) {
                hasSound = hasSound || (info->producer && info->producer->get_int("audio_index") >= 0);
                continue;
            }
            if (i == playlist.count() - 1)
                continue; // nothing after it: not part of the video
            const auto black = uncovered(model, mltIndex, info->start, info->start + info->frame_count);
            int frames = 0;
            for (const auto &span : black)
                frames += span.second - span.first;
            if (frames < qMax(2, qRound(fps / 10.0)) || ++gaps > 3)
                continue;
            const int start = black.first().first;
            checks.append({Check::Warning,
                           start == 0 ? QObject::tr("The video starts with %1 s of black.").arg(frames / fps, 0, 'f', 1)
                                      : QObject::tr("Black gap of %1 s at %2 between clips.")
                                            .arg(frames / fps, 0, 'f', 1)
                                            .arg(clock(start / fps)),
                           QObject::tr("Show Me"),
                           [window, start]() { window->seekTimeline(start); }});
        }
        QScopedPointer<Mlt::ClipInfo> first(playlist.count() ? playlist.clip_info(0) : nullptr);
        if (vertical && first && !playlist.is_blank(0)) {
            const double heard = firstSound(*first, fps);
            if (heard > 1.0)
                checks.append({Check::Warning,
                               QObject::tr("Nothing is heard until %1 s. People decide in the first second whether "
                                           "to keep watching.")
                                   .arg(heard, 0, 'f', 1),
                               QObject::tr("Remove Pauses"),
                               []() {
                                   if (auto a = Actions["removePausesAction"])
                                       a->trigger();
                               }});
        }
    }
    if (burnedCaptions) {
        checks.append({Check::Good, QObject::tr("Captions are on the video."), {}, {}});
    } else if (vertical && hasSound && talking(model, mltIndex, fps) == 0) {
        checks.append({Check::Good, QObject::tr("Nobody talks, so no captions are needed."), {}, {}});
    } else if (vertical && hasSound) {
        checks.append({Check::Warning,
                       QObject::tr("No captions on the video. Most people watch shorts with the sound off."),
                       QObject::tr("Add Captions"),
                       [window]() {
                           if (auto a = window->findChild<QAction *>(QStringLiteral("studioCaptionsAction")))
                               a->trigger();
                       }});
    } else if (hasSound) {
        checks.append({Check::Note, QObject::tr("No captions drawn on the video (YouTube can add its own)."), {}, {}});
    }
}

} // namespace

QList<Check> run(MainWindow *window, bool evenVolume)
{
    QList<Check> checks;
    auto timeline = window->timelineDock();
    auto model = timeline->model();
    if (!window->isMultitrackValid() || !model->tractor())
        return checks;
    const double fps = MLT.profile().fps();
    const double width = MLT.profile().width(), height = MLT.profile().height();
    const bool vertical = height > width * 1.2;
    const double seconds = model->tractor()->get_playtime() / fps;

    checkGuideSong(model, checks);

    checkLength(vertical, seconds, checks);

    const bool burnedCaptions = checkTextPlacement(window, vertical, width, height, fps, checks);

    checkMainTrack(window, model, vertical, burnedCaptions, fps, checks);

    // 4. Volume: before the export this is a setting, not a result. The level is measured on the finished file, and
    // the export screen shows that number with it.
    checks.append(evenVolume ? Check{Check::Note,
                                     vertical ? QObject::tr("Volume adjustment is on: after the export the whole mix is "
                                                            "set to the level phones and social apps "
                                                            "play at (about -14 LUFS) and measured on the file.")
                                              : QObject::tr("Volume adjustment is on: after the export the whole mix is "
                                                            "set to the level YouTube plays at (about -14 LUFS) and "
                                                            "measured on the file."),
                                     {},
                                     {}}
                             : Check{Check::Note,
                                     QObject::tr("Volume adjustment is off: the sound is exported as you mixed it."),
                                     {},
                                     {}});

    // 5. Credit lines: library assets whose licence asks for one (Google's animated emoji, CC BY 4.0) - the line goes
    // in the video's description; Copy puts it on the clipboard.
    const QJsonArray owed = LeFeatures::credits(window);
    if (!owed.isEmpty()) {
        const QString text = LeFeatures::creditText(owed);
        checks.append({Check::Note,
                       QObject::tr("This video uses an asset that needs a credit line. Put this in the video's "
                                   "description: %1")
                           .arg(text),
                       QObject::tr("Copy"),
                       [text]() { QApplication::clipboard()->setText(text); },
                       true});
    }
    return checks;
}

bool confirm(MainWindow *window, bool evenVolume)
{
    const QList<Check> checks = run(window, evenVolume);
    // a warning, or a credit line to copy, shows the list
    const bool attention = std::any_of(checks.begin(), checks.end(), [](const Check &c) {
        return c.level == Check::Warning || c.keepOpen;
    });
    if (!attention) {
        window->showStatusMessage(QObject::tr("Checked before export: all good."));
        return true;
    }
    QDialog dialog(window);
    dialog.setObjectName(QStringLiteral("exportChecksDialog"));
    dialog.setWindowTitle(QObject::tr("Before You Export"));
    dialog.setMinimumWidth(560);
    auto *layout = new QVBoxLayout(&dialog);
    auto *intro = new QLabel(QObject::tr("A few things to look at first. Export anyway, or fix them and export again."));
    intro->setWordWrap(true);
    layout->addWidget(intro);
    auto *grid = new QGridLayout;
    grid->setHorizontalSpacing(10);
    grid->setVerticalSpacing(8);
    grid->setColumnStretch(1, 1);
    std::function<void()> chosen;
    for (int i = 0; i < checks.size(); ++i) {
        const Check &check = checks[i];
        auto *icon = new QLabel(check.level == Check::Good      ? QStringLiteral("✓")
                                : check.level == Check::Warning ? QStringLiteral("⚠")
                                                                : QStringLiteral("•"));
        icon->setStyleSheet(check.level == Check::Good      ? QStringLiteral("color: #5ec8b4; font-weight: bold;")
                            : check.level == Check::Warning ? QStringLiteral("color: #ffb347; font-weight: bold;")
                                                            : QStringLiteral("color: gray;"));
        auto *text = new QLabel(check.text);
        text->setWordWrap(true);
        grid->addWidget(icon, i, 0, Qt::AlignTop);
        grid->addWidget(text, i, 1);
        if (!check.button.isEmpty() && check.act && check.keepOpen) {
            auto *button = new QPushButton(check.button);
            button->setObjectName(QStringLiteral("exportCheckCopy%1").arg(i));
            QObject::connect(button, &QPushButton::clicked, &dialog, [button, act = check.act]() {
                act();
                button->setText(QObject::tr("Copied"));
            });
            grid->addWidget(button, i, 2, Qt::AlignTop);
        } else if (!check.button.isEmpty() && check.act) {
            auto *button = new QPushButton(check.button);
            button->setObjectName(QStringLiteral("exportCheckFix%1").arg(i));
            QObject::connect(button, &QPushButton::clicked, &dialog, [&dialog, &chosen, act = check.act]() {
                chosen = act;
                dialog.done(2);
            });
            grid->addWidget(button, i, 2, Qt::AlignTop);
        }
    }
    layout->addLayout(grid);
    auto *buttons = new QDialogButtonBox;
    auto *back = buttons->addButton(QObject::tr("Go Back"), QDialogButtonBox::RejectRole);
    back->setObjectName(QStringLiteral("exportChecksBack"));
    auto *go = buttons->addButton(QObject::tr("Export Anyway"), QDialogButtonBox::AcceptRole);
    go->setObjectName(QStringLiteral("exportChecksExport"));
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);
    const int result = dialog.exec();
    if (result == QDialog::Accepted)
        return true;
    if (chosen)
        chosen();
    return false;
}

} // namespace ExportChecks
