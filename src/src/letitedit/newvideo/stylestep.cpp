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

// New video, step 3: Style (the kind of video), and which of its Looks suit this video.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// a Look suits the chosen format (Both and Something else suit any)
bool NewVideoDialog::kindFits(const QString &lookKind) const
{
    return lookKind.isEmpty() || lookKind == QLatin1String("both") || m_kind == QLatin1String("both")
           || m_kind == QLatin1String("custom") || lookKind == m_kind;
}

bool NewVideoDialog::routeFits(const LookChoice &look) const
{
    return look.worksWith == QLatin1String("both")
           || look.worksWith == (m_noFootage ? QLatin1String("no-footage") : QLatin1String("footage"));
}

// the Looks of a Style that this video can use: not cut, for this route and this format
QList<const LookChoice *> NewVideoDialog::offeredLooks(const LookStyle &style) const
{
    QList<const LookChoice *> list;
    for (int pass = 0; pass < 2; ++pass) // the catalogue's own first, then the person's
        for (const auto &look : style.looks)
            if (look.personal == (pass == 1) && (!look.cut || m_review) && routeFits(look) && kindFits(look.kind))
                list << &look;
    return list;
}

// Looks of the Style that work with this route at all, in any format: the formats they support
QSet<QString> NewVideoDialog::styleFormats(const LookStyle &style) const
{
    QSet<QString> formats;
    for (const auto &look : style.looks) {
        if (look.cut || !routeFits(look))
            continue;
        if (look.kind == QLatin1String("both") || look.kind.isEmpty()) {
            formats << QStringLiteral("short") << QStringLiteral("long");
        } else {
            formats << look.kind;
        }
    }
    return formats;
}

// a Look that only suits the other format is let go when the format changes
void NewVideoDialog::dropLookForFormat()
{
    if (m_look == QLatin1String("auto") || m_look == QLatin1String("pending-learn"))
        return;
    const LookStyle *style = lookStyle(m_style);
    const LookChoice *look = style ? findLook(*style, m_look) : nullptr;
    if (look && !kindFits(look->kind)) {
        m_lookNote = tr("%1 is for %2 only, so it's no longer chosen.")
                         .arg(look->label, look->kind == QLatin1String("short") ? tr("Shorts") : tr("YouTube videos"));
        m_look = QStringLiteral("auto");
        m_theme = QStringLiteral("freestyle");
        m_themeChosen = false;
    }
}

QWidget *NewVideoDialog::styleChoicePage()
{
    QVBoxLayout *column = nullptr;
    auto w = page(tr("Pick a style"), tr("The kind of video to make."), &column);
    m_stylePickLead = w->findChild<QLabel *>(QStringLiteral("newVideoLead"));
    auto scroll = new QScrollArea(w);
    scroll->setObjectName(QStringLiteral("newVideoStyleChoices"));
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    m_styleChoiceBody = new QWidget(scroll);
    m_styleChoiceGrid = new QGridLayout(m_styleChoiceBody);
    m_styleChoiceGrid->setSpacing(12);
    m_styleChoiceGrid->setContentsMargins(0, 0, 8, 0);
    scroll->setWidget(m_styleChoiceBody);
    column->addWidget(scroll, 1);
    m_styleChoiceGroup = new QButtonGroup(this);
    return w;
}

void NewVideoDialog::chooseStyle(const QString &id)
{
    m_style = id;
    m_browseStyle = id;
    m_look = QStringLiteral("auto");
    m_theme = QStringLiteral("freestyle");
    m_themeChosen = false;
    m_personChose = true;
    m_styleExplicit = true;
    m_lookNote.clear();
    m_problem->hide();
}

void NewVideoDialog::fillStyleChoices()
{
    if (!m_styleChoiceGrid)
        return;
    m_filling = true;
    clearLayout(m_styleChoiceGrid, [this](QWidget *widget) {
        if (auto button = qobject_cast<QAbstractButton *>(widget))
            m_styleChoiceGroup->removeButton(button);
    });
    m_stylePickLead->setText(m_noFootage ? tr("100% AI: the kind of video your AI makes from scratch.")
                                         : tr("The kind of video your AI makes from your footage."));
    QList<const LookStyle *> list;
    for (const auto &style : std::as_const(m_lookStyles)) {
        const bool ai = style.footage == QLatin1String("no");
        if (style.hidden || (style.cut && !m_review) || ai != m_noFootage)
            continue;
        if (style.looks.isEmpty() && !m_review)
            continue;
        list << &style;
    }
    // a Style that suits this format first; the one chosen stays if it still can be used
    const auto usable = [this](const LookStyle *style) { return !offeredLooks(*style).isEmpty(); };
    const LookStyle *chosen = lookStyle(m_style);
    if (!chosen || !list.contains(chosen) || !usable(chosen)) {
        QString first;
        for (const LookStyle *style : std::as_const(list))
            if (usable(style)) {
                first = style->id;
                break;
            }
        if (first.isEmpty()) {
            m_style = QStringLiteral("none");
        } else {
            chooseStyle(first);
        }
    }
    const QSize pictureSize(170, 104);
    const QString moreLine = tr("Travel, build and more, as they pass our tests.");
    int descriptionHeight = m_noFootage ? 18 : cardTextHeight(moreLine, pictureSize.width());
    for (const LookStyle *style : std::as_const(list))
        descriptionHeight = qMax(descriptionHeight, cardTextHeight(style->line, pictureSize.width()));
    const int cardHeight = 190 + descriptionHeight;
    const int columns = qMax(2, (m_pages->width() - 60) / (pictureSize.width() + 2 * LookCard::kCardMargin + 12));
    int index = 0;
    const auto place = [&](QWidget *card) {
        m_styleChoiceGrid->addWidget(card, index / columns, index % columns, Qt::AlignTop | Qt::AlignLeft);
        ++index;
    };
    for (const LookStyle *style : std::as_const(list)) {
        QString clip, poster;
        for (const auto &look : style->looks)
            if (!look.preview.isEmpty() && QFileInfo::exists(look.preview) && routeFits(look)) {
                clip = look.preview;
                poster = look.poster;
                break;
            }
        const bool can = !style->cut && (usable(style) || (m_review && style->looks.isEmpty()));
        auto card = new LookCard(style->id, style->label, style->line, clip, poster,
                                 framedPicture(placeholderPicture(style->label, false), pictureSize), pictureSize,
                                 lookPlayback(list.size() + 6), m_styleChoiceBody);
        card->setObjectName(QStringLiteral("newVideoStyleCard_%1").arg(style->id));
        card->setProperty("styleCard", style->id);
        card->setFixedHeight(cardHeight);
        if (auto title = card->findChild<QLabel *>(QStringLiteral("newVideoCardTitle")))
            title->setFixedHeight(36);
        if (auto description = card->findChild<QLabel *>(QStringLiteral("newVideoCardText"))) {
            description->setWordWrap(true);
            description->setFixedHeight(descriptionHeight);
        }
        if (!can && !style->cut) {
            const QSet<QString> formats = styleFormats(*style);
            const QString word = formats.contains(QStringLiteral("long")) && !formats.contains(QStringLiteral("short")) ? tr("YouTube only for now")
                                 : formats.contains(QStringLiteral("short")) && !formats.contains(QStringLiteral("long")) ? tr("Short only for now")
                                                                                                                       : tr("Not available yet");
            card->setBadge(word);
            card->setEnabled(false);
            card->setToolTip(tr("%1: %2").arg(style->line, word));
        }
        m_styleChoiceGroup->addButton(card);
        card->setChecked(can && style->id == m_style);
        connect(card, &QPushButton::toggled, this, [this, id = style->id](bool on) {
            if (on && !m_filling)
                chooseStyle(id);
        });
        auto tile = new QWidget(m_styleChoiceBody);
        auto tileColumn = new QVBoxLayout(tile);
        tileColumn->setContentsMargins(0, 0, 0, 0);
        tileColumn->addWidget(card);
        auto reviewRow = new QHBoxLayout;
        tileColumn->addLayout(reviewRow);
        addReviewButtons(reviewRow, QStringLiteral("style"), style->id, style->review, style->cut);
        place(tile);
    }
    if (!m_noFootage) {
        auto more = new LookCard(QStringLiteral("more-styles"), tr("More styles coming"),
                                 moreLine, QString(), QString(),
                                 framedPicture(placeholderPicture(tr("More styles coming"), false), pictureSize), pictureSize,
                                 LookCard::WhenHovered, m_styleChoiceBody);
        more->setObjectName(QStringLiteral("newVideoStyleCard_more"));
        more->setFixedHeight(cardHeight);
        more->setCheckable(false);
        more->setEnabled(false);
        if (auto title = more->findChild<QLabel *>(QStringLiteral("newVideoCardTitle")))
            title->setFixedHeight(36);
        if (auto description = more->findChild<QLabel *>(QStringLiteral("newVideoCardText"))) {
            description->setWordWrap(true);
            description->setFixedHeight(descriptionHeight);
        }
        place(more);
    }
    for (int c = 0; c <= columns; ++c)
        m_styleChoiceGrid->setColumnStretch(c, c == columns ? 1 : 0); // the cards sit together on the left
    m_styleChoiceGrid->setRowStretch(index / columns + 1, 1);
    m_filling = false;
}

} // namespace NewVideo
