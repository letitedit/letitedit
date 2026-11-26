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

// Review: Live Review inside the window (talk and draw; a pause ends a note; notes go to the AI one at a time and come back as Undo steps).
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"

#include "letitedit/bridge/jsonprocess.h"

namespace ReviewMode {

// ---- Live Review ----
void ReviewWindow::buildOffer(QVBoxLayout *outer)
{
    using namespace LetItEditColors;
    m_offer = new QFrame;
    m_offer->setObjectName(QStringLiteral("reviewLiveOffer"));
    m_offer->setStyleSheet(QStringLiteral("QFrame#reviewLiveOffer { background: %1; border: 1px solid %2; border-radius: 10px; }")
                               .arg(tealDeep, teal));
    auto row = new QHBoxLayout(m_offer);
    row->setContentsMargins(16, 10, 12, 10);
    row->setSpacing(12);
    auto words = new QLabel(tr("<b>Try Live Review.</b> Watch your video and just talk and draw: your AI fixes things "
                               "while you watch. Use headphones or a quiet room, so it hears you and not the video."));
    words->setObjectName(QStringLiteral("reviewLiveOfferText"));
    words->setWordWrap(true);
    row->addWidget(words, 1);
    auto on = new QPushButton(tr("Turn it on"));
    on->setObjectName(QStringLiteral("reviewLiveTurnOn"));
    on->setFocusPolicy(Qt::NoFocus);
    on->setMinimumHeight(38);
    on->setStyleSheet(QStringLiteral("background: %1; border-color: %1; font-weight: 600;").arg(rust));
    auto off = new QPushButton(tr("Watch without it"));
    off->setObjectName(QStringLiteral("reviewLiveSkip"));
    off->setFocusPolicy(Qt::NoFocus);
    off->setMinimumHeight(38);
    row->addWidget(on);
    row->addWidget(off);
    const auto chosen = [this]() {
        QSettings(Settings.appDataLocation() + QStringLiteral("/review-talk-draw.ini"), QSettings::IniFormat)
            .setValue(QStringLiteral("review/liveOffered"), true);
        m_offer->hide();
    };
    connect(on, &QPushButton::clicked, this, [this, chosen]() {
        chosen();
        m_liveSwitch->setChecked(true);
    });
    connect(off, &QPushButton::clicked, this, [chosen]() { chosen(); });
    m_offer->hide();
    outer->addWidget(m_offer);
}

void ReviewWindow::buildLiveBox(QVBoxLayout *sideOuter)
{
    using namespace LetItEditColors;
    m_liveBox = new QWidget;
    m_liveBox->setObjectName(QStringLiteral("reviewLiveBox"));
    auto box = new QVBoxLayout(m_liveBox);
    box->setContentsMargins(0, 0, 0, 0);
    box->setSpacing(8);
    m_liveListening = new QLabel(tr("\u25CF Listening \u2014 microphone on"));
    m_liveListening->setObjectName(QStringLiteral("reviewLiveListening"));
    m_liveListening->setStyleSheet(QStringLiteral("color: %1; font-weight: 600;").arg(tealLight));
    m_liveListening->hide();
    box->addWidget(m_liveListening);
    auto how = new QLabel(tr("Just talk and draw. A pause ends a note. Pause or rewind whenever you like."));
    how->setWordWrap(true);
    how->setStyleSheet(QStringLiteral("color: %1;").arg(muted));
    box->addWidget(how);
    m_liveAutoSend = new QCheckBox(tr("Send without asking"));
    m_liveAutoSend->setObjectName(QStringLiteral("reviewLiveAutoSend"));
    m_liveAutoSend->setFocusPolicy(Qt::NoFocus);
    m_liveAutoSend->setToolTip(tr("Off: each note waits here for you to press Send."));
    box->addWidget(m_liveAutoSend);
    m_liveBar = new QFrame;
    m_liveBar->setObjectName(QStringLiteral("reviewLiveBar"));
    m_liveBar->setStyleSheet(QStringLiteral("QFrame#reviewLiveBar { background: %1; border: 1px solid %2; border-radius: 8px; }")
                                 .arg(tealDeep, teal));
    auto bar = new QVBoxLayout(m_liveBar);
    bar->setContentsMargins(10, 8, 10, 8);
    m_liveBarText = new QLabel;
    m_liveBarText->setObjectName(QStringLiteral("reviewLiveBarText"));
    m_liveBarText->setWordWrap(true);
    bar->addWidget(m_liveBarText);
    auto barButtons = new QHBoxLayout;
    m_liveWatch = new QPushButton(tr("Watch it"));
    m_liveWatch->setObjectName(QStringLiteral("reviewLiveWatch"));
    m_liveWatch->setFocusPolicy(Qt::NoFocus);
    m_liveWatch->setStyleSheet(QStringLiteral("background: %1; border-color: %1; font-weight: 600;").arg(rust));
    connect(m_liveWatch, &QPushButton::clicked, this, [this]() { loadChanges(); });
    barButtons->addWidget(m_liveWatch);
    m_liveWait = new QPushButton(tr("Wait"));
    m_liveWait->setObjectName(QStringLiteral("reviewLiveWait"));
    m_liveWait->setFocusPolicy(Qt::NoFocus);
    connect(m_liveWait, &QPushButton::clicked, this, [this]() {
        m_waitChosen = true;
        m_liveBar->hide();
    });
    barButtons->addWidget(m_liveWait);
    bar->addLayout(barButtons);
    m_liveBar->hide();
    box->addWidget(m_liveBar);
    m_liveCounts = new QLabel;
    m_liveCounts->setObjectName(QStringLiteral("reviewLiveCounts"));
    m_liveCounts->setStyleSheet(QStringLiteral("color: %1;").arg(muted));
    box->addWidget(m_liveCounts);
    m_liveScroll = new QScrollArea;
    m_liveScroll->setObjectName(QStringLiteral("reviewLiveList"));
    m_liveScroll->setWidgetResizable(true);
    m_liveScroll->setFrameShape(QFrame::NoFrame);
    m_liveScroll->setFocusPolicy(Qt::NoFocus);
    m_liveScroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    auto rows = new QWidget;
    rows->setObjectName(QStringLiteral("reviewLiveRows"));
    m_liveRows = new QVBoxLayout(rows);
    m_liveRows->setContentsMargins(0, 0, 4, 0);
    m_liveRows->setSpacing(6);
    m_liveRows->addStretch(1);
    m_liveScroll->setWidget(rows);
    box->addWidget(m_liveScroll, 1);
    m_liveInput = new QLineEdit;
    m_liveInput->setObjectName(QStringLiteral("reviewLiveInput"));
    m_liveInput->setPlaceholderText(tr("Or type a note here"));
    connect(m_liveInput, &QLineEdit::returnPressed, this, [this]() { addLiveTyped(); });
    box->addWidget(m_liveInput);
    sideOuter->addWidget(m_liveBox, 1);
}

QImage ReviewWindow::smallPicture(const QImage &image)
{
    return image.isNull() ? QImage() : image.scaled(192, 108, Qt::KeepAspectRatio, Qt::FastTransformation);
}

void ReviewWindow::setLive(bool on)
{
    if (m_recording)
        stopTake();
    setListening(false);
    m_live = on;
    if (on) {
        setListening(true);
        if (!m_listening) { // no microphone: say so (setListening has) and stay in today's Review
            m_live = false;
            m_liveSwitch->blockSignals(true);
            m_liveSwitch->setChecked(false);
            m_liveSwitch->blockSignals(false);
        } else {
            m_offer->hide();
            loadVideoWords(m_window->fileName());
            if (qEnvironmentVariableIsSet("LETITEDIT_QA")) {
                Timing::get().reset();
                Timing::get().active = true;
            }
        }
    }
    if (!m_live && !m_closing && m_listenSwitch->isChecked())
        setListening(true); // Talk while I draw (on unless turned off behind the gear): it listens from the start
    m_classicBox->setVisible(!m_live);
    m_liveBox->setVisible(m_live);
    refresh();
    if (!m_live) {
        m_submit->show();
        if (m_session && (m_session->waiting() + m_session->working() + m_session->ready()) > 0)
            m_status->setText(tr("Your AI is still on your Live Review notes. Turn Live Review on to see them."));
    }
    evaluateLoading();
}

QProcess *ReviewWindow::runLive(const QStringList &args, const std::function<void(int, const QJsonObject &)> &done)
{
    auto process = new QProcess(this);
    process->setProgram(aiChatSettings().value("python").toString());
    process->setArguments(QStringList{QStringLiteral("-u"), aiRootPath(QStringLiteral("bridge/live_review.py"))} + args);
    process->setWorkingDirectory(aiRootPath(QStringLiteral("bridge")));
    QProcessEnvironment env = QProcessEnvironment::systemEnvironment();
    env.remove(QStringLiteral("LETITEDIT_OWNER"));
    process->setProcessEnvironment(env);
    return startJsonProcess(process, this,
        [done](int code, const QJsonObject &result, const QString &) { done(code, result); });
}

// What the video says, so its own sound through the speakers can be told from the person (transcripts already made).
void ReviewWindow::loadVideoWords(const QString &project)
{
    m_videoSpeechProject = project;
    QDir().mkpath(m_dir);
    const QString out = QDir(m_dir).filePath(QStringLiteral("video-words.json"));
    runLive({QStringLiteral("words"), QStringLiteral("--project"), project, QStringLiteral("--out"), out},
            [this, out](int code, const QJsonObject &r) {
                m_videoWords = code == 0 && r.value("count").toInt() > 0 ? out : QString();
            });
}

// Writing down what was said, one note at a time, by one helper that stays open while Live Review is on, so the
// speech model is loaded once. A note can be made while the one before is being written down.
void ReviewWindow::queueWords(int id)
{
    const int i = noteIndex(id);
    if (i < 0 || m_notes[i].audio.isEmpty())
        return;
    m_notes[i].writing = true;
    m_wordsQueue << id;
    updateCopyPause();
    changed();
    m_status->setText(tr("Listening. Writing down your note..."));
    pumpWords();
}

void ReviewWindow::pumpWords()
{
    if (m_wordsBusy || m_closing)
        return;
    int id = 0;
    while (!m_wordsQueue.isEmpty() && !id) {
        const int next = m_wordsQueue.takeFirst();
        if (noteIndex(next) >= 0)
            id = next;
    }
    if (!id) {
        if (!m_listening && m_wordsProcess) {
            m_wordsProcess->disconnect(this);
            m_wordsProcess->kill();
            m_wordsProcess->deleteLater();
            m_wordsProcess = nullptr;
        }
        return;
    }
    const QString python = aiChatSettings().value("python").toString();
    const QString helper = aiVoiceSettings().value("helper").toString();
    const QString wav = QDir(m_dir).filePath(m_notes[noteIndex(id)].audio);
    if (!QFileInfo::exists(python) || !QFileInfo::exists(helper) || !QFileInfo::exists(wav)) {
        ++m_transcribing;
        finishTranscription(id, false, QJsonObject(), tr("the speech helper isn't on this PC"));
        pumpWords();
        return;
    }
    startWords();
    if (!m_wordsProcess) { // it could not start (start() reports that at once, and the helper is let go)
        ++m_transcribing;
        finishTranscription(id, false, QJsonObject(), tr("the speech helper could not start"));
        pumpWords();
        return;
    }
    m_wordsBusy = id;
    ++m_transcribing;
    const Note &note = m_notes[noteIndex(id)];
    QJsonArray ranges;
    double start = note.frame / m_fps, last = start;
    for (const auto &[ms, frame] : note.clock) {
        Q_UNUSED(ms)
        const double at = frame / m_fps;
        if (at < last || at > last + 2) {
            ranges.append(QJsonArray{start, last});
            start = at;
        }
        last = at;
    }
    ranges.append(QJsonArray{start, last});
    const QByteArray line = QJsonDocument(QJsonObject{{"cmd", "transcribe"}, {"id", id}, {"delete", false}, {"not_behind_others", true},
                                                      {"review", true}, {"video", m_live ? m_videoWords : QString()}, {"ranges", ranges},
                                                      {"project", m_live ? m_videoSpeechProject : QString()},
                                                      {"wav", QDir::toNativeSeparators(wav)}})
                                .toJson(QJsonDocument::Compact);
    m_wordsProcess->write(line + '\n');
    // a limit a stuck helper can't outlast, long enough for an export the speech model waits behind
    const int limitMs = qEnvironmentVariableIsSet("LETITEDIT_QA_TRANSCRIBE_TIMEOUT_MS")
                            ? qEnvironmentVariableIntValue("LETITEDIT_QA_TRANSCRIBE_TIMEOUT_MS") : 17 * 60000;
    m_wordsTimer.setSingleShot(true);
    m_wordsTimer.disconnect(this);
    connect(&m_wordsTimer, &QTimer::timeout, this, [this]() { wordsEnded(tr("writing it down took too long")); });
    m_wordsTimer.start(limitMs);
}

void ReviewWindow::startWords()
{
    if (m_wordsProcess || m_closing)
        return;
    const QString python = aiChatSettings().value("python").toString();
    const QString helper = aiVoiceSettings().value("helper").toString();
    if (!QFileInfo::exists(python) || !QFileInfo::exists(helper))
        return;
    m_wordsRestartClock.restart();
    m_wordsProcess = new QProcess(this);
    m_wordsProcess->setWorkingDirectory(QFileInfo(helper).absolutePath());
    connect(m_wordsProcess, &QProcess::readyReadStandardOutput, this, [this]() { readWords(); });
    connect(m_wordsProcess, &QProcess::finished, this, [this]() { wordsEnded(tr("the speech helper stopped")); });
    connect(m_wordsProcess, &QProcess::errorOccurred, this, [this](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart)
            wordsEnded(tr("the speech helper could not start"));
    });
    m_wordsProcess->start(python, {QStringLiteral("-u"), helper, QStringLiteral("serve")});
    if (m_wordsProcess) // a program that could not start has already been let go (wordsEnded)
        m_wordsProcess->write("{\"cmd\":\"warm\",\"review\":true}\n");
}

void ReviewWindow::detectSpeech()
{
    if (!m_audio)
        return;
    if (m_vadPending && m_vadRequestClock.elapsed() > 15000) {
        m_audio->detectedSpeech(-1, 0);
        wordsEnded(tr("speech detection took too long"));
        return;
    }
    if (!m_wordsProcess && (!m_wordsRestartClock.isValid() || m_wordsRestartClock.elapsed() >= 5000))
        startWords();
    if (!m_wordsProcess || m_vadPending)
        return;
    const QByteArray pcm = m_audio->speechChunk();
    if (pcm.isEmpty())
        return;
    QString format = QStringLiteral("int16");
    if (m_format.sampleFormat() == QAudioFormat::Float)
        format = QStringLiteral("float");
    else if (m_format.sampleFormat() == QAudioFormat::Int32)
        format = QStringLiteral("int32");
    else if (m_format.sampleFormat() == QAudioFormat::UInt8)
        format = QStringLiteral("uint8");
    const QJsonObject request{{"cmd", "review_audio"}, {"id", m_vadEpoch}, {"reset", m_vadReset},
                              {"pcm", QString::fromLatin1(pcm.toBase64())}, {"rate", m_format.sampleRate()},
                              {"channels", m_format.channelCount()}, {"format", format},
                              {"end_ms", double(m_audio->clock.elapsed())}};
    m_vadReset = false;
    m_vadPending = true;
    m_vadRequestClock.restart();
    m_wordsProcess->write(QJsonDocument(request).toJson(QJsonDocument::Compact) + '\n');
}

void ReviewWindow::readWords()
{
    if (!m_wordsProcess)
        return;
    while (m_wordsProcess->canReadLine()) {
        const QJsonObject r = QJsonDocument::fromJson(m_wordsProcess->readLine()).object();
        if (r.value("cmd").toString() == QLatin1String("review_audio")) {
            if (r.value("id").toInt() != m_vadEpoch)
                continue;
            m_vadPending = false;
            if (m_audio && r.value("ok").toBool()) {
                const qint64 last = qint64(r.value("last_voice_ms").toDouble(-1));
                const qint64 end = qint64(r.value("end_ms").toDouble());
                const qint64 processed = qint64(r.value("processed_ms").toDouble());
                m_audio->detectedSpeech(last < 0 ? -1 : end - processed + last,
                                        qint64(r.value("voiced_ms").toDouble()));
            } else {
                if (m_audio)
                    m_audio->detectedSpeech(-1, 0);
                m_status->setText(tr("Speech detection isn't ready: %1").arg(r.value("error").toString().left(160)));
            }
            continue;
        }
        if (r.value("cmd").toString() == QLatin1String("transcribe") && m_previewBusy
            && r.value("id").toInt() == m_previewBusy) {
            previewReady(r); // the words of a note still being spoken (T210)
            continue;
        }
        if (r.value("cmd").toString() != QLatin1String("transcribe") || r.value("id").toInt() != m_wordsBusy)
            continue;
        const int id = std::exchange(m_wordsBusy, 0);
        m_wordsTimer.stop();
        const bool ok = r.value("ok").toBool();
        finishTranscription(id, ok, r, ok ? QString() : r.value("error").toString().left(200));
        pumpWords();
    }
}

void ReviewWindow::wordsEnded(const QString &why)
{
    if (m_wordsProcess) {
        m_wordsProcess->disconnect(this);
        m_wordsProcess->kill();
        m_wordsProcess->deleteLater();
        m_wordsProcess = nullptr;
    }
    m_wordsTimer.stop();
    m_vadPending = false;
    m_vadReset = true;
    ++m_vadEpoch;
    m_previewBusy = 0; // the next quiet asks again
    m_previewAskedVoice = -1;
    if (const int id = std::exchange(m_wordsBusy, 0))
        finishTranscription(id, false, QJsonObject(), why);
    pumpWords();
}

// Takes out what is the video's own sound coming through the speakers.
void ReviewWindow::cleanWords(int id)
{
    const int i = noteIndex(id);
    if (i < 0)
        return;
    if (m_videoWords.isEmpty() || m_notes[i].words.isEmpty()) {
        afterWords(id);
        return;
    }
    const Note &n = m_notes[i];
    QJsonArray words, ranges;
    for (const Word &w : n.words)
        words.append(QJsonObject{{"w", w.text}, {"s", w.start}, {"e", w.end}});
    double start = n.frame / m_fps, last = start;
    for (const auto &[ms, frame] : n.clock) {
        Q_UNUSED(ms)
        const double at = frame / m_fps;
        if (at < last || at > last + 2) { // rewound or scrubbed: another stretch of the video
            ranges.append(QJsonArray{start, last});
            start = at;
        }
        last = at;
    }
    ranges.append(QJsonArray{start, last});
    const QString file = QDir(m_dir).filePath(QStringLiteral("clean-%1.json").arg(id));
    QFile f(file);
    if (!f.open(QIODevice::WriteOnly)) {
        afterWords(id);
        return;
    }
    f.write(QJsonDocument(QJsonObject{{"words", words}, {"ranges", ranges}}).toJson());
    f.close();
    runLive({QStringLiteral("clean"), QStringLiteral("--note"), file, QStringLiteral("--video"), m_videoWords},
            [this, id, file](int code, const QJsonObject &r) {
                QFile::remove(file);
                const int at = noteIndex(id);
                if (at < 0)
                    return;
                if (code == 0 && r.value("matched").toInt() > 0) {
                    Note &n = m_notes[at];
                    n.heardVideo = r.value("heard_video").toBool() && n.strokes.isEmpty();
                    if (!n.heardVideo) {
                        n.text = r.value("text").toString();
                        n.words.clear();
                        for (const auto &v : r.value("words").toArray()) {
                            const QJsonObject o = v.toObject();
                            n.words.append({o.value("w").toString(), o.value("s").toDouble(), o.value("e").toDouble()});
                        }
                    }
                }
                afterWords(id);
            });
}

// A note is written down: its card, or straight to the AI with Send without asking.
void ReviewWindow::afterWords(int id)
{
    const int i = noteIndex(id);
    if (i < 0)
        return;
    m_notes[i].writing = false;
    changed();
    if (m_notes[i].heardVideo) {
        m_status->setText(tr("That sounded like the video's own sound, so it won't be sent."));
    } else if (m_liveAutoSend->isChecked() && !m_closing) {
        // in the order they were made: a quick one (a drawing) doesn't overtake one still being written down
        QVector<int> ids;
        for (const Note &n : std::as_const(m_notes))
            ids << n.id;
        std::sort(ids.begin(), ids.end());
        for (int next : std::as_const(ids)) {
            const int k = noteIndex(next);
            if (k < 0 || m_notes[k].writing)
                break;
            if (!m_notes[k].heardVideo)
                sendLive(next);
        }
    } else {
        m_status->setText(tr("Listening. A note is ready for you to send."));
    }
    evaluateLoading();
}

void ReviewWindow::addLiveTyped()
{
    const QString text = m_liveInput->text().trimmed();
    if (text.isEmpty())
        return;
    Note n;
    n.id = m_nextId++;
    n.frame = m_position;
    n.text = text;
    n.image = captureScenePicture();
    if (n.image.isNull())
        n.shot = m_frame;
    n.thumb = smallPicture(m_canvas->image);
    m_notes.append(n);
    m_liveInput->clear();
    m_canvas->setFocus();
    sortNotes();
    afterWords(n.id);
}

// Notes that can go now.
QList<int> ReviewWindow::sendableCards() const
{
    QList<int> ids;
    for (const Note &n : m_notes)
        if (!n.writing && !n.heardVideo && !m_sendingIds.contains(n.id))
            ids << n.id;
    std::sort(ids.begin(), ids.end());
    return ids;
}

void ReviewWindow::sendAllCards()
{
    const QList<int> ids = sendableCards();
    for (int id : ids)
        sendLive(id);
}

void ReviewWindow::sendNewestCard()
{
    const QList<int> ids = sendableCards();
    if (!ids.isEmpty())
        sendLive(ids.last());
}

// The note's pictures are written on their own thread: this carries on when they are done, and never holds the screen.
void ReviewWindow::sendLive(int id)
{
    const int i = noteIndex(id);
    if (i < 0 || m_notes[i].writing || m_sendingIds.contains(id))
        return;
    if (m_editingId == id)
        finishEdit();
    m_sendingIds.insert(id);
    save();
    QPointer<ReviewWindow> guard(this);
    writerPool().start(QRunnable::create([guard, id]() {
        QMetaObject::invokeMethod(qApp, [guard, id]() {
            if (guard && guard->m_alive && !guard->m_closing)
                guard->sendLiveWritten(id);
        }, Qt::QueuedConnection);
    }));
}

void ReviewWindow::sendLiveWritten(int id)
{
    m_sendingIds.remove(id);
    const int i = noteIndex(id);
    if (i < 0)
        return;
    Note n = m_notes[i];
    auto session = LiveReview::Session::of(m_window);
    attachSession(session);
    QString folder;
    const int sentId = session->reserve(&folder);
    const QDir draft(m_dir), to(folder);
    const QStringList noteFiles = files(n);
    for (const QString &file : noteFiles) {
        if (!QFileInfo::exists(draft.filePath(file)))
            continue; // a picture that couldn't be written: the note still goes, with what it has
        QFile::remove(to.filePath(file));
        if (!QFile::copy(draft.filePath(file), to.filePath(file))) {
            m_status->setText(tr("Could not copy %1 for your AI; the note is still here.").arg(file));
            return;
        }
    }
    {
        QSaveFile f(to.filePath(QStringLiteral("notes.json")));
        if (f.open(QIODevice::WriteOnly)) {
            f.write(QJsonDocument(QJsonObject{{"project", QDir::toNativeSeparators(m_window->fileName())},
                                              {"fps", m_fps},
                                              {"notes", QJsonArray{toJson(n)}}})
                        .toJson());
            f.commit();
        }
    }
    LiveReview::Item item;
    item.id = sentId;
    item.frame = n.frame;
    item.when = n.frame < 0 ? tr("Whole video") : stamp(n.frame / m_fps);
    item.words = n.text.isEmpty() ? (n.strokes.isEmpty() ? tr("(no words)") : tr("(a drawing, no words)")) : n.text;
    item.folder = folder;
    item.thumb = n.thumb;
    QStringList pictures;
    if (n.hasImage())
        pictures << (n.strokes.isEmpty() ? frameFile(n) : markedFile(n));
    for (int k = 0; k < n.strokes.size(); ++k) {
        if (n.strokes[k].hasImage())
            pictures << markFile(n, k);
        QJsonArray points;
        for (const QPointF &p : n.strokes[k].points)
            points.append(QJsonArray{p.x(), p.y()});
        item.strokes.append(QJsonObject{{"frame", n.strokes[k].frame}, {"points", points}});
        Stroke shown;
        shown.color = n.strokes[k].color;
        shown.points = n.strokes[k].points;
        shown.frame = n.strokes[k].frame;
        m_sentMarks << shown;
    }
    item.picture = pictures.isEmpty() ? QString() : to.filePath(pictures.first());
    item.body = QStringLiteral("What they said and drew (the pictures and the recording are in \"%1\", and notes.json there "
                               "has the times, the words and the marks as points 0-1 across the picture; look at a marked "
                               "frame to see what they pointed at):%2\n%3")
                    .arg(QDir::toNativeSeparators(folder), n.take ? takesExplained() : QString(), noteLine(n, 1));
    for (const QString &file : noteFiles) {
        if (auto process = m_pictureRefinements.value(draft.filePath(file)))
            process->setProperty("destination", folder);
        QFile::remove(draft.filePath(file));
    }
    m_written.remove(n.id);
    for (int k = 0; k < n.strokes.size(); ++k)
        m_writtenMarks.remove(QStringLiteral("%1-%2").arg(n.id).arg(k));
    m_notes.removeAt(i);
    m_unwritten.remove(n.id);
    session->add(item);
    changed();
    if (!m_recording)
        m_status->setText(tr("Listening. Just talk and draw."));
}

void ReviewWindow::attachSession(LiveReview::Session *session)
{
    if (m_session == session)
        return;
    m_session = session;
    connect(session, &LiveReview::Session::changed, this, [this]() {
        if (m_closing)
            return;
        if (m_live)
            refreshLiveList();
        evaluateLoading();
    });
}

void ReviewWindow::deleteCard(int id)
{
    const int i = noteIndex(id);
    if (i < 0)
        return;
    if (m_editingId == id)
        m_editingId = -1;
    const QStringList noteFiles = files(m_notes[i]);
    for (const QString &file : noteFiles)
        QFile::remove(QDir(m_dir).filePath(file));
    m_notes.removeAt(i);
    changed();
    evaluateLoading();
}

void ReviewWindow::startEdit(int id)
{
    const int i = noteIndex(id);
    if (i < 0)
        return;
    m_editingId = id;
    m_editingText = m_notes[i].text;
    refreshLiveList();
}

void ReviewWindow::finishEdit()
{
    const int i = noteIndex(m_editingId);
    m_editingId = -1;
    if (i >= 0) {
        m_notes[i].text = m_editingText.trimmed();
        m_notes[i].heardVideo = false;
    }
    m_canvas->setFocus();
    changed();
}

QFrame *ReviewWindow::liveRow(const QString &key, const QImage &thumb, const QString &picture, const QString &when, int jumpFrame,
                    QWidget *words, const QString &state, const QString &stateColor, const QString &detail,
                    const QList<RowButton> &buttons, bool highlighted)
{
    using namespace LetItEditColors;
    auto row = new QFrame;
    row->setObjectName(QStringLiteral("reviewLiveRow-") + key);
    row->setStyleSheet(QStringLiteral("QFrame#%1 { background: %2; border: 1px solid %3; border-radius: 8px; }")
                           .arg(row->objectName(), panel, highlighted ? rust : line));
    auto out = new QHBoxLayout(row);
    out->setContentsMargins(6, 6, 6, 6);
    out->setSpacing(8);
    auto pic = new QLabel;
    pic->setObjectName(QStringLiteral("reviewLivePicture-") + key);
    pic->setFixedSize(64, 64);
    pic->setAlignment(Qt::AlignCenter);
    pic->setStyleSheet(QStringLiteral("background: %1; border-radius: 4px;").arg(deep));
    QImage shown = thumb;
    if (shown.isNull() && !picture.isEmpty()) // from an earlier session: read once
        shown = QImage(picture).scaled(192, 108, Qt::KeepAspectRatio, Qt::SmoothTransformation);
    if (!shown.isNull())
        pic->setPixmap(QPixmap::fromImage(shown.scaled(64, 64, Qt::KeepAspectRatio, Qt::SmoothTransformation)));
    out->addWidget(pic, 0, Qt::AlignTop);
    auto col = new QVBoxLayout;
    col->setSpacing(3);
    auto head = new QHBoxLayout;
    head->setSpacing(6);
    auto jump = new QToolButton;
    jump->setObjectName(QStringLiteral("reviewLiveJump-") + key);
    jump->setText(when);
    jump->setFocusPolicy(Qt::NoFocus);
    jump->setToolTip(tr("Go to this moment"));
    jump->setStyleSheet(QStringLiteral("QToolButton { padding: 1px 6px; font-weight: 600; }"));
    connect(jump, &QToolButton::clicked, this, [this, jumpFrame]() {
        if (jumpFrame >= 0)
            m_window->seekTimeline(qBound(0, jumpFrame, m_length - 1));
    });
    head->addWidget(jump);
    auto badge = new QLabel(state);
    badge->setObjectName(QStringLiteral("reviewLiveState-") + key);
    badge->setStyleSheet(QStringLiteral("color: %1; font-weight: 600;").arg(stateColor));
    head->addWidget(badge, 1);
    col->addLayout(head);
    col->addWidget(words);
    if (!detail.isEmpty()) {
        auto more = new QLabel(detail);
        more->setObjectName(QStringLiteral("reviewLiveDetail-") + key);
        more->setWordWrap(true);
        more->setStyleSheet(QStringLiteral("color: %1;").arg(muted));
        col->addWidget(more);
    }
    if (!buttons.isEmpty()) {
        auto actions = new QHBoxLayout;
        actions->setSpacing(4);
        for (const RowButton &b : buttons) {
            auto button = new QPushButton(b.label);
            button->setObjectName(QStringLiteral("reviewLive%1-%2").arg(b.name, key));
            button->setFocusPolicy(Qt::NoFocus);
            button->setStyleSheet(b.main ? QStringLiteral("background: %1; border-color: %1; font-weight: 600; padding: 3px 10px;").arg(rust)
                                         : QStringLiteral("padding: 3px 8px;"));
            const auto run = b.run;
            connect(button, &QPushButton::clicked, this, [this, run]() {
                // the list is made again by what this does: not from inside the button's own click
                QTimer::singleShot(0, this, run);
            });
            actions->addWidget(button);
        }
        actions->addStretch(1);
        col->addLayout(actions);
    }
    out->addLayout(col, 1);
    return row;
}

namespace {
// A card's words: a click on them opens them for editing, the cursor where the click was (T210).
class ClickableWords : public QLabel
{
public:
    std::function<void(const QPoint &)> clicked;
    using QLabel::QLabel;

protected:
    void mouseReleaseEvent(QMouseEvent *e) override
    {
        if (clicked && e->button() == Qt::LeftButton)
            clicked(e->position().toPoint());
        QLabel::mouseReleaseEvent(e);
    }
};
} // namespace

QWidget *ReviewWindow::wordsLabel(const QString &text, const QString &key)
{
    auto words = new ClickableWords(text);
    words->setObjectName(QStringLiteral("reviewLiveWords-") + key);
    words->setWordWrap(true);
    words->setTextFormat(Qt::PlainText);
    return words;
}

// One note not yet with the AI (being written down, held back, sending or waiting for an OK), as its row in the list.
QWidget *ReviewWindow::draftNoteRow(const Note &n)
{
    using namespace LetItEditColors;
    const int id = n.id;
    const QString key = QStringLiteral("n%1").arg(id);
    if (n.frame >= 0)
        m_scrubber->pins << n.frame;
    QWidget *words;
    if (m_editingId == id) {
        // the whole note in a box that wraps and grows with it, the cursor where it was clicked (T210)
        auto edit = noteEditor(m_editingText, nullptr, [this](bool keep) {
            QTimer::singleShot(0, this, [this, keep]() {
                if (keep) {
                    finishEdit();
                } else {
                    m_editingId = -1;
                    m_canvas->setFocus();
                    refreshLiveList();
                }
            });
        });
        edit->setObjectName(QStringLiteral("reviewLiveEditBox-") + key);
        connect(edit, &QPlainTextEdit::textChanged, this, [this, edit]() { m_editingText = edit->toPlainText(); });
        words = edit;
        const QPoint click = m_editClick;
        m_editClick = QPoint(-1, -1);
        QTimer::singleShot(0, edit, [edit, click]() {
            edit->setFocus();
            if (click.x() >= 0)
                edit->setTextCursor(edit->cursorForPosition(click));
            else
                edit->moveCursor(QTextCursor::End);
        });
    } else {
        words = wordsLabel(n.text.isEmpty() ? (n.writing ? QStringLiteral("...")
                                             : n.strokes.isEmpty() ? tr("(no words)") : tr("(a drawing, no words)"))
                                            : n.text, key);
        if (!n.writing && !n.heardVideo && !n.text.isEmpty())
            if (auto clickable = dynamic_cast<ClickableWords *>(words)) {
                clickable->setCursor(Qt::IBeamCursor);
                clickable->setToolTip(tr("Click to change the words"));
                clickable->clicked = [this, id](const QPoint &at) {
                    m_editClick = at;
                    QTimer::singleShot(0, this, [this, id]() { startEdit(id); });
                };
            }
    }
    QString state, detail;
    QString color = QString::fromLatin1(rust);
    QList<RowButton> buttons;
    const RowButton remove{tr("Delete"), QStringLiteral("Delete"), [this, id]() { deleteCard(id); }};
    if (n.writing) {
        state = tr("Writing it down...");
        color = QString::fromLatin1(tealLight);
        buttons << remove;
    } else if (n.heardVideo) {
        state = tr("Not sent");
        color = QString::fromLatin1(muted);
        detail = tr("It sounded like the video's own sound.");
        buttons << RowButton{tr("Send it anyway"), QStringLiteral("SendAnyway"), [this, id]() {
            if (int k = noteIndex(id); k >= 0) {
                m_notes[k].heardVideo = false;
                sendLive(id);
            }
        }} << remove;
    } else {
        state = m_sendingIds.contains(id) ? tr("Sending...") : tr("Needs your OK");
        if (m_unwritten.contains(id))
            detail = tr("Couldn't write down the words. Your AI gets the recording.");
        buttons << RowButton{tr("Send"), QStringLiteral("Send"), [this, id]() { sendLive(id); }, true}
                << (m_editingId == id ? RowButton{tr("Done"), QStringLiteral("EditDone"), [this]() { finishEdit(); }}
                                      : RowButton{tr("Edit"), QStringLiteral("Edit"), [this, id]() { startEdit(id); }})
                << remove;
    }
    return liveRow(key, n.thumb, n.imageFile, n.frame < 0 ? tr("Whole video") : stamp(n.frame / m_fps), n.frame,
                   words, state, color, detail, buttons, !n.writing && !n.heardVideo);
}

// The list: what is waiting for the person first, then what went to the AI, newest first. Made again when something
// changes, never per frame.
void ReviewWindow::refreshLiveList()
{
    using namespace LetItEditColors;
    if (!m_liveRows)
        return;
    const int scroll = m_liveScroll->verticalScrollBar()->value();
    while (m_liveRows->count() > 1) {
        auto item = m_liveRows->takeAt(0);
        if (auto w = item->widget()) {
            w->hide();
            w->deleteLater();
        }
        delete item;
    }
    int at = 0;
    QVector<int> order;
    for (int i = 0; i < m_notes.size(); ++i)
        order << i;
    std::sort(order.begin(), order.end(), [this](int a, int b) { return m_notes[a].id > m_notes[b].id; });
    m_scrubber->pins.clear();
    for (int i : std::as_const(order)) {
        m_liveRows->insertWidget(at++, draftNoteRow(m_notes[i]));
    }
    const QList<int> cards = sendableCards();
    int done = 0, ready = 0;
    if (m_session) {
        const auto &items = m_session->items();
        for (int k = items.size() - 1; k >= 0; --k) {
            const LiveReview::Item &it = items[k];
            const int id = it.id;
            const QString key = QStringLiteral("s%1").arg(id);
            QString state, detail;
            QString color = QString::fromLatin1(muted);
            QList<RowButton> buttons;
            const QPointer<LiveReview::Session> session(m_session);
            const auto call = [session](void (LiveReview::Session::*fn)(int), int which) {
                return [session, fn, which]() {
                    if (session)
                        (session.data()->*fn)(which);
                };
            };
            const RowButton clear{tr("Clear"), QStringLiteral("Clear"), call(&LiveReview::Session::clear, id)};
            const RowButton again{tr("Send again"), QStringLiteral("Again"), call(&LiveReview::Session::again, id)};
            switch (it.state) {
            case LiveReview::State::Waiting:
                state = tr("Waiting");
                buttons << RowButton{tr("Cancel"), QStringLiteral("Cancel"), call(&LiveReview::Session::cancel, id)};
                if (it.frame >= 0)
                    m_scrubber->pins << it.frame;
                break;
            case LiveReview::State::Working:
                state = it.cancelAsked ? tr("Stopping...") : tr("Being worked on");
                color = QString::fromLatin1(tealLight);
                if (!it.cancelAsked)
                    buttons << RowButton{tr("Cancel"), QStringLiteral("Cancel"), call(&LiveReview::Session::cancel, id)};
                if (const qint64 minutes = (QDateTime::currentMSecsSinceEpoch() - it.sentMs) / 60000; minutes >= 3)
                    detail = tr("Still on it after %1 minutes. Cancel stops it.").arg(minutes);
                if (it.frame >= 0)
                    m_scrubber->pins << it.frame;
                break;
            case LiveReview::State::Done:
                ++done;
                state = it.landed ? tr("Done") : tr("Done, ready to watch");
                ready += !it.landed;
                color = QString::fromLatin1(tealLight);
                detail = it.why.isEmpty() ? it.what : it.why;
                buttons << RowButton{tr("Undo"), QStringLiteral("Undo"), call(&LiveReview::Session::undo, id)};
                break;
            case LiveReview::State::NotAnEdit:
                state = tr("Not an edit");
                detail = it.why;
                buttons << RowButton{tr("It was a note"), QStringLiteral("Again"), call(&LiveReview::Session::again, id)} << clear;
                break;
            case LiveReview::State::CouldNot:
                state = tr("Couldn't be done");
                color = QString::fromLatin1(rust);
                detail = it.why;
                buttons << again << clear;
                break;
            case LiveReview::State::Cancelled:
                state = tr("Canceled");
                detail = it.why;
                buttons << again << clear;
                break;
            case LiveReview::State::Undone:
                state = tr("Undone");
                buttons << clear;
                break;
            }
            const int frame = it.state == LiveReview::State::Done && it.landed && it.changeAt >= 0 ? qRound(it.changeAt * m_fps)
                                                                                                  : it.frame;
            m_liveRows->insertWidget(at++, liveRow(key, it.thumb, it.picture, it.when, frame, wordsLabel(it.words, key), state,
                                                   color, detail, buttons, false));
        }
        QStringList counts;
        if (done)
            counts << tr("%1 done").arg(done);
        if (m_session->working())
            counts << tr("%1 being worked on").arg(m_session->working());
        if (m_session->waiting())
            counts << tr("%1 waiting").arg(m_session->waiting());
        QString line = counts.join(QStringLiteral(" \u00B7 "));
        if (!m_session->aiBusyNote().isEmpty())
            line += (line.isEmpty() ? QString() : QStringLiteral(". ")) + m_session->aiBusyNote();
        m_liveCounts->setWordWrap(true);
        m_liveCounts->setText(line);
    } else {
        m_liveCounts->clear();
    }
    m_scrubber->update();
    m_submit->setVisible(!cards.isEmpty());
    m_submit->setEnabled(!cards.isEmpty());
    m_submit->setText(cards.size() <= 1 ? tr("Send") : tr("Send all %1").arg(cards.size()));
    QTimer::singleShot(0, m_liveScroll, [this, scroll]() { m_liveScroll->verticalScrollBar()->setValue(scroll); });
}

// When the new version comes in. While the video plays the picture never changes by itself. A note being made or a card
// awaiting Send holds it back.
void ReviewWindow::evaluateLoading()
{
    if (!m_session || m_closing)
        return;
    const int ready = m_session->ready();
    const int pending = m_session->waiting() + m_session->working();
    if (m_session->loading() || ready == 0) {
        m_liveBar->hide();
        if (ready == 0)
            m_waitChosen = false;
        return;
    }
    const bool atEnd = m_position >= m_length - 2;
    const bool playing = (!MLT.isPaused() || m_slow.isActive()) && !atEnd;
    int cards = 0;
    for (const Note &n : std::as_const(m_notes))
        cards += !n.heardVideo;
    const bool hold = m_recording || cards > 0 || !m_sendingIds.isEmpty();
    if (!m_session->loadProblem().isEmpty()) {
        m_liveBarText->setText(tr("A change couldn't come in: %1").arg(m_session->loadProblem()));
        m_liveWatch->setText(tr("Try again"));
        m_liveWait->hide();
        m_liveBar->setVisible(m_live);
        return;
    }
    if (pending == 0 && !hold) {
        if (!playing) {
            loadChanges();
            return;
        }
        m_liveBarText->setText(ready == 1 ? tr("Your change is ready.") : tr("All %1 changes are ready.").arg(ready));
        m_liveWatch->setText(tr("Watch it"));
        m_liveWait->hide();
        m_liveBar->setVisible(m_live);
        return;
    }
    if (atEnd && !m_waitChosen) {
        const QString left = pending ? tr("%1 still working").arg(pending)
                                     : tr("%1 waiting for your OK").arg(cards);
        m_liveBarText->setText(tr("%1 done, %2.").arg(ready).arg(left));
        m_liveWatch->setText(tr("Watch what's ready"));
        m_liveWait->setText(tr("Wait"));
        m_liveWait->show();
        m_liveBar->setVisible(m_live);
        return;
    }
    m_liveBar->hide();
}

// Every finished note into the video, one Undo step each; it then plays from a couple of seconds before the first change.
void ReviewWindow::loadChanges()
{
    if (!m_session || m_session->loading() || !m_session->ready())
        return;
    stopPlaying();
    m_liveBar->hide();
    m_status->setText(tr("Bringing in your changes..."));
    const int count = m_session->ready();
    auto clock = std::make_shared<QElapsedTimer>();
    clock->start();
    QPointer<ReviewWindow> guard(this);
    m_session->load([guard, count, clock](double first, const QString &problem) {
        if (!guard || !guard->m_alive || guard->m_closing)
            return;
        guard->changesLoaded(first, problem, count, clock->elapsed());
    });
}

void ReviewWindow::changesLoaded(double first, const QString &problem, int count, qint64 ms)
{
    Timing::get();
    m_loadMs = ms;
    if (m_window->multitrack())
        m_length = qMax(1, m_window->multitrack()->get_length());
    m_scrubber->length = m_length;
    m_sentMarks.clear(); // those frames are of the version before
    if (!problem.isEmpty()) {
        m_status->setText(tr("A change couldn't come in: %1").arg(problem));
        refresh();
        return;
    }
    loadVideoWords(m_window->fileName());
    m_status->setText(count == 1 ? tr("Your change is in. Undo takes it back.")
                                 : tr("Your %1 changes are in, one Undo each.").arg(count));
    refresh();
    updateTime();
    m_window->seekTimeline(qBound(0, qRound((first - 2.0) * m_fps), m_length - 1));
    playAt(1.0);
}

QJsonObject ReviewWindow::liveState() const
{
    QJsonArray cards;
    for (const Note &n : m_notes)
        cards.append(QJsonObject{{"id", n.id}, {"frame", n.frame}, {"text", n.text}, {"writing", n.writing},
                                 {"heard_video", n.heardVideo}, {"strokes", int(n.strokes.size())},
                                 {"audio", n.audio}, {"unwritten", m_unwritten.contains(n.id)},
                                 {"clock", int(n.clock.size())}});
    return QJsonObject{{"on", m_live},
                       {"offer_visible", m_offer && m_offer->isVisibleTo(const_cast<ReviewWindow *>(this))},
                       {"listening_sign", m_liveListening && !m_liveListening->isHidden()},
                       {"mic_open", m_mic != nullptr},
                       {"test_sound", !m_qaPcm.isEmpty()},
                       {"send_without_asking", m_liveAutoSend && m_liveAutoSend->isChecked()},
                       {"room_db", m_audio ? m_audio->roomDb : 0.0},
                       {"cards", cards},
                       {"words_busy", m_wordsBusy},
                       {"video_words", !m_videoWords.isEmpty()},
                       {"session", m_session ? m_session->state() : QJsonObject()},
                       {"bar", m_liveBar && !m_liveBar->isHidden() ? m_liveBarText->text() : QString()},
                       {"watch", m_liveWatch ? m_liveWatch->text() : QString()},
                       {"counts", m_liveCounts ? m_liveCounts->text() : QString()},
                       {"playing", !MLT.isPaused()},
                       {"length", m_length},
                       {"load_ms", m_loadMs},
                       {"sent_marks", int(m_sentMarks.size())}};
}

} // namespace ReviewMode
