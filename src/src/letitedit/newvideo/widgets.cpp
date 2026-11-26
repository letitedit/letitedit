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

// New video's own widgets: the sliders, the choice and Look cards, the moving previews, the file tiles.
// (Split out of firstcut.cpp; the class is declared in newvideodialog.h.)

#include "newvideodialog.h"

namespace NewVideo {

// The card's picture when a style has no preview image: its name on a calm block, so every card lines up.
QPixmap placeholderPicture(const QString &label, bool ai)
{
    const QSize size(196, 110);
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    // a steady colour per style, from the brand's darker shades
    static const QList<QColor> shades{QColor("#144F5F"), QColor("#3A2A22"), QColor("#2E363B"), QColor("#1F3A33")};
    const QColor base = ai ? QColor(LetItEditColors::tealDeep) : shades[qHash(label) % shades.size()];
    p.setPen(Qt::NoPen);
    p.setBrush(base);
    p.drawRoundedRect(QRectF(QPointF(0, 0), QSizeF(size)), 10, 10);
    if (ai) {
        QIcon(QStringLiteral(":/icons/letitedit/ui/ai.svg")).paint(&p, QRect(size.width() / 2 - 20, 22, 40, 40));
        QFont f = p.font();
        f.setPixelSize(13);
        f.setBold(true);
        p.setFont(f);
        p.setPen(QColor(LetItEditColors::cream));
        p.drawText(QRect(0, 70, size.width(), 24), Qt::AlignCenter, QObject::tr("Your AI picks the look"));
    } else {
        QFont f = p.font();
        f.setPixelSize(19);
        f.setBold(true);
        p.setFont(f);
        p.setPen(QColor(LetItEditColors::cream));
        p.drawText(QRect(12, 8, size.width() - 24, size.height() - 16), Qt::AlignCenter | Qt::TextWordWrap, label);
    }
    return pixmap;
}

// The import card's picture: a film strip with a plus, in the brand's teal.
QPixmap importPicture()
{
    const QSize size(196, 110);
    const qreal ratio = qApp->devicePixelRatio();
    QPixmap pixmap(size * ratio);
    pixmap.setDevicePixelRatio(ratio);
    pixmap.fill(Qt::transparent);
    QPainter p(&pixmap);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(QPen(QColor(LetItEditColors::teal), 2, Qt::DashLine));
    p.setBrush(Qt::NoBrush);
    p.drawRoundedRect(QRectF(1, 1, size.width() - 2, size.height() - 2), 10, 10);
    for (int i = 0; i < 3; ++i) {
        const QRectF frame(46 + i * 36, 30, 30, 22);
        p.setPen(Qt::NoPen);
        p.setBrush(QColor(LetItEditColors::tealDeep));
        p.drawRoundedRect(frame, 3, 3);
    }
    QFont f = p.font();
    f.setPixelSize(30);
    f.setBold(true);
    p.setFont(f);
    p.setPen(QColor(LetItEditColors::tealLight));
    p.drawText(QRect(0, 52, size.width(), 44), Qt::AlignCenter, QStringLiteral("+"));
    return pixmap;
}

CustomSlider::CustomSlider(QWidget *parent)
    : QSlider(Qt::Horizontal, parent) { setFocusPolicy(Qt::ClickFocus); }

void CustomSlider::onTouch(std::function<void()> action) { m_onTouch = std::move(action); }

void CustomSlider::wheelEvent(QWheelEvent *event) { event->ignore(); }

void CustomSlider::mousePressEvent(QMouseEvent *event)
{
    if (m_onTouch)
        m_onTouch();
    QSlider::mousePressEvent(event);
}

SliderToy::SliderToy(const QString &kind, QWidget *parent)
    : QWidget(parent), m_kind(kind) { setFixedSize(66, 46); }

// A negative level means the AI decides: the setting's own picture, faded, at a middle level.
void SliderToy::setLevel(int level) { m_automatic = level < 0; m_level = level < 0 ? 2 : level; update(); }

void SliderToy::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    p.setRenderHint(QPainter::Antialiasing);
    const QColor rust("#C8653B"), teal("#2A8597"), cream("#F4EFE6");
    p.setPen(QPen(teal, 2));
    p.setBrush(Qt::NoBrush);
    if (m_automatic)
        p.setOpacity(0.38);
    const int n = m_level + 1;
    if (m_kind == "master") {
        p.setBrush(teal);
        for (int i = 0; i < 3; ++i)
            p.drawRoundedRect(QRectF(10 + i * 17, 35 - (i + 1) * (4 + m_level), 11,
                                     (i + 1) * (4 + m_level)), 3, 3);
    } else if (m_kind == "courage") {
        const qreal spread = 5.0 + m_level * 3.4;
        const qreal top = 29.0 - m_level * 3.2;
        p.setBrush(rust);
        QPainterPath flame;
        flame.moveTo(33 - spread, 39);
        flame.cubicTo(25 - spread, 30, 29 - spread / 2, 24, 25 - spread / 3, top + 5);
        flame.cubicTo(32 - spread / 3, top + 11, 29, top + 8, 33, top);
        flame.cubicTo(38, top + 8, 37 + spread / 3, top + 10, 41 + spread / 3, top + 3);
        flame.cubicTo(40 + spread / 2, 23, 44 + spread, 31, 33 + spread, 39);
        flame.cubicTo(47, 44, 19, 44, 33 - spread, 39);
        p.setPen(Qt::NoPen);
        p.drawPath(flame);
        if (m_level >= 3) {
            p.setBrush(QColor("#F3B45B"));
            QPainterPath inner;
            inner.moveTo(33 - spread * .45, 40);
            inner.cubicTo(29, 34, 30, 29, 33, top + 10);
            inner.cubicTo(37, 32, 39, 36, 33 + spread * .45, 40);
            inner.closeSubpath();
            p.drawPath(inner);
        }
        if (m_level >= 5) {
            p.setBrush(cream);
            p.drawEllipse(QRectF(29, 35, 8, 6));
            p.setPen(QPen(rust, 2));
            p.drawLine(9, 43, 54, 43);
        }
    } else if (m_kind == "pauses") {
        p.setPen(QPen(teal, 3));
        p.drawLine(5, 24, 18, 24);
        p.drawLine(25, 24, 39, 24);
        p.drawLine(47, 24, 60, 24);
        p.setPen(QPen(rust, 2));
        for (int i = 0; i < m_level; ++i)
            p.drawLine(18 + i * 5, 11, 18 + i * 5, 36);
    } else if (m_kind == "cutting") {
        static const QStringList icons{QString::fromUtf8("🐌"), QString::fromUtf8("🐢"),
            QString::fromUtf8("🚶"), QString::fromUtf8("🏃"), QString::fromUtf8("🚗"),
            QString::fromUtf8("🚀"), QString::fromUtf8("🚀")};
        QFont f(QStringLiteral("Segoe UI Emoji"), 21); p.setFont(f); p.setPen(cream);
        p.drawText(rect(), Qt::AlignCenter, icons[m_level]);
        p.setPen(QPen(rust, 2));
        for (int i = 0; i < m_level / 2; ++i) p.drawLine(4, 23 + i * 6, 13, 23 + i * 6);
    } else if (m_kind == "emoji") {
        static const QStringList faces{QString::fromUtf8("😐"), QString::fromUtf8("🙂"),
            QString::fromUtf8("😊"), QString::fromUtf8("😄"), QString::fromUtf8("🤩"),
            QString::fromUtf8("🤯"), QString::fromUtf8("🤯")};
        p.setFont(QFont(QStringLiteral("Segoe UI Emoji"), 18 + m_level)); p.setPen(cream);
        p.drawText(rect(), Qt::AlignCenter, faces[m_level]);
    } else if (m_kind == "punch_ins") {
        p.drawEllipse(QRectF(10 - m_level, 5 - m_level / 2, 24 + 3 * m_level, 24 + 3 * m_level));
        p.drawLine(34 + 2 * m_level, 29 + m_level, 51 + 2 * m_level, 43);
    } else if (m_kind == "captions") {
        QFont f = p.font(); f.setBold(true); f.setPixelSize(17 + 3 * m_level); p.setFont(f); p.setPen(cream);
        p.drawText(rect(), Qt::AlignCenter, m_level >= 4 ? QStringLiteral("Aa!") : QStringLiteral("Aa"));
    } else if (m_kind == "three_d") {
        const int shift = 3 + m_level * 2;
        p.drawRect(14, 13, 25, 25); p.drawRect(14 + shift, 13 - shift / 2, 25, 25);
        p.drawLine(14, 13, 14 + shift, 13 - shift / 2); p.drawLine(39, 13, 39 + shift, 13 - shift / 2);
    } else if (m_kind == "motion") {
        p.translate(33, 23); p.setPen(QPen(rust, 2 + m_level / 2));
        for (int i = 0; i < n + 2; ++i) { p.save(); p.rotate(i * 360.0 / (n + 2)); p.drawLine(0, 7, 0, 12 + m_level * 2); p.restore(); }
    } else if (m_kind == "overlays") {
        for (int i = 0; i < n; ++i) { p.setBrush(QColor(42, 133, 151, 35 + i * 20)); p.drawRect(8 + i * 5, 7 + i * 3, 26, 20); }
    } else if (m_kind == "transitions") {
        p.setBrush(teal); p.drawRect(5, 9, 51, 30); p.setBrush(rust);
        p.drawRect(5, 9, 6 + m_level * 8, 30);
        if (m_level > 3) { p.setPen(QPen(cream, 2)); p.drawLine(13 + m_level * 6, 12, 19 + m_level * 6, 36); }
    } else if (m_kind == "dialogue") {
        p.setBrush(teal); p.drawRoundedRect(7, 6, 49, 29, 7, 7); p.drawLine(20, 34, 15, 42);
        p.setPen(cream); for (int i = 0; i < qMin(4, n); ++i) p.drawLine(14, 13 + i * 5, 18 + m_level * 5, 13 + i * 5);
    } else if (m_kind == "music") {
        p.setBrush(rust); for (int i = 0; i < 5; ++i) p.drawRect(8 + i * 11, 39 - (5 + ((i + m_level) % 5) * n), 7, 5 + ((i + m_level) % 5) * n);
    } else if (m_kind == "sound") {
        p.setPen(QPen(rust, 2)); for (int i = 0; i < n; ++i) p.drawLine(7 + i * 8, 18 - i % 2 * 6, 15 + i * 8, 26 + i % 2 * 6);
    } else if (m_kind == "broll") {
        p.setPen(QPen(teal, 2)); p.drawRect(5, 11, 12 + n * 7, 26);
        p.setBrush(rust); for (int i = 0; i < n; ++i) p.drawRect(9 + i * 7, 15, 3, 4);
    }
}

ChoiceCard::ChoiceCard(const QString &title, const QString &text, QWidget *parent, const QString &badge,
               const QPixmap &picture, const QString &tags)
    : QPushButton(parent)
{
    setCheckable(true);
    setAutoExclusive(false); // a QButtonGroup keeps one chosen
    setCursor(Qt::PointingHandCursor);
    setProperty("newVideoCard", true);
    setAccessibleName(title);
    setToolTip(text);
    setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Fixed);
    auto column = new QVBoxLayout(this);
    column->setContentsMargins(14, 12, 14, 12);
    column->setSpacing(4);
    if (!picture.isNull()) {
        auto image = new QLabel(this);
        image->setPixmap(picture);
        image->setAlignment(Qt::AlignCenter);
        image->setFixedHeight(int(picture.height() / picture.devicePixelRatio()));
        column->addWidget(image);
    }
    auto top = new QHBoxLayout;
    auto heading = new QLabel(title, this);
    heading->setObjectName(QStringLiteral("newVideoCardTitle"));
    heading->setWordWrap(true);
    top->addWidget(heading, 1);
    if (!badge.isEmpty()) {
        auto b = new QLabel(badge, this);
        b->setObjectName(QStringLiteral("newVideoCardBadge"));
        top->addWidget(b, 0, Qt::AlignTop);
    }
    column->addLayout(top);
    auto body = new QLabel(text, this);
    body->setObjectName(QStringLiteral("newVideoCardText"));
    body->setWordWrap(true);
    column->addWidget(body);
    if (!tags.isEmpty()) {
        auto t = new QLabel(tags, this);
        t->setObjectName(QStringLiteral("newVideoCardTags"));
        t->setWordWrap(true);
        column->addWidget(t);
    }
    column->addStretch(1);
    for (auto child : findChildren<QLabel *>())
        child->setAttribute(Qt::WA_TransparentForMouseEvents);
}

QSize ChoiceCard::sizeHint() const { return layout() ? layout()->totalSizeHint() : QPushButton::sizeHint(); }

QSize ChoiceCard::minimumSizeHint() const
{
    return layout() ? layout()->totalMinimumSize() : QPushButton::minimumSizeHint();
}

LookPreview::LookPreview(const QString &clip, const QString &poster, const QSize &size, QWidget *parent)
    : QLabel(parent)
    , m_clip(clip)
    , m_size(size)
{
    setFixedSize(size);
    setAlignment(Qt::AlignCenter);
    setStyleSheet(QStringLiteral("background: %1; border-radius: 8px;").arg(LetItEditColors::deep));
    if (!poster.isEmpty() && QFileInfo::exists(poster)) {
        const QImage still(poster);
        // a box of the poster's own shape (the Look step sizes it so): fill it, centred; else as before (top-left crop)
        m_exact = !still.isNull() && size.height() > 0
                  && qAbs(double(still.width()) / still.height() - double(size.width()) / size.height())
                         <= 0.03 * double(size.width()) / size.height();
        m_poster = m_exact ? QPixmap::fromImage(fitted(still))
                           : QPixmap(poster).scaled(size, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation)
                                 .copy(0, 0, size.width(), size.height());
    }
    showPoster();
}

// the picture scaled to cover the box exactly and centred (the box is its own shape, so at most a pixel is trimmed)
QImage LookPreview::fitted(const QImage &image) const
{
    const QImage scaled = image.scaled(m_size, Qt::KeepAspectRatioByExpanding, Qt::SmoothTransformation);
    return scaled.copy((scaled.width() - m_size.width()) / 2, (scaled.height() - m_size.height()) / 2, m_size.width(), m_size.height());
}

bool LookPreview::hasClip() const { return !m_clip.isEmpty() && QFileInfo::exists(m_clip); }

bool LookPreview::playing() const { return m_player && m_player->playbackState() == QMediaPlayer::PlayingState; }

bool LookPreview::sound() const { return m_audio && !m_audio->isMuted(); }

int LookPreview::frames() const { return m_frames; }

// play muted and looping, or stop and show the poster again
void LookPreview::setPlaying(bool on)
{
    if (on == playing() || (on && !hasClip()))
        return;
    if (on) {
        ensurePlayer();
        m_player->play();
    } else if (m_player) {
        m_player->pause();
        showPoster();
    }
}

void LookPreview::setSound(bool on)
{
    if (on) {
        ensurePlayer();
        if (!m_audio) {
            // no audio output until the person asks to hear it: a silent preview is video only
            m_audio = new QAudioOutput(this);
            m_audio->setVolume(0.8f);
            m_player->setAudioOutput(m_audio);
        }
    }
    if (m_audio)
        m_audio->setMuted(!on);
}

void LookPreview::ensurePlayer()
{
    if (m_player)
        return;
    m_sink = new QVideoSink(this);
    m_player = new QMediaPlayer(this);
    m_player->setVideoSink(m_sink);
    m_player->setLoops(QMediaPlayer::Infinite);
    m_player->setSource(QUrl::fromLocalFile(m_clip));
    if (m_startMs > 0) {
        // the first play starts where the poster was taken; later loops run from the start
        connect(m_player, &QMediaPlayer::mediaStatusChanged, this, [this](QMediaPlayer::MediaStatus status) {
            if (m_startMs > 0 && (status == QMediaPlayer::LoadedMedia || status == QMediaPlayer::BufferedMedia)) {
                if (m_startMs < m_player->duration())
                    m_player->setPosition(m_startMs);
                m_startMs = 0;
            }
        });
    }
    connect(m_sink, &QVideoSink::videoFrameChanged, this, [this](const QVideoFrame &frame) {
        if (!playing())
            return;
        const QImage image = frame.toImage();
        if (image.isNull())
            return;
        ++m_frames;
        setPixmap(QPixmap::fromImage(image.size() == m_size ? image
                                     : m_exact ? fitted(image)
                                               : image.scaled(m_size, Qt::KeepAspectRatio, Qt::FastTransformation)));
    });
}

void LookPreview::showPoster()
{
    if (!m_poster.isNull())
        setPixmap(m_poster);
}

LookCard::LookCard(const QString &id, const QString &title, const QString &text, const QString &clip, const QString &poster,
             const QPixmap &placeholder, const QSize &pictureSize, Playback playback, QWidget *parent)
    : QPushButton(parent)
    , m_playback(playback)
{
    setCheckable(true);
    setAutoExclusive(false); // a QButtonGroup keeps one chosen
    setCursor(Qt::PointingHandCursor);
    setProperty("newVideoCard", true);
    setAccessibleName(title);
    setToolTip(text);
    setObjectName(QStringLiteral("newVideoLook_%1").arg(id));
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    setFixedWidth(qMax(pictureSize.width(), kMinTextWidth) + 2 * kCardMargin); // the wrapped texts never widen the card
    setAttribute(Qt::WA_Hover);
    auto column = new QVBoxLayout(this);
    column->setContentsMargins(kCardMargin, 12, kCardMargin, 12);
    column->setSpacing(6);
    if (!clip.isEmpty()) {
        m_preview = new LookPreview(clip, poster, pictureSize, this);
        m_preview->setObjectName(QStringLiteral("newVideoLookPreview_%1").arg(id));
        m_picture = m_preview;
        column->addWidget(m_preview, 0, Qt::AlignHCenter);
        // the sound switch sits on the preview's corner; sound never starts by itself
        m_sound = new QToolButton(this);
        m_sound->setObjectName(QStringLiteral("newVideoLookSound_%1").arg(id));
        m_sound->setCheckable(true);
        m_sound->setCursor(Qt::ArrowCursor);
        m_sound->setText(soundOffText());
        m_sound->setAccessibleName(tr("Sound for %1").arg(title));
        m_sound->setToolTip(tr("Hear this preview"));
        m_sound->setStyleSheet(QStringLiteral(
            "QToolButton { background: rgba(22,26,29,200); color: #F4EFE6; border: 1px solid #4A545B; "
            "border-radius: 13px; padding: 0; font-size: 14px; }"
            "QToolButton:checked { background: #2A8597; border-color: #A8E1E7; }"));
        m_sound->setFixedSize(26, 26);
        m_sound->setParent(m_preview);
        m_sound->move(pictureSize.width() - 32, pictureSize.height() - 32);
        m_sound->show();
        connect(m_sound, &QToolButton::toggled, this, [this](bool on) {
            m_sound->setText(on ? soundOnText() : soundOffText());
            m_sound->setToolTip(on ? tr("Mute this preview") : tr("Hear this preview"));
            m_preview->setSound(on);
            if (on)
                m_preview->setPlaying(true);
            else
                update(); // the playing rule applies again
            if (m_onSound)
                m_onSound(this, on);
        });
    } else {
        auto picture = new QLabel(this);
        picture->setObjectName(QStringLiteral("newVideoLookPicture_%1").arg(id));
        m_picture = picture;
        picture->setPixmap(placeholder);
        picture->setFixedSize(pictureSize);
        picture->setAlignment(Qt::AlignCenter);
        picture->setAttribute(Qt::WA_TransparentForMouseEvents);
        column->addWidget(picture, 0, Qt::AlignHCenter);
    }
    auto heading = new QLabel(title, this);
    heading->setObjectName(QStringLiteral("newVideoCardTitle"));
    heading->setWordWrap(true);
    column->addWidget(heading);
    auto body = new QLabel(text, this);
    body->setObjectName(QStringLiteral("newVideoCardText"));
    body->setWordWrap(true);
    column->addWidget(body);
    column->addStretch(1);
    for (auto child : findChildren<QLabel *>())
        if (child != m_preview)
            child->setAttribute(Qt::WA_TransparentForMouseEvents);
    // a label for tests and screen readers: what the preview is doing (frames shown, sound on)
    m_state = new QLabel(this);
    m_state->setObjectName(QStringLiteral("newVideoLookState_%1").arg(id));
    m_state->setFixedSize(1, 1);
    m_state->setAttribute(Qt::WA_TransparentForMouseEvents);
    m_state->setStyleSheet(QStringLiteral("color: transparent; background: transparent;"));
    connect(this, &QPushButton::toggled, this, [this]() { applyPlayback(); });
    auto tick = new QTimer(this);
    tick->setInterval(250);
    connect(tick, &QTimer::timeout, this, [this]() { applyPlayback(); });
    tick->start();
    applyPlayback();
}

// called when another card's sound is switched on, so only one preview is heard at a time
void LookCard::onSound(std::function<void(LookCard *, bool)> action) { m_onSound = std::move(action); }

void LookCard::silence()
{
    if (m_sound && m_sound->isChecked())
        m_sound->setChecked(false);
}

QSize LookCard::sizeHint() const { return layout() ? layout()->totalSizeHint() : QPushButton::sizeHint(); }

QSize LookCard::minimumSizeHint() const { return sizeHint(); }

// a small mark above the card's name ("Your style")
void LookCard::setBadge(const QString &text)
{
    auto badge = new QLabel(text, this);
    badge->setObjectName(QStringLiteral("newVideoCardBadge"));
    badge->setAttribute(Qt::WA_TransparentForMouseEvents);
    auto column = qobject_cast<QVBoxLayout *>(layout());
    const int after = m_picture ? column->indexOf(m_picture) : 0;
    // after the picture and the space that centres it, if any
    int at = after + 1;
    if (at < column->count() && column->itemAt(at)->spacerItem())
        ++at;
    column->insertWidget(at, badge, 0, Qt::AlignLeft);
}

void LookCard::setPictureHeight(int height)
{
    auto column = qobject_cast<QVBoxLayout *>(layout());
    if (!m_picture || !column || m_picture->height() >= height)
        return;
    const int spare = height - m_picture->height();
    const int at = column->indexOf(m_picture);
    column->insertSpacing(at + 1, spare - spare / 2);
    column->insertSpacing(at, spare / 2);
}

void LookCard::enterEvent(QEnterEvent *event)
{
    QPushButton::enterEvent(event);
    applyPlayback();
}

void LookCard::leaveEvent(QEvent *event)
{
    QPushButton::leaveEvent(event);
    applyPlayback();
}

void LookCard::showEvent(QShowEvent *event)
{
    QPushButton::showEvent(event);
    applyPlayback();
}

void LookCard::hideEvent(QHideEvent *event)
{
    QPushButton::hideEvent(event);
    applyPlayback();
}

// the preview plays while the card is on screen and (always) or (hovered, chosen, or its sound is on)
void LookCard::applyPlayback()
{
    if (!m_preview)
        return;
    const bool hovered = underMouse();
    const bool wanted = isVisible()
                        && (m_playback == Always || hovered || isChecked() || (m_sound && m_sound->isChecked()));
    m_preview->setPlaying(wanted);
    m_state->setText(QStringLiteral("playing=%1 sound=%2 frames=%3")
                         .arg(m_preview->playing() ? 1 : 0)
                         .arg(m_preview->sound() ? 1 : 0)
                         .arg(m_preview->frames()));
}

QString LookCard::soundOffText() { return QString::fromUtf8("\xF0\x9F\x94\x87"); }

QString LookCard::soundOnText() { return QString::fromUtf8("\xF0\x9F\x94\x8A"); }

QString AskFiles::mime() { return QStringLiteral("application/x-letitedit-ask-file"); }

AskFiles::AskFiles(const QString &askId, bool single, QWidget *parent)
    : QListWidget(parent)
    , m_ask(askId)
    , m_single(single)
{
    setObjectName(QStringLiteral("newVideoAskFiles_%1").arg(askId));
    setViewMode(QListView::IconMode);
    setResizeMode(QListView::Adjust);
    setMovement(QListView::Static);
    setSelectionMode(QAbstractItemView::ExtendedSelection);
    setSpacing(6);
    setUniformItemSizes(true);
    setAcceptDrops(true);
    setDragEnabled(true);
    setDragDropMode(QAbstractItemView::DragDrop);
    setFixedHeight(kEmptyHeight);
    setStyleSheet(QStringLiteral("QListWidget { border: 1px dashed #4A545B; border-radius: 8px; }"));
    setHorizontalScrollBarPolicy(Qt::ScrollBarAlwaysOff);
    setFrameShape(QFrame::StyledPanel);
    setToolTip(single ? tr("Drop a file here, or press Add a file") : tr("Drop files here, or press Add files"));
}

QStringList AskFiles::files() const
{
    QStringList out;
    for (int i = 0; i < count(); ++i)
        out << item(i)->data(Qt::UserRole).toString();
    return out;
}

void AskFiles::fitHeight() { setFixedHeight(count() ? kFilledHeight : kEmptyHeight); }

void AskFiles::addFiles(const QStringList &paths)
{
    QStringList added;
    for (const QString &path : paths) {
        if (path.isEmpty() || files().contains(path))
            continue;
        if (m_single)
            clearFiles();
        addTile(path);
        added << path;
    }
    if (!added.isEmpty()) {
        fitHeight();
        if (m_onAdded)
            m_onAdded(added);
        if (m_onChanged)
            m_onChanged();
    }
}

void AskFiles::removeFile(const QString &path)
{
    for (int i = 0; i < count(); ++i)
        if (item(i)->data(Qt::UserRole).toString() == path) {
            delete takeItem(i);
            fitHeight();
            if (m_onChanged)
                m_onChanged();
            return;
        }
}

void AskFiles::clearFiles()
{
    clear();
}

// the length and picture of a file, as they arrive from bridge\look_inputs.py
void AskFiles::setFacts(const QString &path, const QString &length, const QPixmap &picture)
{
    for (int i = 0; i < count(); ++i)
        if (item(i)->data(Qt::UserRole).toString() == path)
            if (auto tile = itemWidget(item(i))) {
                for (auto l : tile->findChildren<QLabel *>()) {
                    if (!length.isEmpty() && l->property("tileLength").toBool())
                        l->setText(length);
                    if (!picture.isNull() && l->property("tilePicture").toBool())
                        l->setPixmap(picture.scaled(l->size(), Qt::KeepAspectRatio, Qt::SmoothTransformation));
                }
            }
}

void AskFiles::setCanMove(bool can, const QString &destinationLabel)
{
    m_canMove = can;
    m_destination = destinationLabel;
    for (int i = 0; i < count(); ++i)
        if (auto tile = itemWidget(item(i)))
            for (auto b : tile->findChildren<QToolButton *>())
                if (b->property("tileMove").toBool()) {
                    b->setVisible(can);
                    b->setToolTip(tr("Move to \"%1\"").arg(destinationLabel));
                }
}

void AskFiles::onChanged(std::function<void()> f) { m_onChanged = std::move(f); }

void AskFiles::onAdded(std::function<void(const QStringList &)> f) { m_onAdded = std::move(f); }

void AskFiles::onMove(std::function<void(AskFiles *, const QString &)> f) { m_onMove = std::move(f); }

QString AskFiles::askId() const { return m_ask; }

QString AskFiles::tileName(const QString &path)
{
    QString name = QFileInfo(path).fileName();
    name.replace(QRegularExpression(QStringLiteral("[^A-Za-z0-9]")), QStringLiteral("_"));
    return name;
}

void AskFiles::paintEvent(QPaintEvent *event)
{
    QListWidget::paintEvent(event);
    if (count() > 0)
        return;
    QPainter p(viewport());
    p.setPen(QColor(LetItEditColors::muted));
    p.drawText(viewport()->rect(), Qt::AlignCenter, m_single ? tr("Drop a file here") : tr("Drop files here"));
}

void AskFiles::startDrag(Qt::DropActions)
{
    const auto picked = selectedItems();
    if (picked.isEmpty())
        return;
    QStringList paths;
    for (auto it : picked)
        paths << it->data(Qt::UserRole).toString();
    // our own format only: a drop on Explorer or another program must never move the person's files
    auto data = new QMimeData;
    data->setData(mime(), paths.join(QLatin1Char('\n')).toUtf8());
    auto drag = new QDrag(this);
    drag->setMimeData(data);
    if (drag->exec(Qt::MoveAction, Qt::MoveAction) == Qt::MoveAction)
        for (const QString &path : paths)
            removeFile(path);
}

void AskFiles::dragEnterEvent(QDragEnterEvent *event) { acceptIfFiles(event); }

void AskFiles::dragMoveEvent(QDragMoveEvent *event) { acceptIfFiles(event); }

void AskFiles::dropEvent(QDropEvent *event)
{
    const QMimeData *data = event->mimeData();
    if (data->hasFormat(mime())) {
        if (event->source() == this) {
            event->ignore();
            return;
        }
        addFiles(QString::fromUtf8(data->data(mime())).split(QLatin1Char('\n'), Qt::SkipEmptyParts));
        event->setDropAction(Qt::MoveAction);
        event->accept();
    } else if (data->hasUrls()) {
        QStringList paths;
        for (const QUrl &url : data->urls())
            if (url.isLocalFile() && QFileInfo(url.toLocalFile()).isFile())
                paths << QDir::toNativeSeparators(url.toLocalFile());
        addFiles(paths);
        event->setDropAction(Qt::CopyAction);
        event->accept();
    } else {
        event->ignore();
    }
}

void AskFiles::acceptIfFiles(QDropEvent *event)
{
    if ((event->mimeData()->hasFormat(mime()) && event->source() != this) || event->mimeData()->hasUrls())
        event->acceptProposedAction();
    else
        event->ignore();
}

void AskFiles::addTile(const QString &path)
{
    const QString name = tileName(path);
    auto it = new QListWidgetItem(this);
    it->setData(Qt::UserRole, path);
    it->setSizeHint(QSize(112, 144));
    it->setToolTip(QDir::toNativeSeparators(path));
    auto tile = new QWidget;
    tile->setObjectName(QStringLiteral("newVideoAskTile_%1_%2").arg(m_ask, name));
    auto column = new QVBoxLayout(tile);
    column->setContentsMargins(4, 4, 4, 2);
    column->setSpacing(2);
    auto picture = new QLabel(tile);
    picture->setProperty("tilePicture", true);
    picture->setFixedSize(96, 66);
    picture->setAlignment(Qt::AlignCenter);
    picture->setPixmap(placeholder(path));
    column->addWidget(picture, 0, Qt::AlignHCenter);
    auto label = new QLabel(tile);
    label->setObjectName(QStringLiteral("newVideoAskName_%1_%2").arg(m_ask, name));
    label->setText(fontMetrics().elidedText(QFileInfo(path).fileName(), Qt::ElideMiddle, 100));
    label->setAlignment(Qt::AlignHCenter);
    column->addWidget(label);
    auto length = new QLabel(tile);
    length->setProperty("tileLength", true);
    length->setObjectName(QStringLiteral("newVideoAskLength_%1_%2").arg(m_ask, name));
    length->setAlignment(Qt::AlignHCenter);
    length->setProperty("studioMuted", true);
    column->addWidget(length);
    // the picture and the texts pass the mouse to the list, so a tile can be picked up and dragged
    for (auto child : {static_cast<QWidget *>(picture), static_cast<QWidget *>(label), static_cast<QWidget *>(length)})
        child->setAttribute(Qt::WA_TransparentForMouseEvents);
    auto buttons = new QHBoxLayout;
    buttons->setSpacing(4);
    auto move = new QToolButton(tile);
    move->setText(QString::fromUtf8("\xE2\x87\x84")); // two arrows
    move->setVisible(m_canMove);
    move->setToolTip(tr("Move to \"%1\"").arg(m_destination));
    move->setProperty("tileMove", true);
    move->setObjectName(QStringLiteral("newVideoAskMove_%1_%2").arg(m_ask, name));
    connect(move, &QToolButton::clicked, this, [this, path]() {
        if (m_onMove)
            m_onMove(this, path);
    });
    auto remove = new QToolButton(tile);
    remove->setObjectName(QStringLiteral("newVideoAskRemove_%1_%2").arg(m_ask, name));
    remove->setText(QString::fromUtf8("\xE2\x9C\x95")); // a cross
    remove->setToolTip(tr("Remove from this list (your file is not changed)"));
    connect(remove, &QToolButton::clicked, this, [this, path]() { removeFile(path); });
    buttons->addStretch(1);
    buttons->addWidget(move);
    buttons->addWidget(remove);
    buttons->addStretch(1);
    column->addLayout(buttons);
    setItemWidget(it, tile);
}

QPixmap AskFiles::placeholder(const QString &path)
{
    QPixmap pixmap(96, 66);
    pixmap.fill(QColor(LetItEditColors::deep));
    QPainter p(&pixmap);
    p.setPen(QColor(LetItEditColors::tealLight));
    QFont f = p.font();
    f.setBold(true);
    p.setFont(f);
    p.drawText(QRect(0, 0, 96, 66), Qt::AlignCenter, QFileInfo(path).suffix().toUpper().left(5));
    return pixmap;
}

} // namespace NewVideo
