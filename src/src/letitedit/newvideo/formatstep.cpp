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

// New video, step 1: Format (Short or YouTube).
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// ---- Format and Content (T164) -----------------------------------------------------------------------------------
// A Short is tall and a YouTube video wide: the card shows which
QPixmap NewVideoDialog::formatPicture(bool vertical)
{
    const QSize size(120, 64);
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(Qt::NoPen);
    p.setBrush(QColor(vertical ? LetItEditColors::rust : LetItEditColors::teal));
    const QSizeF shape = vertical ? QSizeF(34, 58) : QSizeF(88, 50);
    p.drawRoundedRect(QRectF((size.width() - shape.width()) / 2, (size.height() - shape.height()) / 2, shape.width(), shape.height()), 7, 7);
    return pixmap;
}

QWidget *NewVideoDialog::formatPage()
{
    QVBoxLayout *column = nullptr;
    auto w = page(tr("What are you making?"), tr("You can make another version later from the same project."), &column);
    makeParts(w);
    auto row = new QHBoxLayout;
    row->setSpacing(14);
    for (auto b : m_kinds->buttons())
        if (b->property("kind").toString() == QLatin1String("short") || b->property("kind").toString() == QLatin1String("long"))
            row->addWidget(b, 1);
    column->addLayout(row);
    column->addStretch(1);
    return w;
}

} // namespace NewVideo
