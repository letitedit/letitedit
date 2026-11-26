/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The bridge's calls for test windows (LETITEDIT_QA): keys, mouse and widgets driven inside a window, never the real screen.
 * (Split out of claudebridge.cpp; ClaudeBridge is declared in claudebridge.h.)
 */
#include "letitedit/bridge/claudebridge.h"
#include "letitedit/bridge/bridgehelpers.h"
#include "letitedit/panels/musicpicker.h"
#include "letitedit/export/othersizes.h"
#include "letitedit/export/exportchecks.h"
#include "letitedit/airoot.h"
#include "letitedit/panels/aiaudiolibrary.h"
#include "letitedit/bridge/aicollaboration.h"
#include "letitedit/panels/hookpanel.h"
#include "letitedit/panels/myassets.h"
#include "letitedit/panels/mystyle.h"
#include "letitedit/review/reviewmode.h"
#include "letitedit/dialogs/lefeatures.h"
#include "jobqueue.h"
#include "jobs/abstractjob.h"
#include "letitedit/chat/aichatpanel.h"
#include "models/subtitlesselectionmodel.h"
#include "settings.h"
#include <QStandardPaths>
#include <QCryptographicHash>
#include <QLineEdit>
#include <QTextBrowser>
#include <QVBoxLayout>
#include <QFormLayout>
#include <QSpinBox>
#include <QDoubleSpinBox>
#include <QComboBox>
#include <QListWidget>
#include <QPlainTextEdit>
#include <QTabWidget>
#include <QDialogButtonBox>
#include <QMenuBar>
#include <QDateTime>
#include <QPixmap>
#include <QWindow>
#include <qpa/qwindowsysteminterface.h>

#include "Logger.h"
#include "actions.h"
#include "commands/timelinecommands.h"
#include "commands/subtitlecommands.h"
#include "controllers/filtercontroller.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "qmltypes/qmlutilities.h"
#include "videowidget.h"
#include "mltcontroller.h"
#include "player.h"
#include "models/markersmodel.h"
#include "models/attachedfiltersmodel.h"
#include "models/metadatamodel.h"
#include "models/multitrackmodel.h"
#include "models/subtitles.h"
#include "models/subtitlesmodel.h"
#include "qmltypes/qmlfilter.h"
#include "qmltypes/qmlmetadata.h"

#include <QAbstractButton>
#include <QApplication>
#include <QDialog>
#include <QLabel>
#include <QMessageBox>
#include <QDockWidget>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalServer>
#include <QLocalSocket>
#include <QTimer>
#include <QTreeWidget>
#include <QHeaderView>
#include <QUndoStack>
#include <QDir>
#include <QLockFile>
#include <QSaveFile>
#include <QRegularExpression>

using namespace BridgeHelpers;

// QA (LETITEDIT_QA test windows only): a key pressed or released on the editor window through Qt's own key path, the
// shortcut-override stage and the shortcut map included, without the window having to be in front (the push-to-talk
// check never needs the real keyboard or the microphone). type: press | release | tap | deactivate (the window loses
// the keyboard, as when another window comes up). Returns the voice state and whether the 540p preview is on.
QJsonObject ClaudeBridge::qaKey(const QJsonObject &params)
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_key is only for test windows (LETITEDIT_QA)");
    const QString type = params.value("type").toString(QStringLiteral("tap"));
    // an open dialog gets the key, as it would for a person (the window behind it is blocked)
    QWidget *modal = QApplication::activeModalWidget();
    QWindow *window = modal && modal->windowHandle() ? modal->windowHandle() : MAIN.windowHandle();
    // window: another top-level window by its object name (T210: Review's own window); focus: a widget in it to have the
    // keyboard focus first, as if it had been clicked
    if (const QString name = params.value("window").toString(); !name.isEmpty() && !modal) {
        QWidget *top = nullptr;
        for (QWidget *w : QApplication::topLevelWidgets())
            if (w->objectName() == name && w->isVisible())
                top = w;
        if (!top || !top->windowHandle())
            throw BridgeError(QStringLiteral("no open window named %1").arg(name));
        window = top->windowHandle();
        if (const QString focus = params.value("focus").toString(); !focus.isEmpty()) {
            auto target = top->findChild<QWidget *>(focus);
            if (!target)
                throw BridgeError(QStringLiteral("no %1 in %2").arg(focus, name));
            target->setFocus(Qt::MouseFocusReason);
        }
    }
    if (!window)
        throw BridgeError("the editor window has no native window yet");
    qApp->setProperty("letitedit:qaKey", true);
    if (type == QLatin1String("deactivate")) {
        QEvent deactivate(QEvent::WindowDeactivate);
        QCoreApplication::sendEvent(&MAIN, &deactivate);
    } else {
        const QKeySequence seq = QKeySequence::fromString(params.value("key").toString());
        if (seq.isEmpty()) {
            qApp->setProperty("letitedit:qaKey", false);
            throw BridgeError("qa_key needs 'key', e.g. \"F12\"");
        }
        const QKeyCombination k = seq[0];
        const bool repeat = params.value("autorepeat").toBool();
        if (type == QLatin1String("press") || type == QLatin1String("tap"))
            QWindowSystemInterface::handleKeyEvent<QWindowSystemInterface::SynchronousDelivery>(
                window, QEvent::KeyPress, k.key(), k.keyboardModifiers(), params.value("text").toString(), repeat);
        if (type == QLatin1String("release") || type == QLatin1String("tap"))
            QWindowSystemInterface::handleKeyEvent<QWindowSystemInterface::SynchronousDelivery>(
                window, QEvent::KeyRelease, k.key(), k.keyboardModifiers(), QString(), repeat);
    }
    qApp->setProperty("letitedit:qaKey", false);
    QString error;
    QJsonObject out = aiVoiceCommand(&MAIN, QStringLiteral("voice_state"), {}, &error);
    if (QAction *preview = Actions["actionPreview540"])
        out["preview_540"] = preview->isChecked();
    out["active_window"] = QApplication::activeWindow() == &MAIN;
    return out;
}

// QA (LETITEDIT_QA test windows only): the mouse, delivered straight into the window through Qt's own event path, so a
// check never moves the person's real cursor or needs the window on screen. type: press | release | move | click |
// wheel | double. x, y are screen coordinates as UI Automation and the window rectangle report them (a test window sits
// outside every monitor; relative: true counts them from the editor window's own top-left corner); the window under
// that point gets the event (an open popup or modal dialog first). button: left (default) | right | middle. wheel: delta (120 = one notch, up). Returns which window took it and where.
QJsonObject ClaudeBridge::qaMouse(const QJsonObject &params)
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_mouse is only for test windows (LETITEDIT_QA)");
    const QString type = params.value("type").toString(QStringLiteral("click"));
    QPointF global(params.value("x").toDouble(), params.value("y").toDouble());
    if (params.value("relative").toBool()) // x, y from the editor window's outer top-left corner, as the old drag script used
        global += QPointF(MAIN.frameGeometry().topLeft());
    QWindow *window = nullptr;
    if (QWidget *popup = QApplication::activePopupWidget(); popup && popup->windowHandle()
        && popup->windowHandle()->geometry().contains(global.toPoint()))
        window = popup->windowHandle();
    if (!window && QApplication::activeModalWidget() && QApplication::activeModalWidget()->windowHandle()
        && QApplication::activeModalWidget()->windowHandle()->geometry().contains(global.toPoint()))
        window = QApplication::activeModalWidget()->windowHandle();
    if (!window) {
        const auto windows = QGuiApplication::topLevelWindows();
        for (auto *w : windows) {
            if (w->isVisible() && w->geometry().contains(global.toPoint()) && w->type() != Qt::ToolTip) {
                if (!window || window == MAIN.windowHandle()) // a window of its own beats the editor under it
                    window = w;
            }
        }
    }
    if (!window)
        throw BridgeError("no window of this editor is at that point");
    const QString buttonName = params.value("button").toString(QStringLiteral("left"));
    const Qt::MouseButton button = buttonName == QLatin1String("right") ? Qt::RightButton
        : buttonName == QLatin1String("middle")                         ? Qt::MiddleButton
                                                                        : Qt::LeftButton;
    const QPointF local = global - QPointF(window->geometry().topLeft());
    using Sync = QWindowSystemInterface::SynchronousDelivery;
    auto send = [&](QEvent::Type t, Qt::MouseButtons state, Qt::MouseButton b) {
        QWindowSystemInterface::handleMouseEvent<Sync>(window, local, global, state, b, t);
    };
    if (type == QLatin1String("move")) {
        send(QEvent::MouseMove, m_qaButtons, Qt::NoButton);
    } else if (type == QLatin1String("press")) {
        m_qaButtons |= button;
        send(QEvent::MouseButtonPress, m_qaButtons, button);
    } else if (type == QLatin1String("release")) {
        m_qaButtons &= ~Qt::MouseButtons(button);
        send(QEvent::MouseButtonRelease, m_qaButtons, button);
    } else if (type == QLatin1String("click") || type == QLatin1String("double")) {
        send(QEvent::MouseMove, Qt::NoButton, Qt::NoButton);
        for (int i = 0; i < (type == QLatin1String("double") ? 2 : 1); ++i) {
            send(i ? QEvent::MouseButtonDblClick : QEvent::MouseButtonPress, button, button);
            send(QEvent::MouseButtonRelease, Qt::NoButton, button);
        }
        m_qaButtons = Qt::NoButton;
    } else if (type == QLatin1String("wheel")) {
        const int delta = params.value("delta").toInt(120);
        QWindowSystemInterface::handleWheelEvent(window, local, global, QPoint(), QPoint(0, delta));
        QWindowSystemInterface::flushWindowSystemEvents();
    } else {
        throw BridgeError("qa_mouse type is press, release, move, click, double or wheel");
    }
    return QJsonObject{{"window", window->objectName()}, {"title", window->title()}, {"x", local.x()}, {"y", local.y()}};
}

namespace {

QWidget *findQaWidget(const QString &name)
{
    QWidget *w = nullptr;
    for (auto *top : QApplication::topLevelWidgets()) {
        if (!top->isVisible())
            continue;
        if (top->objectName() == name) {
            w = top;
            break;
        }
        for (auto *c : top->findChildren<QWidget *>(name)) {
            if (c->isVisible()) {
                w = c;
                break;
            }
            if (!w)
                w = c;
        }
        if (w && w->isVisible())
            break;
    }
    if (!w)
        throw BridgeError("no widget named '" + name + "'");
    return w;
}

QJsonObject qaWidgetState(QWidget *w, const QString &name, const QString &action, const QJsonValue &value)
{
    QJsonObject out{{"name", name}, {"class", QString::fromLatin1(w->metaObject()->className())},
                    {"visible", w->isVisible()}, {"enabled", w->isEnabled()},
                    {"width", w->width()}, {"height", w->height()}, {"focus", w->hasFocus()}};
    if (w->isWindow())
        out.insert("title", w->windowTitle());
    if (auto *b = qobject_cast<QAbstractButton *>(w)) {
        out.insert("text", b->text());
        out.insert("checked", b->isChecked());
    } else if (auto *l = qobject_cast<QLabel *>(w)) {
        out.insert("text", l->text());
    } else if (auto *e = qobject_cast<QLineEdit *>(w)) {
        out.insert("text", e->text());
        out.insert("placeholder", e->placeholderText());
    } else if (auto *t = qobject_cast<QPlainTextEdit *>(w)) {
        out.insert("text", t->toPlainText());
    } else if (auto *c = qobject_cast<QComboBox *>(w)) {
        out.insert("text", c->currentText());
        out.insert("data", QJsonValue::fromVariant(c->currentData()));
        out.insert("count", c->count());
    } else if (auto *list = qobject_cast<QListWidget *>(w)) {
        out.insert("count", list->count());
        out.insert("current", list->currentRow());
        if (list->currentItem())
            out.insert("text", list->currentItem()->text());
    } else if (auto *browser = qobject_cast<QTextBrowser *>(w)) {
        out.insert("text", browser->toPlainText());
    } else if (auto *menu = qobject_cast<QMenu *>(w)) {
        // a menu: its entries in order (test windows only), and a picture of it
        QJsonArray entries;
        for (QAction *entry : menu->actions())
            entries.append(entry->isSeparator() ? QStringLiteral("-") : entry->text());
        out.insert("actions", entries);
        if (action == QLatin1String("grab") || !value.toString().isEmpty()) {
            menu->ensurePolished();
            menu->resize(menu->sizeHint());
            menu->grab().save(value.toString());
        }
    } else if (name == QLatin1String("aiTerminal")) {
        out.insert("text", static_cast<AiTerminal *>(w)->visibleText());
    } else if (auto *tree = qobject_cast<QTreeWidget *>(w)) {
        // a list of rows (New video's files, T176): each row's text, highlight, check box and where it is on screen
        QJsonArray rows;
        for (int i = 0; i < tree->topLevelItemCount(); ++i) {
            QTreeWidgetItem *item = tree->topLevelItem(i);
            const QRect area = tree->visualItemRect(item);
            const QPoint at = tree->viewport()->mapToGlobal(area.topLeft());
            QJsonObject row{{"text", item->text(0)}, {"selected", item->isSelected()},
                            {"x", at.x()}, {"y", at.y()}, {"width", area.width()}, {"height", area.height()}};
            for (int column = 0; column < tree->columnCount(); ++column) {
                const QVariant check = item->data(column, Qt::CheckStateRole);
                if (check.isValid()) {
                    row.insert("checked", check.toInt() == Qt::Checked);
                    const int left = tree->header()->sectionViewportPosition(column);
                    row.insert("box_x", tree->viewport()->mapToGlobal(QPoint(left + tree->header()->sectionSize(column) / 2, 0)).x());
                }
            }
            rows.append(row);
        }
        out.insert("rows", rows);
        out.insert("count", tree->topLevelItemCount());
    }
    // any widget's own picture (a card's preview, T176), as it is drawn now
    if (action == QLatin1String("grab") && !value.toString().isEmpty() && !qobject_cast<QMenu *>(w)) {
        w->grab().save(value.toString());
        out.insert("width", w->width());
        out.insert("height", w->height());
    }
    QRect area(w->mapToGlobal(QPoint(0, 0)), w->size());
    out.insert("rect", QJsonObject{{"x", area.x()}, {"y", area.y()}, {"width", area.width()}, {"height", area.height()}});
    return out;
}

} // namespace

// QA (test windows only): a widget by object name in any open window - its state, or a click (queued, so a dialog
// it opens doesn't hold the answer), a value set, a row chosen or activated, as a person would.
QJsonValue ClaudeBridge::qaWidget(const QJsonObject &params)
{
    if (!qEnvironmentVariableIsSet("LETITEDIT_QA"))
        throw BridgeError("qa_widget is only for test windows (LETITEDIT_QA)");
    const QString name = requireString(params, "name");
    QWidget *w = findQaWidget(name);
    const QString action = params.value("action").toString(QStringLiteral("state"));
    const QJsonValue value = params.value("value");
    if (action == QLatin1String("click")) {
        auto *b = qobject_cast<QAbstractButton *>(w);
        if (!b)
            throw BridgeError("'" + name + "' is not a button");
        if (!b->isEnabled() || !b->isVisible())
            throw BridgeError("'" + name + "' can't be pressed now");
        QTimer::singleShot(0, b, &QAbstractButton::click);
    } else if (action == QLatin1String("paste") && name == QLatin1String("aiTerminal")) {
        static_cast<AiTerminal *>(w)->paste(value.toString());
    } else if (action == QLatin1String("key") && name == QLatin1String("aiTerminal")) {
        const QString chord = value.toString();
        const bool ctrl = chord.startsWith(QLatin1String("Ctrl+"));
        const bool shift = chord.startsWith(QLatin1String("Shift+"));
        const QString keyName = chord.section(QLatin1Char('+'), -1);
        const int key = keyName == QLatin1String("Enter") ? Qt::Key_Return
            : keyName == QLatin1String("Escape") ? Qt::Key_Escape
            : keyName == QLatin1String("Up") ? Qt::Key_Up
            : keyName == QLatin1String("Down") ? Qt::Key_Down
            : keyName.size() == 1 ? keyName.toUpper().at(0).unicode() : 0;
        if (!key) throw BridgeError("unsupported terminal test key");
        const Qt::KeyboardModifiers modifiers = (ctrl ? Qt::ControlModifier : Qt::NoModifier)
            | (shift ? Qt::ShiftModifier : Qt::NoModifier);
        QCoreApplication::postEvent(w, new QKeyEvent(QEvent::KeyPress, key, modifiers, keyName));
    } else if (action == QLatin1String("set")) {
        if (auto *e = qobject_cast<QLineEdit *>(w))
            e->setText(value.toString());
        else if (auto *t = qobject_cast<QPlainTextEdit *>(w))
            t->setPlainText(value.toString());
        else if (auto *c = qobject_cast<QComboBox *>(w)) {
            int i = c->findData(value.toVariant());
            if (i < 0)
                i = c->findText(value.toString());
            if (i < 0 && value.isDouble())
                i = value.toInt();
            if (i < 0 || i >= c->count())
                throw BridgeError("'" + name + "' has no choice '" + value.toString() + "'");
            c->setCurrentIndex(i);
        } else if (auto *d = qobject_cast<QDoubleSpinBox *>(w))
            d->setValue(value.toDouble());
        else if (auto *n = qobject_cast<QSpinBox *>(w))
            n->setValue(value.toInt());
        else if (auto *b = qobject_cast<QAbstractButton *>(w))
            b->setChecked(value.toBool());
        else if (auto *tabs = qobject_cast<QTabWidget *>(w)) {
            int i = value.isDouble() ? value.toInt() : -1;
            for (int t = 0; t < tabs->count() && i < 0; ++t)
                if (tabs->tabText(t).remove(QLatin1Char('&')) == value.toString())
                    i = t;
            if (i < 0 || i >= tabs->count())
                throw BridgeError("'" + name + "' has no tab '" + value.toString() + "'");
            tabs->setCurrentIndex(i);
        } else
            throw BridgeError("'" + name + "' takes no value");
    } else if (action == QLatin1String("select") || action == QLatin1String("activate")) {
        auto *list = qobject_cast<QListWidget *>(w);
        if (!list)
            throw BridgeError("'" + name + "' is not a list");
        const int row = value.toInt();
        if (row < 0 || row >= list->count())
            throw BridgeError("'" + name + "' has no row " + QString::number(row));
        list->setCurrentRow(row);
        if (action == QLatin1String("activate"))
            QTimer::singleShot(0, list, [list, row]() { emit list->itemDoubleClicked(list->item(row)); });
    } else if (action == QLatin1String("close")) {
        QTimer::singleShot(0, w->window(), &QWidget::close); // the window it is in (a dialog's Close button)
    } else if (action == QLatin1String("focus")) {
        w->window()->activateWindow();
        w->setFocus();
    } else if (action != QLatin1String("state") && action != QLatin1String("grab")) {
        throw BridgeError("action is state, click, set, select, activate, close or grab");
    }
    return qaWidgetState(w, name, action, value);
}
