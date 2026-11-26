/*
 * letitedit: TEST windows stay out of the person's way (T52).
 *
 * What this does, only when LETITEDIT_QA (the journey checks' test windows) or LETITEDIT_OFFSCREEN is set and LETITEDIT_QA_ONSCREEN
 * is not: every top-level window this process makes (the editor, dialogs, message boxes, menus, the splash) is created and kept
 * far outside every monitor, has no taskbar button, and Qt is told the window that comes up is the active one, so focus,
 * shortcuts and dialogs work inside the process. The window is still a real window that is drawn, so Windows' window capture
 * (PrintWindow) and UI Automation still work.
 *
 * What it does NOT do (measured, 3 Nov): stop a window from taking the keyboard focus. On this PC any process may take the
 * foreground; denying the activation here (HCBT_ACTIVATE) left Windows with no active window for as long as a test window
 * lived, and allowing it lets the window take the foreground. Keeping focus where it is needs the test window on another
 * desktop: tools/journey-checks/hidden_desktop.py runs every journey check there by default, and this hook is then not used.
 * The person's own window and a customer's install never set these variables, so none of this runs there.
 */
#ifndef QAOFFSCREEN_H
#define QAOFFSCREEN_H

#include <QtGlobal>

#ifdef Q_OS_WIN
#include <windows.h>

#include <unordered_map>

#include <QApplication>
#include <QEvent>
#include <QObject>
#include <QPointer>
#include <QTimer>
#include <QWidget>
#include <QWindow>
#include <qpa/qwindowsysteminterface.h>

namespace QaOffscreen {

constexpr int kFar = -24000; // far left of and above every monitor (Windows keeps its window arithmetic in 16 bits)

inline bool wanted()
{
    // LETITEDIT_QA: the journey checks' test windows. LETITEDIT_OFFSCREEN: a check or experiment that starts the editor
    // without the other test switches (it gets only this: out of sight, never focused). LETITEDIT_QA_ONSCREEN opts out.
    return (qEnvironmentVariableIsSet("LETITEDIT_QA") || qEnvironmentVariableIsSet("LETITEDIT_OFFSCREEN"))
        && !qEnvironmentVariableIsSet("LETITEDIT_QA_ONSCREEN");
}

inline bool isTopLevel(HWND hwnd)
{
    return !(GetWindowLongPtrW(hwnd, GWL_STYLE) & WS_CHILD);
}

inline LRESULT CALLBACK cbtProc(int code, WPARAM wParam, LPARAM lParam)
{
    if (code == HCBT_CREATEWND) {
        auto *create = reinterpret_cast<CBT_CREATEWNDW *>(lParam);
        CREATESTRUCTW *cs = create ? create->lpcs : nullptr;
        if (cs && !(cs->style & WS_CHILD)) {
            cs->x = kFar;
            cs->y = kFar;
            cs->dwExStyle |= WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW;
        }
    } else if (code == HCBT_ACTIVATE && qEnvironmentVariableIsSet("LETITEDIT_QA_DENY_ACTIVATE")) {
        // Experiment switch only. Denying here left Windows with NO active window (the person's window had already been
        // deactivated) for as long as a test window lived: typing went nowhere. Nothing may try to activate instead: see
        // WS_EX_NOACTIVATE and WA_ShowWithoutActivating below.
        return 1;
    }
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

// Every top-level window of this process is subclassed as it is created, and every move, resize or show that Qt or Windows
// asks for is rewritten (WM_WINDOWPOSCHANGING) before it happens, so a dialog centred on a screen, a menu pulled back inside
// the screen, a maximised window all land far outside it. (A message hook cannot do this: it is not allowed to change the
// message, and dialogs came up on the screen.)
inline std::unordered_map<HWND, WNDPROC> &subclassed()
{
    static std::unordered_map<HWND, WNDPROC> map; // GUI thread only
    return map;
}

inline LRESULT CALLBACK farProc(HWND hwnd, UINT message, WPARAM wParam, LPARAM lParam)
{
    auto &map = subclassed();
    const auto it = map.find(hwnd);
    if (it == map.end())
        return DefWindowProcW(hwnd, message, wParam, lParam);
    const WNDPROC original = it->second;
    if (message == WM_WINDOWPOSCHANGING) {
        auto *pos = reinterpret_cast<WINDOWPOS *>(lParam);
        if (pos) {
            pos->x = kFar;
            pos->y = kFar;
            pos->flags &= ~SWP_NOMOVE;
            pos->flags |= SWP_NOACTIVATE;
        }
    } else if (message == WM_NCDESTROY) {
        map.erase(it);
        SetWindowLongPtrW(hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(original));
    }
    return CallWindowProcW(original, hwnd, message, wParam, lParam);
}

inline LRESULT CALLBACK callWndProc(int code, WPARAM wParam, LPARAM lParam)
{
    if (code == HC_ACTION) {
        const auto *msg = reinterpret_cast<const CWPSTRUCT *>(lParam);
        if (msg && msg->message == WM_NCCREATE && isTopLevel(msg->hwnd) && !subclassed().count(msg->hwnd)) {
            // no taskbar button, no Alt+Tab entry, never activated by a click (CREATESTRUCT's ex-style is not honoured)
            const LONG_PTR ex = GetWindowLongPtrW(msg->hwnd, GWL_EXSTYLE);
            SetWindowLongPtrW(msg->hwnd, GWL_EXSTYLE, ex | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE);
            const LONG_PTR original = GetWindowLongPtrW(msg->hwnd, GWLP_WNDPROC);
            subclassed()[msg->hwnd] = reinterpret_cast<WNDPROC>(original);
            SetWindowLongPtrW(msg->hwnd, GWLP_WNDPROC, reinterpret_cast<LONG_PTR>(&farProc));
        }
    }
    return CallNextHookEx(nullptr, code, wParam, lParam);
}

// Qt does not learn about an activation Windows never made, so it is told: the window that comes up is the active one.
class Activator : public QObject
{
public:
    using QObject::QObject;

protected:
    bool eventFilter(QObject *watched, QEvent *event) override
    {
        if (event->type() == QEvent::Polish) {
            // before the native window exists: shown without activation (SW_SHOWNOACTIVATE), never asking for the foreground
            auto *widget = qobject_cast<QWidget *>(watched);
            if (widget && widget->isWindow())
                widget->setAttribute(Qt::WA_ShowWithoutActivating);
        }
        if (event->type() == QEvent::Show) {
            auto *widget = qobject_cast<QWidget *>(watched);
            if (widget && widget->isWindow()) {
                const Qt::WindowType type = widget->windowType();
                if (type == Qt::Window || type == Qt::Dialog) {
                    QPointer<QWidget> guard(widget);
                    QTimer::singleShot(0, widget, [guard]() {
                        if (guard && guard->isVisible() && guard->windowHandle())
                            QWindowSystemInterface::handleFocusWindowChanged(guard->windowHandle(),
                                                                             Qt::ActiveWindowFocusReason);
                    });
                }
            }
        }
        return false;
    }
};

// Call once on the GUI thread, before the first window is made.
inline void install(QApplication &app)
{
    if (!wanted())
        return;
    const DWORD thread = GetCurrentThreadId();
    SetWindowsHookExW(WH_CBT, cbtProc, nullptr, thread);
    SetWindowsHookExW(WH_CALLWNDPROC, callWndProc, nullptr, thread);
    app.installEventFilter(new Activator(&app));
    app.setProperty("letitedit:qaOffscreen", true);
}

} // namespace QaOffscreen
#else
namespace QaOffscreen {
inline bool wanted() { return false; }
}
#endif

#endif // QAOFFSCREEN_H
