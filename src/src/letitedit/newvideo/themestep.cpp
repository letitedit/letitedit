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

// New video, step 5: Theme (how it is drawn).
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

#include <cmath>

namespace NewVideo {

// Ready, as it stands now: built each time it is shown, so Back and Change Look land on what is true
// A Look with its own Theme (one the person learned) keeps it until the person chooses another. The Theme step sets this
// when it is seen; a stage button can jump past it (T167), so Go and the request settle it too.
void NewVideoDialog::settleTheme()
{
    if (!m_themeChosen && !ownTheme(chosenLookCard()).isEmpty())
        m_theme = QStringLiteral("none");
}

bool NewVideoDialog::themeFits(const QJsonObject &theme, const LookStyle *style, const LookChoice *look) const
{
    if (!style || style->cut || theme.value("cut").toBool())
        return false;
    if (!look) {
        if (m_look == QLatin1String("freestyle")) { // no set Look: any kit or film Theme not kept to other Styles or Looks
            const QString kind = theme.value("kind").toString();
            const QJsonArray styles = theme.value("styles").toArray();
            return !theme.value("personal").toBool() && (kind == QLatin1String("kit") || kind == QLatin1String("film"))
                   && theme.value("looks").toArray().isEmpty() && (styles.isEmpty() || styles.contains(style->id));
        }
        if (m_look == QLatin1String("auto")) // the Looks under the tab it picks from (T179)
            for (const auto &shown : pickLooks())
                if (!shown.second->cut && themeFits(theme, shown.first, shown.second))
                    return true;
        for (const auto &choice : style->looks)
            if (!choice.cut && themeFits(theme, style, &choice))
                return true;
        return false;
    }
    if (theme.value("personal").toBool())
        return theme.value("looks").toArray().contains(look->id);
    const QString kind = theme.value("kind").toString();
    if (!(look->themes == QLatin1String("kits") && kind == QLatin1String("kit"))
        && !(look->themes == QLatin1String("film") && kind == QLatin1String("film")))
        return false;
    const auto matches = [](const QJsonArray &ids, const QString &id) {
        return ids.isEmpty() || ids.contains(id) || (id == QLatin1String("idea") && ids.contains(QStringLiteral("made-with-code")));
    };
    return matches(theme.value("styles").toArray(), style->id) && matches(theme.value("looks").toArray(), look->id);
}

// ---- Theme ------------------------------------------------------------------------------------------------------
// a Look the person learned has its own Theme (the one it was learned with)
QJsonObject NewVideoDialog::ownTheme(const LookChoice *look) const
{
    if (!look || !look->personal)
        return {};
    for (const auto &value : m_themes) {
        const QJsonObject theme = value.toObject();
        if (theme.value("personal").toBool() && !theme.value("cut").toBool() && theme.value("looks").toArray().contains(look->id))
            return theme;
    }
    return {};
}

namespace {

QJsonObject themeEntry(const QJsonObject &theme)
{
    return QJsonObject{{"id", theme.value("id").toString()},
                       {"title", theme.value("title").toString()},
                       {"recipe", theme.value("recipe").toString()},
                       {"recipe_shared", theme.value("recipe_shared").toString()}};
}

// what the request says about a resolved Theme choice (bridge/letitedit/app/new_video_request.py renders the same)
QString themeText(const QJsonObject &choice)
{
    const QJsonObject own = choice.value("own").toObject();
    const QString ownId = own.value("id").toString();
    const QString mode = choice.value("mode").toString();
    const QString keep = ownId.isEmpty() ? QString()
                         : QStringLiteral("\nTheme: none chosen. Keep this Look as learned; its own theme file (%1) is part of the Look.\n")
                               .arg(own.value("recipe").toString());
    if (mode == QLatin1String("none"))
        return keep;
    const QString replaces = QStringLiteral("A Theme you choose replaces the Look's own surface (grade, lighting mood, texture, palette "
                                            "and drawn elements) completely; the Look keeps its structure and timing.");
    if (mode == QLatin1String("pick")) {
        // Let the AI pick: one of the Themes shown for this Look, named with its reasons
        QStringList shown;
        for (const auto &value : choice.value("shown").toArray()) {
            const auto theme = value.toObject();
            QString one = QStringLiteral("%1 (%2), recipe: %3").arg(theme.value("title").toString(), theme.value("id").toString(),
                                                                   theme.value("recipe").toString());
            if (!theme.value("recipe_shared").toString().isEmpty())
                one += QStringLiteral(", shared: %1").arg(theme.value("recipe_shared").toString());
            shown << one;
        }
        if (!shown.isEmpty())
            return QStringLiteral("\nTheme: pick. Choose one of the Themes I was shown for this Look, read its recipe, and tell me which "
                                  "you chose and why before you start: %1.%2\n")
                .arg(shown.join(QStringLiteral("; ")), ownId.isEmpty() ? QString() : QStringLiteral(" ") + replaces);
    }
    if (mode == QLatin1String("freestyle") || mode == QLatin1String("pick")) {
        // Freestyle: no set Theme; how it is drawn or filmed is the AI's own call, and none is fine
        if (ownId.isEmpty())
            return QStringLiteral("\nTheme: Freestyle (freestyle). No set Theme: decide how the video is drawn or filmed your own way; "
                                  "using no Theme is fine.\n");
        return QStringLiteral("\nTheme: Freestyle (freestyle). This Look has its own colours and lighting (its theme file %1 is part of "
                              "the Look); keep them unless another treatment clearly suits this video better. %2\n")
            .arg(own.value("recipe").toString(), replaces);
    }
    QString text;
    for (const auto &value : choice.value("chosen").toArray()) {
        const auto theme = value.toObject();
        text += QStringLiteral("\nTheme: %1 (%2); recipe: %3")
                    .arg(theme.value("title").toString(), mode, theme.value("recipe").toString());
        if (!theme.value("recipe_shared").toString().isEmpty())
            text += QStringLiteral("; shared: %1").arg(theme.value("recipe_shared").toString());
        text += QLatin1Char('\n');
    }
    if (text.isEmpty())
        return keep; // a Theme that is no longer in the catalogue: nothing to replace the Look's own with
    if (!ownId.isEmpty())
        text += QStringLiteral("\nThis Theme replaces the Look's own surface (grade, lighting mood, texture, palette and drawn elements) "
                               "completely: don't read or use the Look's own theme file. The Look keeps its structure and timing.\n");
    return text;
}

} // namespace

// The Theme choice as resolved when Go is pressed: one Theme at most. A Theme chosen replaces the Look's own surface (grade,
// lighting mood, texture, palette, drawn elements); the Look keeps its structure and timing. "No Theme" keeps a Look as it was
// learned. `shown` is what Let the AI pick picks from; `chosen` the catalogue's entries for a named Theme (T331 P4).
QJsonObject NewVideoDialog::themeChoice(const LookChoice *look) const
{
    const QJsonObject own = ownTheme(look);
    const QString ownId = own.value("id").toString();
    QJsonObject choice{{"mode", m_theme}};
    if (!ownId.isEmpty())
        choice.insert("own", QJsonObject{{"id", ownId}, {"recipe", own.value("recipe").toString()}});
    QJsonArray shown, chosen;
    if (m_theme == QLatin1String("pick")) {
        const LookStyle *style = lookStyle(m_style) ? lookStyle(m_style) : lookStyle(tabStyleFor()); // the Look step skipped: the tab's Style
        for (const auto &value : m_themes) {
            const auto theme = value.toObject();
            if (themeFits(theme, style, look) && theme.value("id").toString() != ownId)
                shown << themeEntry(theme);
        }
    } else if (m_theme != QLatin1String("none") && m_theme != QLatin1String("freestyle")) {
        for (const auto &value : m_themes) {
            const auto theme = value.toObject();
            if (theme.value("id").toString() == m_theme)
                chosen << themeEntry(theme);
        }
    }
    choice.insert("shown", shown);
    choice.insert("chosen", chosen);
    return choice;
}

// what the request says about the Theme
QString NewVideoDialog::themeRequest(const LookChoice *look) const
{
    return themeText(themeChoice(look));
}

// ---- Theme cards (T176) ------------------------------------------------------------------------------------------
// Every Theme is a trading card: a frame that suits its family, its name, its picture and a short line. The cards start
// small; the one under the pointer (or with keyboard focus) grows and its neighbours ease up a little and shift away,
// like a dock. The movement follows Windows' "Show animations" setting (off: the cards change size at once, no motion).
namespace {

enum class CardFamily { Choice, Drawn, Print, Film, Yours };

CardFamily familyOf(const QJsonObject &theme)
{
    if (theme.value("personal").toBool())
        return CardFamily::Yours;
    if (theme.value("kind").toString() == QLatin1String("film"))
        return CardFamily::Film;
    if (theme.value("folder").toString().startsWith(QLatin1String("Print")))
        return CardFamily::Print;
    return CardFamily::Drawn;
}

bool animationsOn()
{
    if (qEnvironmentVariable("LETITEDIT_REDUCED_MOTION") == QLatin1String("1"))
        return false;
#ifdef Q_OS_WIN
    BOOL on = TRUE;
    if (SystemParametersInfoW(SPI_GETCLIENTAREAANIMATION, 0, &on, 0))
        return on != FALSE;
#endif
    return true;
}

class ThemeCard : public QAbstractButton
{
public:
    static constexpr qreal kW = 132, kH = 212; // the card's own drawing units; it is painted scaled to its size

    ThemeCard(const QString &id, const QString &title, const QString &line, const QString &tag, CardFamily family,
              const QPixmap &picture, QWidget *parent)
        : QAbstractButton(parent)
        , m_title(title)
        , m_line(line)
        , m_tag(tag)
        , m_family(family)
    {
        setObjectName(QStringLiteral("newVideoTheme_%1").arg(id));
        setCheckable(true);
        setCursor(Qt::PointingHandCursor);
        setFocusPolicy(Qt::StrongFocus);
        setAttribute(Qt::WA_Hover);
        setMouseTracking(true);
        setAccessibleName(title);
        setAccessibleDescription(tag.isEmpty() ? line : QStringLiteral("%1. %2").arg(tag, line));
        setToolTip(line);
        // the picture once, at the largest size it is drawn (grown, on a high-density screen)
        const qreal ratio = qMax<qreal>(1.0, qApp->devicePixelRatio()) * 1.3;
        const QSize window = (QSizeF(pictureRect().size()) * ratio).toSize();
        if (!picture.isNull()) {
            const QPixmap cover = picture.scaled(window, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation);
            m_picture = cover.copy((cover.width() - window.width()) / 2, (cover.height() - window.height()) / 2, window.width(),
                                   window.height());
        }
        // the words, for tests and screen readers (the card itself is painted)
        const auto hidden = [this](const QString &name, const QString &text) {
            auto label = new QLabel(text, this);
            label->setObjectName(name);
            label->setGeometry(0, 0, 1, 1);
            label->setAttribute(Qt::WA_TransparentForMouseEvents);
            label->setStyleSheet(QStringLiteral("color: transparent; background: transparent;"));
        };
        hidden(QStringLiteral("newVideoThemeTitle_%1").arg(id), title);
        if (!tag.isEmpty())
            hidden(QStringLiteral("newVideoThemeTag_%1").arg(id), tag);
        if (id == QLatin1String("none") || id == QLatin1String("freestyle") || id == QLatin1String("pick"))
            hidden(QStringLiteral("newVideoThemeNote_%1").arg(id), line);
    }

    static QRectF pictureRect() { return QRectF(9, 31, kW - 18, 116); }
    static QSize baseSize() { return QSize(int(kW), int(kH)); }

protected:
    void paintEvent(QPaintEvent *) override
    {
        QPainter p(this);
        p.setRenderHint(QPainter::Antialiasing);
        p.setRenderHint(QPainter::SmoothPixmapTransform);
        p.setRenderHint(QPainter::TextAntialiasing);
        p.scale(width() / kW, height() / kH);
        const bool hot = underMouse() || hasFocus();
        QColor frame, edge, text, sub;
        QString familyName;
        switch (m_family) {
        case CardFamily::Choice:
            frame = QColor(LetItEditColors::tealDeep), edge = QColor(LetItEditColors::tealLight), text = QColor(LetItEditColors::cream),
            sub = QColor(LetItEditColors::tealLight), familyName = tr("letitedit");
            break;
        case CardFamily::Drawn:
            frame = QColor(LetItEditColors::cream), edge = QColor(LetItEditColors::rust), text = QColor(LetItEditColors::ink),
            sub = QColor(QStringLiteral("#5B544B")), familyName = tr("Drawn");
            break;
        case CardFamily::Print:
            frame = QColor(LetItEditColors::ink), edge = QColor(QStringLiteral("#C9A24A")), text = QColor(LetItEditColors::cream),
            sub = QColor(QStringLiteral("#D9C38C")), familyName = tr("Print & light");
            break;
        case CardFamily::Film:
            frame = QColor(QStringLiteral("#0B0D0E")), edge = QColor(QStringLiteral("#8A949B")), text = QColor(LetItEditColors::cream),
            sub = QColor(LetItEditColors::muted), familyName = tr("Film");
            break;
        case CardFamily::Yours:
            frame = QColor(QStringLiteral("#1F3A33")), edge = QColor(LetItEditColors::ok), text = QColor(LetItEditColors::cream),
            sub = QColor(LetItEditColors::ok), familyName = tr("Yours");
            break;
        }
        const QRectF outer(1, 1, kW - 2, kH - 2);
        p.setPen(Qt::NoPen);
        p.setBrush(frame);
        p.drawRoundedRect(outer, 10, 10);
        // the inner rule of a trading card
        p.setPen(QPen(edge, hot ? 1.6 : 1.1));
        p.setBrush(Qt::NoBrush);
        p.drawRoundedRect(outer.adjusted(3.5, 3.5, -3.5, -3.5), 7, 7);
        // name band
        // the whole name: a size smaller for a long one, and two lines when even that is too wide (never cut with "...")
        QFont f = font();
        f.setBold(true);
        const QRectF nameRect(10, 9, kW - 34, 18);
        int pixels = 11;
        for (; pixels > 9; --pixels) {
            f.setPixelSize(pixels);
            if (QFontMetricsF(f).horizontalAdvance(m_title) <= nameRect.width())
                break;
        }
        f.setPixelSize(pixels);
        p.setFont(f);
        p.setPen(text);
        if (QFontMetricsF(f).horizontalAdvance(m_title) <= nameRect.width())
            p.drawText(nameRect, Qt::AlignLeft | Qt::AlignVCenter, m_title);
        else
            p.drawText(QRectF(10, 5, kW - 34, 25), Qt::AlignLeft | Qt::AlignVCenter | Qt::TextWordWrap, m_title);
        // the family's mark, top right
        p.setPen(Qt::NoPen);
        p.setBrush(edge);
        p.drawEllipse(QRectF(kW - 23, 11, 13, 13));
        // picture window
        const QRectF window = pictureRect();
        QPainterPath clip;
        clip.addRoundedRect(window, 4, 4);
        p.save();
        p.setClipPath(clip);
        if (!m_picture.isNull())
            p.drawPixmap(window, m_picture, QRectF(m_picture.rect()));
        else {
            p.fillRect(window, QColor(LetItEditColors::deep));
        }
        p.restore();
        p.setPen(QPen(QColor(0, 0, 0, 90), 1));
        p.setBrush(Qt::NoBrush);
        p.drawRoundedRect(window, 4, 4);
        // the tag (Default, Recommended) as a ribbon over the picture
        if (!m_tag.isEmpty()) {
            QFont t = font();
            t.setPixelSize(9);
            t.setBold(true);
            const qreal w = QFontMetricsF(t).horizontalAdvance(m_tag) + 12;
            const QRectF pill(window.left() + 4, window.top() + 4, w, 15);
            p.setPen(Qt::NoPen);
            p.setBrush(m_tag == tr("Recommended") ? QColor(LetItEditColors::rust) : QColor(LetItEditColors::tealDeep));
            p.drawRoundedRect(pill, 7.5, 7.5);
            p.setFont(t);
            p.setPen(QColor(LetItEditColors::cream));
            p.drawText(pill, Qt::AlignCenter, m_tag);
        }
        // the short line
        QFont l = font();
        l.setPixelSize(9);
        p.setFont(l);
        p.setPen(sub);
        p.drawText(QRectF(11, window.bottom() + 5, kW - 22, 40), Qt::AlignLeft | Qt::AlignTop | Qt::TextWordWrap, m_line);
        // footer: the family's name, and a film strip's holes for film Themes
        QFont small = font();
        small.setPixelSize(8);
        small.setBold(true);
        small.setLetterSpacing(QFont::AbsoluteSpacing, 0.8);
        p.setFont(small);
        p.setPen(edge);
        const QRectF footer(11, kH - 20, kW - 22, 12);
        if (m_family == CardFamily::Film) {
            p.setPen(Qt::NoPen);
            p.setBrush(QColor(QStringLiteral("#3A4247")));
            for (qreal x = 11; x < kW - 14; x += 9)
                p.drawRoundedRect(QRectF(x, footer.top() + 2, 5, 7), 1.2, 1.2);
        } else {
            p.drawText(footer, Qt::AlignLeft | Qt::AlignVCenter, familyName.toUpper());
        }
        // chosen: a teal ring round the whole card and a tick in the corner
        if (isChecked()) {
            p.setPen(QPen(QColor(LetItEditColors::teal), 4));
            p.setBrush(Qt::NoBrush);
            p.drawRoundedRect(outer.adjusted(1, 1, -1, -1), 9, 9);
            const QRectF bubble(kW - 30, kH - 30, 22, 22);
            p.setPen(QPen(QColor(LetItEditColors::cream), 1.5));
            p.setBrush(QColor(LetItEditColors::teal));
            p.drawEllipse(bubble);
            QPainterPath tick;
            tick.moveTo(bubble.left() + 6, bubble.top() + 11.5);
            tick.lineTo(bubble.left() + 9.5, bubble.top() + 15);
            tick.lineTo(bubble.left() + 16, bubble.top() + 7.5);
            p.setPen(QPen(QColor(LetItEditColors::cream), 2.2, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin));
            p.drawPath(tick);
        } else if (hasFocus()) {
            p.setPen(QPen(QColor(LetItEditColors::cream), 1.5, Qt::DashLine));
            p.setBrush(Qt::NoBrush);
            p.drawRoundedRect(outer.adjusted(1, 1, -1, -1), 9, 9);
        }
    }

    bool hitButton(const QPoint &pos) const override { return rect().contains(pos); }

private:
    QString m_title, m_line, m_tag;
    CardFamily m_family;
    QPixmap m_picture;
};

// The grid of cards and headings, with the dock-like hover
class ThemeDeck : public QWidget
{
public:
    explicit ThemeDeck(QWidget *parent)
        : QWidget(parent)
    {
        setObjectName(QStringLiteral("newVideoThemeDeck"));
        setMouseTracking(true);
        m_tick = new QTimer(this);
        m_tick->setInterval(16);
        connect(m_tick, &QTimer::timeout, this, [this]() { step(); });
        // for tests: the card that is grown now and how much, and whether the movement is animated
        m_state = new QLabel(this);
        m_state->setObjectName(QStringLiteral("newVideoThemeDeckState"));
        m_state->setGeometry(0, 0, 1, 1);
        m_state->setAttribute(Qt::WA_TransparentForMouseEvents);
        m_state->setStyleSheet(QStringLiteral("color: transparent; background: transparent;"));
        m_animate = animationsOn();
    }

    void clear()
    {
        for (auto &item : m_items)
            if (item.widget)
                item.widget->deleteLater();
        m_items.clear();
        m_pointer = QPointF(-1, -1);
        m_hasPointer = false;
    }

    void addHeading(QWidget *heading) { add(heading, true, false); }
    void addCard(QWidget *card, bool grows)
    {
        add(card, false, grows);
        card->installEventFilter(this);
        card->setMouseTracking(true);
    }

    void relayout()
    {
        const QSize card = ThemeCard::baseSize();
        const int usable = qMax(card.width(), width() - 2 * kPad);
        m_columns = qMax(1, (usable + kGapX) / (card.width() + kGapX));
        int x = 0, y = kPad, column = 0;
        int rowHeight = 0;
        for (auto &item : m_items) {
            if (!item.widget)
                continue;
            if (item.heading) {
                if (column) {
                    y += rowHeight + kGapY;
                    column = 0;
                }
                const int h = item.widget->sizeHint().height();
                item.base = QRectF(kPad, y, width() - 2 * kPad, h);
                y += h + 8;
                rowHeight = 0;
                continue;
            }
            const QSize size = item.grows ? card : item.widget->sizeHint().expandedTo(card);
            x = kPad + column * (card.width() + kGapX);
            item.base = QRectF(x, y, size.width(), size.height());
            rowHeight = qMax(rowHeight, size.height());
            if (++column == m_columns) {
                column = 0;
                y += rowHeight + kGapY;
                rowHeight = 0;
            }
        }
        if (column)
            y += rowHeight + kGapY;
        setMinimumHeight(y + kPad);
        targets();
        for (auto &item : m_items)
            place(item);
    }

    // a card's index in the grid, to move between cards with the arrow keys
    QWidget *neighbour(QWidget *from, int dx, int dy) const
    {
        QList<const Item *> cards;
        for (const auto &item : m_items)
            if (!item.heading && item.widget)
                cards << &item;
        int at = -1;
        for (int i = 0; i < cards.size(); ++i)
            if (cards[i]->widget == from)
                at = i;
        if (at < 0)
            return nullptr;
        if (dx)
            return cards.value(at + dx) ? cards.value(at + dx)->widget.data() : nullptr;
        // up or down: the nearest card in the row above or below, by the middle of its cell
        const QPointF centre = cards[at]->base.center();
        const Item *best = nullptr;
        qreal bestScore = 1e9;
        for (const Item *other : std::as_const(cards)) {
            const qreal dyc = other->base.center().y() - centre.y();
            if ((dy > 0 && dyc <= 4) || (dy < 0 && dyc >= -4))
                continue;
            const qreal score = qAbs(dyc) * 4 + qAbs(other->base.center().x() - centre.x());
            if (score < bestScore) {
                bestScore = score;
                best = other;
            }
        }
        return best ? best->widget.data() : nullptr;
    }

protected:
    void resizeEvent(QResizeEvent *event) override
    {
        QWidget::resizeEvent(event);
        if (event->size().width() != event->oldSize().width())
            relayout();
    }

    void mouseMoveEvent(QMouseEvent *event) override
    {
        pointAt(event->position());
        QWidget::mouseMoveEvent(event);
    }

    void leaveEvent(QEvent *event) override
    {
        m_hasPointer = false;
        targets();
        QWidget::leaveEvent(event);
    }

    bool eventFilter(QObject *watched, QEvent *event) override
    {
        auto widget = qobject_cast<QWidget *>(watched);
        switch (event->type()) {
        case QEvent::MouseMove:
            pointAt(widget->mapTo(this, static_cast<QMouseEvent *>(event)->position()));
            break;
        case QEvent::HoverMove:
            pointAt(widget->mapTo(this, static_cast<QHoverEvent *>(event)->position()));
            break;
        case QEvent::FocusIn:
        case QEvent::FocusOut:
            targets();
            if (event->type() == QEvent::FocusIn)
                if (auto scroll = scrollArea())
                    scroll->ensureWidgetVisible(widget, 30, 40);
            break;
        case QEvent::KeyPress: {
            const int key = static_cast<QKeyEvent *>(event)->key();
            const int dx = key == Qt::Key_Left ? -1 : key == Qt::Key_Right ? 1 : 0;
            const int dy = key == Qt::Key_Up ? -1 : key == Qt::Key_Down ? 1 : 0;
            if (dx || dy) {
                if (auto next = neighbour(widget, dx, dy))
                    next->setFocus(Qt::TabFocusReason);
                return true;
            }
            break;
        }
        default:
            break;
        }
        return QWidget::eventFilter(watched, event);
    }

private:
    static constexpr int kPad = 22, kGapX = 16, kGapY = 20;
    static constexpr qreal kGrow = 0.24;  // the card under the pointer: 24% bigger
    static constexpr qreal kReach = 0.75; // how far (in cells) the growth reaches its neighbours
    static constexpr qreal kShift = 9;    // how far a neighbour moves away, in pixels

    struct Item
    {
        QPointer<QWidget> widget;
        bool heading = false;
        bool grows = false;
        QRectF base;
        qreal scale = 1, scaleTarget = 1;
        QPointF offset, offsetTarget;
    };

    void add(QWidget *widget, bool heading, bool grows)
    {
        widget->setParent(this);
        Item item;
        item.widget = widget;
        item.heading = heading;
        item.grows = grows;
        m_items << item;
        widget->show();
    }

    QScrollArea *scrollArea() const
    {
        for (QWidget *up = parentWidget(); up; up = up->parentWidget())
            if (auto scroll = qobject_cast<QScrollArea *>(up))
                return scroll;
        return nullptr;
    }

    void pointAt(const QPointF &position)
    {
        m_pointer = position;
        m_hasPointer = true;
        targets();
    }

    // where every card wants to be: grown and pushed by its distance from the pointer (or the focused card)
    void targets()
    {
        QPointF focus;
        bool any = m_hasPointer;
        if (any)
            focus = m_pointer;
        else
            for (const auto &item : std::as_const(m_items))
                if (item.widget && !item.heading && item.widget->hasFocus()) {
                    focus = item.base.center();
                    any = true;
                }
        const QSizeF cell(ThemeCard::kW + kGapX, ThemeCard::kH + kGapY);
        for (auto &item : m_items) {
            item.scaleTarget = 1;
            item.offsetTarget = QPointF();
            if (!any || item.heading || !item.grows || !item.widget)
                continue;
            const QPointF d((item.base.center().x() - focus.x()) / cell.width(), (item.base.center().y() - focus.y()) / cell.height());
            const qreal distance = std::hypot(d.x(), d.y());
            const qreal pull = std::exp(-(distance * distance) / (2 * kReach * kReach));
            item.scaleTarget = 1 + kGrow * pull;
            if (distance > 0.001)
                item.offsetTarget = QPointF(d.x() / distance, d.y() / distance) * kShift * pull * qMin<qreal>(1.0, distance * 1.6);
        }
        if (!m_animate) {
            for (auto &item : m_items) {
                item.scale = item.scaleTarget;
                item.offset = item.offsetTarget;
                place(item);
            }
            report();
        } else if (!m_tick->isActive()) {
            m_tick->start();
        }
    }

    // one frame of the easing: each card moves a fifth of the way to where it wants to be
    void step()
    {
        bool moving = false;
        for (auto &item : m_items) {
            if (item.heading || !item.widget)
                continue;
            const qreal ds = item.scaleTarget - item.scale;
            const QPointF dp = item.offsetTarget - item.offset;
            if (qAbs(ds) < 0.002 && qAbs(dp.x()) < 0.2 && qAbs(dp.y()) < 0.2) {
                if (item.scale != item.scaleTarget || item.offset != item.offsetTarget) {
                    item.scale = item.scaleTarget;
                    item.offset = item.offsetTarget;
                    place(item);
                }
                continue;
            }
            moving = true;
            item.scale += ds * 0.2;
            item.offset += dp * 0.2;
            place(item);
        }
        report();
        if (!moving)
            m_tick->stop();
    }

    void place(Item &item)
    {
        if (!item.widget)
            return;
        if (item.heading || !item.grows) {
            item.widget->setGeometry(item.base.toRect());
            return;
        }
        const QSizeF size = item.base.size() * item.scale;
        const QPointF centre = item.base.center() + item.offset;
        item.widget->setGeometry(QRectF(centre.x() - size.width() / 2, centre.y() - size.height() / 2, size.width(), size.height()).toRect());
    }

    // the biggest card on top, and a line for tests
    void report()
    {
        const Item *top = nullptr;
        for (const auto &item : std::as_const(m_items))
            if (!item.heading && item.widget && (!top || item.scale > top->scale))
                top = &item;
        if (top && top->scale > 1.01 && top->widget != m_raised) {
            top->widget->raise();
            m_raised = top->widget;
        }
        m_state->raise();
        m_state->setText(QStringLiteral("hover=%1 scale=%2 animated=%3")
                             .arg(top && top->scale > 1.01 ? top->widget->objectName().section(QLatin1Char('_'), 1) : QStringLiteral("none"))
                             .arg(top ? top->scale : 1.0, 0, 'f', 2)
                             .arg(m_animate ? 1 : 0));
    }

    QList<Item> m_items;
    int m_columns = 1;
    QPointF m_pointer;
    bool m_hasPointer = false;
    bool m_animate = true;
    QTimer *m_tick = nullptr;
    QLabel *m_state = nullptr;
    QPointer<QWidget> m_raised;
};

// the picture of "No Theme: keep this Look as learned": the Look's own colours, kept
QPixmap keepPicture(const QSize &size)
{
    QPixmap picture(size);
    picture.fill(QColor(LetItEditColors::tealDeep));
    QPainter p(&picture);
    p.setRenderHint(QPainter::Antialiasing);
    const QList<QColor> swatches{QColor(LetItEditColors::rust), QColor(LetItEditColors::cream), QColor(LetItEditColors::teal)};
    const qreal r = size.width() * 0.13;
    for (int i = 0; i < swatches.size(); ++i) {
        p.setPen(QPen(QColor(LetItEditColors::deep), 2));
        p.setBrush(swatches[i]);
        p.drawEllipse(QPointF(size.width() * (0.32 + i * 0.18), size.height() * 0.42), r, r);
    }
    QFont f = p.font();
    f.setBold(true);
    f.setPixelSize(qMax(11, size.width() / 9));
    p.setFont(f);
    p.setPen(QColor(LetItEditColors::cream));
    p.drawText(QRectF(0, size.height() * 0.62, size.width(), size.height() * 0.3), Qt::AlignCenter, QObject::tr("As learned"));
    return picture;
}

} // namespace

QWidget *NewVideoDialog::themePage()
{
    QVBoxLayout *column = nullptr;
    auto w = page(tr("Pick a Theme (optional)"), tr("How it's drawn or filmed. Your Look works with any of these."), &column);
    m_themeLead = w->findChild<QLabel *>(QStringLiteral("newVideoLead"));
    auto scroll = new QScrollArea(w);
    scroll->setObjectName(QStringLiteral("newVideoThemesScroll"));
    scroll->setWidgetResizable(true);
    scroll->setFrameShape(QFrame::NoFrame);
    scroll->setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    auto deck = new ThemeDeck(scroll);
    m_themeDeck = deck;
    scroll->setWidget(deck);
    column->addWidget(scroll, 1);
    m_themeGroup = new QButtonGroup(this);
    return w;
}

void NewVideoDialog::fillThemePage()
{
    if (!m_themeDeck)
        return;
    auto deck = static_cast<ThemeDeck *>(m_themeDeck);
    m_filling = true;
    for (auto button : m_themeGroup->buttons())
        m_themeGroup->removeButton(button);
    deck->clear();
    const LookStyle *style = lookStyle(m_style) ? lookStyle(m_style) : lookStyle(tabStyleFor()); // the Look step skipped: the tab's Style
    const LookChoice *look = style ? findLook(*style, m_look) : nullptr;
    const QJsonObject own = ownTheme(look);
    const QString ownId = own.value("id").toString();
    QList<QJsonObject> themes;
    QStringList folders;
    bool valid = m_theme == QLatin1String("freestyle") || m_theme == QLatin1String("pick");
    for (const auto &value : m_themes) {
        const auto theme = value.toObject();
        if (!themeFits(theme, style, look) || theme.value("id").toString() == ownId)
            continue;
        themes << theme;
        if (!folders.contains(theme.value("folder").toString()))
            folders << theme.value("folder").toString();
        valid |= theme.value("id").toString() == m_theme;
    }
    valid |= !ownId.isEmpty() && m_theme == QLatin1String("none");
    if (!valid || (m_theme == QLatin1String("pick") && themes.isEmpty()))
        m_theme = QStringLiteral("freestyle");
    // a Look with its own Theme starts on keeping it as learned, until the person chooses
    if (!ownId.isEmpty() && !m_themeChosen)
        m_theme = QStringLiteral("none");
    m_themeLead->setText(!ownId.isEmpty() ? tr("Another Theme replaces this Look's colours and lighting; its cuts and timing stay.")
                         : themes.isEmpty() ? tr("This Look has its own finish, so there is nothing to add. You can go on.")
                                            : tr("How it's drawn or filmed. Your Look works with any of these."));
    const auto addCard = [&](const QString &id, const QString &title, const QPixmap &picture, const QString &tag, const QString &line,
                             CardFamily family) {
        auto card = new ThemeCard(id, title, line, tag, family, picture, deck);
        card->setChecked(id == m_theme);
        m_themeGroup->addButton(card);
        connect(card, &QAbstractButton::toggled, this, [this, id, card](bool on) {
            if (on && !m_filling) {
                m_theme = id;
                m_themeChosen = true;
            }
            card->update();
        });
        if (m_review && id != QLatin1String("freestyle") && id != QLatin1String("pick") && id != QLatin1String("none")) {
            const QJsonObject entry = [&]() {
                for (const auto &value : m_themes)
                    if (value.toObject().value("id").toString() == id)
                        return value.toObject();
                return QJsonObject();
            }();
            auto tile = new QWidget(deck);
            auto tileColumn = new QVBoxLayout(tile);
            tileColumn->setContentsMargins(0, 0, 0, 0);
            card->setFixedSize(ThemeCard::baseSize());
            tileColumn->addWidget(card);
            auto reviewRow = new QHBoxLayout;
            tileColumn->addLayout(reviewRow);
            addReviewButtons(reviewRow, QStringLiteral("theme"), id, entry.value("review").toString(), false);
            deck->addCard(tile, false);
            return;
        }
        deck->addCard(card, true);
    };
    const QSize window = ThemeCard::pictureRect().size().toSize() * 2;
    // the first choice is a normal card, plainly marked when it is chosen, like any other (T176)
    if (!ownId.isEmpty())
        addCard(QStringLiteral("none"), tr("No Theme"), keepPicture(window), tr("Recommended"),
                tr("This Look already has its own colours and lighting."), CardFamily::Choice);
    // Freestyle (the default: Themes are optional and never forced) and Let the AI pick (one of the Themes below), T179
    addCard(QStringLiteral("freestyle"), tr("Freestyle"), freestylePicture(window), ownId.isEmpty() ? tr("Default") : QString(),
            tr("No set Theme. Your AI draws or films it its own way, or uses none."), CardFamily::Choice);
    if (!themes.isEmpty())
        addCard(QStringLiteral("pick"), tr("Let the AI pick"), aiPickPicture(window, false), QString(),
                tr("Your AI chooses one of these Themes and says why."), CardFamily::Choice);
    for (const QString &folder : std::as_const(folders)) {
        auto heading = new QLabel(folder, deck);
        heading->setObjectName(QStringLiteral("newVideoThemeFolder_%1").arg(folder));
        heading->setStyleSheet(QStringLiteral("font-weight: 700; padding-top: 6px;"));
        deck->addHeading(heading);
        for (const auto &theme : std::as_const(themes)) {
            if (theme.value("folder").toString() != folder)
                continue;
            const QString id = theme.value("id").toString();
            const bool recommended = ownId.isEmpty()
                                     && (theme.value("recommended_for").toArray().contains(look ? look->id : QString())
                                         || theme.value("recommended_for").toArray().contains(style ? style->id : QString()));
            addCard(id, theme.value("title").toString(), QPixmap(theme.value("poster").toString()), recommended ? tr("Recommended") : QString(),
                    theme.value("blurb").toString(), familyOf(theme));
        }
    }
    deck->relayout();
    m_filling = false;
}

} // namespace NewVideo
