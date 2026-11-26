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

// Review: spoken takes, and writing down what was said (bridge/voice_chat.py transcribe).
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"

namespace ReviewMode {

// ---- spoken takes ----
// The frame on screen at a moment of the recording.
int ReviewWindow::frameAt(const Note &n, qint64 ms)
{
    int frame = n.frame;
    for (const auto &[t, f] : n.clock) {
        if (t > ms)
            break;
        frame = f;
    }
    return frame;
}

// What was said, with each mark where it was drawn and the video's time at the start and after each pause:
// "(0:12.3) I want a ball [mark 1: arrow, 0:12.6] to fly across here, (0:14.0) and a frisbee [mark 2: ...]".
QString ReviewWindow::script(const Note &n) const
{
    if (n.words.isEmpty())
        return n.text;
    QVector<int> order(n.strokes.size());
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&n](int a, int b) { return n.strokes[a].t0 < n.strokes[b].t0; });
    int next = 0;
    QStringList out;
    double lastEnd = -10;
    const auto markText = [&](int i) {
        const Stroke &s = n.strokes[i];
        return s.endFrame >= 0
                   ? QStringLiteral("[mark %1: %2 from %3 to %4]")
                         .arg(i + 1).arg(toolName(s.tool), stamp(s.frame / m_fps), stamp(s.endFrame / m_fps))
                   : QStringLiteral("[mark %1: %2 at %3]").arg(i + 1).arg(toolName(s.tool), stamp(s.frame / m_fps));
    };
    for (const Word &w : n.words) {
        while (next < order.size() && n.strokes[order[next]].t0 <= qint64(w.start * 1000))
            out << markText(order[next++]);
        if (w.start - lastEnd >= 0.7)
            out << QStringLiteral("(%1)").arg(stamp(frameAt(n, qint64(w.start * 1000)) / m_fps));
        out << w.text;
        lastEnd = w.end;
    }
    while (next < order.size())
        out << markText(order[next++]);
    QString spoken = out.join(QLatin1Char(' '));
    if (!n.text.isEmpty()) {
        QStringList raw;
        for (const Word &w : n.words) raw << w.text;
        if (n.text.simplified() != raw.join(QLatin1Char(' ')).simplified())
            spoken += QStringLiteral(" [edited instruction: %1]").arg(n.text);
    }
    return spoken;
}

void ReviewWindow::updateCopyPause()
{
    const QString path = QDir::temp().filePath(QStringLiteral("letitedit-speech-%1.busy").arg(QCoreApplication::applicationPid()));
    if (!m_closing && (m_recording || m_transcribing || !m_wordsQueue.isEmpty())) {
        QFile file(path);
        if (file.open(QIODevice::WriteOnly))
            file.write("speech");
    } else {
        QFile::remove(path);
    }
}

void ReviewWindow::setListening(bool on)
{
    if (!on) {
        if (m_recording) stopTake();
        m_qaAudioTimer.stop();
        if (m_mic) { m_mic->stop(); m_mic->deleteLater(); m_mic = nullptr; }
        if (m_audio) { m_audio->deleteLater(); m_audio = nullptr; }
        m_qaPcm.clear();
        m_listening = false;
        updateCopyPause();
        ++m_vadEpoch;
        m_vadPending = false;
        m_vadReset = true;
        m_listeningSign->hide();
        m_liveListening->hide();
        m_talkTimer.stop();
        return;
    }
    if (m_listening) return;
    const QString qaWav = qEnvironmentVariableIsSet("LETITEDIT_QA")
                              ? qEnvironmentVariable("LETITEDIT_QA_REVIEW_WAV") : QString();
    if (qEnvironmentVariableIsSet("LETITEDIT_QA") && qaWav.isEmpty()) {
        if (m_live) // a test window never opens the microphone; plain Review just goes without
            m_status->setText(tr("Review test needs a sound file; no microphone was opened."));
        return;
    }
    QAudioDevice device;
    QAudioFormat format;
    format.setSampleRate(16000);
    format.setChannelCount(1);
    format.setSampleFormat(QAudioFormat::Int16);
    if (qaWav.isEmpty()) {
        const QJsonObject v = aiVoiceSettings();
        device = aiVoiceDevice(v.value("mic_device").toString());
        if (device.isNull()) {
            m_status->setText(tr("No microphone found. You can still draw and type notes."));
            return;
        }
        format.setSampleRate(v.value("sample_rate_hz").toInt(16000));
        if (!device.isFormatSupported(format)) format = device.preferredFormat();
    }
    m_format = format;
    m_audio = new RollingAudio(this);
    m_audio->format = format;
    m_audio->thresholdDb = aiVoiceSettings().value("silence_threshold_db").toDouble(-45.0);
    m_audio->followRoom = true;
    if (qaWav.isEmpty()) {
        m_mic = new QAudioSource(device, format, this);
        m_mic->start(m_audio);
        if (m_mic->error() != QAudio::NoError) {
            m_status->setText(tr("The microphone could not start. You can still draw and type notes."));
            setListening(false);
            return;
        }
    } else {
        QFile f(qaWav);
        if (!f.open(QIODevice::ReadOnly)) {
            m_status->setText(tr("The review test sound file could not be read."));
            setListening(false);
            return;
        }
        const QByteArray wav = f.readAll();
        const int dataAt = wav.indexOf("data");
        const auto le32 = [&wav](int i) {
            return quint32(quint8(wav[i])) | (quint32(quint8(wav[i + 1])) << 8)
                   | (quint32(quint8(wav[i + 2])) << 16) | (quint32(quint8(wav[i + 3])) << 24);
        };
        if (dataAt < 36 || dataAt + 8 >= wav.size() || wav.mid(0, 4) != "RIFF"
            || wav.mid(8, 4) != "WAVE" || quint8(wav[22]) != 1 || quint8(wav[34]) != 16) {
            m_status->setText(tr("The review test sound file is invalid."));
            setListening(false);
            return;
        }
        format.setSampleRate(int(le32(24)));
        m_format = format;
        m_audio->format = format;
        m_qaPcm = wav.mid(dataAt + 8, int(le32(dataAt + 4)));
        m_qaOffset = 0;
        m_qaAudioTimer.setInterval(40);
        disconnect(&m_qaAudioTimer, nullptr, this, nullptr);
        m_qaFed.start();
        connect(&m_qaAudioTimer, &QTimer::timeout, this, [this]() {
            if (!m_audio) return;
            const int chunk = m_format.sampleRate() * 2 * 40 / 1000; // 40 ms of mono Int16
            for (qint64 due = m_qaFed.restart() + m_qaOwedMs; ; due -= 40) {
                if (due < 40) {
                    m_qaOwedMs = due;
                    break;
                }
                if (m_qaOffset < m_qaPcm.size()) {
                    const int n = qMin(chunk, int(m_qaPcm.size()) - m_qaOffset);
                    m_audio->feed(m_qaPcm.constData() + m_qaOffset, n);
                    m_qaOffset += n;
                } else {
                    const QByteArray quiet(chunk, '\0');
                    m_audio->feed(quiet.constData(), quiet.size());
                }
            }
        });
        m_qaAudioTimer.start();
    }
    m_listening = true;
    updateCopyPause();
    m_vadReset = true;
    startWords();
    m_talkTimer.setInterval(50);
    (m_live ? m_liveListening : m_listeningSign)->show();
    m_talkTimer.start();
    m_status->setText(m_live ? tr("Listening. Just talk and draw.") : tr("Listening. Talk while you draw on the picture."));
}

// Live Review: speech that lasts starts a note by itself, and a pause ends it. A stroke still being drawn keeps it
// open; a drawing with no words gets a little longer, since people often draw first and talk after.
void ReviewWindow::checkLive()
{
    if (!m_recording) {
        if (m_audio->voicedRun() >= 320 && m_audio->clock.elapsed() - m_audio->lastVoice() < 200)
            startTake();
        return;
    }
    const qint64 now = m_audio->clock.elapsed();
    const qint64 heard = m_audio->lastVoice();
    if (heard >= m_audioStartMs - m_prerollMs)
        m_heardSpeech = true;
    if (!m_take.strokes.isEmpty() && m_take.strokes.last().t1 < 0)
        return;
    const qint64 last = qMax(qMax(m_heardSpeech ? heard : qint64(-1), m_lastPenUpMs), m_audioStartMs);
    notePreview(heard, now - last);
    const qint64 wait = m_heardSpeech ? m_pauseMs : kDrawOnlyMs;
    if (now - last >= wait || m_clock.elapsed() >= 40000) // a limit: the video's own sound can keep it open for ever
        stopTake();
}

void ReviewWindow::checkPause()
{
    if (m_audio)
        detectSpeech();
    if (m_audio && m_live) {
        checkLive();
        return;
    }
    if (!m_recording || !m_audio) return;
    const qint64 heard = m_audio->lastVoice();
    if (heard >= m_audioStartMs - m_prerollMs) m_heardSpeech = true;
    if (!m_take.strokes.isEmpty() && m_take.strokes.last().t1 < 0 && m_clock.elapsed() < 40000)
        return; // the pen is still down: the note and the video go on, up to a limit (a release that never came)
    const qint64 now = m_audio->clock.elapsed();
    if (m_heardSpeech && heard >= 0)
        notePreview(heard, now - qMax(heard, m_lastPenUpMs));
    if (m_heardSpeech && heard >= 0 && now - qMax(heard, m_lastPenUpMs) >= m_pauseMs)
        stopTake();
    else if (!m_heardSpeech && m_takeByPen && m_lastPenUpMs >= 0 && now - m_lastPenUpMs >= kDrawOnlyMs)
        stopTake(); // drawn without a word: it stays a drawing (type a note to go with it)
}

// After a short quiet the note's words so far are written down (the speech model is kept warm) and shown with Send;
// the note stays open, and words said before it closes join it and are written down again.
void ReviewWindow::notePreview(qint64 heard, qint64 quietFor)
{
    if (!m_recording || !m_heardSpeech || heard < 0 || quietFor < kTextReadyMs || m_closing)
        return;
    if (heard == m_previewAskedVoice || m_previewBusy || !m_wordsProcess || !m_audio)
        return;
    const QByteArray pcm = m_audio->soFar();
    if (pcm.size() < m_format.bytesForDuration(300000))
        return;
    QDir().mkpath(m_dir);
    const QString wav = QDir(m_dir).filePath(QStringLiteral("note-preview.wav"));
    if (!aiVoiceWriteWav(pcm, m_format, wav))
        return;
    QJsonArray ranges;
    double start = m_take.frame / m_fps, last = start;
    for (const auto &[ms, frame] : m_take.clock) {
        Q_UNUSED(ms)
        const double at = frame / m_fps;
        if (at < last || at > last + 2) {
            ranges.append(QJsonArray{start, last});
            start = at;
        }
        last = at;
    }
    ranges.append(QJsonArray{start, last});
    m_previewBusy = -(++m_previewSeq);
    m_previewAskedVoice = heard;
    const QByteArray line = QJsonDocument(QJsonObject{{"cmd", "transcribe"}, {"id", m_previewBusy}, {"delete", false},
                                                      {"not_behind_others", true}, {"review", true},
                                                      {"video", m_live ? m_videoWords : QString()}, {"ranges", ranges},
                                                      {"project", m_live ? m_videoSpeechProject : QString()},
                                                      {"wav", QDir::toNativeSeparators(wav)}})
                                .toJson(QJsonDocument::Compact);
    m_wordsProcess->write(line + '\n');
}

void ReviewWindow::previewReady(const QJsonObject &r)
{
    const qint64 covered = m_previewAskedVoice;
    m_previewBusy = 0;
    if (!m_recording || !r.value("ok").toBool())
        return;
    m_previewResult = r;
    m_previewVoice = covered;
    if (m_audio && covered >= 0)
        m_textReadyMs = m_audio->clock.elapsed() - covered;
    const QString text = r.value("text").toString().trimmed();
    if (!text.isEmpty())
        m_status->setText(tr("\u201C%1\u201D  Keep talking to add to it, or press Send (Enter).").arg(text));
    refresh();
}

bool ReviewWindow::startTake()
{
    if (m_recording || !m_listening || !m_audio) {
        m_talk->setChecked(m_recording);
        if (!m_listening)
            m_status->setText(m_listenSwitch->isChecked() ? tr("No microphone is on, so notes are drawn and typed.")
                                                          : tr("Talk while I draw is off (the gear at the top)."));
        return false;
    }
    m_takeByPen = false; // set by the canvas when a mark starts it
    m_previewAskedVoice = m_previewVoice = -1;
    m_previewResult = QJsonObject();
    m_textReadyMs = -1;
    if (!m_live && m_draftFrame != m_position)
        commitDraft(); // a drawing on this frame waits: if nothing is said it goes on with it
    else if (m_live)
        commitDraft();
    m_sendWhenWritten = false; // a new note: Send again when it's done
    m_audio->begin(m_live ? 800000 : 0);
    m_prerollMs = m_audio->cappedRecentMs();
    m_audioStartMs = m_audio->clock.elapsed();
    m_heardSpeech = m_audio->lastVoice() >= m_audioStartMs - m_prerollMs;
    m_take = Note();
    m_take.take = true;
    m_take.leadInMs = m_prerollMs;
    if (m_live) // just after a rewind the frame may not have shown yet: where the playhead is, not the last frame shown
        m_position = qBound(0, m_window->player()->position(), m_length - 1);
    m_take.frame = m_position;
    m_clock.start();
    m_take.clock.append({0, m_position});
    m_take.clock.append({m_prerollMs, m_position});
    m_recording = true;
    updateCopyPause();
    m_talk->setChecked(true);
    updateTalkButton();
    m_lastPenUpMs = -1;
    if (m_live) {
        // the picture for the list and for the AI, as it is now; nothing here touches the player
        m_take.image = captureScenePicture();
        if (m_take.image.isNull())
            m_take.shot = m_frame;
        m_take.thumb = smallPicture(m_canvas->image);
        m_status->setText(tr("\u25CF Hearing a note..."));
        return true;
    }
    m_status->setText(tr("Spoken note started. Draw more marks or step frames; a pause finishes it."));
    refresh(); // the video goes on as it was: playing at the speed chosen, or still
    return true;
}

void ReviewWindow::stopTake()
{
    if (!m_recording)
        return;
    m_recording = false;
    QTimer::singleShot(0, this, [this]() { updateCopyPause(); });
    const bool drawingOnly = !m_live && m_takeByPen && !m_heardSpeech;
    m_lastHeard = m_audio ? m_audio->lastVoice() : -1;
    // the words already written down cover everything said: they are the note's (no second wait)
    const QJsonObject preview = !m_previewResult.isEmpty() && m_previewVoice >= 0 && m_previewVoice == m_lastHeard
                                    ? m_previewResult : QJsonObject();
    m_previewResult = QJsonObject();
    m_previewAskedVoice = m_previewVoice = -1;
    m_takeByPen = false;
    const QByteArray pcm = m_audio ? m_audio->finish() : QByteArray();
    m_talk->setChecked(false);
    m_talk->setText(tr("Start spoken note (T)"));
    Note take = m_take;
    m_take = Note();
    take.id = m_nextId++;
    if (m_lastMarkId == -2) m_lastMarkId = take.id;
    m_lastTakeId = take.id;
    take.endFrame = m_position;
    for (auto &s : take.strokes)
        if (s.t1 < 0)
            s.t1 = m_prerollMs + m_clock.elapsed();
    if (drawingOnly) {
        // marks with no words: a drawing on its frame, as if no microphone listened (type a note to go with it)
        if (!take.strokes.isEmpty()) {
            if (m_draftFrame != take.frame)
                commitDraft();
            if (m_draft.isEmpty()) {
                m_draftFrame = take.frame;
                m_draftImage = take.strokes.first().image;
                m_draftShot = take.strokes.first().shot;
            }
            for (Stroke s : std::as_const(take.strokes)) {
                s.t0 = s.t1 = -1;
                s.image = QImage();
                s.shot = SharedFrame();
                m_draft.append(s);
            }
            m_lastMarkId = 0;
            m_lastMarkIndex = m_draft.size() - 1;
            m_lastMarkFrame = take.frame;
        }
        m_status->setText(tr("Listening. Talk while you draw, or type a note for this drawing."));
        changed();
        return;
    }
    if (m_live && !m_heardSpeech && take.strokes.isEmpty()) {
        m_status->setText(tr("Listening. Just talk and draw."));
        evaluateLoading();
        return;
    }
    if (pcm.size() < m_format.bytesForDuration(300000) && take.strokes.isEmpty()) {
        m_status->setText(tr("Nothing was said or drawn."));
        refresh();
        return;
    }
    if (m_live && !m_heardSpeech) {
        keepTake(take);
        m_status->setText(tr("Listening. Just talk and draw."));
        if (!m_closing)
            afterWords(take.id);
        return;
    }
    QDir().mkpath(m_dir);
    take.audio = QStringLiteral("note-%1.wav").arg(take.id);
    const QString wav = QDir(m_dir).filePath(take.audio);
    if (!aiVoiceWriteWav(pcm, m_format, wav))
        take.audio.clear();
    // kept now, words added when they are written down (a take whose words never came is transcribed when
    // Review opens again)
    keepTake(take);
    if (take.audio.isEmpty()) {
        m_status->setText(tr("Couldn't keep the recording; the marks are kept."));
        return;
    }
    if (!preview.isEmpty() && !m_closing) {
        if (m_live) {
            if (int k = noteIndex(take.id); k >= 0)
                m_notes[k].writing = true;
        } else if (m_autoSend->isChecked()) {
            m_autoPendingId = take.id;
        }
        ++m_transcribing;
        finishTranscription(take.id, true, preview, QString());
        return;
    }
    if (m_live) {
        if (!m_closing) // else its words are written down when Review opens again
            queueWords(take.id);
        return;
    }
    if (m_autoSend->isChecked() && !m_closing) m_autoPendingId = take.id;
    transcribe(take.id);
}

void ReviewWindow::keepTake(const Note &take)
{
    m_notes.append(take);
    sortNotes();
    changed();
}

int ReviewWindow::noteIndex(int id) const
{
    for (int i = 0; i < m_notes.size(); ++i)
        if (m_notes[i].id == id)
            return i;
    return -1;
}

// Writes down what was said in a take (bridge/voice_chat.py transcribe, on this PC). However it ends - the words,
// an error, a helper that never started or one that took too long - it ends through finishTranscription(), which
// always lets go of the busy state: the recording and the marks stay with the note either way, and Send works.
void ReviewWindow::transcribe(int id)
{
    m_unwritten.remove(id);
    queueWords(id);
}

// The one way a transcription ends.
void ReviewWindow::finishTranscription(int id, bool ok, const QJsonObject &r, const QString &why)
{
    m_transcribing = qMax(0, m_transcribing - 1);
    updateCopyPause();
    const auto sendIfWaiting = [this]() {
        if (m_sendWhenWritten && !m_transcribing && !m_closing)
            QTimer::singleShot(0, this, [this]() { if (m_sendWhenWritten) submit(); });
    };
    const int i = noteIndex(id);
    if (i < 0) { // deleted meanwhile
        refresh();
        sendIfWaiting();
        return;
    }
    const QString statusBefore = m_status->text();
    Note &take = m_notes[i];
    if (ok) {
        take.text = r.value("text").toString().trimmed();
        take.words.clear();
        for (const auto &v : r.value("words").toArray()) {
            const QJsonObject o = v.toObject();
            const QString w = o.value("w").toString().trimmed();
            if (!w.isEmpty())
                take.words.append({w, o.value("s").toDouble(), o.value("e").toDouble()});
        }
    }
    if (m_live) {
        if (!ok) {
            take.writing = false;
            m_unwritten.insert(id);
            m_status->setText(tr("Couldn't write down what you said (%1). The recording and marks are kept with the note.").arg(why));
            changed();
        } else if (take.text.isEmpty() && take.strokes.isEmpty()) {
            // a cough, a door: nothing to send and nothing to look at
            for (const QString &file : files(take))
                QFile::remove(QDir(m_dir).filePath(file));
            m_notes.removeAt(i);
            changed();
            m_status->setText(tr("Listening. Just talk and draw."));
            evaluateLoading();
        } else if (r.value("review_cleaned").toBool()) {
            m_unwritten.remove(id);
            take.heardVideo = r.value("heard_video").toBool();
            afterWords(id);
        } else {
            m_unwritten.remove(id);
            cleanWords(id);
        }
        return;
    }
    if (!ok) {
        m_unwritten.insert(id);
        m_status->setText(tr("Couldn't write down what you said (%1). The recording and marks are kept with the "
                             "note: press Write it down again, or send it as it is.")
                              .arg(why));
    } else if (take.text.isEmpty()) {
        m_unwritten.remove(id);
        m_status->setText(tr("Didn't hear words; the recording and marks are kept."));
    } else {
        m_unwritten.remove(id);
        if (!m_transcribing)
            m_status->setText(tr("Got it: %1 words, %2. Not right? Press Record it again.")
                                  .arg(take.words.size())
                                  .arg(take.strokes.size() == 1 ? tr("1 mark") : tr("%1 marks").arg(take.strokes.size())));
    }
    if (m_recording || m_sendWhenWritten) // the next note's line, or that a Send is waiting, stays on screen
        m_status->setText(statusBefore);
    changed();
    if (m_autoPendingId == id) {
        m_autoPendingId = -1;
        if (ok && !take.text.isEmpty() && !m_closing)
            m_sendWhenWritten = true;
    }
    sendIfWaiting();
}

} // namespace ReviewMode
