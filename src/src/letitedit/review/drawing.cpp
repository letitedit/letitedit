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

// Review: the picture on screen and the marks drawn on it.
// (Split out of reviewmode.cpp; the classes are declared in reviewwindow.h.)

#include "reviewwindow.h"

namespace ReviewMode {

// The frame on screen, made into a picture of the picture area's size on another thread; a newer frame that
// arrives meanwhile follows it, the ones in between are skipped.
void ReviewWindow::requestPicture()
{
    if (Timing::get().legacy)
        return;
    if (!m_frame.is_valid()) {
        // the frame shown when Review opened, made the size of the picture area once
        const QSize size = m_canvas->pictureSize();
        if (!m_canvas->image.isNull() && size.width() > 4 && m_canvas->image.size() != size) {
            m_canvas->image = m_canvas->image.scaled(size, Qt::IgnoreAspectRatio, Qt::SmoothTransformation)
                                  .convertToFormat(QImage::Format_RGB32);
            m_canvas->image.setDevicePixelRatio(m_canvas->devicePixelRatioF());
            m_canvas->update();
        }
        return;
    }
    if (m_converting) {
        m_morePending = true;
        return;
    }
    const QSize size = m_canvas->pictureSize();
    if (size.width() < 4 || size.height() < 4)
        return;
    m_converting = true;
    m_morePending = false;
    const SharedFrame frame = m_frame;
    const bool smooth = MLT.isPaused() && !m_slow.isActive();
    QPointer<ReviewWindow> guard(this);
    writerPictures().start(QRunnable::create([frame, size, smooth, guard]() {
        QImage picture;
        if (const uint8_t *data = frame.get_image(mlt_image_rgba)) {
            const QImage whole(data, frame.get_image_width(), frame.get_image_height(), QImage::Format_RGBA8888);
            picture = whole.scaled(size, Qt::IgnoreAspectRatio, smooth ? Qt::SmoothTransformation : Qt::FastTransformation)
                          .convertToFormat(QImage::Format_RGB32);
        }
        QMetaObject::invokeMethod(qApp, [guard, picture]() {
            if (guard && guard->m_alive)
                guard->pictureReady(picture);
        }, Qt::QueuedConnection);
    }));
}

void ReviewWindow::pictureReady(const QImage &picture)
{
    m_converting = false;
    if (!picture.isNull()) {
        m_canvas->image = picture;
        m_canvas->image.setDevicePixelRatio(m_canvas->devicePixelRatioF());
        m_canvas->update();
    }
    if (m_morePending)
        requestPicture();
}

// Pictures for the screen are made on their own thread too (two at most: one being made, one waiting).
QThreadPool &ReviewWindow::writerPictures()
{
    static QThreadPool *pool = []() {
        auto p = new QThreadPool;
        p->setMaxThreadCount(1);
        p->setExpiryTimeout(-1);
        return p;
    }();
    return *pool;
}

QVector<Stroke> *ReviewWindow::activeStrokes()
{
    if (m_recording)
        return &m_take.strokes;
    const int i = noteAt(m_position);
    if (i >= 0)
        return &m_notes[i].strokes;
    return &m_draft;
}

// While talking: the take's marks made within the last second and a half (they follow the video), numbered.
// Otherwise: this frame's typed note or draft, and the marks any take made on this frame.
void ReviewWindow::shownStrokes(QVector<Stroke> &strokes, QList<int> &numbers)
{
    if (m_recording) {
        const int window = qRound(m_fps * 1.5);
        for (int i = 0; i < m_take.strokes.size(); ++i) {
            const Stroke &s = m_take.strokes[i];
            if (s.t1 < 0 || (s.endFrame >= 0 && m_position >= s.frame && m_position <= s.endFrame)
                || std::abs(m_position - s.frame) <= window || (m_speed == 0 && !m_live)) {
                strokes << s;
                numbers << i + 1;
            }
        }
        return;
    }
    if (auto active = activeStrokes()) {
        strokes << *active;
        for (int i = 0; i < active->size(); ++i)
            numbers << 0;
    }
    for (const auto &n : std::as_const(m_notes)) {
        if (!n.take && n.frame == m_position) continue; // already shown as the active note
        for (int i = 0; i < n.strokes.size(); ++i)
            if (n.strokes[i].frame == m_position || (n.strokes[i].endFrame >= 0
                && m_position >= n.strokes[i].frame && m_position <= n.strokes[i].endFrame)) {
                strokes << n.strokes[i];
                numbers << (n.take ? i + 1 : 0);
            }
    }
    // notes already sent keep their drawing on the frame it was made on, until a new version comes in
    for (const Stroke &s : std::as_const(m_sentMarks))
        if (s.frame == m_position) {
            strokes << s;
            numbers << 0;
        }
}

void ReviewWindow::updateReviewMarkup()
{
#ifdef Q_OS_WIN
    if (!m_liveScene) return;
    QVector<Stroke> strokes;
    QList<int> numbers;
    shownStrokes(strokes, numbers);
    QJsonArray items;
    for (int i = 0; i < strokes.size(); ++i) {
        QJsonArray points;
        for (const QPointF &p : strokes[i].points)
            points.append(QJsonArray{p.x(), p.y()});
        items.append(QJsonObject{{"tool", int(strokes[i].tool)},
                                 {"color", strokes[i].color.name()},
                                 {"points", points},
                                 {"number", i < numbers.size() ? numbers[i] : 0}});
    }
    m_liveScene->setReviewMarkup(items);
#endif
}

} // namespace ReviewMode
