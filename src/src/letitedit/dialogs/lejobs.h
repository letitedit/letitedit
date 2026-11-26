/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit: heavy helper programs (ffmpeg, whisper-cli, the export's sound finishing) take turns on this PC with every
 * other heavy job - letitedit's exports, hook previews, another window's work, the AI's renders - through the PC-wide
 * render lock (bridge/render_lock.py: first come, first served; a lock left by a program that is gone is cleared). The
 * program runs inside `render_lock.py run`, so the lock is held exactly while it runs. While another job has the
 * lock, the person sees "Waiting for another job to finish". Each uses at most leThreads() threads. Cancelling ends
 * the program and anything it started, and gives up its place in line (or its lock). Without the tools' Python the
 * program simply runs.
 */
#ifndef LEJOBS_H
#define LEJOBS_H

#include "letitedit/airoot.h"
#include "letitedit/chat/aichatpanel.h"
#include "letitedit/letitedit.h"

#include <QCoreApplication>
#include <QDir>
#include <QElapsedTimer>
#include <QFile>
#include <QFileInfo>
#include <QPointer>
#include <QProcess>
#include <QProgressDialog>
#include <QRegularExpression>
#include <QThread>
#include <QTimer>

#include <functional>

// The threads one heavy helper may use (the PC's rule: at most 4).
inline int leThreads()
{
    return qBound(1, QThread::idealThreadCount() - 1, 4);
}

// The PC render lock file (the same one render_lock.py and the export queue use).
inline QString leRenderLockPath()
{
    const QString own = qEnvironmentVariable("LETITEDIT_RENDER_LOCK");
    return !own.isEmpty() ? QDir::fromNativeSeparators(own) : QDir::homePath() + QStringLiteral("/Videos/render.lock");
}

// The command that runs program under the lock: python render_lock.py run --name ... -- program args. Empty when the
// tools' Python or render_lock.py is missing (the program then runs on its own).
inline QStringList leLockedCommand(const QString &name, const QString &program, const QStringList &args)
{
    const QString python = aiChatSettings().value("python").toString();
    const QString lock = aiRootPath(QStringLiteral("bridge/render_lock.py"));
    if (qEnvironmentVariableIsSet("LETITEDIT_NO_RENDER_LOCK") || !QFileInfo::exists(python) || !QFileInfo::exists(lock))
        return {};
    return QStringList{python, QStringLiteral("-u"), lock, QStringLiteral("run"), QStringLiteral("--name"), name,
                       QStringLiteral("--poll-s"), QStringLiteral("2"), QStringLiteral("--"), program}
           + args;
}

// What a "[render_lock] waiting ..." line says, in plain words: who has the lock or how many wait ahead. Empty when the
// line is not a wait.
inline QString leWaitWords(const QString &line)
{
    if (!line.startsWith(QLatin1String("[render_lock] waiting")))
        return QString();
    static const QRegularExpression held(QStringLiteral("held by \"([^\"]*)\""));
    static const QRegularExpression ahead(QStringLiteral("(\\d+) waiting ahead"));
    const auto h = held.match(line);
    QString who = h.hasMatch() ? h.captured(1) : QString();
    who.remove(QRegularExpression(QStringLiteral("\\s+pid\\s+\\d+.*$")));
    const auto a = ahead.match(line);
    const int before = a.hasMatch() ? a.captured(1).toInt() : 0;
    if (!who.isEmpty())
        return before > 0 ? QObject::tr("Waiting for another job to finish (%1), then %2 more ahead...").arg(who).arg(before)
                          : QObject::tr("Waiting for another job to finish (%1)...").arg(who);
    return before > 0 ? QObject::tr("Waiting for %1 other jobs ahead of this one...").arg(before)
                      : QObject::tr("Waiting for another job to finish...");
}

// Ends a process and everything it started (Windows: taskkill /T), then clears the lock or the place in line it held.
inline void leEndTree(QProcess &process)
{
    const qint64 pid = process.processId();
    if (pid > 0) {
#ifdef Q_OS_WIN
        QProcess::execute(QStringLiteral("taskkill"), {QStringLiteral("/T"), QStringLiteral("/F"), QStringLiteral("/PID"),
                                                      QString::number(pid)});
#endif
    }
    process.kill();
    process.waitForFinished(3000);
    if (pid <= 0)
        return;
    // a lock or a ticket naming that process is let go at once (others would also clear it as stale)
    QFile lock(leRenderLockPath());
    if (lock.open(QIODevice::ReadOnly)) {
        const QString text = QString::fromUtf8(lock.readAll());
        lock.close();
        if (text.contains(QStringLiteral(" pid %1 ").arg(pid)))
            QFile::remove(lock.fileName());
    }
    QDir queue(leRenderLockPath() + QStringLiteral(".queue"));
    for (const QString &ticket : queue.entryList({QStringLiteral("*-%1-*.ticket").arg(pid)}, QDir::Files))
        queue.remove(ticket);
}

// Like leRun, under the PC render lock: waits its turn (progress, when given, then says what it waits for), runs the
// program while holding the lock, and gives it up however the program ends. False when it fails, times out (the
// timeout counts from its turn) or the person presses Cancel. onLine gets each line the program prints on stdout;
// output, if given, everything it printed (stdout, then stderr).
inline bool leRunHeavy(const QString &name, const QString &program, const QStringList &args, QProgressDialog *progress,
                       QByteArray *output = nullptr, int timeoutMs = -1,
                       const std::function<void(const QByteArray &)> &onLine = {})
{
    const QStringList locked = leLockedCommand(name, program, args);
    QProcess process;
    if (locked.isEmpty())
        process.start(program, args);
    else
        process.start(locked.first(), locked.mid(1));
    if (!process.waitForStarted(10000))
        return false;
    const QString label = progress ? progress->labelText() : QString();
    bool myTurn = locked.isEmpty();
    QElapsedTimer clock;
    clock.start();
    QByteArray out, err, outLine, errLine;
    while (process.state() != QProcess::NotRunning) {
        process.waitForReadyRead(50);
        const QByteArray o = process.readAllStandardOutput();
        out += o;
        outLine += o;
        int nl;
        while ((nl = outLine.indexOf('\n')) >= 0) {
            if (onLine)
                onLine(outLine.left(nl).trimmed());
            outLine.remove(0, nl + 1);
        }
        const QByteArray e = process.readAllStandardError();
        err += e;
        errLine += e;
        while ((nl = errLine.indexOf('\n')) >= 0) {
            const QString line = QString::fromUtf8(errLine.left(nl)).trimmed();
            errLine.remove(0, nl + 1);
            const QString waiting = leWaitWords(line);
            if (!waiting.isEmpty() && progress) {
                progress->setLabelText(waiting);
            } else if (line.startsWith(QLatin1String("[render_lock] holding"))) {
                myTurn = true;
                clock.restart();
                if (progress)
                    progress->setLabelText(label);
            }
        }
        QCoreApplication::processEvents();
        if ((progress && progress->wasCanceled()) || (myTurn && timeoutMs > 0 && clock.elapsed() > timeoutMs)) {
            leEndTree(process);
            return false;
        }
    }
    out += process.readAllStandardOutput();
    err += process.readAllStandardError();
    if (output)
        *output = out + err;
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        LOG_WARNING() << program << "failed:" << (out + err).right(400);
        return false;
    }
    return true;
}

// The same, without waiting in place: start() returns at once; waiting(text) says what it waits for ("" when its turn
// came), done(ok, stdout, stderr) when it ended. cancel() ends it (done then reports a failure).
class LeHeavyRun : public QObject
{
public:
    explicit LeHeavyRun(QObject *parent)
        : QObject(parent)
    {}

    std::function<void(const QString &)> waiting;
    std::function<void(bool, const QByteArray &, const QByteArray &)> done;

    void start(const QString &name, const QString &program, const QStringList &args)
    {
        const QStringList locked = leLockedCommand(name, program, args);
        m_process = new QProcess(this);
        connect(m_process, &QProcess::readyReadStandardOutput, this, [this]() { m_out += m_process->readAllStandardOutput(); });
        connect(m_process, &QProcess::readyReadStandardError, this, [this]() {
            const QByteArray e = m_process->readAllStandardError();
            m_err += e;
            m_errLine += e;
            int nl;
            while ((nl = m_errLine.indexOf('\n')) >= 0) {
                const QString line = QString::fromUtf8(m_errLine.left(nl)).trimmed();
                m_errLine.remove(0, nl + 1);
                const QString words = leWaitWords(line);
                if (!words.isEmpty() && waiting)
                    waiting(words);
                else if (line.startsWith(QLatin1String("[render_lock] holding")) && waiting)
                    waiting(QString());
            }
        });
        connect(m_process, &QProcess::finished, this, [this](int code, QProcess::ExitStatus status) {
            finish(!m_cancelled && status == QProcess::NormalExit && code == 0);
        });
        connect(m_process, &QProcess::errorOccurred, this, [this](QProcess::ProcessError e) {
            if (e == QProcess::FailedToStart)
                finish(false);
        });
        if (locked.isEmpty())
            m_process->start(program, args);
        else
            m_process->start(locked.first(), locked.mid(1));
    }

    void cancel()
    {
        if (!m_process || m_finished)
            return;
        m_cancelled = true;
        leEndTree(*m_process);
        finish(false);
    }

    bool running() const { return m_process && !m_finished; }

private:
    void finish(bool ok)
    {
        if (m_finished)
            return;
        m_finished = true;
        if (m_process) {
            m_out += m_process->readAllStandardOutput();
            m_err += m_process->readAllStandardError();
        }
        if (done)
            done(ok, m_out, m_err);
    }

    QPointer<QProcess> m_process;
    QByteArray m_out, m_err, m_errLine;
    bool m_cancelled = false;
    bool m_finished = false;
};

#endif // LEJOBS_H
