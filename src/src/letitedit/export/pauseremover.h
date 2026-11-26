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

#ifndef PAUSEREMOVER_H
#define PAUSEREMOVER_H

#include <QByteArray>
#include <QList>
#include <QPair>
#include <QString>
#include <QVector>

class QProgressDialog;
class QWidget;

// letitedit "Remove pauses": which parts of the quiet stretches in talking to cut. It reads the sound level at two
// levels (the gaps between words, and the softer word endings and onsets that always stay) and, when a speech model
// is installed, whisper's word alignment: a word heard inside a quiet stretch is a quiet word and keeps its place,
// a sentence end keeps a longer beat, and an um or uh that stands alone between two gaps goes with the pause.
namespace PauseRemover {

enum Mode { Gentle, Normal, Tight };

struct Word
{
    QString text;
    double time; // seconds from the clip start where the alignment puts the word (its start, or a little after)
};

struct Cut
{
    double from; // seconds from the clip start
    double to;
    bool filler;
};

struct Plan
{
    QList<Cut> cuts;
    int fillersRemoved = 0;
    int fillersKept = 0; // um or uh that run straight into a word: cutting them would clip it
};

// The options dialog (pause length, um and uh). Remembers the choice. False if cancelled.
bool askOptions(QWidget *parent, Mode &mode, bool &removeFillers);

// Loudness in dB per 10 ms of a 16-bit mono WAV file.
QVector<float> loudness(const QString &wavPath);
// Words and their aligned times from whisper-cli's full JSON (-ojf with -dtw).
QList<Word> words(const QString &jsonPath);
// The alignment preset whisper-cli needs for a model file (ggml-base.en.bin: base.en), or empty if unknown.
QString alignmentPreset(const QString &modelPath);
bool isFiller(const QString &word);
// How many words the speech model hears in some 16 kHz mono 16-bit sound (a few short stretches is enough), not
// counting what it writes for noise ([BLANK_AUDIO], (wind), music notes). -1 when it cannot tell: no speech model.
int wordsHeard(const QByteArray &pcm16kMono);

struct Phrase
{
    double from; // seconds
    double to;
    int words;
    double firstWord; // where its first word is aligned (seconds; it lags the word's start by up to 0.4 s), or -1
    QList<double> wordTimes; // every word's aligned time (empty without word alignment)
};
// What the speech model hears in a whole 16 kHz mono WAV, phrase by phrase (whisper's segments, noise notes left
// out). ok is false when it cannot tell (no speech model, it failed or was cancelled).
QList<Phrase> phrases(const QString &wav16kMono, QProgressDialog *progress, bool *ok);

Plan plan(const QVector<float> &loudness, const QList<Word> &words, Mode mode, bool removeFillers);

} // namespace PauseRemover

#endif // PAUSEREMOVER_H
