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

#include "letitedit/export/pauseremover.h"

#include "letitedit/dialogs/lejobs.h"

#include "letitedit/letitedit.h"

#include <QButtonGroup>
#include <QCheckBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLabel>
#include <QPushButton>
#include <QRadioButton>
#include <QRegularExpression>
#include <QSet>
#include <QTemporaryDir>
#include <QThread>
#include <QVBoxLayout>
#include <QtEndian>

#include <algorithm>
#include <cmath>

namespace PauseRemover {

namespace {

const double kHop = 0.01;    // seconds per loudness step
const int kGapSteps = 15;    // the shortest quiet stretch (0.15 s) that counts as a gap between sounds
const double kMinCut = 0.15; // a shorter cut is not worth the jump

struct Hold
{
    double midSentence;
    double afterSentence;
};

// Seconds of each pause that stay.
Hold holdFor(Mode mode)
{
    switch (mode) {
    case Gentle:
        return {0.60, 1.00};
    case Tight:
        return {0.20, 0.45};
    default:
        return {0.35, 0.70};
    }
}

bool endsSentence(const QString &word)
{
    for (int i = word.size() - 1; i >= 0; --i) {
        const QChar c = word.at(i);
        if (c == '.' || c == '?' || c == '!')
            return true;
        if (c.isLetterOrNumber())
            return false;
    }
    return false;
}

struct Span
{
    double from;
    double to;
};

} // namespace

bool isFiller(const QString &word)
{
    QString bare;
    for (const QChar c : word) {
        if (c.isLetter())
            bare += c.toLower();
    }
    // Only sounds that are never a real word ("er" is German for "he", "ah" and "eh" are words in many languages).
    static const QSet<QString> fillers{"um", "umm", "uh", "uhh", "uhm", "erm", "hmm", "hm", "mm", "mhm",
                                       QString::fromUtf8("äh"), QString::fromUtf8("ähm"), "euh"};
    return fillers.contains(bare);
}

int wordsHeard(const QByteArray &pcm16kMono)
{
    const QString whisper = Settings.whisperExe();
    const QString speechModel = Settings.whisperModel();
    if (!QFileInfo(whisper).isExecutable() || !QFileInfo::exists(speechModel) || pcm16kMono.size() < 32000)
        return -1;
    QTemporaryDir temp;
    const QString wav = temp.filePath(QStringLiteral("sample.wav"));
    QFile file(wav);
    if (!file.open(QIODevice::WriteOnly))
        return -1;
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
    file.write("RIFF" + le32(36 + pcm16kMono.size()) + "WAVE" + "fmt " + le32(16) + le16(1) + le16(1) + le32(16000)
               + le32(32000) + le16(2) + le16(16) + "data" + le32(pcm16kMono.size()));
    file.write(pcm16kMono);
    file.close();
    const QString base = temp.filePath(QStringLiteral("sample"));
    QStringList args{"-m", speechModel, "-f", wav, "-l",
                     QFileInfo(speechModel).fileName().contains(QLatin1String(".en")) ? "en" : "auto",
                     "-otxt", "-of", base, "-nt", "-np", "-t", QString::number(leThreads())};
    if (!Settings.whisperUseGpu())
        args << "--no-gpu";
    if (!leRun(whisper, args, nullptr, nullptr, 30000))
        return -1;
    QFile text(base + ".txt");
    if (!text.open(QIODevice::ReadOnly))
        return -1;
    // What the model writes for no speech: [BLANK_AUDIO], (wind blowing), [Music], music notes.
    static const QRegularExpression noise(QStringLiteral("\\[[^\\]]*\\]|\\([^)]*\\)|\\*[^*]*\\*|[\\x{266A}\\x{266B}]"));
    static const QRegularExpression word(QStringLiteral("[\\p{L}']{2,}"));
    const QString heard = QString::fromUtf8(text.readAll()).replace(noise, QStringLiteral(" "));
    int words = 0;
    for (auto it = word.globalMatch(heard); it.hasNext(); it.next())
        ++words;
    LOG_INFO() << "speech check: heard" << words << "words in" << pcm16kMono.size() / 32000 << "s of sound:"
               << heard.simplified().left(120);
    return words;
}

QList<Phrase> phrases(const QString &wav16kMono, QProgressDialog *progress, bool *ok)
{
    *ok = false;
    QList<Phrase> result;
    const QString whisper = Settings.whisperExe();
    const QString speechModel = Settings.whisperModel();
    if (!QFileInfo(whisper).isExecutable() || !QFileInfo::exists(speechModel))
        return result;
    QTemporaryDir temp;
    const QString base = temp.filePath(QStringLiteral("speech"));
    QStringList args{"-m", speechModel, "-f", wav16kMono, "-l",
                     QFileInfo(speechModel).fileName().contains(QLatin1String(".en")) ? "en" : "auto",
                     "-oj", "-of", base, "-nfa", "-np", "-t", QString::number(leThreads())};
    // Word alignment gives where each phrase's first word really starts (a phrase's own start is often early).
    const QString preset = alignmentPreset(speechModel);
    if (!preset.isEmpty())
        args << "-ojf" << "-dtw" << preset;
    if (!Settings.whisperUseGpu())
        args << "--no-gpu";
    // the whole talk is listened to: one heavy job at a time on this PC (it waits its turn for the render lock)
    if (!leRunHeavy(QStringLiteral("letitedit listening for pauses"), whisper, args, progress))
        return result;
    QFile file(base + ".json");
    if (!file.open(QIODevice::ReadOnly))
        return result;
    static const QRegularExpression noise(QStringLiteral("\\[[^\\]]*\\]|\\([^)]*\\)|\\*[^*]*\\*|[\\x{266A}\\x{266B}]"));
    static const QRegularExpression word(QStringLiteral("[\\p{L}']{2,}"));
    for (const auto &value : QJsonDocument::fromJson(file.readAll()).object().value("transcription").toArray()) {
        const QJsonObject segment = value.toObject();
        const QString text = segment.value("text").toString().replace(noise, QStringLiteral(" "));
        int words = 0;
        for (auto it = word.globalMatch(text); it.hasNext(); it.next())
            ++words;
        const QJsonObject offsets = segment.value("offsets").toObject();
        const double from = offsets.value("from").toDouble() / 1000.0, to = offsets.value("to").toDouble() / 1000.0;
        QList<double> times;
        for (const auto &token : segment.value("tokens").toArray()) {
            const QJsonObject t = token.toObject();
            const QString piece = t.value("text").toString();
            if (piece.startsWith(' ') && piece.size() > 1 && piece.at(1).isLetterOrNumber()
                && t.value("t_dtw").toDouble(-1) >= 0)
                times.append(t.value("t_dtw").toDouble() / 100.0);
        }
        if (words > 0 && to > from)
            result.append({from, to, words, times.isEmpty() ? -1.0 : times.first(), times});
    }
    *ok = true;
    return result;
}

bool askOptions(QWidget *parent, Mode &mode, bool &removeFillers)
{
    QDialog dialog(parent);
    dialog.setObjectName(QStringLiteral("removePausesDialog"));
    dialog.setWindowTitle(QObject::tr("Remove Pauses"));
    auto *layout = new QVBoxLayout(&dialog);
    auto *intro = new QLabel(QObject::tr("Cuts the quiet gaps out of the talking on the main video track. The other "
                                         "tracks, captions and markers move with it. Music plays on without a jump "
                                         "and is fitted to the new length. One Undo brings it all back."));
    intro->setWordWrap(true);
    layout->addWidget(intro);

    const QStringList keys{"gentle", "normal", "tight"};
    const QStringList labels{QObject::tr("Gentle: only long pauses get shorter"),
                             QObject::tr("Normal: snappy, with a beat after each sentence"),
                             QObject::tr("Tight: fast, for shorts")};
    const QString saved = leSettings().value("pauses/mode", "normal").toString();
    auto *group = new QButtonGroup(&dialog);
    for (int i = 0; i < keys.size(); ++i) {
        auto *button = new QRadioButton(labels[i]);
        button->setObjectName(QStringLiteral("removePauses_") + keys[i]);
        button->setChecked(keys[i] == saved);
        group->addButton(button, i);
        layout->addWidget(button);
    }
    if (!group->checkedButton())
        group->button(Normal)->setChecked(true);

    auto *fillers = new QCheckBox(QObject::tr("Also cut um and uh"));
    fillers->setObjectName(QStringLiteral("removePausesFillers"));
    fillers->setToolTip(QObject::tr("Only the ones with a pause on both sides, so no word gets clipped"));
    fillers->setChecked(leSettings().value("pauses/fillers", true).toBool());
    layout->addWidget(fillers);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel);
    auto *go = buttons->addButton(QObject::tr("Remove Pauses"), QDialogButtonBox::AcceptRole);
    go->setObjectName(QStringLiteral("removePausesGo"));
    go->setDefault(true);
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    layout->addWidget(buttons);

    if (dialog.exec() != QDialog::Accepted)
        return false;
    mode = Mode(group->checkedId());
    removeFillers = fillers->isChecked();
    leSettings().setValue("pauses/mode", keys[group->checkedId()]);
    leSettings().setValue("pauses/fillers", removeFillers);
    return true;
}

QVector<float> loudness(const QString &wavPath)
{
    QVector<float> result;
    QFile file(wavPath);
    if (!file.open(QIODevice::ReadOnly))
        return result;
    const QByteArray data = file.readAll();
    if (data.size() < 12 || !data.startsWith("RIFF") || data.mid(8, 4) != "WAVE")
        return result;
    int channels = 1, rate = 16000, bits = 16;
    qint64 pos = 12;
    while (pos + 8 <= data.size()) {
        const QByteArray id = data.mid(pos, 4);
        const quint32 size = qFromLittleEndian<quint32>(data.constData() + pos + 4);
        const qint64 body = pos + 8;
        if (id == "fmt " && size >= 16 && body + 16 <= data.size()) {
            channels = qFromLittleEndian<quint16>(data.constData() + body + 2);
            rate = int(qFromLittleEndian<quint32>(data.constData() + body + 4));
            bits = qFromLittleEndian<quint16>(data.constData() + body + 14);
        } else if (id == "data") {
            if (bits != 16 || channels < 1 || rate < 1000)
                return result;
            const qint64 end = (size == 0 || body + size > data.size()) ? data.size() : body + size;
            const int frameBytes = channels * 2;
            const int hop = qMax(1, int(rate * kHop));
            const char *samples = data.constData() + body;
            const qint64 count = (end - body) / frameBytes;
            for (qint64 i = 0; i + hop <= count; i += hop) {
                double sum = 0.0;
                for (int k = 0; k < hop; ++k) {
                    const double s = qFromLittleEndian<qint16>(samples + (i + k) * frameBytes);
                    sum += s * s;
                }
                const double rms = std::sqrt(sum / hop);
                result.append(float(20.0 * std::log10(qMax(rms, 1.0) / 32768.0)));
            }
            return result;
        }
        pos = body + size + (size & 1);
    }
    return result;
}

QList<Word> words(const QString &jsonPath)
{
    QList<Word> result;
    QFile file(jsonPath);
    if (!file.open(QIODevice::ReadOnly))
        return result;
    const QJsonArray segments = QJsonDocument::fromJson(file.readAll()).object().value("transcription").toArray();
    for (const auto &segment : segments) {
        for (const auto &value : segment.toObject().value("tokens").toArray()) {
            const QJsonObject token = value.toObject();
            const QString text = token.value("text").toString();
            if (text.isEmpty() || text.startsWith("[_") || text.startsWith("<|"))
                continue;
            bool letters = false;
            for (const QChar c : text) {
                if (c.isLetterOrNumber()) {
                    letters = true;
                    break;
                }
            }
            if (letters && (text.startsWith(' ') || result.isEmpty()))
                result.append({text.trimmed(), token.value("t_dtw").toDouble(-1.0) / 100.0});
            else if (!result.isEmpty())
                result.last().text += text; // the rest of a word, or its punctuation
        }
    }
    // Sound notes such as [BLANK_AUDIO] or (music) are not words.
    result.removeIf([](const Word &w) {
        return w.text.startsWith('[') || w.text.startsWith('(') || w.text.startsWith('*');
    });
    return result;
}

QString alignmentPreset(const QString &modelPath)
{
    QString name = QFileInfo(modelPath).completeBaseName();
    if (name.startsWith("ggml-"))
        name = name.mid(5);
    name.remove(QRegularExpression("-q[0-9].*$"));
    name.replace('-', '.');
    static const QStringList presets{"tiny",
                                     "tiny.en",
                                     "base",
                                     "base.en",
                                     "small",
                                     "small.en",
                                     "medium",
                                     "medium.en",
                                     "large.v1",
                                     "large.v2",
                                     "large.v3",
                                     "large.v3.turbo"};
    return presets.contains(name) ? name : QString();
}

namespace {

QSet<int> findLoneFillers(const QList<Span> &quiet, const QList<Word> &fillers,
                          const QList<Word> &spoken, bool removeFillers, Plan &result)
{
    // An um or uh goes only when it stands alone: a gap on both sides, and the words around it aligned outside.
    QSet<int> merged; // quiet stretch indexes whose following sound is a lone filler
    if (removeFillers) {
        for (const auto &f : fillers) {
            int k = -1;
            for (int r = 0; r + 1 < quiet.size(); ++r) {
                const double from = quiet[r].to, to = quiet[r + 1].from;
                if ((f.time >= from - 0.05 && f.time <= to + 0.05)
                    || (f.time > to && f.time - from <= 0.5 && f.time < quiet[r + 1].to)) {
                    k = r;
                    break;
                }
            }
            bool alone = false;
            if (k >= 0) {
                const double from = quiet[k].to, to = quiet[k + 1].from, gapEnd = quiet[k + 1].to;
                const Word *before = nullptr, *after = nullptr;
                for (const auto &w : spoken) {
                    if (w.time < f.time)
                        before = &w;
                    else if (w.time > f.time && !after)
                        after = &w;
                }
                alone = to - from >= 0.12 && to - from <= 1.0 && (!before || before->time < from - 0.05)
                        && (!after || after->time >= gapEnd - 0.05);
            }
            if (alone) {
                merged.insert(k);
                ++result.fillersRemoved;
            } else {
                ++result.fillersKept;
            }
        }
    }
    return merged;
}

} // namespace

Plan plan(const QVector<float> &db, const QList<Word> &heard, Mode mode, bool removeFillers)
{
    Plan result;
    const int n = db.size();
    if (n < 2 * kGapSteps)
        return result;
    const double duration = n * kHop;

    // Two levels from this clip's own sound: under the gap level is a pause between words; between it and the soft
    // level are word endings and onsets (an s, a breathy vowel), which always stay.
    QVector<float> sorted = db;
    std::sort(sorted.begin(), sorted.end());
    const double floor = sorted[n / 20], speech = sorted[n * 9 / 10];
    const double gapLevel = qBound(-46.0, speech - 14.0, -28.0);
    const double softLevel = qMax(-52.0, qMin(gapLevel - 4.0, qMin(floor + 9.0, speech - 20.0)));

    QList<Span> quiet; // at least kGapSteps long, or touching the start or end
    for (int i = 0; i < n;) {
        if (db[i] >= gapLevel) {
            ++i;
            continue;
        }
        int j = i;
        while (j < n && db[j] < gapLevel)
            ++j;
        if (j - i >= kGapSteps || i == 0 || j == n)
            quiet.append({i * kHop, j * kHop});
        i = j;
    }

    QList<Word> spoken; // aligned words that are not um or uh
    QList<Word> fillers;
    for (const auto &w : heard) {
        if (w.time < 0.0)
            continue;
        (isFiller(w.text) ? fillers : spoken).append(w);
    }

    const QSet<int> merged = findLoneFillers(quiet, fillers, spoken, removeFillers, result);

    const Hold hold = holdFor(mode);
    for (int r = 0; r < quiet.size(); ++r) {
        const double from = quiet[r].from;
        double to = quiet[r].to;
        QList<Span> islands; // lone fillers inside this pause
        while (merged.contains(r) && r + 1 < quiet.size()) {
            islands.append({quiet[r].to, quiet[r + 1].from});
            ++r;
            to = quiet[r].to;
        }

        const Word *before = nullptr;
        for (const auto &w : spoken) {
            if (w.time <= from + 0.05)
                before = &w;
        }
        const double keep = (before && endsSentence(before->text)) ? hold.afterSentence : hold.midSentence;

        // Move the edges past the soft ending of the word before and the soft onset of the word after.
        double s0 = from, s1 = to;
        if (from > 0.0) {
            int i = qRound(from / kHop);
            while (i < n && i * kHop < from + 0.25 && db[i] >= softLevel)
                ++i;
            s0 = i * kHop;
        }
        if (to < duration - kHop) {
            int i = qRound(to / kHop) - 1;
            while (i > 0 && s1 > to - 0.25 && db[i] >= softLevel) {
                s1 = i * kHop;
                --i;
            }
        }
        if (s1 <= s0)
            continue;

        double c0, c1;
        if (from <= 0.0) { // dead air before the first word
            c0 = 0.0;
            c1 = s1 - keep * 0.6;
        } else if (to >= duration - kHop) { // dead air after the last word
            c0 = s0 + keep * 0.6;
            c1 = duration;
        } else {
            double head = keep * 0.55, tail = keep * 0.45;
            if (!islands.isEmpty()) {
                head = qMin(head, islands.first().from - s0);
                tail = qMin(tail, s1 - islands.last().to);
            }
            c0 = s0 + head;
            c1 = s1 - tail;
        }
        if (!islands.isEmpty()) {
            // The filler's own soft onset and fading tail go with it.
            if (c0 > 0.0) {
                const double start = islands.first().from;
                int i = qRound(start / kHop) - 1;
                while (i > 0 && i * kHop > qMax(s0, start - 0.25) && db[i] >= softLevel)
                    --i;
                c0 = qMax(s0, qMin(c0, (i + 1) * kHop));
            }
            if (c1 < duration) {
                const double end = islands.last().to;
                int i = qRound(end / kHop);
                while (i < n && i * kHop < qMin(s1, end + 0.25) && db[i] >= softLevel)
                    ++i;
                c1 = qMin(s1, qMax(c1, i * kHop));
            }
        }

        // A word aligned inside the quiet stretch is a quiet word: keep the time around it.
        QList<Span> pieces{{c0, c1}};
        for (const auto &w : spoken) {
            if (w.time <= c0 || w.time >= c1)
                continue;
            QList<Span> split;
            for (const auto &piece : pieces) {
                if (piece.from < w.time && w.time < piece.to) {
                    split.append({piece.from, w.time - 0.45});
                    split.append({w.time + 0.6, piece.to});
                } else {
                    split.append(piece);
                }
            }
            pieces = split;
        }
        for (const auto &piece : pieces) {
            if (piece.to - piece.from >= kMinCut)
                result.cuts.append({piece.from, piece.to, !islands.isEmpty()});
        }
    }
    return result;
}

} // namespace PauseRemover
