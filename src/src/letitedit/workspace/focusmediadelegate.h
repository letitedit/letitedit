/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef FOCUSMEDIADELEGATE_H
#define FOCUSMEDIADELEGATE_H
#include "models/playlistmodel.h"
#include <QtWidgets>

// Presentation only: the native model still owns selection, MIME data and edits.
class FocusMediaDelegate : public QStyledItemDelegate
{
public:
    explicit FocusMediaDelegate(QObject *parent) : QStyledItemDelegate(parent) {}
    QSize sizeHint(const QStyleOptionViewItem &option, const QModelIndex &) const override
    {
        return QSize(260, qMax(88, option.fontMetrics.height() * 4 + 16));
    }
    void paint(QPainter *p, const QStyleOptionViewItem &option, const QModelIndex &index) const override
    {
        p->save();
        p->setRenderHint(QPainter::Antialiasing);
        const QRect r = option.rect.adjusted(4, 3, -4, -3);
        const bool selected = option.state & QStyle::State_Selected;
        const bool hovered = option.state & QStyle::State_MouseOver;
        p->setPen(selected ? QPen(option.palette.highlight(), 1.5) : QPen(Qt::NoPen));
        p->setBrush(selected || hovered ? option.palette.alternateBase() : option.palette.base());
        p->drawRoundedRect(r, 5, 5);
        const QRect thumb(r.left() + 9, r.top() + 9, 102, r.height() - 18);
        p->setPen(Qt::NoPen);
        p->setBrush(option.palette.base());
        p->drawRoundedRect(thumb, 3, 3);
        const auto image = qvariant_cast<QImage>(index.data(PlaylistModel::FIELD_THUMBNAIL));
        if (!image.isNull()) {
            const QSize size = image.size().scaled(thumb.size(), Qt::KeepAspectRatio);
            p->drawImage(QRect(thumb.center() - QPoint(size.width() / 2, size.height() / 2), size), image);
        }
        const int x = thumb.right() + 12;
        const int width = qMax(0, r.right() - x - 10);
        QFont font = option.font;
        font.setWeight(QFont::DemiBold);
        p->setFont(font);
        p->setPen(option.palette.text().color());
        p->drawText(QRect(x, r.top() + 13, width, option.fontMetrics.height() + 4), Qt::AlignLeft | Qt::AlignVCenter,
                    QFontMetrics(font).elidedText(index.data(Qt::DisplayRole).toString().section('\n', 0, 0), Qt::ElideMiddle, width));
        font.setWeight(QFont::Normal);
        p->setFont(font);
        p->setPen(option.palette.color(QPalette::PlaceholderText));
        p->drawText(QRect(x, r.top() + 20 + option.fontMetrics.height(), width, option.fontMetrics.height() * 2), Qt::AlignLeft | Qt::AlignTop,
                    option.fontMetrics.elidedText(index.data(PlaylistModel::FIELD_MEDIA_TYPE).toString() + QStringLiteral("  ·  ")
                        + index.data(PlaylistModel::FIELD_DURATION).toString(), Qt::ElideRight, width));
        if (option.state & QStyle::State_HasFocus) {
            p->setPen(QPen(option.palette.highlight(), 1, Qt::DotLine));
            p->setBrush(Qt::NoBrush);
            p->drawRoundedRect(r.adjusted(3, 3, -3, -3), 3, 3);
        }
        p->restore();
    }
};
#endif
