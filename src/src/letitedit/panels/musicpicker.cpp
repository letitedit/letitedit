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

#include "letitedit/panels/musicpicker.h"

#include "Logger.h"
#include "actions.h"
#include "letitedit/airoot.h"
#include "docks/timelinedock.h"
#include "letitedit/dialogs/lefeatures.h"
#include "letitedit/letitedit.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/multitrackmodel.h"
#include "letitedit/export/pauseremover.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"

#include <MltFilter.h>
#include <MltPlaylist.h>
#include <MltProducer.h>
#include <QAction>
#include <QAudioOutput>
#include <QButtonGroup>
#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QHideEvent>
#include <QShowEvent>
#include <QTimer>
#include <QTabWidget>
#include <QDockWidget>
#include <QDirIterator>
#include <QElapsedTimer>
#include <QFileDialog>
#include <QFileInfo>
#include <QHBoxLayout>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QLineEdit>
#include <QListWidget>
#include <QMap>
#include <QMediaPlayer>
#include <QPushButton>
#include <QRadioButton>
#include <QRandomGenerator>
#include <QRegularExpression>
#include <QSaveFile>
#include <QSet>
#include <QSignalBlocker>
#include <QStandardPaths>
#include <QTemporaryDir>
#include <QTextStream>
#include <QThread>
#include <QUndoStack>
#include <QUrl>
#include <QVBoxLayout>
#include <QtEndian>

#include <algorithm>
#include <cmath>
#include <limits>

namespace MusicPicker {

namespace {

const QStringList kAudioSuffixes{"mp3", "wav", "m4a", "aac", "flac", "ogg", "opus", "aiff", "aif", "wma"};
// Track names the AI tools also treat as music (and not as talking).
const QRegularExpression kMusicName(QStringLiteral("music|song|score|bed"), QRegularExpression::CaseInsensitiveOption);
const QRegularExpression kNotTalkName(QStringLiteral("music|song|score|bed|sfx|effect|sound|foley|ambien"),
                                      QRegularExpression::CaseInsensitiveOption);

// Music level against the talking's loudness (dB), the same numbers the AI's score tool uses for medium.
struct Levels
{
    double underTalk;
    double inGaps;
};
const Levels kLevels[] = {{-22.0, -10.0}, {-18.0, -6.0}, {-14.0, -3.0}};
const double kAttack = 0.35; // the dip takes this long
const double kPreroll = 0.1;  // and is complete this long before the first word
const double kHold = 0.3;     // the music stays down this long after the last word (its tail, a breath)
const double kRelease = 1.0;  // then lifts this slowly
const double kMergeGap = 4.0; // talking with shorter breaks keeps the music down (no pumping)
const double kFadeIn = 1.5, kFadeOut = 3.0, kJoint = 1.5;
const double kMontageLift[] = {4.0, 8.0, 12.0}; // music over the shots' own sound when nobody talks (dB)
// Kept on each song piece Add music places, so the music can be fitted again later with the same settings.
const char *kVolumeProperty = "letitedit:music_volume";
const char *kDuckProperty = "letitedit:music_duck";

QString appTool(const QString &name)
{
    return QDir(qApp->applicationDirPath()).filePath(name);
}

QString clockText(double seconds)
{
    const int s = qRound(seconds);
    return QStringLiteral("%1:%2").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0'));
}

double clockSeconds(const QString &text)
{
    double total = 0.0;
    for (const auto &part : text.trimmed().split(':')) {
        bool ok = false;
        total = total * 60.0 + part.toDouble(&ok);
        if (!ok)
            return 0.0;
    }
    return total;
}

QStringList csvFields(const QString &line)
{
    QStringList fields;
    QString field;
    bool quoted = false;
    for (int i = 0; i < line.size(); ++i) {
        const QChar c = line.at(i);
        if (quoted) {
            if (c == '"' && i + 1 < line.size() && line.at(i + 1) == '"') {
                field += '"';
                ++i;
            } else if (c == '"') {
                quoted = false;
            } else {
                field += c;
            }
        } else if (c == '"') {
            quoted = true;
        } else if (c == ',') {
            fields << field.trimmed();
            field.clear();
        } else {
            field += c;
        }
    }
    fields << field.trimmed();
    return fields;
}

// A list kept beside the music (any CSV with a file name column) names each song: title, artist, genre, length.
void readList(const QString &path, QHash<QString, Song> &listed)
{
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly | QIODevice::Text))
        return;
    QTextStream in(&file);
    in.setEncoding(QStringConverter::Utf8);
    const QStringList header = csvFields(in.readLine().remove(QChar(0xFEFF)));
    int fileColumn = -1, titleColumn = -1, artistColumn = -1, genreColumn = -1, lengthColumn = -1, moodColumn = -1;
    int bpmColumn = -1;
    for (int i = 0; i < header.size(); ++i) {
        const QString h = header[i].toLower();
        if (fileColumn < 0 && h.contains("file"))
            fileColumn = i;
        else if (titleColumn < 0 && h.contains("title"))
            titleColumn = i;
        else if (artistColumn < 0 && h.contains("artist"))
            artistColumn = i;
        else if (genreColumn < 0 && h.contains("genre"))
            genreColumn = i;
        else if (lengthColumn < 0 && (h.contains("length") || h.contains("duration")))
            lengthColumn = i;
        else if (moodColumn < 0 && h.contains("mood"))
            moodColumn = i;
        else if (bpmColumn < 0 && h == "bpm")
            bpmColumn = i;
    }
    if (fileColumn < 0)
        return;
    const auto field = [](const QStringList &row, int column) {
        return column >= 0 && column < row.size() ? row[column] : QString();
    };
    while (!in.atEnd()) {
        const QStringList row = csvFields(in.readLine());
        const QString name = field(row, fileColumn);
        if (name.isEmpty())
            continue;
        Song song;
        song.title = field(row, titleColumn);
        song.artist = field(row, artistColumn);
        song.genre = field(row, genreColumn);
        song.mood = field(row, moodColumn);
        song.seconds = clockSeconds(field(row, lengthColumn));
        song.bpm = field(row, bpmColumn).toInt();
        // The catalog's File is relative to its CSV; two albums may contain the same basename.
        listed.insert(QDir(QFileInfo(path).absolutePath()).absoluteFilePath(name).toLower(), song);
    }
}

QString cachePath()
{
    return Settings.appDataLocation() + QStringLiteral("/letitedit-music.json");
}

QJsonObject loadCache()
{
    QFile file(cachePath());
    return file.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(file.readAll()).object() : QJsonObject();
}

// Lengths no list gave: asked once per file (six at a time) and remembered.
void probeMissing(QList<Song> &songs, QWidget *parent)
{
    QStringList missing;
    for (const auto &song : songs) {
        if (song.seconds <= 0.0)
            missing << song.path;
    }
    if (missing.isEmpty())
        return;
    QProgressDialog progress(QObject::tr("Getting to know your music..."),
                             QObject::tr("Skip"),
                             0,
                             missing.size(),
                             parent);
    progress.setWindowTitle(QObject::tr("Add Music"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(400);
    const QString ffprobe = appTool("ffprobe");
    QHash<QString, double> found;
    struct Probe
    {
        QProcess *process;
        QString path;
        QElapsedTimer clock;
    };
    QList<Probe> running;
    int next = 0;
    while (found.size() < missing.size()) {
        while (running.size() < 6 && next < missing.size()) {
            Probe probe{new QProcess, missing[next++], {}};
            probe.process->start(ffprobe,
                                 {"-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", probe.path});
            probe.clock.start();
            running.append(probe);
        }
        for (int i = running.size() - 1; i >= 0; --i) {
            Probe &probe = running[i];
            const bool finished = probe.process->state() == QProcess::NotRunning
                                  || probe.process->waitForFinished(5);
            if (!finished && probe.clock.elapsed() < 15000)
                continue;
            if (!finished)
                probe.process->kill();
            found.insert(probe.path, QString::fromUtf8(probe.process->readAllStandardOutput()).trimmed().toDouble());
            delete probe.process;
            running.removeAt(i);
        }
        progress.setValue(found.size());
        QCoreApplication::processEvents();
        if (progress.wasCanceled()) {
            for (auto &probe : running) {
                probe.process->kill();
                probe.process->waitForFinished(1000);
                delete probe.process;
            }
            return;
        }
    }
    QJsonObject cache = loadCache();
    for (auto it = found.cbegin(); it != found.cend(); ++it) {
        const QFileInfo info(it.key());
        cache.insert(it.key(),
                     QJsonObject{{"size", double(info.size())},
                                 {"modified", double(info.lastModified().toSecsSinceEpoch())},
                                 {"seconds", it.value()}});
    }
    for (auto &song : songs)
        song.seconds = found.value(song.path, song.seconds);
    QSaveFile file(cachePath());
    if (file.open(QIODevice::WriteOnly)) {
        file.write(QJsonDocument(cache).toJson(QJsonDocument::Compact));
        file.commit();
    }
}

double integratedLufs(const QString &path, double seconds, QProgressDialog *progress)
{
    QStringList args{"-hide_banner", "-nostats"};
    if (seconds > 0.0)
        args << "-t" << QString::number(seconds, 'f', 2);
    args << "-i" << path << "-vn" << "-af" << "ebur128=framelog=quiet" << "-f" << "null" << "-";
    QByteArray printed;
    if (!leRun(appTool("ffmpeg"), args, progress, &printed))
        return -70.0;
    double value = -70.0;
    auto matches = QRegularExpression(QStringLiteral("I:\\s+(-?[0-9.]+) LUFS")).globalMatch(QString::fromUtf8(printed));
    while (matches.hasNext())
        value = matches.next().captured(1).toDouble();
    return value;
}

// The video's own sound without its music and effects tracks, as one 16 kHz mono WAV as long as the video: each
// clip's file read with ffmpeg and laid at its place (fast; clip filters are not applied, muted tracks are left out).
bool renderTalk(MultitrackModel *model, double fps, int videoFrames, const QString &out, QProgressDialog *progress)
{
    const int rate = 16000;
    const qint64 total = qint64(double(videoFrames) / fps * rate);
    QVector<float> mix(total, 0.0f);
    QTemporaryDir temp;
    // Each file's sound is read once for all its pieces (when they lie close together in it): an edit with a
    // hundred cuts from one take would otherwise start ffmpeg a hundred times.
    struct Piece
    {
        qint64 at;      // first sample on the timeline
        double from;    // seconds into the file
        double seconds; // length
    };
    QMap<QString, QList<Piece>> files;
    for (const auto &track : model->trackList()) {
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(track.mlt_index));
        if (!producer || !producer->is_valid() || (producer->get_int("hide") & 2)
            || kNotTalkName.match(QString::fromUtf8(producer->get(kTrackNameProperty))).hasMatch())
            continue;
        Mlt::Playlist playlist(*producer);
        for (int i = 0; i < playlist.count(); ++i) {
            QScopedPointer<Mlt::ClipInfo> info(playlist.clip_info(i));
            if (!info || playlist.is_blank(i) || !info->producer)
                continue;
            const QString resource = QString::fromUtf8(info->producer->get("resource"));
            if (!QFileInfo(resource).isFile() || info->producer->get_int("audio_index") < 0)
                continue;
            files[resource].append(
                {qint64(double(info->start) / fps * rate), info->frame_in / fps, info->frame_count / fps});
        }
    }
    int part = 0;
    for (auto it = files.begin(); it != files.end(); ++it) {
        QList<Piece> &pieces = it.value();
        std::sort(pieces.begin(), pieces.end(), [](const Piece &a, const Piece &b) { return a.from < b.from; });
        for (int first = 0; first < pieces.size();) {
            // One read covers the pieces with less than 20 s unused between them, up to 15 minutes of the file.
            double from = pieces[first].from, to = from + pieces[first].seconds;
            int last = first;
            while (last + 1 < pieces.size() && pieces[last + 1].from - to < 20.0
                   && pieces[last + 1].from + pieces[last + 1].seconds - from < 900.0) {
                ++last;
                to = qMax(to, pieces[last].from + pieces[last].seconds);
            }
            const QString raw = temp.filePath(QStringLiteral("part%1.raw").arg(part++));
            const bool read = leRun(appTool("ffmpeg"),
                                    {"-hide_banner", "-nostats", "-loglevel", "error", "-y", "-ss",
                                     QString::number(from, 'f', 3), "-t", QString::number(to - from, 'f', 3), "-i",
                                     it.key(), "-map", "0:a:0", "-ac", "1", "-ar", QString::number(rate), "-f",
                                     "s16le", raw},
                                    progress);
            if (!read && progress && progress->wasCanceled())
                return false;
            QFile file(raw);
            if (read && file.open(QIODevice::ReadOnly)) {
                const QByteArray data = file.readAll();
                const auto *samples = reinterpret_cast<const qint16 *>(data.constData());
                const qint64 count = data.size() / 2;
                for (int p = first; p <= last; ++p) {
                    const qint64 offset = qRound64((pieces[p].from - from) * rate);
                    const qint64 length = qRound64(pieces[p].seconds * rate);
                    for (qint64 k = 0; k < length && offset + k < count && pieces[p].at + k < total; ++k) {
                        if (pieces[p].at + k >= 0)
                            mix[pieces[p].at + k] += samples[offset + k];
                    }
                }
            }
            first = last + 1;
        }
    }
    QFile file(out);
    if (!file.open(QIODevice::WriteOnly))
        return false;
    QByteArray pcm(total * 2, Qt::Uninitialized);
    auto *samples = reinterpret_cast<qint16 *>(pcm.data());
    for (qint64 k = 0; k < total; ++k)
        samples[k] = qint16(qBound(-32768.0f, mix[k], 32767.0f));
    const auto le32 = [](quint32 v) {
        QByteArray b(4, 0);
        qToLittleEndian<quint32>(v, b.data());
        return b;
    };
    const auto le16 = [](quint16 v) {
        QByteArray b(2, 0);
        qToLittleEndian<quint16>(v, b.data());
        return b;
    };
    file.write("RIFF" + le32(36 + pcm.size()) + "WAVE" + "fmt " + le32(16) + le16(1) + le16(1) + le32(rate)
               + le32(rate * 2) + le16(2) + le16(16) + "data" + le32(pcm.size()));
    file.write(pcm);
    return true;
}

struct Key
{
    double time;
    double db;
};

double valueAt(const QList<Key> &keys, double t)
{
    if (keys.isEmpty())
        return 0.0;
    if (t <= keys.first().time)
        return keys.first().db;
    for (int i = 1; i < keys.size(); ++i) {
        if (t <= keys[i].time) {
            const double span = keys[i].time - keys[i - 1].time;
            const double f = span > 1e-9 ? (t - keys[i - 1].time) / span : 1.0;
            return keys[i - 1].db + f * (keys[i].db - keys[i - 1].db);
        }
    }
    return keys.last().db;
}

// The music level over the whole video: down under talking (ramped so the first word is already clear), up in gaps.
QList<Key> levelCurve(const QList<QPair<double, double>> &talk, double total, const Levels &levels)
{
    struct Segment
    {
        double from, to, db;
    };
    QList<Segment> segments;
    double t = 0.0;
    for (const auto &span : talk) {
        if (span.first > t)
            segments.append({t, span.first, levels.inGaps});
        segments.append({span.first, qMin(span.second, total), levels.underTalk});
        t = span.second;
    }
    if (t < total)
        segments.append({t, total, levels.inGaps});
    // A gap too short to ramp up in (at the very start or end) is part of the talking.
    if (segments.size() > 1 && segments.first().db > segments[1].db
        && segments.first().to - segments.first().from < kAttack) {
        segments[1].from = segments.first().from;
        segments.removeFirst();
    }
    if (segments.size() > 1 && segments.last().db > segments[segments.size() - 2].db
        && segments.last().to - segments.last().from < kRelease) {
        segments[segments.size() - 2].to = segments.last().to;
        segments.removeLast();
    }
    QList<Key> keys;
    if (segments.isEmpty())
        return keys;
    keys.append({segments.first().from, segments.first().db});
    for (int i = 1; i < segments.size(); ++i) {
        const double a = segments[i - 1].db, b = segments[i].db, at = segments[i].from;
        if (b < a) {
            const double t1 = qMax(qMax(at - kPreroll, keys.last().time), segments[i - 1].from);
            const double t0 = qMax(qMax(t1 - kAttack, keys.last().time), segments[i - 1].from);
            keys.append({t0, a});
            keys.append({t1, b});
        } else {
            const double t0 = qMin(at + kHold, segments[i].to);
            keys.append({t0, a});
            keys.append({qMin(t0 + kRelease, segments[i].to), b});
        }
    }
    keys.append({segments.last().to, segments.last().db});
    QList<Key> tidy;
    for (const auto &k : keys) {
        if (!tidy.isEmpty() && std::abs(tidy.last().time - k.time) < 1e-6)
            tidy.last() = k;
        else
            tidy.append(k);
    }
    return tidy;
}

bool contains(const QList<Song> &songs, const QString &path)
{
    for (const auto &s : songs) {
        if (s.path == path)
            return true;
    }
    return false;
}

// The song's loudness per 10 ms (16 kHz mono through ffmpeg), for keeping it steady under the voice.
QVector<float> songLoudness(const QString &song, double seconds, QProgressDialog *progress)
{
    QTemporaryDir temp;
    const QString wav = temp.filePath(QStringLiteral("song.wav"));
    if (!leRun(appTool("ffmpeg"),
               {"-hide_banner", "-nostats", "-loglevel", "error", "-y", "-t", QString::number(seconds + 1.0, 'f', 2),
                "-i", song, "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", wav},
               progress))
        return {};
    return PauseRemover::loudness(wav);
}

// A level per 10 ms frame averaged (as power) over a window, using only the frames marked; NaN where none are.
QVector<float> smoothed(const QVector<float> &db, const QVector<bool> &use, int window)
{
    const int n = db.size();
    QVector<double> sum(n + 1, 0.0), count(n + 1, 0.0);
    for (int i = 0; i < n; ++i) {
        const bool on = use.isEmpty() || use[i];
        sum[i + 1] = sum[i] + (on ? std::pow(10.0, db[i] / 10.0) : 0.0);
        count[i + 1] = count[i] + (on ? 1.0 : 0.0);
    }
    QVector<float> out(n, std::numeric_limits<float>::quiet_NaN());
    for (int i = 0; i < n; ++i) {
        const int a = qMax(0, i - window / 2), b = qMin(n, i + window / 2 + 1);
        const double c = count[b] - count[a];
        if (c >= window / 10.0)
            out[i] = float(10.0 * std::log10(qMax(1e-12, (sum[b] - sum[a]) / c)));
    }
    return out;
}

float median(QVector<float> values)
{
    values.removeIf([](float v) { return std::isnan(v); });
    if (values.isEmpty())
        return std::numeric_limits<float>::quiet_NaN();
    std::nth_element(values.begin(), values.begin() + values.size() / 2, values.end());
    return values[values.size() / 2];
}

// Fewer keys, same shape: drop the ones a straight line between their neighbours already gives (within 0.4 dB).
QList<Key> simplified(const QList<Key> &keys)
{
    if (keys.size() < 3)
        return keys;
    QVector<bool> keep(keys.size(), false);
    keep.first() = keep.last() = true;
    QList<QPair<int, int>> stack{{0, int(keys.size()) - 1}};
    while (!stack.isEmpty()) {
        const auto [a, b] = stack.takeLast();
        double worst = 0.0;
        int at = -1;
        for (int i = a + 1; i < b; ++i) {
            const double f = (keys[i].time - keys[a].time) / qMax(1e-9, keys[b].time - keys[a].time);
            const double d = std::abs(keys[i].db - (keys[a].db + f * (keys[b].db - keys[a].db)));
            if (d > worst) {
                worst = d;
                at = i;
            }
        }
        if (at >= 0 && worst > 0.4) {
            keep[at] = true;
            stack.append({a, at});
            stack.append({at, b});
        }
    }
    QList<Key> out;
    for (int i = 0; i < keys.size(); ++i) {
        if (keep[i])
            out.append(keys[i]);
    }
    return out;
}

// Rides the music's level on top of the dips and rises: under the talking it follows the voice and the song, so the
// music sits the same distance under every line (a softly spoken one too) and a chorus or drop does not push up
// against the words; in the gaps the song's own swings are evened out a little. Changes are gentle (3 dB a second).
QList<Key> rideLevels(const QList<Key> &envelope, const Levels &levels, const QVector<float> &talkDb,
                      const QList<QPair<double, double>> &talk, double gapLevel, const QVector<float> &songDb,
                      const QList<QPair<int, int>> &pieces, double fps, double total)
{
    const double hop = 0.01;
    QVector<bool> speaking(talkDb.size(), false);
    for (const auto &span : talk) {
        for (int i = qMax(0, int(span.first / hop)); i < qMin(int(talkDb.size()), int(span.second / hop)); ++i)
            speaking[i] = talkDb[i] >= gapLevel;
    }
    const QVector<float> voice = smoothed(talkDb, speaking, 300);
    const QVector<float> song = smoothed(songDb, {}, 200);
    const float voiceRef = median(voice), songRef = median(song);
    if (std::isnan(voiceRef) || std::isnan(songRef))
        return envelope;
    const double step = 0.25;
    QList<double> times, correction;
    double lastVoice = voiceRef;
    for (double t = 0.0; t <= total + 1e-6; t += step) {
        const double env = valueAt(envelope, t);
        const double w = qBound(0.0, (levels.inGaps - env) / (levels.inGaps - levels.underTalk), 1.0);
        const int i = qBound(0, int(t / hop), int(voice.size()) - 1);
        if (!voice.isEmpty() && !std::isnan(voice[i]))
            lastVoice = voice[i];
        double s = songRef;
        for (const auto &piece : pieces) {
            const double from = piece.first / fps, to = (piece.first + piece.second) / fps;
            if (t >= from && t < to) {
                const int k = qBound(0, int((t - from) / hop), int(song.size()) - 1);
                if (!song.isEmpty() && !std::isnan(song[k]))
                    s = song[k];
                break;
            }
        }
        // Only ever down: a softer line or a louder stretch of the song turns the music down; nothing turns it up.
        const double under = qBound(-8.0, (lastVoice - voiceRef) - (s - songRef), 0.0);
        const double gap = qBound(-6.0, -(s - songRef), 0.0);
        times.append(t);
        correction.append(w * under + (1.0 - w) * gap);
    }
    // gentle: at most 3 dB a second either way (both directions, so a change is eased on both sides)
    const double most = 3.0 * step;
    for (int i = 1; i < correction.size(); ++i)
        correction[i] = qBound(correction[i - 1] - most, correction[i], correction[i - 1] + most);
    for (int i = correction.size() - 2; i >= 0; --i)
        correction[i] = qBound(correction[i + 1] - most, correction[i], correction[i + 1] + most);
    // the dips and rises keep their own timing: the keys of the envelope plus the riding between them
    QList<Key> keys;
    for (int i = 0; i < times.size(); ++i)
        keys.append({times[i], valueAt(envelope, times[i]) + correction[i]});
    for (const auto &k : envelope) {
        const int i = qBound(0, int(std::lround(k.time / step)), int(correction.size()) - 1);
        keys.append({k.time, k.db + correction[i]});
    }
    std::sort(keys.begin(), keys.end(), [](const Key &a, const Key &b) { return a.time < b.time; });
    QList<Key> tidy;
    for (const auto &k : keys) {
        if (!tidy.isEmpty() && std::abs(tidy.last().time - k.time) < 0.02)
            continue;
        tidy.append(k);
    }
    return simplified(tidy);
}

// The genre and mood words of a song (lower case, three letters or more), for keeping a chain of songs in one feel.
QSet<QString> styleWords(const Song &song)
{
    static const QSet<QString> generic{"and", "the", "for", "with", "music", "song", "songs", "track"};
    QSet<QString> words;
    static const QRegularExpression split(QStringLiteral("[^a-z]+"));
    for (const auto &w : QString(song.genre + ' ' + song.mood).toLower().split(split, Qt::SkipEmptyParts))
        if (w.size() >= 3 && !generic.contains(w))
            words << w;
    return words;
}

// The song to follow the chain: the best fit for the time left (ranked) that is not in the chain or in `skip`, by
// another artist than the chain's when there is one and sharing a genre or mood word with the first song when there
// is one (those wishes are let go in that order). Empty when no other song is there.
QString nextSong(const QList<Song> &songs, const QStringList &chain, const QStringList &skip, double seconds,
                 bool talking)
{
    const QList<Song> order = ranked(songs, seconds, talking);
    QStringList artists;
    QSet<QString> words;
    for (const auto &song : songs) {
        if (!chain.contains(song.path))
            continue;
        if (!song.artist.isEmpty())
            artists << song.artist.toLower();
        if (song.path == chain.first())
            words = styleWords(song);
    }
    for (int pass = 0; pass < 3; ++pass) {
        for (const auto &song : order) {
            if (chain.contains(song.path) || skip.contains(song.path) || !QFileInfo::exists(song.path))
                continue;
            const bool otherArtist = song.artist.isEmpty() || !artists.contains(song.artist.toLower());
            const bool sameFeel = words.isEmpty() || styleWords(song).intersects(words);
            if (pass == 2 || (otherArtist && (pass == 1 || sameFeel)))
                return song.path;
        }
    }
    return QString();
}

QString describe(const Song &song)
{
    QStringList first{song.title};
    if (song.seconds > 0.0)
        first << clockText(song.seconds);
    first << (song.bpm > 0 ? QObject::tr("%1 BPM").arg(song.bpm) : QObject::tr("No steady beat"));
    QStringList parts;
    if (!song.artist.isEmpty())
        parts << song.artist;
    if (!song.genre.isEmpty())
        parts << song.genre;
    if (!song.mood.isEmpty() && song.mood.compare(song.genre, Qt::CaseInsensitive) != 0)
        parts << song.mood;
    return first.join(QStringLiteral(" \u00b7 ")) + QLatin1Char('\n') + parts.join(QStringLiteral(" \u00b7 "));
}

} // namespace

QString musicFolder()
{
    QString folder = leSettings().value("music/folder").toString();
    if (folder.isEmpty()) {
        // The folder the AI's music tools use, so both find the same songs.
        QFile file(aiRootPath(QStringLiteral("appdata/ai-audio-libraries.json")));
        if (file.open(QIODevice::ReadOnly))
            folder = QJsonDocument::fromJson(file.readAll()).object().value("music_folder").toString();
    }
    if (folder.isEmpty() || !QFileInfo(folder).isDir())
        folder = QStandardPaths::writableLocation(QStandardPaths::MusicLocation);
    return QDir::fromNativeSeparators(folder);
}

QString freeLibraryFolder()
{
    return QDir::fromNativeSeparators(aiRootPath(QStringLiteral("music-library")));
}

QList<Song> allSongs(const QString &folder)
{
    QList<Song> songs = library(folder);
    const QString free = freeLibraryFolder();
    const QString mine = QDir::cleanPath(folder).toLower(), theirs = QDir::cleanPath(free).toLower();
    if (QFileInfo(free).isDir() && !mine.startsWith(theirs) && !theirs.startsWith(mine))
        songs += library(free);
    std::sort(songs.begin(), songs.end(), [](const Song &a, const Song &b) {
        return a.title.compare(b.title, Qt::CaseInsensitive) < 0;
    });
    return songs;
}

QList<Song> library(const QString &folder)
{
    QList<Song> songs;
    if (folder.isEmpty() || !QFileInfo(folder).isDir())
        return songs;
    QHash<QString, Song> listed;
    QStringList files;
    QDirIterator it(folder, QDir::Files, QDirIterator::Subdirectories);
    while (it.hasNext()) {
        const QFileInfo file(it.next());
        const QString suffix = file.suffix().toLower();
        if (suffix == "csv")
            readList(file.absoluteFilePath(), listed);
        else if (kAudioSuffixes.contains(suffix))
            files << file.absoluteFilePath();
    }
    const QJsonObject cache = loadCache();
    for (const auto &path : files) {
        const QFileInfo info(path);
        Song song = listed.value(info.absoluteFilePath().toLower());
        song.path = path;
        if (song.title.isEmpty()) {
            // "Title - Artist.mp3", the way music libraries name downloads
            const QString base = info.completeBaseName();
            const int dash = base.lastIndexOf(QStringLiteral(" - "));
            song.title = dash > 0 ? base.left(dash) : base;
            if (song.artist.isEmpty() && dash > 0)
                song.artist = base.mid(dash + 3);
        }
        if (song.seconds <= 0.0) {
            const QJsonObject entry = cache.value(path).toObject();
            if (entry.value("size").toDouble() == double(info.size())
                && entry.value("modified").toDouble() == double(info.lastModified().toSecsSinceEpoch()))
                song.seconds = entry.value("seconds").toDouble();
        }
        songs.append(song);
    }
    std::sort(songs.begin(), songs.end(), [](const Song &a, const Song &b) {
        return a.title.compare(b.title, Qt::CaseInsensitive) < 0;
    });
    return songs;
}

QList<Song> ranked(const QList<Song> &songs, double videoSeconds, bool talking)
{
    const QStringList recent = leSettings().value("music/recent").toStringList();
    // My style's music taste: words of genres and moods to prefer and to leave out.
    const QStringList likes = leSettings().value("music/likes").toStringList();
    const QStringList avoid = leSettings().value("music/avoid").toStringList();
    static const QStringList calm{"calm", "chill", "relax", "ambient", "acoustic", "piano", "inspir", "dream", "bright",
                                  "happy", "funk", "jazz", "lofi", "lo-fi", "folk", "soft", "warm"};
    static const QStringList lively{"upbeat", "energ", "dance", "electro", "epic", "hip hop", "funk", "happy",
                                    "bright", "pop", "driv", "action", "groove"};
    static const QStringList harsh{"screamo", "dissonan", "noisy", "noise", "distort", "industrial",
                                   "aggressive", "harsh", "hyper metal", "extreme metal"};
    QList<QPair<double, int>> scores;
    for (int i = 0; i < songs.size(); ++i) {
        const Song &song = songs[i];
        if (song.seconds > 0.0 && song.seconds < 20.0)
            continue; // stingers and sound effects
        const QString style = QStringList{song.genre, song.mood, song.title}.join(' ').toLower();
        double score = 0.0;
        if (song.seconds <= 0.0)
            score += 0.6;
        else if (song.seconds < videoSeconds)
            score += std::ceil(videoSeconds / song.seconds) - 1.0; // each repeat counts against it
        const int used = recent.indexOf(song.path);
        if (used >= 0)
            score += 2.0 * (1.0 - used / 12.0); // so every video does not sound the same
        for (const auto &word : likes) {
            if (!word.trimmed().isEmpty() && style.contains(word.trimmed().toLower())) {
                score -= 1.0;
                break;
            }
        }
        for (const auto &word : avoid) {
            if (!word.trimmed().isEmpty() && style.contains(word.trimmed().toLower())) {
                score += 4.0;
                break;
            }
        }
        for (const auto &word : talking ? calm : lively) {
            if (style.contains(word)) {
                score -= 0.3;
                break;
            }
        }
        // Genre and mood alone are broad: "energetic" included the abrasive
        // style-test song. Keep these available for a deliberate manual pick,
        // but put them after pleasant alternatives for one-click Add music.
        for (const auto &word : harsh) {
            if (style.contains(word)) {
                score += 8.0;
                break;
            }
        }
        // equal songs take turns between videos (steady for one video)
        score += (qHash(song.path + QString::number(qRound(videoSeconds)), 0) % 1000) / 4000.0;
        scores.append({score, i});
    }
    std::sort(scores.begin(), scores.end());
    QList<Song> order;
    for (const auto &score : scores)
        order.append(songs[score.second]);
    return order;
}

QList<Song> suggest(const QList<Song> &songs, double videoSeconds, quint32 seed)
{
    // Three of the best ten, different artists; the seed picks which, so asking again gives others.
    QList<Song> order = ranked(songs, videoSeconds, true);
    QRandomGenerator random(seed);
    const int head = qMin(10, int(order.size()));
    for (int i = head - 1; i > 0; --i)
        order.swapItemsAt(i, int(random.bounded(i + 1)));
    QList<Song> picks;
    QStringList artists;
    for (const auto &song : order) {
        if (!song.artist.isEmpty() && artists.contains(song.artist.toLower()))
            continue;
        picks.append(song);
        artists << song.artist.toLower();
        if (picks.size() == 3)
            return picks;
    }
    for (const auto &song : order) {
        if (picks.size() == 3)
            break;
        if (!contains(picks, song.path))
            picks.append(song);
    }
    return picks;
}

namespace {

struct SpeechMeasurement
{
    QList<QPair<double, double>> spans;
    double level = -70.0;
    bool montage = false; // sound, but nobody talks
    QVector<float> loudness;
    double gapLevel = -40.0;
};

bool measureSpeech(MultitrackModel *model, double fps, int videoFrames, const QTemporaryDir &temp,
                   QProgressDialog &progress, SpeechMeasurement &speech)
{
    // 1. Where someone talks, and how loud: the video's own sound without its music and effects tracks.
    const QString wav = temp.filePath(QStringLiteral("talk.wav"));
    const bool rendered = renderTalk(model, fps, videoFrames, wav, &progress);
    if (progress.wasCanceled())
        return false;
    progress.setValue(1);
    if (rendered) {
        // Measured in mono; the export plays it on both channels, which reads 3 dB louder than one.
        speech.level = integratedLufs(wav, -1.0, &progress);
        if (speech.level > -69.0)
            speech.level += 3.0;
        const QVector<float> db = PauseRemover::loudness(wav);
        speech.loudness = db;
        if (db.size() > 100) {
            QVector<float> sorted = db;
            std::sort(sorted.begin(), sorted.end());
            speech.gapLevel = qBound(-46.0, double(sorted[sorted.size() * 9 / 10]) - 14.0, -28.0);
            const double step = 0.01;
            QList<QPair<double, double>> loud;
            for (int i = 0; i < db.size();) {
                if (db[i] < speech.gapLevel) {
                    ++i;
                    continue;
                }
                int j = i;
                while (j < db.size() && db[j] >= speech.gapLevel)
                    ++j;
                loud.append({i * step, j * step});
                i = j;
            }
            // To the sound level alone, a drill, wind or a song in the shot look like talking. The speech model
            // says where the words are: only loud stretches with words in them (or right beside them) duck the
            // music, and a video nobody talks in gets the music over its own sound instead.
            progress.setLabelText(QObject::tr("Listening for the talking..."));
            bool listened = false;
            const auto heard = PauseRemover::phrases(wav, &progress, &listened);
            if (progress.wasCanceled())
                return false;
            if (listened) {
                int words = 0;
                for (const auto &p : heard)
                    words += p.words;
                speech.montage = words < 3; // a lone "Thank you." is what the model hears in plain noise
                // Each word, from just before it starts (its aligned time lags the start by up to 0.4 s) to its
                // end: a drill right after a sentence is not talking. Phrases without word times keep the loud
                // stretches they overlap.
                QList<QPair<double, double>> spoken;
                for (const auto &p : heard) {
                    for (double w : p.wordTimes)
                        spoken.append({qMax(0.0, w - 0.45), w + 0.6});
                    if (!p.wordTimes.isEmpty())
                        continue;
                    for (const auto &span : std::as_const(loud)) {
                        if (span.second > p.from - 0.3 && span.first < p.to + 0.3)
                            spoken.append(span);
                    }
                }
                std::sort(spoken.begin(), spoken.end());
                loud.clear();
                for (const auto &span : std::as_const(spoken)) {
                    if (!loud.isEmpty() && span.first <= loud.last().second)
                        loud.last().second = qMax(loud.last().second, span.second);
                    else
                        loud.append(span);
                }
            }
            for (const auto &span : std::as_const(loud)) {
                if (!speech.spans.isEmpty() && span.first - speech.spans.last().second <= kMergeGap)
                    speech.spans.last().second = span.second;
                else
                    speech.spans.append(span);
            }
            speech.spans.removeIf([](const QPair<double, double> &s) { return s.second - s.first < 0.35; });
            if (speech.montage)
                speech.spans.clear();
        }
    }
    if (progress.wasCanceled())
        return false;
    progress.setValue(2);
    if (speech.level <= -69.0)
        speech.level = -14.0; // nobody talks: the music is the sound of the video, at the export loudness
    return true;
}

struct SongPiece
{
    int start;    // frame on the timeline
    int frames;   // length
    QString song; // file
};

QList<SongPiece> chooseSongPieces(const Options &options, int songFrames, int videoFrames, double fps, bool montage)
{
    // 2. The songs: the chosen one, then, when the video is longer, others that follow it (Add music used to repeat
    // the one song): each the best fit for the time left that is not in the chain yet, by another artist and in the
    // same feel when it can (nextSong). A refit keeps the chain it has (options.chain), adding songs only when the
    // video got longer. Each piece plays its song from the start.
    QList<QPair<QString, int>> chain{{options.song, songFrames}}; // songs in order, with their length in frames
    {
        int covered = songFrames;
        int kept = 0;
        QList<Song> listed;
        bool read = false;
        QStringList skip;
        while (covered < videoFrames) {
            QString next;
            while (next.isEmpty() && kept < options.chain.size()) {
                const QString earlier = options.chain.at(kept++);
                if (QFileInfo::exists(earlier) && !skip.contains(earlier))
                    next = earlier;
            }
            if (next.isEmpty()) {
                if (!read) {
                    listed = allSongs(musicFolder());
                    read = true;
                }
                QStringList paths;
                for (const auto &c : std::as_const(chain))
                    paths << c.first;
                next = nextSong(listed, paths, skip, (videoFrames - covered) / fps, !montage);
            }
            if (next.isEmpty())
                next = options.song; // nothing else to play: the song again, as before
            Mlt::Producer candidate(MLT.profile(), next.toUtf8().constData());
            if (!candidate.is_valid() || candidate.get_length() < qRound(fps)) {
                if (next == options.song)
                    break;
                skip << next; // unreadable: another one
                continue;
            }
            chain.append({next, candidate.get_length()});
            covered += candidate.get_length();
        }
    }
    QList<SongPiece> pieces;
    for (int i = 0, start = 0; i < chain.size() && start < videoFrames; start += chain[i].second, ++i)
        pieces.append({start, qMin(chain[i].second, videoFrames - start), chain[i].first});
    if (pieces.size() > 1 && pieces.last().frames < qRound(4 * fps))
        pieces.removeLast(); // a few seconds of another start sounds like a mistake; end with the previous piece
    return pieces;
}

void insertMusic(MainWindow *window, const Options &options, int musicTrack, const QList<SongPiece> &pieces,
                 const QList<QList<Key>> &curves, const QHash<QString, double> &base, double fps)
{
    auto timeline = window->timelineDock();
    auto model = timeline->model();
    window->undoStack()->beginMacro(QObject::tr("Add music"));
    int track = musicTrack;
    if (options.replace && musicTrack >= 0) {
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(model->trackList().at(musicTrack).mlt_index));
        Mlt::Playlist playlist(*producer);
        for (int c = playlist.count() - 1; c >= 0; --c) {
            if (!playlist.is_blank(c))
                timeline->lift(musicTrack, c, true);
        }
    } else {
        track = timeline->addAudioTrack();
        timeline->setTrackName(track, QStringLiteral("Music"));
    }
    for (int p = 0; p < pieces.size(); ++p) {
        const SongPiece &piece = pieces[p];
        const QList<Key> &own = curves[p];
        const double gainBase = base.value(piece.song);
        Mlt::Producer clip(MLT.profile(), piece.song.toUtf8().constData());
        clip.set(kShotcutCaptionProperty, QFileInfo(piece.song).completeBaseName().toUtf8().constData());
        clip.set(kVolumeProperty, qBound(0, options.volume, 2));
        clip.set(kDuckProperty, options.duck ? 1 : 0);
        clip.set_in_and_out(0, piece.frames - 1);
        Mlt::Filter gain(MLT.profile(), "volume");
        gain.set(kShotcutFilterProperty, "audioGain");
        gain.set("channel_mask", -1);
        const double s = piece.start / fps, e = (piece.start + piece.frames) / fps;
        QList<Key> keys{{0.0, gainBase + valueAt(own, s)}};
        for (const auto &k : own) {
            if (k.time > s && k.time < e)
                keys.append({k.time - s, gainBase + k.db});
        }
        keys.append({e - s, gainBase + valueAt(own, e)});
        bool flat = true;
        for (const auto &k : keys)
            flat = flat && std::abs(k.db - keys.first().db) < 0.05;
        if (flat) {
            gain.set("level", keys.first().db);
        } else {
            int last = -1;
            for (const auto &k : keys) {
                // Two keys on one frame would let the later one stand in for both and stretch a ramp.
                const int frame = qBound(0, qRound(k.time * fps), piece.frames - 1);
                if (frame == last)
                    continue;
                gain.anim_set("level", k.db, frame, piece.frames);
                last = frame;
            }
        }
        clip.attach(gain);
        gain.set_in_and_out(clip.get_in(), clip.get_out());
        timeline->overwrite(track, piece.start, MLT.XML(&clip), false);
    }
    // Fades: in at the start, a short dip where the next song (or a repeat) starts, out at the end.
    QScopedPointer<Mlt::Producer> producer(model->tractor()->track(model->trackList().at(track).mlt_index));
    Mlt::Playlist playlist(*producer);
    for (int i = 0; i < pieces.size(); ++i) {
        const int clipIndex = playlist.get_clip_index_at(pieces[i].start);
        const int length = pieces[i].frames;
        timeline->fadeIn(track, clipIndex, qMin(qRound((i == 0 ? kFadeIn : kJoint) * fps), length / 2));
        timeline->fadeOut(track,
                          clipIndex,
                          qMin(qRound((i == pieces.size() - 1 ? kFadeOut : kJoint) * fps), length / 2));
    }
    window->undoStack()->endMacro();
}

} // namespace

QString apply(MainWindow *window, const Options &given)
{
    // one spelling of every song path, the song list's (forward slashes), whoever passed them (the panel, the bridge,
    // a refit): the chain, the panel and the "in the video" mark compare paths
    Options options = given;
    options.song = QDir::fromNativeSeparators(options.song);
    for (auto &song : options.chain)
        song = QDir::fromNativeSeparators(song);
    auto timeline = window->timelineDock();
    auto model = timeline->model();
    if (!window->isMultitrackValid() || !model->tractor() || !QFileInfo::exists(options.song))
        return QString();
    const double fps = MLT.profile().fps();

    // The video's length without its music, and the music track already there (if any).
    int videoFrames = 0;
    int musicTrack = -1;
    for (int i = 0; i < model->trackList().size(); ++i) {
        const Track &track = model->trackList().at(i);
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(track.mlt_index));
        if (!producer || !producer->is_valid())
            continue;
        const QString name = QString::fromUtf8(producer->get(kTrackNameProperty));
        if (track.type == AudioTrackType && kMusicName.match(name).hasMatch()) {
            if (musicTrack < 0 || i == options.track)
                musicTrack = i;
            continue;
        }
        Mlt::Playlist playlist(*producer);
        videoFrames = qMax(videoFrames, playlist.get_playtime());
    }
    if (videoFrames < qRound(fps)) {
        window->showStatusMessage(QObject::tr("Add some video first: the music goes under it."));
        return QString();
    }
    if (options.replace && musicTrack >= 0 && timeline->isTrackLocked(musicTrack)) {
        window->showStatusMessage(QObject::tr("Unlock the music track first."));
        return QString();
    }
    const double videoSeconds = videoFrames / fps;

    Mlt::Producer song(MLT.profile(), options.song.toUtf8().constData());
    if (!song.is_valid() || song.get_length() < qRound(fps)) {
        window->showStatusMessage(QObject::tr("That song could not be read."));
        return QString();
    }
    const int songFrames = song.get_length();

    QProgressDialog progress(QObject::tr("Fitting the music to your video..."),
                             QObject::tr("Cancel"),
                             0,
                             3,
                             window);
    progress.setWindowTitle(QObject::tr("Add Music"));
    progress.setWindowModality(Qt::WindowModal);
    progress.setMinimumDuration(0);
    progress.setValue(0);
    QTemporaryDir temp;

    SpeechMeasurement speech;
    if (!measureSpeech(model, fps, videoFrames, temp, progress, speech))
        return QString();

    const QList<SongPiece> pieces = chooseSongPieces(options, songFrames, videoFrames, fps, speech.montage);

    // 3. How loud each song is, so it sits at the same place against the talking whatever its mastering.
    const Levels levels = kLevels[qBound(0, options.volume, 2)];
    // Over a video's own sound (no talking) the music sits this much above it: the shots' sound stays as texture.
    if (speech.montage)
        speech.level += kMontageLift[qBound(0, options.volume, 2)] - levels.inGaps;
    QStringList songs; // each song once, in order
    QHash<QString, double> played, songLufs, base;
    for (const auto &piece : std::as_const(pieces)) {
        if (!songs.contains(piece.song))
            songs << piece.song;
        played[piece.song] = qMax(played.value(piece.song), piece.frames / fps);
    }
    for (int i = 0; i < songs.size(); ++i) {
        if (songs.size() > 1)
            progress.setLabelText(QObject::tr("Measuring song %1 of %2...").arg(i + 1).arg(songs.size()));
        const double lufs = integratedLufs(songs[i], played.value(songs[i]), &progress);
        if (progress.wasCanceled())
            return QString();
        songLufs[songs[i]] = lufs;
        base[songs[i]] = lufs > -69.0 ? qBound(-40.0, speech.level - lufs, 15.0) : 0.0;
    }
    progress.setValue(3);

    // 4. The level over the video, ridden per piece against its own song.
    const QList<Key> curve = speech.montage ? QList<Key>{{0.0, levels.inGaps}, {videoSeconds, levels.inGaps}}
                             : options.duck
                                 ? levelCurve(speech.spans, videoSeconds, levels)
                                 : QList<Key>{{0.0, levels.underTalk}, {videoSeconds, levels.underTalk}};
    QList<QList<Key>> curves;
    for (const auto &piece : std::as_const(pieces)) {
        QList<Key> own = curve;
        if (options.duck && !speech.montage && !speech.spans.isEmpty() && !speech.loudness.isEmpty()) {
            progress.setLabelText(QObject::tr("Fitting the music to the voice..."));
            const QVector<float> songDb = songLoudness(piece.song, piece.frames / fps, &progress);
            if (progress.wasCanceled())
                return QString();
            if (!songDb.isEmpty())
                own = rideLevels(curve, levels, speech.loudness, speech.spans, speech.gapLevel, songDb, {{piece.start, piece.frames}}, fps,
                                 videoSeconds);
        }
        curves.append(own);
    }

    insertMusic(window, options, musicTrack, pieces, curves, base, fps);

    QStringList recent = leSettings().value("music/recent").toStringList();
    for (int i = songs.size() - 1; i >= 0; --i) {
        recent.removeAll(songs[i]);
        recent.prepend(songs[i]);
    }
    leSettings().setValue("music/recent", recent.mid(0, 12));
    for (const auto &song : std::as_const(songs))
        LOG_INFO() << "add music:" << song << "dialogue" << speech.level << "LUFS, song" << songLufs.value(song)
                   << "LUFS, base" << base.value(song) << "dB";
    LOG_INFO() << "add music:" << speech.spans.size() << "talking stretches," << pieces.size() << "pieces," << songs.size()
               << "songs" << (speech.montage ? "(nobody talks)" : "");

    // What the person hears, in a line short enough for the status bar.
    double talkSeconds = 0.0;
    for (const auto &span : speech.spans)
        talkSeconds += qMin(span.second, videoSeconds) - span.first;
    QStringList names;
    for (const auto &song : std::as_const(songs)) {
        const QString title = QFileInfo(song).completeBaseName().section(QStringLiteral(" - "), 0, 0);
        names << QStringLiteral("\u201c%1\u201d").arg(title);
    }
    const QString name = names.size() == 1 ? names.first()
                         : names.size() <= 3
                             ? QObject::tr("%1 and %2").arg(names.mid(0, names.size() - 1).join(QStringLiteral(", ")),
                                                            names.last())
                             : QObject::tr("%1, %2 and %3 more").arg(names[0], names[1]).arg(names.size() - 2);
    QString line;
    if (speech.montage)
        line = QObject::tr("Added %1 as music over the video's own sound (nobody talks), with fades.").arg(name);
    else if (!options.duck)
        line = QObject::tr("Added %1 as music at a steady level, with fades.").arg(name);
    else if (talkSeconds > 0.9 * videoSeconds)
        line = QObject::tr("Added %1 as music, kept low under the talking, with fades.").arg(name);
    else if (talkSeconds > 0.0)
        line = QObject::tr("Added %1 as music: low under the talking, up in the gaps, with fades.").arg(name);
    else
        line = QObject::tr("Added %1 as music, with fades.").arg(name);
    if (songs.size() > 1)
        line += ' ' + QObject::tr("%1 songs, one after another, each at its own level.").arg(songs.size());
    else if (pieces.size() > 1)
        line += ' ' + QObject::tr("It plays %1 times (no other song to follow it).").arg(pieces.size());
    return line + ' ' + QObject::tr("Undo removes it.");
}

bool isMusicName(const QString &trackName)
{
    return kMusicName.match(trackName).hasMatch();
}

bool fitted(MainWindow *window, int track, Options &options)
{
    auto model = window->timelineDock()->model();
    if (!model->tractor() || track < 0 || track >= model->trackList().size())
        return false;
    QScopedPointer<Mlt::Producer> producer(model->tractor()->track(model->trackList().at(track).mlt_index));
    if (!producer || !producer->is_valid())
        return false;
    Mlt::Playlist playlist(*producer);
    QStringList songs; // in order; a song repeated in a row (older Add music) counts once
    for (int i = 0; i < playlist.count(); ++i) {
        if (playlist.is_blank(i))
            continue;
        QScopedPointer<Mlt::ClipInfo> info(playlist.clip_info(i));
        // A piece without the marks was placed by hand: that music is not refitted.
        if (!info || !info->producer || !info->producer->property_exists(kVolumeProperty))
            return false;
        const QString resource = QDir::fromNativeSeparators(QString::fromUtf8(info->producer->get("resource")));
        if (songs.isEmpty() || songs.last() != resource)
            songs << resource;
        options.volume = qBound(0, info->producer->get_int(kVolumeProperty), 2);
        options.duck = info->producer->get_int(kDuckProperty) != 0;
    }
    if (songs.isEmpty() || !QFileInfo::exists(songs.first()))
        return false;
    options.song = songs.first();
    options.chain = songs.mid(1);
    options.replace = true;
    options.track = track;
    return true;
}

// The music on this video's music track from Add music, if any: the songs' paths, the first one first.
QStringList currentSongs(MainWindow *window)
{
    auto model = window->timelineDock()->model();
    for (int i = 0; i < model->trackList().size(); ++i) {
        Options options;
        if (model->trackList().at(i).type == AudioTrackType && fitted(window, i, options))
            return QStringList{options.song} + options.chain;
    }
    return {};
}

// The length of the video and whether it has music already (a track named like Music with clips on it).
void videoInfo(MainWindow *window, double &videoSeconds, bool &hasMusic)
{
    videoSeconds = 0.0;
    hasMusic = false;
    auto model = window->timelineDock()->model();
    if (!model->tractor())
        return;
    const double fps = MLT.profile().fps();
    for (const auto &track : model->trackList()) {
        QScopedPointer<Mlt::Producer> producer(model->tractor()->track(track.mlt_index));
        if (!producer || !producer->is_valid())
            continue;
        Mlt::Playlist playlist(*producer);
        const QString name = QString::fromUtf8(producer->get(kTrackNameProperty));
        if (track.type == AudioTrackType && kMusicName.match(name).hasMatch())
            hasMusic = hasMusic || playlist.count() > 0;
        else
            videoSeconds = qMax(videoSeconds, playlist.get_playtime() / fps);
    }
}

// Every song in the folder and the free library, best fit first, to play and to put in the video (or change the
// volume of the one there). A panel in the "Music & sound" dock, beside the video and the timeline.
class MusicPanel : public QWidget
{
public:
    MusicPanel(MainWindow *window, QWidget *parent)
        : QWidget(parent)
        , m_window(window)
    {
        setObjectName(QStringLiteral("musicPanel"));
        auto *layout = new QVBoxLayout(this);
        buildFilters(layout);
        buildMusicControls(layout);
        // where the songs come from is a detail: the folder line sits at the bottom
        auto *folderRow = new QHBoxLayout;
        m_folderLabel = new QLabel(this);
        m_folderLabel->setWordWrap(true);
        m_folderLabel->setProperty("studioMuted", true);
        auto *change = new QPushButton(QObject::tr("Change Folder..."), this);
        change->setObjectName(QStringLiteral("addMusicFolder"));
        folderRow->addWidget(m_folderLabel, 1);
        folderRow->addWidget(change);
        layout->addLayout(folderRow);
        // letitedit: the rest of the sound, where a beginner looks for it
        auto *soundRow = new QHBoxLayout;
        auto *voice = new QPushButton(QObject::tr("Clean up the voice..."), this);
        voice->setObjectName(QStringLiteral("musicCleanVoice"));
        voice->setToolTip(QObject::tr("Your AI takes out background noise and room echo from the talking, gently"));
        QObject::connect(voice, &QPushButton::clicked, this, []() {
            if (auto a = Actions["cleanVoiceAction"])
                a->trigger();
        });
        soundRow->addWidget(voice, 1);
        layout->addLayout(soundRow);

        setupPlayer();
        QObject::connect(change, &QPushButton::clicked, this, [this]() {
            const QString path = QFileDialog::getExistingDirectory(this, QObject::tr("Music Folder"), m_folder);
            if (path.isEmpty())
                return;
            leSettings().setValue("music/folder", QDir::fromNativeSeparators(path));
            refresh(true);
        });
        connectMusicControls();
    }

    // The video, the song in it and the list again (songs = re-read the folder). Every way to the list ends here:
    // the Music step, Add music, the AI's audio_library, and the panel simply coming into view (showEvent).
    void refresh(bool songs = true)
    {
        stop();
        videoInfo(m_window, m_videoSeconds, m_hasMusic);
        if (songs || m_songs.isEmpty()) {
            m_folder = musicFolder();
            // loading: said at once, before the folder and the library are read
            setState(QStringLiteral("loading"));
            m_list->clear();
            m_now->setText(QObject::tr("<b>Loading the music library...</b>"));
            m_folderLabel->clear();
            m_play->setEnabled(false);
            m_use->setEnabled(false);
            m_now->repaint();
            m_songs = allSongs(m_folder);
            probeMissing(m_songs, m_window);
        }
        m_inVideo = m_hasMusic ? currentSongs(m_window) : QStringList();
        m_current = m_inVideo.value(0);
        m_seen = signature();
        load();
    }

    QString state() const { return m_state; }

protected:
    void hideEvent(QHideEvent *event) override
    {
        stop();
        QWidget::hideEvent(event);
    }

    // shown by any way at all (a dock or tab coming back, the layout restored at start): filled and current
    void showEvent(QShowEvent *event) override
    {
        QWidget::showEvent(event);
        QTimer::singleShot(0, this, [this]() {
            if (isVisible() && (m_songs.isEmpty() || signature() != m_seen))
                refresh(m_songs.isEmpty());
        });
    }

private:
    void buildFilters(QVBoxLayout *layout)
    {
        m_now = new QLabel(this);
        m_now->setObjectName(QStringLiteral("addMusicNow"));
        m_now->setWordWrap(true);
        layout->addWidget(m_now);
        m_search = new QLineEdit(this);
        m_search->setObjectName(QStringLiteral("addMusicSearch"));
        m_search->setPlaceholderText(QObject::tr("Search titles, artists, genres and moods"));
        m_search->setClearButtonEnabled(true);
        layout->addWidget(m_search);
        auto *genreRow = new QHBoxLayout;
        m_genre = new QComboBox(this);
        m_genre->setObjectName(QStringLiteral("addMusicGenre"));
        m_genre->setAccessibleName(QObject::tr("Music genre"));
        m_genre->addItem(QObject::tr("All genres"));
        m_mood = new QComboBox(this);
        m_mood->setObjectName(QStringLiteral("addMusicMood"));
        m_mood->setAccessibleName(QObject::tr("Music mood"));
        m_mood->addItem(QObject::tr("All moods"));
        genreRow->addWidget(m_genre, 1);
        genreRow->addWidget(m_mood, 1);
        layout->addLayout(genreRow);
        auto *rangeRow = new QHBoxLayout;
        m_length = new QComboBox(this);
        m_length->setObjectName(QStringLiteral("addMusicLength"));
        m_length->setAccessibleName(QObject::tr("Music length"));
        m_length->addItem(QObject::tr("Any length"), 0);
        m_length->addItem(QObject::tr("Under 1 minute"), 60);
        m_length->addItem(QObject::tr("1–3 minutes"), 180);
        m_length->addItem(QObject::tr("3–5 minutes"), 300);
        m_length->addItem(QObject::tr("Over 5 minutes"), 301);
        m_bpm = new QComboBox(this);
        m_bpm->setObjectName(QStringLiteral("addMusicBpm"));
        m_bpm->setAccessibleName(QObject::tr("Music tempo"));
        m_bpm->addItem(QObject::tr("Any tempo"), 0);
        m_bpm->addItem(QObject::tr("Slow: under 90 BPM"), 90);
        m_bpm->addItem(QObject::tr("Medium: 90–119 BPM"), 120);
        m_bpm->addItem(QObject::tr("Fast: 120–149 BPM"), 150);
        m_bpm->addItem(QObject::tr("Very fast: 150+ BPM"), 151);
        m_bpm->addItem(QObject::tr("No steady beat"), -1);
        rangeRow->addWidget(m_length, 1);
        rangeRow->addWidget(m_bpm, 1);
        layout->addLayout(rangeRow);
        m_list = new QListWidget(this);
        m_list->setObjectName(QStringLiteral("addMusicList"));
        m_list->setWordWrap(true);
        m_list->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
        layout->addWidget(m_list, 1);
    }

    void buildMusicControls(QVBoxLayout *layout)
    {
        auto *playRow = new QHBoxLayout;
        m_play = new QPushButton(QObject::tr("Play"), this);
        m_play->setObjectName(QStringLiteral("addMusicPlay"));
        m_play->setToolTip(QObject::tr("Hear the song here; it stops when you pick another"));
        m_use = new QPushButton(QObject::tr("Use This Song"), this);
        m_use->setObjectName(QStringLiteral("addMusicGo"));
        m_use->setProperty("studioPrimary", true);
        m_here = new QPushButton(QObject::tr("Add at playhead"), this);
        m_here->setObjectName(QStringLiteral("addMusicAtPlayhead"));
        m_here->setToolTip(QObject::tr("Place this song on a Music track starting where the playhead is"));
        playRow->addWidget(m_play);
        playRow->addWidget(m_here);
        playRow->addWidget(m_use, 1);
        layout->addLayout(playRow);
        m_play->setEnabled(false);
        m_here->setEnabled(false);
        m_use->setEnabled(false);
        auto *volumeRow = new QHBoxLayout;
        volumeRow->addWidget(new QLabel(QObject::tr("Volume:"), this));
        m_volume = new QButtonGroup(this);
        const QStringList names{QObject::tr("Low"), QObject::tr("Medium"), QObject::tr("High")};
        const int saved = qBound(0, leSettings().value("music/volume", 1).toInt(), 2);
        for (int i = 0; i < 3; ++i) {
            auto *radio = new QRadioButton(names[i], this);
            radio->setObjectName(QStringLiteral("addMusicVolume%1").arg(i));
            radio->setChecked(i == saved);
            m_volume->addButton(radio, i);
            volumeRow->addWidget(radio);
        }
        volumeRow->addStretch(1);
        layout->addLayout(volumeRow);
        m_duck = new QCheckBox(QObject::tr("Quieter while someone talks"), this);
        m_duck->setObjectName(QStringLiteral("addMusicDuck"));
        m_duck->setChecked(leSettings().value("music/duck", true).toBool());
        layout->addWidget(m_duck);
        m_status = new QLabel(this);
        m_status->setObjectName(QStringLiteral("aiAudioStatus_music"));
        m_status->setWordWrap(true);
        m_status->setProperty("studioMuted", true);
        layout->addWidget(m_status);
    }

    void setupPlayer()
    {
        m_player = new QMediaPlayer(this);
        m_output = new QAudioOutput(this);
        m_player->setAudioOutput(m_output);
        m_output->setVolume(0.8f);
        QObject::connect(m_player, &QMediaPlayer::mediaStatusChanged, this, [this](QMediaPlayer::MediaStatus status) {
            if (status == QMediaPlayer::EndOfMedia || status == QMediaPlayer::InvalidMedia)
                stop();
        });
    }

    void connectMusicControls()
    {
        QObject::connect(m_search, &QLineEdit::textChanged, this, [this]() { filterSongs(); });
        for (auto *filter : {m_genre, m_mood, m_length, m_bpm})
            QObject::connect(filter, &QComboBox::currentIndexChanged, this, [this]() { filterSongs(); });
        QObject::connect(m_list, &QListWidget::itemSelectionChanged, this, [this]() { refreshUse(); });
        QObject::connect(m_list, &QListWidget::currentItemChanged, this, [this]() {
            if (m_player->playbackState() == QMediaPlayer::PlayingState && !selected().isEmpty()) {
                m_player->setSource(QUrl::fromLocalFile(selected()));
                m_player->play();
            }
            refreshUse();
        });
        QObject::connect(m_play, &QPushButton::clicked, this, [this]() {
            if (m_player->playbackState() == QMediaPlayer::PlayingState) {
                stop();
                return;
            }
            if (selected().isEmpty())
                return;
            m_player->setSource(QUrl::fromLocalFile(selected()));
            m_player->play();
            m_play->setText(QObject::tr("Stop"));
        });
        QObject::connect(m_list, &QListWidget::itemDoubleClicked, this, [this](QListWidgetItem *) { m_play->click(); });
        QObject::connect(m_here, &QPushButton::clicked, this, [this]() {
            const QString path = selected();
            if (path.isEmpty() || !m_window->isMultitrackValid())
                return;
            stop();
            QString why;
            const QString label = QObject::tr("Add music at playhead: %1").arg(QFileInfo(path).completeBaseName());
            const QString xml = LeFeatures::producerXml(path, true, QString(), 0, 0, &why);
            if (!xml.isEmpty() && LeFeatures::placeAtPlayhead(m_window, xml, true, QObject::tr("Music"), label, &why)) {
                m_status->setText(QObject::tr("Added at the playhead on a Music track. Undo takes it back."));
                m_window->showStatusMessage(label, 8);
            } else {
                m_status->setText(why);
            }
        });
        QObject::connect(m_use, &QPushButton::clicked, this, [this]() {
            if (selected().isEmpty())
                return;
            if (!m_window->isMultitrackValid()) {
                m_status->setText(QObject::tr("Add clips to the timeline first."));
                return;
            }
            stop();
            Options options;
            options.song = selected();
            options.volume = m_volume->checkedId();
            options.duck = m_duck->isChecked();
            options.replace = m_hasMusic;
            if (options.song == m_current)
                options.chain = m_inVideo.mid(1); // Update the Music: the same songs, the new settings
            leSettings().setValue("music/volume", options.volume);
            leSettings().setValue("music/duck", options.duck);
            const QString line = apply(m_window, options);
            if (!line.isEmpty()) {
                m_window->showStatusMessage(line, 15);
                m_status->setText(line + ' ' + QObject::tr("Undo takes it back."));
            }
            refresh(false);
        });
    }

    void filterSongs()
    {
        int shown = 0;
        for (int i = 0; i < m_list->count(); ++i) {
            auto *item = m_list->item(i);
            const auto path = item->data(Qt::UserRole).toString();
            const auto song = std::find_if(m_songs.cbegin(), m_songs.cend(), [&path](const Song &s) { return s.path == path; });
            if (song == m_songs.cend())
                continue;
            const QString words = QStringList{song->title, song->artist, song->genre, song->mood, song->path}.join(' ');
            const int length = m_length->currentData().toInt();
            const int bpm = m_bpm->currentData().toInt();
            const bool lengthOk = !length || (song->seconds > 0 && (length == 60 ? song->seconds < 60
                : length == 180 ? song->seconds >= 60 && song->seconds < 180
                : length == 300 ? song->seconds >= 180 && song->seconds <= 300 : song->seconds > 300));
            const bool bpmOk = !bpm || (bpm == -1 ? song->bpm == 0 : song->bpm > 0 &&
                (bpm == 90 ? song->bpm < 90 : bpm == 120 ? song->bpm >= 90 && song->bpm < 120
                 : bpm == 150 ? song->bpm >= 120 && song->bpm < 150 : song->bpm >= 150));
            const bool visible = words.contains(m_search->text().trimmed(), Qt::CaseInsensitive)
                && (m_genre->currentData().toString().isEmpty() || song->genre == m_genre->currentData().toString())
                && (m_mood->currentData().toString().isEmpty() || song->mood == m_mood->currentData().toString())
                && lengthOk && bpmOk;
            item->setHidden(!visible);
            shown += visible;
        }
        if (m_list->count())
            m_status->setText(QObject::tr("%1 of %2 songs shown.").arg(shown).arg(m_list->count()));
        if (m_list->currentItem() && m_list->currentItem()->isHidden())
            m_list->clearSelection();
        refreshUse();
    }

    // what the list depends on: the project, its length and the music in it
    QString signature() const
    {
        double seconds = 0.0;
        bool music = false;
        videoInfo(m_window, seconds, music);
        return QStringLiteral("%1|%2|%3|%4")
            .arg(m_window->fileName())
            .arg(seconds, 0, 'f', 2)
            .arg(music)
            .arg(music ? currentSongs(m_window).join(QLatin1Char(';')) : QString());
    }

    void setState(const QString &state)
    {
        m_state = state;
        setProperty("musicState", state);
    }

    QString selected() const
    {
        // the highlighted song (a click, the keyboard or a screen reader may move one without the other)
        const auto items = m_list->selectedItems();
        const QListWidgetItem *item = items.isEmpty() ? m_list->currentItem() : items.first();
        return item && !item->isHidden() ? item->data(Qt::UserRole).toString() : QString();
    }
    void stop()
    {
        if (m_player)
            m_player->stop();
        if (m_play)
            m_play->setText(QObject::tr("Play"));
    }
    void refreshUse()
    {
        const QString path = selected();
        m_play->setEnabled(!path.isEmpty());
        m_here->setEnabled(!path.isEmpty() && m_window->isMultitrackValid());
        m_use->setEnabled(!path.isEmpty() && m_window->isMultitrackValid());
        m_use->setText(!m_current.isEmpty() && path == m_current ? QObject::tr("Update the Music")
                                                                : QObject::tr("Use This Song"));
    }
    void load()
    {
        m_list->clear();
        const QString selectedGenre = m_genre->currentData().toString();
        const QString selectedMood = m_mood->currentData().toString();
        QSet<QString> genres, moods;
        for (const auto &song : std::as_const(m_songs)) {
            if (!song.genre.isEmpty()) genres.insert(song.genre);
            if (!song.mood.isEmpty()) moods.insert(song.mood);
        }
        const QSignalBlocker genreBlock(m_genre), moodBlock(m_mood);
        m_genre->clear();
        m_genre->addItem(QObject::tr("All genres"), QString());
        auto sortedGenres = genres.values();
        sortedGenres.sort(Qt::CaseInsensitive);
        for (const auto &genre : std::as_const(sortedGenres)) m_genre->addItem(genre, genre);
        m_genre->setCurrentIndex(qMax(0, m_genre->findData(selectedGenre)));
        m_mood->clear();
        m_mood->addItem(QObject::tr("All moods"), QString());
        auto sortedMoods = moods.values();
        sortedMoods.sort(Qt::CaseInsensitive);
        for (const auto &mood : std::as_const(sortedMoods)) m_mood->addItem(mood, mood);
        m_mood->setCurrentIndex(qMax(0, m_mood->findData(selectedMood)));
        const bool free = QFileInfo(freeLibraryFolder()).isDir();
        const bool folderThere = m_folder.isEmpty() || QFileInfo(m_folder).isDir();
        m_folderLabel->setText(m_songs.isEmpty()
                                   ? QObject::tr("No songs in %1 yet. Put MP3 or WAV files there or choose another "
                                                 "folder.").arg(QDir::toNativeSeparators(m_folder))
                               : free ? QObject::tr("%n songs available from your folder and the free library.", nullptr,
                                                    m_songs.size())
                                      : QObject::tr("%n songs available.", nullptr, m_songs.size()));
        m_folderLabel->setToolTip(QDir::toNativeSeparators(m_folder));
        if (m_songs.isEmpty()) {
            // empty, or a folder that can't be read: said plainly, with what to do; nothing to play or use
            setState(folderThere ? QStringLiteral("empty") : QStringLiteral("error"));
            m_now->setText(folderThere
                               ? QObject::tr("<b>No songs yet.</b> Put MP3 or WAV files in %1, or press Change "
                                             "Folder to pick the folder your music is in.")
                                     .arg(QDir::toNativeSeparators(m_folder).toHtmlEscaped())
                               : QObject::tr("<b>Couldn't read the music folder.</b> %1 isn't there (a drive that is "
                                             "unplugged, or a folder that moved?). Press Change Folder to pick another.")
                                     .arg(QDir::toNativeSeparators(m_folder).toHtmlEscaped()));
            refreshUse();
            return;
        }
        setState(QStringLiteral("ready"));
        // The song in the video first (adding it made it "used lately"), then the rest, best fit first.
        QList<Song> order = ranked(m_songs, m_videoSeconds, true);
        for (int i = 0; i < order.size(); ++i) {
            if (order[i].path == m_current) {
                order.move(i, 0);
                break;
            }
        }
        for (const auto &song : std::as_const(order)) {
            QString text = describe(song);
            if (song.seconds > 0.0 && m_videoSeconds > 0.0 && song.seconds < m_videoSeconds)
                text += QObject::tr(" (other songs follow)");
            if (song.path == m_current)
                text = QStringLiteral("\u25CF ") + text + QObject::tr("  (in the video)");
            auto *item = new QListWidgetItem(text, m_list);
            item->setSizeHint(QSize(0, 44));
            item->setData(Qt::UserRole, song.path);
            item->setToolTip(song.path);
            if (song.path == m_current) {
                QFont font = item->font();
                font.setBold(true);
                item->setFont(font);
                m_list->setCurrentItem(item);
            }
        }
        if (!m_list->currentItem() && m_list->count())
            m_list->setCurrentRow(0);
        m_now->setText(!m_window->isMultitrackValid()
                           ? QObject::tr("<b>Music.</b> Open or start a video to fit music to it.")
                       : m_current.isEmpty()
                           ? QObject::tr("<b>Pick music for this %1 video.</b> Best fit first; Play to hear it.")
                                 .arg(clockText(m_videoSeconds))
                       : m_inVideo.size() > 1
                           ? QObject::tr("<b>In the video: %1, then %2 more.</b> Pick another song to start with, or "
                                         "change the volume and press Update the Music.")
                                 .arg(QFileInfo(m_current).completeBaseName().toHtmlEscaped())
                                 .arg(m_inVideo.size() - 1)
                           : QObject::tr("<b>In the video: %1.</b> Pick another song to change it, or change the "
                                         "volume and press Update the Music.")
                                 .arg(QFileInfo(m_current).completeBaseName().toHtmlEscaped()));
        filterSongs();
        refreshUse();
    }

    MainWindow *m_window;
    QLabel *m_now{nullptr};
    QLabel *m_folderLabel{nullptr};
    QLabel *m_status{nullptr};
    QLineEdit *m_search{nullptr};
    QComboBox *m_genre{nullptr};
    QComboBox *m_mood{nullptr};
    QComboBox *m_length{nullptr};
    QComboBox *m_bpm{nullptr};
    QListWidget *m_list{nullptr};
    QPushButton *m_play{nullptr};
    QPushButton *m_here{nullptr};
    QPushButton *m_use{nullptr};
    QButtonGroup *m_volume{nullptr};
    QCheckBox *m_duck{nullptr};
    QMediaPlayer *m_player{nullptr};
    QAudioOutput *m_output{nullptr};
    QString m_folder;
    QString m_current;     // the song the music starts with
    QStringList m_inVideo; // every song Add music put in, in order
    QList<Song> m_songs;
    double m_videoSeconds = 0.0;
    bool m_hasMusic = false;
    QString m_state;
    QString m_seen; // signature() when the list was last made
};

QWidget *createMusicPanel(MainWindow *window, QWidget *parent)
{
    return new MusicPanel(window, parent);
}

void showMusicPanel(MainWindow *window)
{
    auto *dock = window->findChild<QDockWidget *>(QStringLiteral("aiAudioLibraryDock"));
    // the panel is a plain QWidget subclass (no Q_OBJECT), found by its name
    auto *panel = dock ? static_cast<MusicPanel *>(dock->findChild<QWidget *>(QStringLiteral("musicPanel"))) : nullptr;
    if (!dock || !panel)
        return;
    if (auto *tabs = dock->findChild<QTabWidget *>(QStringLiteral("aiAudioTabs")))
        tabs->setCurrentWidget(panel);
    dock->show();
    dock->raise();
    panel->refresh(true);
}

void addMusic(MainWindow *window)
{
    if (!window->isMultitrackValid()) {
        window->showStatusMessage(QObject::tr("Add clips to the timeline first."));
        return;
    }
    double videoSeconds = 0.0;
    bool hasMusic = false;
    videoInfo(window, videoSeconds, hasMusic);
    // Music already in: the list beside the video, to change the song or its volume.
    if (hasMusic) {
        showMusicPanel(window);
        return;
    }
    // Otherwise the best fit goes straight in; the status line opens the list to change it.
    QList<Song> songs = allSongs(musicFolder());
    probeMissing(songs, window);
    const QList<Song> order = ranked(songs, videoSeconds, true);
    if (order.isEmpty()) {
        showMusicPanel(window);
        return;
    }
    Options options;
    options.song = order.first().path;
    options.volume = qBound(0, leSettings().value("music/volume", 1).toInt(), 2);
    options.duck = leSettings().value("music/duck", true).toBool();
    options.replace = false;
    const QString line = apply(window, options);
    if (line.isEmpty())
        return;
    // The status line takes the action and shows its text; a click on it opens the list.
    auto *more = new QAction(line + ' ' + QObject::tr("Click here for other songs."));
    QObject::connect(more, &QAction::triggered, window, [window]() { showMusicPanel(window); });
    window->showStatusMessage(more, 20);
}

} // namespace MusicPicker
