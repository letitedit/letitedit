/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * A small painted filmstrip for the AI's long editing jobs.
 */
#ifndef PROGRESSVIEW_H
#define PROGRESSVIEW_H

#include <QPainter>
#include <QPainterPath>
#include <QTimer>
#include <QWidget>
#include <QtMath>

class ProgressView : public QWidget
{
public:
    explicit ProgressView(QWidget *parent = nullptr)
        : QWidget(parent)
    {
        setObjectName(QStringLiteral("progressFilmstrip"));
        setMinimumHeight(144);
        setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
        auto *timer = new QTimer(this);
        timer->setInterval(33);
        connect(timer, &QTimer::timeout, this, [this]() {
            if (isVisible()) {
                m_phase += .035;
                update();
            }
        });
        timer->start();
    }

    void setProgress(qreal fraction, int stage)
    {
        m_target = qBound(qreal(0), fraction, qreal(1));
        m_stage = qBound(0, stage, 6);
        update();
    }

protected:
    void paintEvent(QPaintEvent *) override
    {
        m_shown += (m_target - m_shown) * .13;
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        const qreal w = width();
        const bool compact = w < 400;
        const qreal left = compact ? 24 : 35, right = w - left;
        const qreal usable = qMax(qreal(1), right - left);
        const qreal y = 50;
        const qreal barY = 126;
        const QColor rust("#D4744A"), teal("#9ED6E2"), cream("#F4EFE6"), dim("#5F686C");

        // A reel track runs through seven little frames.  The playhead glides as
        // evidence arrives; a subtle moving glint keeps a long wait alive.
        p.setPen(QPen(QColor("#354148"), 9, Qt::SolidLine, Qt::RoundCap));
        p.drawLine(QPointF(left, barY), QPointF(right, barY));
        const qreal head = left + usable * m_shown;
        QLinearGradient fill(left, barY, right, barY);
        fill.setColorAt(0, QColor("#2A8597"));
        fill.setColorAt(.7, rust);
        fill.setColorAt(1, rust);
        p.setPen(QPen(QBrush(fill), 9, Qt::SolidLine, Qt::RoundCap));
        p.drawLine(QPointF(left, barY), QPointF(head, barY));

        static const char *numbers[] = {"01", "02", "03", "04", "05", "06", "07"};
        static const char *names[] = {"WATCH", "PICK", "CUT", "POLISH", "FINISH", "SAVE", "CHECK"};
        const qreal gap = usable / 6;
        for (int i = 0; i < 7; ++i) {
            const qreal x = left + i * gap;
            const qreal halfBox = compact ? 19 : 23;
            const QRectF box(x - halfBox, y - 25, halfBox * 2, 50);
            const bool past = i < m_stage, current = i == m_stage;
            p.setPen(QPen(current ? rust : past ? teal : QColor("#465159"), current ? 2.5 : 1.5));
            p.setBrush(current ? QColor("#4B3028") : past ? QColor("#1E3940") : QColor("#242C30"));
            p.drawRoundedRect(box, 8, 8);
            // Frame perforations make this read as a moving filmstrip.
            p.setPen(Qt::NoPen);
            p.setBrush(current ? rust : past ? teal : dim);
            for (int k = 0; k < 3; ++k) {
                p.drawRoundedRect(QRectF(x - 17 + k * 13, y - 20, 7, 3), 1, 1);
                p.drawRoundedRect(QRectF(x - 17 + k * 13, y + 17, 7, 3), 1, 1);
            }
            p.setPen(current ? rust : past ? teal : cream);
            QFont icon = font();
            icon.setPixelSize(21);
            icon.setBold(true);
            p.setFont(icon);
            p.drawText(QRectF(x - 20, y - 16, 40, 32), Qt::AlignCenter, QString::fromLatin1(numbers[i]));
            QFont label = font();
            label.setPixelSize(11);
            label.setBold(current);
            label.setLetterSpacing(QFont::AbsoluteSpacing, .8);
            p.setFont(label);
            p.setPen(current ? cream : past ? teal : dim);
            if (!compact)
                p.drawText(QRectF(x - 36, y + 30, 72, 19), Qt::AlignCenter, QString::fromLatin1(names[i]));
        }
        // The tiny moving spark is decorative; the filled track runs to the step under way.
        const qreal glow = .5 + .5 * qSin(m_phase);
        p.setBrush(QColor(255, 232, 202, int(70 + 80 * glow)));
        p.setPen(Qt::NoPen);
        p.drawEllipse(QPointF(head, barY), 5 + 2 * glow, 5 + 2 * glow);
    }

private:
    qreal m_target = 0;
    qreal m_shown = 0;
    qreal m_phase = 0;
    int m_stage = 0;
};

#endif // PROGRESSVIEW_H
