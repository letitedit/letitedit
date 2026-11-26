/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#include "letitedit/chat/aiterminal.h"
#include "letitedit/airoot.h"
#include "Logger.h"
#include <QElapsedTimer>
#include <QApplication>
#include <QClipboard>
#include <QContextMenuEvent>
#include <QFontDatabase>
#include <QFontMetrics>
#include <QKeyEvent>
#include <QMenu>
#include <QMouseEvent>
#include <QPainter>
#include <QPointer>
#include <QProcessEnvironment>
#include <QRegularExpression>
#include <QResizeEvent>
#include <QTimer>
#include <QWheelEvent>
#include <algorithm>
#include <thread>
#include <QVector>
extern "C" {
#include "vterm.h"
}
#ifdef Q_OS_WIN
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN 1
#endif
#ifndef NOMINMAX
#define NOMINMAX 1
#endif
#include <windows.h>
#include <processthreadsapi.h>
#endif

namespace {
constexpr int maxHistory = 5000;
QString quoted(const QString &arg)
{
    // Windows CreateProcess quoting, including backslashes immediately before a quote.
    if (!arg.contains(QRegularExpression(QStringLiteral("[\\s\"]"))))
        return arg;
    QString result = QStringLiteral("\"");
    int slashes = 0;
    for (QChar c : arg) {
        if (c == QLatin1Char('\\')) { ++slashes; continue; }
        if (c == QLatin1Char('"')) result += QString(slashes * 2 + 1, QLatin1Char('\\'));
        else result += QString(slashes, QLatin1Char('\\'));
        slashes = 0;
        result += c;
    }
    result += QString(slashes * 2, QLatin1Char('\\')) + QLatin1Char('"');
    return result;
}
}

struct AiTerminal::Private
{
    explicit Private(AiTerminal *widget) : owner(widget) {}
    using Line = QVector<VTermScreenCell>;
    AiTerminal *owner;
    VTerm *m_vt = nullptr;
    VTermScreen *m_screen = nullptr;
    VTermScreenCallbacks m_callbacks{}; // libvterm retains this pointer for the screen's lifetime
    qint64 m_receivedBytes = 0, m_sentBytes = 0;
    std::function<bool(QString *)> m_submitHook;
    int m_typed = 0;      // what the person has typed in the AI's box since the last Enter
    QChar m_typedFirst;
    QTimer *m_exitTimer = nullptr;
    bool m_exitNotified = false;
    QVector<Line> m_history;
    int m_offset = 0;
    int m_rows = 24, m_cols = 80;
    int m_cellW = 9, m_cellH = 18, m_ascent = 14;
    VTermPos m_cursor{0, 0};
    bool m_cursorVisible = true;
    bool m_selecting = false;
    int m_generation = 0;
    QPoint m_anchor, m_selection;
#ifdef Q_OS_WIN
    HPCON m_pty = nullptr;
    HANDLE m_input = nullptr, m_output = nullptr, m_process = nullptr;
    std::thread m_reader;
#endif
    QColor color(VTermColor value, bool foreground) const;
    QString cellText(const VTermScreenCell &cell) const;
    static int onScroll(int cols, const VTermScreenCell *cells, void *user);
    static int onCursor(VTermPos pos, VTermPos oldpos, int visible, void *user);
    static int onDamage(VTermRect rect, void *user);
};

AiTerminal::AiTerminal(QWidget *parent) : QWidget(parent), d(std::make_unique<Private>(this))
{
    d->m_exitTimer = new QTimer(this);
    d->m_exitTimer->setInterval(200);
    connect(d->m_exitTimer, &QTimer::timeout, this, [this]() {
#ifdef Q_OS_WIN
        if (!d->m_process || d->m_exitNotified) return;
        DWORD code = STILL_ACTIVE;
        if (GetExitCodeProcess(d->m_process, &code) && code != STILL_ACTIVE) {
            d->m_exitNotified = true;
            d->m_exitTimer->stop();
            if (exited) exited(int(code));
        }
#endif
    });
    setObjectName(QStringLiteral("aiTerminal"));
    setFocusPolicy(Qt::StrongFocus);
    setAttribute(Qt::WA_InputMethodEnabled);
    setMouseTracking(true);
    setAutoFillBackground(false);
    static const int bundledFont = QFontDatabase::addApplicationFont(
        aiRootPath(QStringLiteral("fonts/library/JetBrains Mono/JetBrainsMono[wght].ttf")));
    const QString family = bundledFont >= 0 && !QFontDatabase::applicationFontFamilies(bundledFont).isEmpty()
        ? QFontDatabase::applicationFontFamilies(bundledFont).first() : QStringLiteral("JetBrains Mono");
    QFont font(family, 10);
    font.setStyleHint(QFont::Monospace);
    font.setFixedPitch(true);
    setFont(font);
    const QFontMetrics fm(font);
    d->m_cellW = qMax(1, fm.horizontalAdvance(QLatin1Char('M')));
    d->m_cellH = qMax(1, fm.height() + 2);
    d->m_ascent = fm.ascent() + 1;
    d->m_vt = vterm_new(d->m_rows, d->m_cols);
    vterm_set_utf8(d->m_vt, 1);
    d->m_screen = vterm_obtain_screen(d->m_vt);
    d->m_callbacks.damage = Private::onDamage;
    d->m_callbacks.movecursor = Private::onCursor;
    d->m_callbacks.sb_pushline = Private::onScroll;
    vterm_screen_set_callbacks(d->m_screen, &d->m_callbacks, d.get());
    vterm_screen_enable_altscreen(d->m_screen, 1);
    vterm_screen_set_damage_merge(d->m_screen, VTERM_DAMAGE_SCREEN);
    VTermColor fg, bg;
    vterm_color_rgb(&fg, 244, 239, 230);
    vterm_color_rgb(&bg, 22, 26, 29);
    vterm_screen_set_default_colors(d->m_screen, &fg, &bg);
    const QColor palette[] = {
        {22, 26, 29}, {200, 101, 59}, {64, 162, 136}, {214, 167, 90},
        {112, 162, 205}, {182, 142, 194}, {82, 177, 179}, {244, 239, 230},
        {112, 120, 124}, {229, 130, 86}, {116, 207, 168}, {242, 196, 113},
        {152, 191, 229}, {211, 166, 220}, {123, 213, 208}, {255, 251, 243},
    };
    for (int i = 0; i < 16; ++i) {
        VTermColor indexed;
        vterm_color_rgb(&indexed, palette[i].red(), palette[i].green(), palette[i].blue());
        vterm_state_set_palette_color(vterm_obtain_state(d->m_vt), i, &indexed);
    }
    vterm_screen_reset(d->m_screen, 1);
}

AiTerminal::~AiTerminal()
{
    stop();
    if (d->m_vt) vterm_free(d->m_vt);
}

int AiTerminal::Private::onScroll(int cols, const VTermScreenCell *cells, void *user)
{
    auto *self = static_cast<Private *>(user);
    Line line;
    line.reserve(cols);
    for (int i = 0; i < cols; ++i) line.append(cells[i]);
    self->m_history.append(line);
    if (self->m_history.size() > maxHistory) self->m_history.remove(0, self->m_history.size() - maxHistory);
    if (self->m_offset) self->m_offset = qMin(self->m_offset + 1, int(self->m_history.size()));
    return 1;
}
int AiTerminal::Private::onCursor(VTermPos pos, VTermPos, int visible, void *user)
{
    auto *self = static_cast<Private *>(user);
    self->m_cursor = pos;
    self->m_cursorVisible = visible;
    return 1;
}
int AiTerminal::Private::onDamage(VTermRect, void *user)
{
    static_cast<Private *>(user)->owner->update();
    return 1;
}

void AiTerminal::dimensions()
{
    const int cols = qMax(20, width() / d->m_cellW), rows = qMax(5, height() / d->m_cellH);
    if (cols == d->m_cols && rows == d->m_rows) return;
    d->m_cols = cols; d->m_rows = rows;
    vterm_set_size(d->m_vt, rows, cols);
#ifdef Q_OS_WIN
    if (d->m_pty) ResizePseudoConsole(d->m_pty, COORD{SHORT(cols), SHORT(rows)});
#endif
    update();
}
void AiTerminal::resizeEvent(QResizeEvent *event)
{
    QWidget::resizeEvent(event);
    dimensions();
}
QColor AiTerminal::Private::color(VTermColor value, bool foreground) const
{
    if (foreground && VTERM_COLOR_IS_DEFAULT_FG(&value)) return QColor(244, 239, 230);
    if (!foreground && VTERM_COLOR_IS_DEFAULT_BG(&value)) return QColor(22, 26, 29);
    vterm_screen_convert_color_to_rgb(m_screen, &value);
    return QColor(value.rgb.red, value.rgb.green, value.rgb.blue);
}
QString AiTerminal::Private::cellText(const VTermScreenCell &cell) const
{
    QString result;
    for (uint32_t cp : cell.chars) {
        if (!cp) break;
        const char32_t scalar = char32_t(cp);
        result += QString::fromUcs4(&scalar, 1);
    }
    return result;
}
void AiTerminal::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    p.fillRect(rect(), QColor(22, 26, 29));
    const int historyStart = d->m_history.size() - d->m_offset;
    for (int row = 0; row < d->m_rows; ++row) {
        const int virtualRow = historyStart + row;
        const bool old = virtualRow < d->m_history.size();
        for (int col = 0; col < d->m_cols; ++col) {
            VTermScreenCell cell{};
            if (old) {
                if (col < d->m_history[virtualRow].size()) cell = d->m_history[virtualRow][col];
            } else if (virtualRow - d->m_history.size() < d->m_rows) {
                vterm_screen_get_cell(d->m_screen, VTermPos{virtualRow - int(d->m_history.size()), col}, &cell);
            }
            QColor fg = d->color(cell.fg, true), bg = d->color(cell.bg, false);
            if (cell.attrs.reverse) std::swap(fg, bg);
            const QRect r(col * d->m_cellW, row * d->m_cellH, d->m_cellW * qMax(1, int(cell.width)), d->m_cellH);
            if (bg != QColor(22, 26, 29)) p.fillRect(r, bg);
            QPoint from = d->m_anchor, to = d->m_selection;
            if (from.y() > to.y() || (from.y() == to.y() && from.x() > to.x())) std::swap(from, to);
            const bool afterStart = virtualRow > from.y() || (virtualRow == from.y() && col >= from.x());
            const bool beforeEnd = virtualRow < to.y() || (virtualRow == to.y() && col <= to.x());
            const bool selected = d->m_selecting && afterStart && beforeEnd;
            if (selected) p.fillRect(r, QColor(42, 133, 139, 120));
            const QString glyph = d->cellText(cell);
            if (!glyph.isEmpty()) {
                QFont f = font(); f.setBold(cell.attrs.bold); f.setItalic(cell.attrs.italic);
                p.setFont(f); p.setPen(fg); p.drawText(r.left(), r.top() + d->m_ascent, glyph);
                if (cell.attrs.underline) p.drawLine(r.bottomLeft(), r.bottomRight());
            }
        }
    }
    if (!d->m_offset && d->m_cursorVisible && hasFocus()) {
        p.fillRect(QRect(d->m_cursor.col * d->m_cellW, d->m_cursor.row * d->m_cellH + d->m_cellH - 2, d->m_cellW, 2), QColor(200, 101, 59));
    }
}
void AiTerminal::receive(const QByteArray &bytes)
{
    if (!d->m_vt) return;
    d->m_receivedBytes += bytes.size();
    vterm_input_write(d->m_vt, bytes.constData(), size_t(bytes.size()));
    vterm_screen_flush_damage(d->m_screen);
    output();
    update();
}
void AiTerminal::output()
{
    char data[4096];
    size_t count;
    while ((count = vterm_output_read(d->m_vt, data, sizeof(data))) != 0) send(QByteArray(data, qsizetype(count)));
}
bool AiTerminal::running() const
{
#ifdef Q_OS_WIN
    if (!d->m_process) return false;
    DWORD code = 0;
    return GetExitCodeProcess(d->m_process, &code) && code == STILL_ACTIVE;
#else
    return false;
#endif
}

bool AiTerminal::start(const QString &program, const QStringList &arguments, const QString &workDir, QString *error,
                       const QStringList &extraEnvironment)
{
    stop();
    d->m_history.clear(); d->m_offset = 0;
    vterm_screen_reset(d->m_screen, 1);
    dimensions();
#ifdef Q_OS_WIN
    HANDLE ptyInput = nullptr, ptyOutput = nullptr;
    auto fail = [&](const QString &what) {
        if (error) *error = what + QStringLiteral(" (Windows error %1)").arg(GetLastError());
        if (ptyInput) CloseHandle(ptyInput);
        if (ptyOutput) CloseHandle(ptyOutput);
        stop();
        return false;
    };
    if (!CreatePipe(&ptyInput, &d->m_input, nullptr, 0) || !CreatePipe(&d->m_output, &ptyOutput, nullptr, 0))
        return fail(QStringLiteral("The program screen could not start on this PC. Use Chat bubbles instead (AI settings, at the top of this panel)."));
    const HRESULT hr = CreatePseudoConsole(COORD{SHORT(d->m_cols), SHORT(d->m_rows)}, ptyInput, ptyOutput, 0, &d->m_pty);
    if (FAILED(hr)) return fail(QStringLiteral("The program screen could not start on this PC (code %1). Use Chat bubbles instead (AI settings, at the top of this panel).").arg(uint(hr)));
    SIZE_T attrSize = 0;
    InitializeProcThreadAttributeList(nullptr, 1, 0, &attrSize);
    auto *attrs = static_cast<PPROC_THREAD_ATTRIBUTE_LIST>(HeapAlloc(GetProcessHeap(), 0, attrSize));
    if (!attrs) return fail(QStringLiteral("The program screen could not start on this PC. Use Chat bubbles instead (AI settings, at the top of this panel)."));
    bool attrsReady = InitializeProcThreadAttributeList(attrs, 1, 0, &attrSize);
    if (attrsReady) attrsReady = UpdateProcThreadAttribute(attrs, 0, PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE, d->m_pty, sizeof(d->m_pty), nullptr, nullptr);
    if (!attrsReady) { HeapFree(GetProcessHeap(), 0, attrs); return fail(QStringLiteral("The program screen could not start on this PC. Use Chat bubbles instead (AI settings, at the top of this panel).")); }
    STARTUPINFOEXW startup{};
    startup.StartupInfo.cb = sizeof(startup);
    // A GUI parent can carry stale std handles. Asking for standard handles
    // with empty fields lets Windows supply CONIN$/CONOUT$ from this ConPTY.
    startup.StartupInfo.dwFlags = STARTF_USESTDHANDLES;
    startup.lpAttributeList = attrs;
    PROCESS_INFORMATION process{};
    QStringList command{quoted(program)};
    for (const QString &arg : arguments) command << quoted(arg);
    std::wstring line = command.join(QLatin1Char(' ')).toStdWString(); line.push_back(L'\0');
    QStringList env = QProcessEnvironment::systemEnvironment().toStringList();
    env.erase(std::remove_if(env.begin(), env.end(), [](const QString &e) {
        return e.startsWith(QLatin1String("CODEX_THREAD_ID="), Qt::CaseInsensitive)
            || e.startsWith(QLatin1String("LETITEDIT_OWNER="), Qt::CaseInsensitive)
            || e.startsWith(QLatin1String("TERM="), Qt::CaseInsensitive)
            || e.startsWith(QLatin1String("COLORTERM="), Qt::CaseInsensitive);
    }), env.end());
    for (const QString &extra : extraEnvironment) {
        const QString name = extra.section(QLatin1Char('='), 0, 0) + QLatin1Char('=');
        env.erase(std::remove_if(env.begin(), env.end(), [&name](const QString &e) {
            return e.startsWith(name, Qt::CaseInsensitive);
        }), env.end());
    }
    env << extraEnvironment;
    env << QStringLiteral("TERM=xterm-256color") << QStringLiteral("COLORTERM=truecolor");
    std::wstring environment;
    for (const QString &value : env) { environment += value.toStdWString(); environment.push_back(L'\0'); }
    environment.push_back(L'\0');
    const std::wstring cwd = workDir.toStdWString();
    // CREATE_NO_WINDOW can suppress console attachment and bypass ConPTY's
    // pipes. The pseudo-console attribute owns the console without a new window.
    const BOOL ok = CreateProcessW(nullptr, line.data(), nullptr, nullptr, FALSE,
                                   EXTENDED_STARTUPINFO_PRESENT | CREATE_UNICODE_ENVIRONMENT,
                                   environment.data(), cwd.c_str(), &startup.StartupInfo, &process);
    DeleteProcThreadAttributeList(attrs); HeapFree(GetProcessHeap(), 0, attrs);
    if (!ok) return fail(QStringLiteral("Could not start %1").arg(program));
    // Keep the PTY-side pipe handles alive through CreateProcess. The console
    // host takes its own references while attaching the child process.
    CloseHandle(ptyInput); ptyInput = nullptr;
    CloseHandle(ptyOutput); ptyOutput = nullptr;
    CloseHandle(process.hThread); d->m_process = process.hProcess;
    QPointer<AiTerminal> self(this);
    const HANDLE output = d->m_output;
    const int generation = ++d->m_generation;
    d->m_reader = std::thread([self, output, processHandle = d->m_process, generation]() {
        char bytes[8192]; DWORD count = 0;
        while (ReadFile(output, bytes, sizeof(bytes), &count, nullptr) && count) {
            const QByteArray part(bytes, int(count));
            if (self) QMetaObject::invokeMethod(self, [self, part, generation]() {
                if (self && self->d->m_generation == generation) self->receive(part);
            }, Qt::QueuedConnection);
        }
        DWORD code = 1; GetExitCodeProcess(processHandle, &code);
        if (self) QMetaObject::invokeMethod(self, [self, code, generation]() {
            if (self && self->d->m_generation == generation && !self->d->m_exitNotified) {
                self->d->m_exitNotified = true;
                self->d->m_exitTimer->stop();
                if (self->exited) self->exited(int(code));
            }
        }, Qt::QueuedConnection);
    });
    d->m_exitNotified = false;
    d->m_exitTimer->start();
    return true;
#else
    Q_UNUSED(program) Q_UNUSED(arguments) Q_UNUSED(workDir)
    if (error) *error = QStringLiteral("The program screen needs Windows 10 or later. Use Chat bubbles instead (AI settings, at the top of this panel).");
    return false;
#endif
}
void AiTerminal::stop()
{
    if (d->m_exitTimer) d->m_exitTimer->stop();
#ifdef Q_OS_WIN
    // Ask first: Ctrl+C twice is how a person leaves Claude Code or Codex, and it lets the program finish what it is doing to
    // its own files (an update it runs by itself can leave it unable to start if it is cut off). Only then force it.
    if (d->m_process && running()) {
        QElapsedTimer asked;
        asked.start();
        send(QByteArray("\x03"));
        DWORD waited = WaitForSingleObject(d->m_process, 300);
        if (waited == WAIT_TIMEOUT) {
            send(QByteArray("\x03"));
            waited = WaitForSingleObject(d->m_process, 1200);
        }
        if (waited == WAIT_TIMEOUT) {
            send(QByteArray("\x03"));
            waited = WaitForSingleObject(d->m_process, 1500);
        }
        LOG_INFO() << "AI terminal stopped:" << (waited == WAIT_TIMEOUT ? "forced after" : "it exited itself in") << asked.elapsed() << "ms";
    }
    ++d->m_generation;
    if (d->m_process && running()) TerminateProcess(d->m_process, 1);
    if (d->m_pty) { ClosePseudoConsole(d->m_pty); d->m_pty = nullptr; }
    if (d->m_reader.joinable()) d->m_reader.join();
    if (d->m_input) { CloseHandle(d->m_input); d->m_input = nullptr; }
    if (d->m_output) { CloseHandle(d->m_output); d->m_output = nullptr; }
    if (d->m_process) { CloseHandle(d->m_process); d->m_process = nullptr; }
#endif
}
void AiTerminal::send(const QByteArray &bytes)
{
#ifdef Q_OS_WIN
    if (d->m_input && running()) {
        DWORD written = 0;
        if (WriteFile(d->m_input, bytes.constData(), DWORD(bytes.size()), &written, nullptr)) d->m_sentBytes += written;
    }
#else
    Q_UNUSED(bytes)
#endif
}
qint64 AiTerminal::receivedBytes() const { return d->m_receivedBytes; }
qint64 AiTerminal::sentBytes() const { return d->m_sentBytes; }
void AiTerminal::paste(const QString &text)
{
    // libvterm knows whether the running TUI enabled bracketed paste.
    vterm_keyboard_start_paste(d->m_vt); output();
    send(text.toUtf8());
    vterm_keyboard_end_paste(d->m_vt); output();
}
void AiTerminal::submit(const QString &text)
{
    paste(text);
    // TUIs process a bracketed paste on their UI loop. An immediate Enter can
    // arrive before the pasted composer has been committed (Codex keeps it in
    // the input box), so submit after the loop has had a moment to catch up.
    const int generation = d->m_generation;
    // letters and digits only: a narrow panel wraps the text and the box adds its own marks
    const auto bare = [](const QString &in) {
        QString out;
        for (const QChar c : in)
            if (c.isLetterOrNumber())
                out += c;
        return out;
    };
    const QString lastWords = bare(text).right(24);
    auto press = std::make_shared<std::function<void(int)>>();
    *press = [this, generation, press, bare, lastWords](int tries) {
        if (d->m_generation != generation || !running()) {
            *press = nullptr; // let go of the lambda that holds itself
            return;
        }
        vterm_keyboard_key(d->m_vt, VTERM_KEY_ENTER, VTERM_MOD_NONE);
        output();
        if (tries <= 0) {
            *press = nullptr;
            return;
        }
        // A TUI still starting up can swallow the Enter and leave the request sitting in its input box (seen with
        // Codex). If the pasted text is still in the box, press Enter again. Never while a question is on screen.
        QTimer::singleShot(2500, this, [this, generation, press, tries, bare, lastWords]() {
            if (d->m_generation != generation || !running()) {
                *press = nullptr;
                return;
            }
            const QString screen = visibleText();
            const bool asking = screen.contains(QStringLiteral("Do you want"))
                                || screen.contains(QStringLiteral("Would you like"));
            QStringList lines = screen.split(QLatin1Char('\n'), Qt::SkipEmptyParts);
            bool held = false;
            for (int i = qMax(0, lines.size() - 8); i < lines.size(); ++i) {
                const QString line = lines[i];
                const bool box = line.startsWith(QLatin1Char('>')) || line.startsWith(QChar(0x203A))
                                 || line.startsWith(QChar(0x276F)) || line.startsWith(QChar(0x2502));
                if (box && (line.contains(QStringLiteral("[Pasted Content")) || line.contains(QStringLiteral("[Pasted text"))))
                    held = true;
            }
            // or the end of the message itself, still at the bottom of the screen and nothing running (a message Codex shows in
            // full, in a Live Review note on a small panel: seen on GPT-6 Luna)
            const QString bottom = bare(lines.mid(qMax(0, lines.size() - 8)).join(QString()));
            const bool working = screen.contains(QStringLiteral("esc to interrupt")) || screen.contains(QStringLiteral("Working"))
                                 || screen.contains(QStringLiteral("esc to cancel"));
            if (!held && !working && !lastWords.isEmpty() && bottom.contains(lastWords))
                held = true;
            if (held && !asking)
                (*press)(tries - 1);
            else
                *press = nullptr;
        });
    };
    QTimer::singleShot(1000, this, [press]() {
        if (*press)
            (*press)(4);
    });
}
void AiTerminal::interrupt() { vterm_keyboard_unichar(d->m_vt, 'c', VTERM_MOD_CTRL); output(); }
void AiTerminal::setSubmitHook(std::function<bool(QString *extra)> hook) { d->m_submitHook = std::move(hook); }
// What's typed here is for the program on this screen. Without this the editor's own one-letter shortcuts took those keys first:
// typing "split it" lost its s, p and i, and split and trimmed a clip. Function keys and Alt or Ctrl+Shift chords still reach the
// window (Hold to talk, say).
bool AiTerminal::event(QEvent *event)
{
    if (event->type() == QEvent::ShortcutOverride) {
        auto *key = static_cast<QKeyEvent *>(event);
        const Qt::KeyboardModifiers mods = key->modifiers() & ~Qt::KeypadModifier;
        const bool chord = (mods & Qt::AltModifier) || (mods & Qt::MetaModifier)
                           || ((mods & Qt::ControlModifier) && (mods & Qt::ShiftModifier));
        const bool functionKey = key->key() >= Qt::Key_F1 && key->key() <= Qt::Key_F35;
        if (!chord && !functionKey) {
            event->accept();
            return true;
        }
    }
    return QWidget::event(event);
}
void AiTerminal::keyPressEvent(QKeyEvent *event)
{
    const bool ctrl = event->modifiers() & Qt::ControlModifier;
    const bool shift = event->modifiers() & Qt::ShiftModifier;
    if (ctrl && shift && event->key() == Qt::Key_C) { QApplication::clipboard()->setText(selectionText()); return; }
    if (ctrl && event->key() == Qt::Key_V) {
        const QString text = QApplication::clipboard()->text();
        if (d->m_typed == 0 && !text.isEmpty())
            d->m_typedFirst = text.at(0);
        d->m_typed += int(text.size());
        paste(text);
        return;
    }
    // T99: the person's own message going off in the AI's box, not a slash command or an answer to a question on screen
    if ((event->key() == Qt::Key_Return || event->key() == Qt::Key_Enter) && event->modifiers() == Qt::NoModifier) {
        const int typed = d->m_typed;
        const QChar first = d->m_typedFirst;
        if (typed > 0 && d->m_submitHook && first != QLatin1Char('/') && first != QLatin1Char('!')) {
            const QStringList lines = visibleText().split(QLatin1Char('\n'), Qt::SkipEmptyParts);
            bool box = false, command = false, asking = false;
            for (int i = qMax(0, int(lines.size()) - 10); i < lines.size(); ++i) {
                const QString &line = lines[i];
                asking = asking || line.contains(QStringLiteral("Do you want")) || line.contains(QStringLiteral("Would you like"));
                if (line.startsWith(QLatin1Char('>')) || line.startsWith(QChar(0x203A)) || line.startsWith(QChar(0x276F))
                    || line.startsWith(QChar(0x2502))) {
                    box = true;
                    QString words = line;
                    while (!words.isEmpty() && !words.at(0).isLetterOrNumber() && words.at(0) != QLatin1Char('/'))
                        words.remove(0, 1);
                    command = words.startsWith(QLatin1Char('/'));
                }
            }
            // A short answer to a question on the screen is left alone; words are a message, whatever the AI last said.
            if (box && !command && !(asking && typed <= 1)) {
                QString extra;
                if (!d->m_submitHook(&extra)) {
                    event->accept();
                    return;
                }
                if (!extra.isEmpty()) {
                    d->m_typed = 0;
                    d->m_typedFirst = QChar();
                    submit(QStringLiteral("\n\n") + extra);
                    event->accept();
                    return;
                }
            }
        }
        d->m_typed = 0;
        d->m_typedFirst = QChar();
    } else if (event->key() == Qt::Key_Backspace) {
        d->m_typed = qMax(0, d->m_typed - 1);
    } else if (event->key() == Qt::Key_Escape) {
        d->m_typed = 0;
        d->m_typedFirst = QChar();
    } else if (!ctrl && !event->text().isEmpty() && event->text().at(0).isPrint()) {
        if (d->m_typed == 0)
            d->m_typedFirst = event->text().at(0);
        d->m_typed += int(event->text().size());
    }
    const VTermModifier mod = VTermModifier((shift ? VTERM_MOD_SHIFT : 0) |
                                            (ctrl ? VTERM_MOD_CTRL : 0) |
                                            ((event->modifiers() & Qt::AltModifier) ? VTERM_MOD_ALT : 0));
    VTermKey key = VTERM_KEY_NONE;
    switch (event->key()) {
    case Qt::Key_Return: case Qt::Key_Enter: key = VTERM_KEY_ENTER; break;
    case Qt::Key_Tab: key = VTERM_KEY_TAB; break;
    case Qt::Key_Backspace: key = VTERM_KEY_BACKSPACE; break;
    case Qt::Key_Escape: key = VTERM_KEY_ESCAPE; break;
    case Qt::Key_Up: key = VTERM_KEY_UP; break;
    case Qt::Key_Down: key = VTERM_KEY_DOWN; break;
    case Qt::Key_Left: key = VTERM_KEY_LEFT; break;
    case Qt::Key_Right: key = VTERM_KEY_RIGHT; break;
    case Qt::Key_Home: key = VTERM_KEY_HOME; break;
    case Qt::Key_End: key = VTERM_KEY_END; break;
    case Qt::Key_PageUp: key = VTERM_KEY_PAGEUP; break;
    case Qt::Key_PageDown: key = VTERM_KEY_PAGEDOWN; break;
    case Qt::Key_Delete: key = VTERM_KEY_DEL; break;
    default: break;
    }
    if (key != VTERM_KEY_NONE) vterm_keyboard_key(d->m_vt, key, mod);
    else if (ctrl && event->key() >= Qt::Key_A && event->key() <= Qt::Key_Z)
        vterm_keyboard_unichar(d->m_vt, uint32_t('a' + event->key() - Qt::Key_A), mod);
    else if (!event->text().isEmpty()) for (uint32_t cp : event->text().toUcs4()) vterm_keyboard_unichar(d->m_vt, cp, mod);
    else { QWidget::keyPressEvent(event); return; }
    output(); event->accept();
}
void AiTerminal::wheelEvent(QWheelEvent *event)
{
    d->m_offset = qBound(0, d->m_offset + event->angleDelta().y() / 120 * 3, int(d->m_history.size()));
    update(); event->accept();
}
void AiTerminal::mousePressEvent(QMouseEvent *event)
{
    setFocus();
    if (event->button() == Qt::MiddleButton) { paste(QApplication::clipboard()->text()); return; }
    if (event->button() != Qt::LeftButton) return;
    const int virtualRow = d->m_history.size() - d->m_offset + event->pos().y() / d->m_cellH;
    d->m_anchor = QPoint(qBound(0, event->pos().x() / d->m_cellW, d->m_cols - 1), virtualRow);
    d->m_selection = d->m_anchor; d->m_selecting = true; update();
}
void AiTerminal::mouseMoveEvent(QMouseEvent *event)
{
    if (!d->m_selecting) return;
    const int virtualRow = d->m_history.size() - d->m_offset + event->pos().y() / d->m_cellH;
    d->m_selection = QPoint(qBound(0, event->pos().x() / d->m_cellW, d->m_cols - 1), virtualRow);
    update();
}
void AiTerminal::mouseReleaseEvent(QMouseEvent *event)
{
    if (event->button() != Qt::LeftButton || !d->m_selecting) return;
    if (d->m_anchor != d->m_selection) QApplication::clipboard()->setText(selectionText());
    d->m_selecting = false; update();
}
QString AiTerminal::selectionText() const
{
    QPoint from = d->m_anchor, to = d->m_selection;
    if (from.y() > to.y() || (from.y() == to.y() && from.x() > to.x())) std::swap(from, to);
    QStringList lines;
    for (int row = from.y(); row <= to.y(); ++row) {
        QString line;
        for (int col = row == from.y() ? from.x() : 0; col <= (row == to.y() ? to.x() : d->m_cols - 1); ++col) {
            VTermScreenCell cell{};
            if (row < d->m_history.size()) { if (col < d->m_history[row].size()) cell = d->m_history[row][col]; }
            else if (row - d->m_history.size() < d->m_rows)
                vterm_screen_get_cell(d->m_screen, VTermPos{row - int(d->m_history.size()), col}, &cell);
            const QString glyph = d->cellText(cell);
            line += glyph.isEmpty() ? QStringLiteral(" ") : glyph;
        }
        lines << line.trimmed();
    }
    return lines.join(QLatin1Char('\n'));
}
QString AiTerminal::visibleText() const
{
    QStringList lines;
    for (int row = 0; row < d->m_rows; ++row) {
        QString line;
        for (int col = 0; col < d->m_cols; ++col) {
            VTermScreenCell cell{};
            vterm_screen_get_cell(d->m_screen, VTermPos{row, col}, &cell);
            const QString glyph = d->cellText(cell);
            line += glyph.isEmpty() ? QStringLiteral(" ") : glyph;
        }
        lines << line.trimmed();
    }
    return lines.join(QLatin1Char('\n'));
}
void AiTerminal::contextMenuEvent(QContextMenuEvent *event)
{
    QMenu menu(this);
    menu.addAction(QStringLiteral("Copy"), this, [this]() { QApplication::clipboard()->setText(selectionText()); });
    menu.addAction(QStringLiteral("Paste"), this, [this]() { paste(QApplication::clipboard()->text()); });
    menu.exec(event->globalPos());
}
