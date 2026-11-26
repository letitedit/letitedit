/*
 * Copyright (c) 2012-2026 Meltytech, LLC
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

#include "timespinbox.h"

#include "mltcontroller.h"
#include "settings.h"

#include <QFontDatabase>
#include <QGuiApplication>
#include <QKeyEvent>
#include <QRegularExpressionValidator>
#include <QStyle>
#include <QStyleOptionSpinBox>

TimeSpinBox::TimeSpinBox(QWidget *parent)
    : QSpinBox(parent)
{
    setLineEdit(new TimeSpinBoxLineEdit);
    setRange(0, INT_MAX);
    setAlignment(Qt::AlignRight);
    m_validator = new QRegularExpressionValidator(QRegularExpression(
                                                      "^\\s*(\\d*:){0,2}(\\d*[.;:])?\\d*\\s*$"),
                                                  this);
    setValue(0);
    QFont font = QFontDatabase::systemFont(QFontDatabase::FixedFont);
    font.setPointSize(QGuiApplication::font().pointSize());
    setFont(font);
    setSizePolicy(QSizePolicy::Fixed, QSizePolicy::Fixed);
    setFixedWidth(sizeHint().width());
    setMinimumHeight(sizeHint().height());

    connect(&Settings, &ShotcutSettings::timeFormatChanged, this, [&]() { setValue(value()); });
}

QSize TimeSpinBox::sizeHint() const
{
    QStyleOptionSpinBox option;
    initStyleOption(&option);
    const QSize text(fontMetrics().horizontalAdvance(QStringLiteral("000:00:00.000")) + 8,
                     fontMetrics().height() + 4);
    return style()->sizeFromContents(QStyle::CT_SpinBox, &option, text, this);
}

bool TimeSpinBox::event(QEvent *event)
{
    const bool result = QSpinBox::event(event);
    if (event->type() == QEvent::FontChange || event->type() == QEvent::StyleChange
        || event->type() == QEvent::Polish || event->type() == QEvent::ScreenChangeInternal) {
        // Measure after the style/font changes, in Qt logical pixels. The line edit must
        // fit the entire clock even when the enclosing window or display scale changes.
        setFixedWidth(sizeHint().width());
        setMinimumHeight(sizeHint().height());
        updateGeometry();
    }
    return result;
}

QValidator::State TimeSpinBox::validate(QString &input, int &pos) const
{
    return m_validator->validate(input, pos);
}

int TimeSpinBox::valueFromText(const QString &text) const
{
    if (MLT.producer() && MLT.producer()->is_valid()) {
        return MLT.producer()->time_to_frames(text.toLatin1().constData());
    } else {
        return Mlt::Producer(MLT.profile(), "color", "").time_to_frames(text.toLatin1().constData());
    }
    return 0;
}

QString TimeSpinBox::textFromValue(int val) const
{
    if (MLT.producer() && MLT.producer()->is_valid()) {
        return MLT.producer()->frames_to_time(val, Settings.timeFormat());
    } else {
        return Mlt::Producer(MLT.profile(), "color", "").frames_to_time(val, Settings.timeFormat());
    }
    return QString();
}

void TimeSpinBox::keyPressEvent(QKeyEvent *event)
{
    if (event->key() == Qt::Key_PageUp || event->key() == Qt::Key_PageDown) {
        // Disable page up & page down (step by 10) since those keys are used for other things in Shotcut.
        event->ignore();
        return;
    }
    QSpinBox::keyPressEvent(event);
    if (event->key() == Qt::Key_Enter || event->key() == Qt::Key_Return) {
        event->accept();
        emit accepted();
    }
}

TimeSpinBoxLineEdit::TimeSpinBoxLineEdit(QWidget *parent)
    : QLineEdit(parent)
    , m_selectOnMousePress(false)
{}

void TimeSpinBoxLineEdit::focusInEvent(QFocusEvent *event)
{
    QLineEdit::focusInEvent(event);
    selectAll();
    m_selectOnMousePress = true;
}

void TimeSpinBoxLineEdit::focusOutEvent(QFocusEvent *event)
{
    // QLineEdit::focusOutEvent() calls deselect() on OtherFocusReason,
    // which prevents using the clipboard actions with the text.
    if (event->reason() != Qt::OtherFocusReason)
        QLineEdit::focusOutEvent(event);
}

void TimeSpinBoxLineEdit::mousePressEvent(QMouseEvent *event)
{
    QLineEdit::mousePressEvent(event);
    if (m_selectOnMousePress) {
        selectAll();
        m_selectOnMousePress = false;
    }
}
