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

// Review: what test windows drive (LETITEDIT_QA): the microphone's stand-in sounds and synthetic pen strokes.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"

namespace ReviewMode {

// QA: another sound file for the microphone's stand-in, from now on (one note's words at a time in a journey).
void ReviewWindow::qaNextSound(const QString &path)
{
    QFile f(path);
    if (!m_audio || !f.open(QIODevice::ReadOnly))
        return;
    const QByteArray wav = f.readAll();
    const int dataAt = wav.indexOf("data");
    if (dataAt < 36 || dataAt + 8 >= wav.size())
        return;
    m_qaPcm = wav.mid(dataAt + 8);
    m_qaOffset = 0;
}

// QA: pen strokes as a hand draws them (a movement every 8 ms), posted to the canvas like real mouse events while
// the video plays (in a spoken take) or stands still; then the measurements are written down.
void ReviewWindow::qaDraw(bool talk, double seconds, const QString &out)
{
    Timing &t = Timing::get();
    t.reset();
    t.active = true;
    if (talk) {
        // Older Review journeys inspect the draft after this synthetic take and press Send themselves.
        // The product's default remains auto-send; this only keeps that QA action deterministic.
        m_autoSend->setChecked(false);
        if (!m_listening && !m_live && qEnvironmentVariableIsSet("LETITEDIT_QA_REVIEW_WAV")) {
            if (m_listenSwitch->isChecked())
                setListening(true);
            else
                m_listenSwitch->setChecked(true); // the switch and listening stay the same
        }
        setSpeed(1.0); // normal speed: frames keep coming while drawing
        if (!m_recording)
            m_talk->click();
        playAt(m_speed);
    } else {
        stopPlaying();
    }
    auto tick = new QTimer(this);
    tick->setTimerType(Qt::PreciseTimer);
    tick->setInterval(8);
    auto clock = std::make_shared<QElapsedTimer>();
    clock->start();
    auto step = std::make_shared<int>(0);
    connect(tick, &QTimer::timeout, this, [this, tick, clock, step, seconds, talk, out]() {
        const double elapsed = clock->elapsed() / 1000.0;
        const QRectF r = m_canvas->pictureRect();
        const int strokeMs = 700, gapMs = 150; // a stroke, a short lift, the next stroke
        const qint64 ms = clock->elapsed();
        const int index = int(ms / (strokeMs + gapMs));
        const int within = int(ms % (strokeMs + gapMs));
        static bool down = false;
        const auto post = [this, &r](QEvent::Type type, double u, double v) {
            const QPointF at(r.left() + u * r.width(), r.top() + v * r.height());
            auto e = new QMouseEvent(type, at, m_canvas->mapToGlobal(at), Qt::LeftButton,
                                     type == QEvent::MouseButtonRelease ? Qt::NoButton : Qt::LeftButton, Qt::NoModifier);
            m_canvas->qaInputNs = Timing::get().clock.nsecsElapsed();
            QCoreApplication::sendEvent(m_canvas, e);
            delete e;
        };
        const double a = 0.15 + 0.1 * (index % 6), phase = within / double(strokeMs);
        const double u = 0.2 + 0.6 * phase, v = a + 0.08 * std::sin(phase * 6.28 * 2);
        if (elapsed >= seconds) {
            if (down)
                post(QEvent::MouseButtonRelease, u, v);
            down = false;
            tick->stop();
            tick->deleteLater();
            if (talk && m_recording)
                m_talk->click();
            stopPlaying();
            Timing::get().active = false;
            QFile f(out);
            if (f.open(QIODevice::WriteOnly))
                f.write(QJsonDocument(state()).toJson());
            return;
        }
        if (within < strokeMs) {
            if (!down) {
                post(QEvent::MouseButtonPress, u, v);
                down = true;
            } else {
                post(QEvent::MouseMove, u, v);
            }
        } else if (down) {
            post(QEvent::MouseButtonRelease, u, v);
            down = false;
        }
        ++*step;
    });
    if (!talk)
        m_slow.stop();
    tick->start();
    if (!talk && m_speed > 0) {
        // drawing on a still frame first pauses the video (beginDraw); nothing else to set up
    }
}

} // namespace ReviewMode
