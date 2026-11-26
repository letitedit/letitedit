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

// Review's own parts: the drawing tools, the canvas over the picture, the scrubber, the microphone's stand-in for test windows.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"
#include <QThread>

namespace ReviewMode {

const char *toolName(Tool t)
{
    return t == Arrow ? "arrow" : t == Circle ? "circle" : t == Box ? "box" : "pen";
}

Tool toolFromName(const QString &name)
{
    return name == QLatin1String("arrow") ? Arrow : name == QLatin1String("circle") ? Circle
                                             : name == QLatin1String("box") ? Box : Pen;
}

// The player's frame as a full-size picture (any thread).
QImage frameImage(const SharedFrame &frame)
{
    if (!frame.is_valid())
        return QImage();
    const uint8_t *image = frame.get_image(mlt_image_rgba);
    if (!image)
        return QImage();
    return QImage(image, frame.get_image_width(), frame.get_image_height(), QImage::Format_RGBA8888)
        .convertToFormat(QImage::Format_RGB32);
}

// PNGs are written one at a time on their own thread, so drawing, closing and opening never wait for them.
QThreadPool &writerPool()
{
    static QThreadPool *pool = []() {
        auto p = new QThreadPool;
        p->setMaxThreadCount(1);
        p->setExpiryTimeout(-1);
        return p;
    }();
    return *pool;
}

QString stamp(double seconds)
{
    const int tenths = qMax(0, int(std::lround(seconds * 10)));
    return QStringLiteral("%1:%2.%3")
        .arg(tenths / 600)
        .arg((tenths / 10) % 60, 2, 10, QLatin1Char('0'))
        .arg(tenths % 10);
}

// Strokes in a rectangle that shows the whole picture; the same drawing for the screen and the saved PNGs.
// numbers: a label at the end of each stroke (the mark's number in a take), 0 for none.
void paintStrokes(QPainter &p, const QRectF &r, const QVector<Stroke> &strokes, const QList<int> &numbers)
{
    p.setRenderHint(QPainter::Antialiasing);
    const double width = qMax(2.5, r.height() * 0.007);
    const auto at = [&r](const QPointF &n) { return QPointF(r.left() + n.x() * r.width(), r.top() + n.y() * r.height()); };
    for (int i = 0; i < strokes.size(); ++i) {
        const Stroke &s = strokes[i];
        if (s.points.isEmpty())
            continue;
        // a dark edge under the colour keeps the mark readable on any picture
        for (int pass = 0; pass < 2; ++pass) {
            QPen pen(pass ? s.color : QColor(0, 0, 0, 110), pass ? width : width * 2.0, Qt::SolidLine, Qt::RoundCap,
                     Qt::RoundJoin);
            p.setPen(pen);
            p.setBrush(Qt::NoBrush);
            const QPointF a = at(s.points.first()), b = at(s.points.last());
            if (s.tool == Pen) {
                QPainterPath path(a);
                for (int j = 1; j < s.points.size(); ++j)
                    path.lineTo(at(s.points[j]));
                if (s.points.size() == 1)
                    path.lineTo(a + QPointF(0.1, 0.1));
                p.drawPath(path);
            } else if (s.tool == Circle) {
                p.drawEllipse(QRectF(a, b).normalized());
            } else if (s.tool == Box) {
                p.drawRect(QRectF(a, b).normalized());
            } else {
                p.drawLine(a, b);
                const double angle = std::atan2(b.y() - a.y(), b.x() - a.x());
                const double head = qMax(width * 4.5, 14.0);
                for (double side : {-0.45, 0.45})
                    p.drawLine(b, b - QPointF(std::cos(angle + side) * head, std::sin(angle + side) * head));
            }
        }
        const int number = i < numbers.size() ? numbers[i] : 0;
        if (number > 0) {
            const double radius = qMax(11.0, r.height() * 0.022);
            QPointF c = s.tool == Circle ? at(QPointF(qMax(s.points.first().x(), s.points.last().x()),
                                                      qMin(s.points.first().y(), s.points.last().y())))
                                         : at(s.tool == Arrow ? s.points.first() : s.points.last());
            c.setX(qBound(r.left() + radius, c.x(), r.right() - radius));
            c.setY(qBound(r.top() + radius, c.y(), r.bottom() - radius));
            p.setPen(QPen(QColor(0, 0, 0, 160), 1.5));
            p.setBrush(s.color);
            p.drawEllipse(c, radius, radius);
            QFont f = p.font();
            f.setBold(true);
            f.setPixelSize(int(radius * 1.2));
            p.setFont(f);
            p.setPen(QColor(LetItEditColors::deep));
            p.drawText(QRectF(c.x() - radius, c.y() - radius, radius * 2, radius * 2), Qt::AlignCenter,
                       QString::number(number));
        }
    }
}

RollingAudio::RollingAudio(QObject *parent)
    : QIODevice(parent) { open(QIODevice::WriteOnly); clock.start(); }

void RollingAudio::feed(const char *data, qint64 len) { writeData(data, len); }

qint64 RollingAudio::voicedRun() { QMutexLocker lock(&mutex); return voicedRunMs; }

void RollingAudio::begin(qint64 leadInUs)
{
    QMutexLocker lock(&mutex);
    take = leadInUs > 0 ? recent.right(format.bytesForFrames(format.framesForDuration(leadInUs))) : recent;
    voicedRunMs = 0;
    prerollMs = format.bytesForDuration(1000000) > 0
                    ? qRound64(double(take.size()) * 1000 / format.bytesForDuration(1000000)) : 0;
    recording = true;
}

QByteArray RollingAudio::finish()
{
    QMutexLocker lock(&mutex);
    recording = false;
    voicedRunMs = 0; // the speech just heard belongs to this note: the next one needs speech of its own
    return std::exchange(take, QByteArray());
}

QByteArray RollingAudio::soFar()
{
    QMutexLocker lock(&mutex);
    return take;
}

qint64 RollingAudio::cappedRecentMs() { QMutexLocker lock(&mutex); return prerollMs; }

qint64 RollingAudio::lastVoice() { QMutexLocker lock(&mutex); return lastVoiceMs; }

QByteArray RollingAudio::speechChunk()
{
    QMutexLocker lock(&mutex);
    return std::exchange(speechPending, QByteArray());
}

void RollingAudio::detectedSpeech(qint64 lastMs, qint64 runMs)
{
    QMutexLocker lock(&mutex);
    lastVoiceMs = lastMs;
    voicedRunMs = runMs;
}

qint64 RollingAudio::readData(char *, qint64) { return -1; }

qint64 RollingAudio::writeData(const char *data, qint64 len)
{
    if (len <= 0) return 0;
    QMutexLocker lock(&mutex);
    recent.append(data, len);
    const qint64 limit = format.bytesForDuration(3000000);
    if (limit > 0 && recent.size() > limit)
        recent.remove(0, recent.size() - int(limit));
    if (recording) take.append(data, len);
    if (followRoom) {
        speechPending.append(data, len);
        if (limit > 0 && speechPending.size() > limit)
            speechPending.remove(0, speechPending.size() - int(limit));
        return len;
    }
    if (format.sampleFormat() == QAudioFormat::Int16) {
        const qint16 *samples = reinterpret_cast<const qint16 *>(data);
        const int count = int(len / 2);
        double energy = 0;
        for (int i = 0; i < count; ++i) energy += double(samples[i]) * samples[i];
        const double rms = count ? std::sqrt(energy / count) / 32768.0 : 0;
        noteLevel(rms, len);
    } else if (format.sampleFormat() == QAudioFormat::Float) {
        double energy = 0;
        const int count = int(len / 4);
        for (int i = 0; i < count; ++i) {
            float sample;
            std::memcpy(&sample, data + i * 4, sizeof(sample));
            energy += double(sample) * sample;
        }
        const double rms = count ? std::sqrt(energy / count) : 0;
        noteLevel(rms, len);
    } else if (format.sampleFormat() == QAudioFormat::Int32) {
        double energy = 0;
        const int count = int(len / 4);
        for (int i = 0; i < count; ++i) {
            qint32 sample;
            std::memcpy(&sample, data + i * 4, sizeof(sample));
            const double normalized = double(sample) / 2147483648.0;
            energy += normalized * normalized;
        }
        const double rms = count ? std::sqrt(energy / count) : 0;
        noteLevel(rms, len);
    }
    return len;
}

void RollingAudio::noteLevel(double rms, qint64 len)
{
    if (!followRoom) {
        if (rms > std::pow(10.0, thresholdDb / 20.0)) lastVoiceMs = clock.elapsed();
        return;
    }
    const qint64 perSecond = format.bytesForDuration(1000000);
    const double ms = perSecond > 0 ? double(len) * 1000 / perSecond : 0;
    const double db = rms > 1e-5 ? 20.0 * std::log10(rms) : -100.0;
    bucketEnergy += rms * rms * ms;
    bucketMs += ms;
    if (bucketMs >= 200.0) {
        const double level = bucketEnergy / bucketMs;
        roomBuckets.append(level > 1e-10 ? 10.0 * std::log10(level) : -100.0);
        if (roomBuckets.size() > 40)
            roomBuckets.removeFirst();
        bucketEnergy = bucketMs = 0;
        roomDb = *std::min_element(roomBuckets.cbegin(), roomBuckets.cend());
    }
    if (roomBuckets.size() < 3)
        return; // a moment to hear the room before anything counts as speech
    if (db > qMax(thresholdDb, roomDb + 12.0)) {
        lastVoiceMs = clock.elapsed();
        voicedRunMs += qRound64(ms);
    } else {
        voicedRunMs = qMax<qint64>(0, voicedRunMs - qRound64(ms / 2)); // the gaps between syllables don't reset it
    }
}

// The picture area in device pixels: frames are made at exactly this size, so painting never scales.
QSize Canvas::pictureSize() const { return (pictureRect().size() * devicePixelRatioF()).toSize(); }

Canvas::Canvas(QWidget *parent)
    : QWidget(parent)
{
    setCursor(Qt::CrossCursor);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    setFocusPolicy(Qt::ClickFocus);
}

QRectF Canvas::pictureRect() const
{
    const QRectF area = QRectF(rect()).adjusted(8, 8, -8, -8);
    double w = area.width(), h = w / dar;
    if (h > area.height()) {
        h = area.height();
        w = h * dar;
    }
    return QRectF(area.center().x() - w / 2, area.center().y() - h / 2, w, h);
}

void Canvas::paintEvent(QPaintEvent *e)
{
    Timing &t = Timing::get();
    if (t.active && !t.legacy && qEnvironmentVariableIntValue("LETITEDIT_QA") == 1
        && qEnvironmentVariableIntValue("LETITEDIT_QA_REVIEW_DELAY_FRAME") == 1)
        QThread::usleep(16667);
    const qint64 start = t.clock.nsecsElapsed();
    QPainter p(this);
    p.fillRect(e->rect(), QColor(LetItEditColors::deep));
    const QRectF r = pictureRect();
    if (image.isNull()) {
        p.fillRect(r, Qt::black);
        p.setPen(QColor(LetItEditColors::muted));
        p.drawText(r, Qt::AlignCenter, tr("Press Play or click the bar below to show the video"));
    } else if (t.legacy) {
        p.setRenderHint(QPainter::SmoothPixmapTransform);
        p.drawImage(r, image);
    } else {
        // made at this size: a plain copy; while the window changes size, a quick scale until the next frame
        p.drawImage(r, image);
    }
    if (shown) {
        QVector<Stroke> strokes;
        QList<int> numbers;
        shown(strokes, numbers);
        paintStrokes(p, r, strokes, numbers);
    }
    p.end();
    const qint64 end = t.clock.nsecsElapsed();
    if (t.active) {
        t.paintUs << (end - start) / 1000;
        if (t.pendingInputNs >= 0) {
            t.inputUs << (end - t.pendingInputNs) / 1000;
            t.pendingInputNs = -1;
        }
    }
    if (t.firstPaintNs < 0 && t.openStartNs >= 0) {
        t.firstPaintNs = end;
        t.openMs = (end - t.openStartNs) / 1000000;
    }
}

void Canvas::resizeEvent(QResizeEvent *e)
{
    QWidget::resizeEvent(e);
    if (resized)
        resized();
}

// What a stroke covers on screen, with room for its edge, arrow head and number.
QRectF Canvas::strokeBounds(const Stroke &s) const
{
    const QRectF r = pictureRect();
    QRectF box;
    for (const auto &n : s.points) {
        const QPointF at(r.left() + n.x() * r.width(), r.top() + n.y() * r.height());
        box = box.isNull() ? QRectF(at, QSizeF(1, 1)) : box.united(QRectF(at, QSizeF(1, 1)));
    }
    const double width = qMax(2.5, r.height() * 0.007);
    const double margin = qMax(qMax(width * 4.5, 14.0), qMax(11.0, r.height() * 0.022) * 2.0) + width * 2 + 4;
    return box.adjusted(-margin, -margin, margin, margin);
}

void Canvas::noteInput()
{
    Timing &t = Timing::get();
    if (t.active && t.pendingInputNs < 0)
        t.pendingInputNs = qaInputNs >= 0 ? qaInputNs : t.clock.nsecsElapsed();
    qaInputNs = -1;
}

QPointF Canvas::normalized(const QPointF &pos) const
{
    const QRectF r = pictureRect();
    return QPointF(qBound(0.0, (pos.x() - r.left()) / r.width(), 1.0),
                   qBound(0.0, (pos.y() - r.top()) / r.height(), 1.0));
}

void Canvas::mousePressEvent(QMouseEvent *e)
{
    if (e->button() != Qt::LeftButton || !target)
        return;
    if (beginDraw)
        beginDraw();
    m_strokes = target();
    if (!m_strokes)
        return;
    Stroke s;
    s.tool = tool;
    s.color = color;
    s.points << normalized(e->position());
    if (tool != Pen)
        s.points << s.points.first();
    if (strokeStarted)
        strokeStarted(s);
    m_strokes->append(s);
    if (markupChanged) markupChanged();
    noteInput();
    if (Timing::get().legacy)
        update();
    else
        update(strokeBounds(s).toAlignedRect());
}

void Canvas::mouseMoveEvent(QMouseEvent *e)
{
    if (!m_strokes || m_strokes->isEmpty())
        return;
    auto &s = m_strokes->last();
    noteInput();
    if (Timing::get().legacy) {
        if (s.tool == Pen)
            s.points << normalized(e->position());
        else
            s.points.last() = normalized(e->position());
        update();
        if (markupChanged) markupChanged();
        return;
    }
    // only the part of the picture the stroke touches is painted again
    QRectF dirty;
    if (s.tool == Pen) {
        Stroke segment;
        segment.points << s.points.last() << normalized(e->position());
        s.points << segment.points.last();
        dirty = strokeBounds(segment);
    } else {
        dirty = strokeBounds(s);
        s.points.last() = normalized(e->position());
        dirty = dirty.united(strokeBounds(s));
    }
    update(dirty.toAlignedRect());
    if (markupChanged) markupChanged();
}

void Canvas::mouseReleaseEvent(QMouseEvent *e)
{
    if (e->button() != Qt::LeftButton || !m_strokes)
        return;
    m_strokes = nullptr;
    if (changed)
        changed();
    if (markupChanged) markupChanged();
}

Scrubber::Scrubber(QWidget *parent)
    : QWidget(parent)
{
    setFixedHeight(34);
    setCursor(Qt::PointingHandCursor);
    setFocusPolicy(Qt::NoFocus);
}

QRectF Scrubber::track() const { return QRectF(10, height() / 2.0 - 3, width() - 20, 6); }

double Scrubber::xAt(int frame) const
{
    const QRectF t = track();
    return t.left() + t.width() * qBound(0.0, double(frame) / qMax(1, length - 1), 1.0);
}

void Scrubber::paintEvent(QPaintEvent *)
{
    using namespace LetItEditColors;
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const QRectF t = track();
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(line));
    p.drawRoundedRect(t, 3, 3);
    p.setBrush(QColor(teal));
    p.drawRoundedRect(QRectF(t.left(), t.top(), xAt(position) - t.left(), t.height()), 3, 3);
    for (int frame : pins) {
        p.setBrush(QColor(frame == activePin ? cream : rust));
        p.drawEllipse(QPointF(xAt(frame), t.center().y()), 6, 6);
    }
    p.setBrush(QColor(cream));
    p.drawRoundedRect(QRectF(xAt(position) - 2, 4, 4, height() - 8), 2, 2);
}

void Scrubber::seekTo(double x)
{
    const QRectF t = track();
    const int frame = qRound(qBound(0.0, (x - t.left()) / t.width(), 1.0) * (length - 1));
    // a click near a pin lands on its note exactly
    int best = frame;
    for (int pin : pins)
        if (std::abs(xAt(pin) - x) < 8)
            best = pin;
    if (seek)
        seek(best);
}

void Scrubber::mousePressEvent(QMouseEvent *e) { seekTo(e->position().x()); }

void Scrubber::mouseMoveEvent(QMouseEvent *e)
{
    if (e->buttons() & Qt::LeftButton)
        seekTo(e->position().x());
}

} // namespace ReviewMode
