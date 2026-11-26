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

// Review: the notes' pictures and files, saving and loading a review, submitting it.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"
#include "proxymanager.h"
#include "letitedit/player/renderedpreview.h"
#include <QTemporaryDir>

namespace ReviewMode {

void ReviewWindow::refinePicture(const QString &xml, int frame, const QString &clean, const QString &markedPath,
                                 const QVector<Stroke> &strokes, const QList<int> &numbers, double dar)
{
    if (auto previous = m_pictureRefinements.take(clean)) {
        previous->setProperty("superseded", true);
        if (!previous->property("rendering").toBool())
            previous->deleteLater();
    }
    auto temporary = std::make_shared<QTemporaryDir>();
    if (!temporary->isValid())
        return;
    QFile project(temporary->filePath("original.mlt"));
    if (!project.open(QIODevice::WriteOnly))
        return;
    project.write(xml.toUtf8());
    project.close();
    auto *process = new QProcess(qApp);
    process->setProperty("destination", QFileInfo(clean).absolutePath());
    m_pictureRefinements.insert(clean, process);
#ifdef Q_OS_WIN
    process->setCreateProcessArgumentsModifier([](QProcess::CreateProcessArguments *arguments) {
        arguments->flags |= 0x08004000;
    });
#endif
    const QString output = temporary->filePath("frame.png");
    QPointer<ReviewWindow> guard(this);
    connect(process, &QProcess::finished, qApp, [=, retained = temporary](int code, QProcess::ExitStatus status) {
        qApp->setProperty("reviewFrameActive", false);
        process->setProperty("rendering", false);
        process->setProperty("finished", true);
        if (code != 0 || status != QProcess::NormalExit || process->property("superseded").toBool()) {
            process->deleteLater();
            return;
        }
        static auto *pool = []() {
            auto pool = new QThreadPool;
            pool->setMaxThreadCount(1);
            return pool;
        }();
        QPointer<QProcess> pending(process);
        pool->start(QRunnable::create([=]() {
            const QString stagedClean = retained->filePath("clean.png"), stagedMarked = retained->filePath("marked.png");
            writeMarked({}, QImage(output), {}, stagedClean, stagedMarked, strokes, numbers, dar, true);
            writerPool().start(QRunnable::create([=, lifetime = retained]() {
                QMetaObject::invokeMethod(qApp, [=]() {
                    Q_UNUSED(lifetime)
                    if (!pending)
                        return;
                    if (guard && guard->m_pictureRefinements.value(clean) == pending)
                        guard->m_pictureRefinements.remove(clean);
                    const QDir destination(pending->property("destination").toString());
                    const QString target = destination.filePath(QFileInfo(clean).fileName());
                    if (!pending->property("superseded").toBool() && QFileInfo::exists(target)) {
                        const QList<QPair<QString, QString>> paths{{stagedClean, target},
                            {stagedMarked, destination.filePath(QFileInfo(markedPath).fileName())}};
                        for (const auto &entry : paths) {
                            QFile source(entry.first);
                            QSaveFile destination(entry.second);
                            if (source.open(QIODevice::ReadOnly) && destination.open(QIODevice::WriteOnly)) {
                                const QByteArray bytes = source.readAll();
                                if (destination.write(bytes) == bytes.size())
                                    destination.commit();
                            }
                        }
                    }
                    pending->deleteLater();
                }, Qt::QueuedConnection);
            }));
        }));
    });
    connect(process, &QProcess::errorOccurred, process, [process](QProcess::ProcessError error) {
        if (error == QProcess::FailedToStart) {
            qApp->setProperty("reviewFrameActive", false);
            process->deleteLater();
        }
    });
    const QString python = aiChatSettings().value("python").toString();
    const QStringList arguments{qEnvironmentVariable("LETITEDIT_REVIEW_FRAME_WORKER", aiRootPath("bridge/original_review_frame.py")),
                                project.fileName(), QString::number(qMax(0, frame)), output};
    auto *startTimer = new QTimer(process);
    connect(startTimer, &QTimer::timeout, process, [=]() {
        if (qApp->property("reviewFrameActive").toBool())
            return;
        startTimer->stop();
        qApp->setProperty("reviewFrameActive", true);
        process->setProperty("rendering", true);
        process->start(python, arguments);
    });
    startTimer->start(100);
    QTimer::singleShot(15000, process, [process]() {
        if (process->property("finished").toBool())
            return;
        if (process->state() == QProcess::NotRunning)
            process->deleteLater();
        else
            process->kill();
    });
}

// ---- files ----
// The marked frame: the picture at its display shape with the drawing on it.
QImage ReviewWindow::marked(const QImage &image, const QVector<Stroke> &strokes, const QList<int> &numbers) const
{
    if (image.isNull())
        return QImage();
    const int h = image.height();
    QImage out = image.scaled(qRound(h * m_canvas->dar), h, Qt::IgnoreAspectRatio, Qt::SmoothTransformation)
                     .convertToFormat(QImage::Format_ARGB32);
    QPainter p(&out);
    paintStrokes(p, QRectF(out.rect()), strokes, numbers);
    return out;
}

// A take's mark k on its frame, with the take's other marks on that frame, numbered.
QImage ReviewWindow::markedTake(const Note &n, int k) const
{
    QVector<Stroke> strokes;
    QList<int> numbers;
    for (int i = 0; i < n.strokes.size(); ++i)
        if (n.strokes[i].frame == n.strokes[k].frame) {
            strokes << n.strokes[i];
            numbers << i + 1;
        }
    return marked(n.strokes[k].image, strokes, numbers);
}

QImage ReviewWindow::captureScenePicture()
{
#ifdef Q_OS_WIN
    if (m_liveScene && m_canvas) {
        const QImage scene = m_liveScene->captureReviewScene();
        if (!scene.isNull() && !m_canvas->image.isNull()) {
            QImage picture = m_canvas->image.convertToFormat(QImage::Format_ARGB32);
            QPainter painter(&picture);
            painter.setRenderHint(QPainter::SmoothPixmapTransform);
            painter.drawImage(picture.rect(), scene);
            return picture;
        }
    }
#endif
    return {};
}

// The same pictures, made on the writer thread: the clean frame (from the player's frame, a picture or an
// earlier PNG) and the frame with the strokes on it.
void ReviewWindow::writeMarked(const SharedFrame &shot, const QImage &image, const QString &imageFile, const QString &clean,
                            const QString &markedPath, const QVector<Stroke> &strokes, const QList<int> &numbers,
                            double dar, bool writeClean)
{
    QImage frame = !image.isNull() ? image : shot.is_valid() ? frameImage(shot) : QImage(imageFile);
    if (frame.isNull())
        frame = QImage(clean);
    if (frame.isNull())
        return;
    if (writeClean) {
        QSaveFile file(clean);
        if (file.open(QIODevice::WriteOnly) && frame.save(&file, "PNG", 80))
            file.commit();
    }
    const int h = frame.height();
    QImage out = frame.scaled(qRound(h * dar), h, Qt::IgnoreAspectRatio, Qt::SmoothTransformation)
                     .convertToFormat(QImage::Format_ARGB32);
    QPainter p(&out);
    paintStrokes(p, QRectF(out.rect()), strokes, numbers);
    p.end();
    QSaveFile file(markedPath);
    if (file.open(QIODevice::WriteOnly) && out.save(&file, "PNG", 80))
        file.commit();
}

// What a note's marked picture depends on: when this changes, it is written again.
QByteArray ReviewWindow::drawingSignature(const QVector<Stroke> &strokes)
{
    QByteArray sig;
    for (const auto &s : strokes)
        sig += QByteArray::number(int(s.tool)) + s.color.name().toLatin1() + ':' + QByteArray::number(s.points.size())
               + ':' + (s.points.isEmpty() ? QByteArray() : QByteArray::number(s.points.last().x() + s.points.last().y())) + ';';
    return sig;
}

QString ReviewWindow::frameFile(const Note &n) { return QStringLiteral("frame-%1.png").arg(n.id); }

QString ReviewWindow::markedFile(const Note &n) { return QStringLiteral("marked-%1.png").arg(n.id); }

QString ReviewWindow::markFrameFile(const Note &n, int k) { return QStringLiteral("frame-%1-mark%2.png").arg(n.id).arg(k + 1); }

QString ReviewWindow::markFile(const Note &n, int k) { return QStringLiteral("marked-%1-mark%2.png").arg(n.id).arg(k + 1); }

QStringList ReviewWindow::files(const Note &n) const
{
    QStringList list;
    if (n.hasImage())
        list << frameFile(n) << markedFile(n);
    for (int k = 0; k < n.strokes.size(); ++k)
        if (n.strokes[k].hasImage())
            list << markFrameFile(n, k) << markFile(n, k);
    if (!n.audio.isEmpty())
        list << n.audio;
    return list;
}

QJsonObject ReviewWindow::toJson(const Note &n) const
{
    QJsonArray strokes;
    for (int k = 0; k < n.strokes.size(); ++k) {
        const Stroke &s = n.strokes[k];
        QJsonArray points;
        for (const auto &pt : s.points)
            points.append(QJsonArray{std::round(pt.x() * 1000) / 1000, std::round(pt.y() * 1000) / 1000});
        QJsonObject so{{"tool", toolName(s.tool)}, {"color", s.color.name()}, {"points", points}};
        if (s.frame >= 0) {
            so["mark"] = k + 1;
            so["frame"] = s.frame;
            so["time"] = stamp(s.frame / m_fps);
            so["time_s"] = std::round(s.frame / m_fps * 100) / 100;
            if (s.endFrame >= 0) {
                so["end_frame"] = s.endFrame;
                so["end_time"] = stamp(s.endFrame / m_fps);
            }
            if (s.t0 >= 0) so["drawn_from_s"] = std::round(s.t0 / 10.0) / 100;
            if (s.t1 >= 0) so["drawn_to_s"] = std::round(s.t1 / 10.0) / 100;
            if (n.take) {
                QJsonArray spoken;
                QStringList spokenText;
                for (const Word &w : n.words) {
                    if (w.end * 1000 < s.t0 || w.start * 1000 > s.t1) continue;
                    spoken.append(QJsonObject{{"w", w.text}, {"s", w.start}, {"e", w.end}});
                    spokenText << w.text;
                }
                so["spoken_words"] = spoken;
                so["spoken_text"] = spokenText.join(QLatin1Char(' '));
            }
            if (s.hasImage()) {
                so["frame_png"] = markFrameFile(n, k);
                so["marked_png"] = markFile(n, k);
            }
        }
        strokes.append(so);
    }
    QJsonObject o{{"id", n.id}, {"text", n.text}, {"strokes", strokes}};
    if (n.frame >= 0) {
        o["frame"] = n.frame;
        o["time_s"] = std::round(n.frame / m_fps * 100) / 100;
        o["time"] = stamp(n.frame / m_fps);
    } else {
        o["whole_video"] = true;
    }
    if (n.take) {
        o["take"] = true;
        o["lead_in_s"] = n.leadInMs / 1000.0;
        o["end_frame"] = n.endFrame;
        o["end_time"] = stamp(n.endFrame / m_fps);
        o["script"] = script(n);
        QJsonArray words;
        for (const auto &w : n.words)
            words.append(QJsonObject{{"w", w.text},
                                     {"s", w.start},
                                     {"e", w.end},
                                     {"frame", frameAt(n, qint64(w.start * 1000))}});
        o["words"] = words;
        QJsonArray clock;
        int last = INT_MIN;
        for (const auto &[t, f] : n.clock)
            if (f != last) {
                clock.append(QJsonArray{t, f});
                last = f;
            }
        o["clock_ms_frame"] = clock;
    }
    if (n.hasImage()) {
        o["frame_png"] = frameFile(n);
        o["marked_png"] = markedFile(n);
    }
    if (!n.audio.isEmpty())
        o["audio"] = n.audio;
    if (n.heardVideo)
        o["heard_video"] = true;
    return o;
}

void ReviewWindow::save()
{
    const bool hasProxy = MLT.XML().contains(QStringLiteral("name=\"shotcut:proxy\""));
    if (Timing::get().legacy && !hasProxy) {
        saveLegacy();
        return;
    }
    if (m_notes.isEmpty() && !QFileInfo::exists(QDir(m_dir).filePath(QStringLiteral("notes.json"))))
        return;
    QDir().mkpath(m_dir);
    const QDir dir(m_dir);
    const double dar = m_canvas->dar;
    // T214: a frame shown while playing may come from the rendered preview: its picture is made again from the
    // original timeline at that frame, as for the playback copies
    const bool refine = hasProxy || RenderedPreview::inUse();
    QString originalXml;
    QJsonArray notes;
    for (auto &n : m_notes) {
        notes.append(toJson(n));
        // a note's pictures are written again only when its drawing changed, on the writer thread
        if (n.hasImage()) {
            const QByteArray sig = drawingSignature(n.strokes);
            const bool cleanMissing = !m_written.contains(n.id) && !QFileInfo::exists(dir.filePath(frameFile(n)));
            if (m_written.value(n.id) != sig || cleanMissing || !QFileInfo::exists(dir.filePath(markedFile(n)))) {
                m_written.insert(n.id, sig);
                const SharedFrame shot = n.shot;
                const QImage image = n.image;
                const QString imageFile = n.imageFile, clean = dir.filePath(frameFile(n)),
                              markedPath = dir.filePath(markedFile(n));
                const QVector<Stroke> strokes = n.strokes;
                if (refine && originalXml.isEmpty())
                    originalXml = ProxyManager::originalXML();
                const int originalFrame = n.frame < 0 ? MLT.producer()->position() : n.frame;
                writerPool().start(QRunnable::create([=]() {
                    writeMarked(shot, image, imageFile, clean, markedPath, strokes, {}, dar, cleanMissing);
                }));
                if (refine)
                    refinePicture(originalXml, originalFrame, clean, markedPath, strokes, {}, dar);
            }
        }
        for (int k = 0; k < n.strokes.size(); ++k) {
            Stroke &stroke = n.strokes[k];
            const QString key = QStringLiteral("%1-%2").arg(n.id).arg(k);
            if (!stroke.hasImage() || m_writtenMarks.contains(key) || QFileInfo::exists(dir.filePath(markFile(n, k))))
                continue; // a take's marks do not change after it ends
            m_writtenMarks.insert(key);
            QVector<Stroke> strokes;
            QList<int> numbers;
            for (int i = 0; i < n.strokes.size(); ++i)
                if (n.strokes[i].frame == stroke.frame) {
                    Stroke light = n.strokes[i];
                    light.shot = SharedFrame();
                    light.image = QImage();
                    strokes << light;
                    numbers << i + 1;
                }
            const SharedFrame shot = stroke.shot;
            const QImage image = stroke.image;
            const QString imageFile = stroke.imageFile, clean = dir.filePath(markFrameFile(n, k)),
                          markedPath = dir.filePath(markFile(n, k));
            if (refine && originalXml.isEmpty())
                originalXml = ProxyManager::originalXML();
            const int originalFrame = stroke.frame;
            writerPool().start(QRunnable::create([=]() {
                writeMarked(shot, image, imageFile, clean, markedPath, strokes, numbers, dar, true);
            }));
            if (refine)
                refinePicture(originalXml, originalFrame, clean, markedPath, strokes, numbers, dar);
            // written from here on: the frame itself is let go
            if (n.take) {
                stroke.shot = SharedFrame();
                stroke.image = QImage();
                stroke.imageFile = clean;
            }
        }
    }
    QSaveFile file(dir.filePath(QStringLiteral("notes.json")));
    if (file.open(QIODevice::WriteOnly)) {
        file.write(QJsonDocument(QJsonObject{{"project", QDir::toNativeSeparators(m_window->fileName())},
                                             {"fps", m_fps},
                                             {"next_id", m_nextId},
                                             {"notes", notes}})
                       .toJson());
        file.commit();
    }
}

// The way pictures were written before 20261030: every picture of every note, at once, on the screen thread.
void ReviewWindow::saveLegacy()
{
    if (m_notes.isEmpty() && !QFileInfo::exists(QDir(m_dir).filePath(QStringLiteral("notes.json"))))
        return;
    QDir().mkpath(m_dir);
    const QDir dir(m_dir);
    QJsonArray notes;
    for (auto &n : m_notes) {
        notes.append(toJson(n));
        if (n.image.isNull() && !n.imageFile.isEmpty())
            n.image.load(n.imageFile);
        if (!n.image.isNull()) {
            if (!QFileInfo::exists(dir.filePath(frameFile(n))))
                n.image.save(dir.filePath(frameFile(n)));
            marked(n.image, n.strokes).save(dir.filePath(markedFile(n)));
        }
        for (int k = 0; k < n.strokes.size(); ++k) {
            if (n.strokes[k].image.isNull() || QFileInfo::exists(dir.filePath(markFile(n, k))))
                continue;
            n.strokes[k].image.save(dir.filePath(markFrameFile(n, k)));
            markedTake(n, k).save(dir.filePath(markFile(n, k)));
        }
    }
    QSaveFile file(dir.filePath(QStringLiteral("notes.json")));
    if (file.open(QIODevice::WriteOnly)) {
        file.write(QJsonDocument(QJsonObject{{"project", QDir::toNativeSeparators(m_window->fileName())},
                                             {"fps", m_fps},
                                             {"next_id", m_nextId},
                                             {"notes", notes}})
                       .toJson());
        file.commit();
    }
}

void ReviewWindow::load()
{
    // no waiting for pictures still being written from the last time: they are read only when a file needs them,
    // and the writer thread keeps its order (Send waits for it before the notes move)
    QFile file(QDir(m_dir).filePath(QStringLiteral("notes.json")));
    if (!file.open(QIODevice::ReadOnly))
        return;
    const QDir dir(m_dir);
    const QJsonObject root = QJsonDocument::fromJson(file.readAll()).object();
    m_nextId = qMax(1, root.value("next_id").toInt(1));
    for (const auto &v : root.value("notes").toArray()) {
        const QJsonObject o = v.toObject();
        Note n;
        n.id = o.value("id").toInt();
        n.frame = o.value("whole_video").toBool() ? -1 : o.value("frame").toInt();
        n.text = o.value("text").toString();
        n.audio = o.value("audio").toString();
        n.take = o.value("take").toBool();
        n.leadInMs = qRound64(o.value("lead_in_s").toDouble() * 1000);
        n.endFrame = o.value("end_frame").toInt(-1);
        n.heardVideo = o.value("heard_video").toBool();
        // pictures are read only when a file needs them again (opening stays quick with many notes)
        if (o.contains("frame_png"))
            n.imageFile = dir.filePath(o.value("frame_png").toString());
        for (const auto &sv : o.value("strokes").toArray()) {
            const QJsonObject so = sv.toObject();
            Stroke s;
            s.tool = toolFromName(so.value("tool").toString());
            s.color = QColor(so.value("color").toString());
            for (const auto &pv : so.value("points").toArray())
                s.points << QPointF(pv.toArray().at(0).toDouble(), pv.toArray().at(1).toDouble());
            s.frame = so.value("frame").toInt(-1);
            s.endFrame = so.value("end_frame").toInt(-1);
            s.t0 = qRound64(so.value("drawn_from_s").toDouble(-0.001) * 1000);
            s.t1 = qRound64(so.value("drawn_to_s").toDouble(-0.001) * 1000);
            if (so.contains("frame_png"))
                s.imageFile = dir.filePath(so.value("frame_png").toString());
            n.strokes << s;
        }
        for (const auto &wv : o.value("words").toArray()) {
            const QJsonObject wo = wv.toObject();
            n.words.append({wo.value("w").toString(), wo.value("s").toDouble(), wo.value("e").toDouble()});
        }
        for (const auto &cv : o.value("clock_ms_frame").toArray())
            n.clock.append({qint64(cv.toArray().at(0).toDouble()), cv.toArray().at(1).toInt()});
        m_nextId = qMax(m_nextId, n.id + 1);
        // its pictures are on disk (or on their way): written again only when its drawing changes
        if (!n.imageFile.isEmpty())
            m_written.insert(n.id, drawingSignature(n.strokes));
        for (int k = 0; k < n.strokes.size(); ++k)
            if (!n.strokes[k].imageFile.isEmpty())
                m_writtenMarks.insert(QStringLiteral("%1-%2").arg(n.id).arg(k));
        m_notes << n;
    }
    if (!m_notes.isEmpty())
        m_status->setText(m_notes.size() == 1 ? tr("1 note from last time, not sent yet.")
                                            : tr("%1 notes from last time, not sent yet.").arg(m_notes.size()));
}

// A complete copy of the notes and their pictures and recordings goes to review/<time>/ and joins the queue of notes
// for the chat panel's AI (NoteQueue, send.cpp): it goes now, or by itself as soon as the AI is free. When it goes, the
// video as it is then becomes "<name> vN.mlt" (an earlier version in Versions of This Video). Review stays open, so
// more notes can be added while the AI works (T221). A failed copy leaves the notes as they were.
void ReviewWindow::submit()
{
    commitDraft();
    if (m_notes.isEmpty() && !m_recording && !m_sending && NoteQueue::of(m_window).stuck()) {
        NoteQueue::of(m_window).retry(); // Send again: the waiting notes try again (saving, an AI that wasn't ready)
        refreshQueueLine();
        return;
    }
    if (m_notes.isEmpty() || m_recording || m_sending)
        return;
    if (m_transcribing) { // so the AI gets the words: it goes by itself when they're in
        m_sendWhenWritten = true;
        m_status->setText(tr("Sending as soon as your words are written down..."));
        refresh();
        return;
    }
    m_sendWhenWritten = false;
    m_sending = true;
    refresh();
    const bool sent = sendNotes();
    m_sending = false;
    refresh();
    if (sent)
        m_status->clear(); // the queue line says where the notes are
}

// Every picture and recording a note refers to, written and on disk in the draft folder (written again if one is
// missing). Empty when all are there; else the missing file names.
QStringList ReviewWindow::draftComplete()
{
    const auto missing = [this]() {
        QStringList out;
        for (const auto &n : std::as_const(m_notes))
            for (const QString &file : files(n))
                if (!QFileInfo::exists(QDir(m_dir).filePath(file)))
                    out << file;
        return out;
    };
    save();
    writerPool().waitForDone();
    QStringList gone = missing();
    if (!gone.isEmpty()) { // written again from what the notes still hold
        m_written.clear();
        m_writtenMarks.clear();
        save();
        writerPool().waitForDone();
        gone = missing();
    }
    // a recording can't be made again: such a note goes without it (its words and marks stay)
    bool dropped = false;
    for (auto &n : m_notes)
        if (!n.audio.isEmpty() && gone.contains(n.audio)) {
            gone.removeAll(n.audio);
            n.audio.clear();
            dropped = true;
        }
    if (dropped)
        save();
    return gone;
}

QString ReviewWindow::noteLine(const Note &n, int number) const
{
    QString line = QStringLiteral("%1. ").arg(number);
    if (n.take && n.words.isEmpty() && n.text.isEmpty() && n.audio.isEmpty()) {
        line += QStringLiteral("Drawn at %1, with no words: the drawing shows it.").arg(stamp(n.frame / m_fps));
        QStringList marks;
        for (int k = 0; k < n.strokes.size(); ++k)
            if (n.strokes[k].hasImage())
                marks << QStringLiteral("mark %1: %2").arg(k + 1).arg(markFile(n, k));
        if (!marks.isEmpty())
            line += QStringLiteral(" Marks: %1.").arg(marks.join(QStringLiteral(", ")));
    } else if (n.take) {
        line += QStringLiteral("Spoken, %1 to %2: \"%3\"")
                    .arg(stamp(n.frame / m_fps), stamp(qMax(n.frame, n.endFrame) / m_fps), script(n));
        QStringList marks;
        for (int k = 0; k < n.strokes.size(); ++k)
            if (n.strokes[k].hasImage())
                marks << QStringLiteral("mark %1: %2").arg(k + 1).arg(markFile(n, k));
        if (!marks.isEmpty())
            line += QStringLiteral(" Marks: %1.").arg(marks.join(QStringLiteral(", ")));
        if (!n.audio.isEmpty())
            line += QStringLiteral(" Recording: %1.").arg(n.audio);
        if (n.words.isEmpty() && !n.audio.isEmpty())
            line += QStringLiteral(" (Its words could not be written down on this PC: listen to the recording.)");
    } else {
        line += n.frame < 0 ? QStringLiteral("Whole video: ")
                            : QStringLiteral("At %1 (%2 s): ").arg(stamp(n.frame / m_fps)).arg(n.frame / m_fps, 0, 'f', 2);
        line += n.text.isEmpty() ? QStringLiteral("(no words; the drawing shows it)") : QStringLiteral("\"%1\"").arg(n.text);
        if (!n.strokes.isEmpty())
            line += QStringLiteral(" Drawing: %1.").arg(markedFile(n));
        else if (n.hasImage())
            line += QStringLiteral(" Frame: %1.").arg(frameFile(n));
    }
    return line;
}

QString ReviewWindow::takesExplained()
{
    return QStringLiteral(
        " In a spoken note I talked and drew while the video played: \"[mark N: ...]\" "
        "sits where I drew mark N while talking, so the words around it are about that "
        "mark, and \"(m:ss.s)\" is the video time on screen when I said the words after "
        "it (\"right here\" means that time). Each mark's PNG is the frame it was drawn "
        "on, numbered. notes.json has every word with its time and frame, and each "
        "mark's spoken_words links the exact words heard while it was drawn. A mark "
        "with end_frame covers the frame range from frame to end_frame.");
}

} // namespace ReviewMode
