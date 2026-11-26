/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit: the app's own buttons run bridge/app_tools.py commands (the same code the AI's tools use). A command
 * prints one JSON object per line - {"progress": 0.4, "message": "..."} while it works, then {"result": {...}} or
 * {"error": "..."} - and the heavy ones run under the PC render lock (lejobs.h), so they wait their turn with the
 * exports, the AI's renders and other windows. Cancel ends the whole process tree and gives up its place in line.
 */
#ifndef LETOOLS_H
#define LETOOLS_H

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/airoot.h"
#include "letitedit/dialogs/lejobs.h"

#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QPointer>
#include <QProcess>

#include <functional>

// The tools' Python (the chat panel's setting, as every helper uses); empty when it isn't there.
inline QString leToolsPython()
{
    const QString python = aiChatSettings().value("python").toString();
    return QFileInfo::exists(python) ? python : QString();
}

class LeToolRun : public QObject
{
public:
    explicit LeToolRun(QObject *parent)
        : QObject(parent)
    {}

    // fraction 0-1 and the words it is on
    std::function<void(double, const QString &)> progress;
    // waiting for another heavy job ("" when its turn came)
    std::function<void(const QString &)> waiting;
    // ok with the command's result, or why not (cancelled: ok false, why empty)
    std::function<void(bool, const QJsonObject &, const QString &)> done;

    // command: an app_tools.py command; heavy: under the render lock, named lockName ("letitedit <what>").
    void start(const QString &command, const QStringList &args, bool heavy = false, const QString &lockName = QString())
    {
        m_result = QJsonObject();
        m_error.clear();
        m_out.clear();
        m_errText.clear();
        m_finished = m_cancelled = false;
        const QString python = leToolsPython();
        const QString script = aiRootPath(QStringLiteral("bridge/app_tools.py"));
        if (python.isEmpty() || !QFileInfo::exists(script)) {
            QMetaObject::invokeMethod(this, [this]() {
                finish(false, tr("letitedit's tools aren't installed on this computer (Python or bridge\\app_tools.py "
                                 "is missing). Run Connect Your AI, or reinstall letitedit."));
            }, Qt::QueuedConnection);
            return;
        }
        const QStringList args0 = QStringList{QStringLiteral("-u"), script, command} + args;
        const QStringList locked = heavy ? leLockedCommand(lockName.isEmpty() ? QStringLiteral("letitedit ") + command
                                                                               : lockName,
                                                           python,
                                                           args0)
                                         : QStringList();
        // a run before this one (stopped) says nothing more: only the newest process speaks
        if (m_process) {
            m_process->disconnect(this);
            m_process->deleteLater();
        }
        auto *process = new QProcess(this);
        m_process = process;
        connect(process, &QProcess::readyReadStandardOutput, this, [this, process]() {
            if (process == m_process)
                readOut();
        });
        connect(process, &QProcess::readyReadStandardError, this, [this, process]() {
            if (process == m_process)
                readErr();
        });
        connect(process, &QProcess::finished, this, [this, process](int code, QProcess::ExitStatus status) {
            if (process != m_process)
                return;
            readOut();
            readErr();
            if (!m_out.trimmed().isEmpty())
                line(m_out.trimmed());
            if (m_cancelled)
                finish(false, QString());
            else if (status == QProcess::NormalExit && code == 0 && !m_result.isEmpty())
                finish(true, QString());
            else
                finish(false, !m_error.isEmpty() ? m_error : lastWords());
        });
        connect(process, &QProcess::errorOccurred, this, [this, process](QProcess::ProcessError e) {
            if (process == m_process && e == QProcess::FailedToStart)
                finish(false, tr("The tools could not start."));
        });
        m_errLine.clear();
        if (locked.isEmpty())
            process->start(python, args0);
        else
            process->start(locked.first(), locked.mid(1));
    }

    void cancel()
    {
        if (!m_process || m_finished)
            return;
        m_cancelled = true;
        leEndTree(*m_process);
        finish(false, QString());
    }

    bool running() const { return m_process && !m_finished; }

private:
    void readOut()
    {
        if (!m_process)
            return;
        m_out += m_process->readAllStandardOutput();
        int nl;
        while ((nl = m_out.indexOf('\n')) >= 0) {
            const QByteArray l = m_out.left(nl).trimmed();
            m_out.remove(0, nl + 1);
            if (!l.isEmpty())
                line(l);
        }
    }

    void line(const QByteArray &l)
    {
        const QJsonObject o = QJsonDocument::fromJson(l).object();
        if (o.contains("progress")) {
            if (progress)
                progress(o.value("progress").toDouble(), o.value("message").toString());
        } else if (o.contains("result")) {
            m_result = o.value("result").toObject();
        } else if (o.contains("error")) {
            m_error = o.value("error").toString();
        }
    }

    void readErr()
    {
        if (!m_process)
            return;
        const QByteArray e = m_process->readAllStandardError();
        m_errText += e;
        m_errLine += e;
        int nl;
        while ((nl = m_errLine.indexOf('\n')) >= 0) {
            const QString l = QString::fromUtf8(m_errLine.left(nl)).trimmed();
            m_errLine.remove(0, nl + 1);
            const QString words = leWaitWords(l);
            if (!words.isEmpty() && waiting)
                waiting(words);
            else if (l.startsWith(QLatin1String("[render_lock] holding")) && waiting)
                waiting(QString());
        }
    }

    QString lastWords() const
    {
        QStringList lines;
        for (const auto &l : QString::fromUtf8(m_errText).split(QLatin1Char('\n'), Qt::SkipEmptyParts))
            if (!l.startsWith(QLatin1String("[render_lock]")))
                lines << l.trimmed();
        return lines.isEmpty() ? tr("The tools stopped without an answer.") : lines.last().left(300);
    }

    void finish(bool ok, const QString &why)
    {
        if (m_finished)
            return;
        m_finished = true;
        if (done)
            done(ok, m_result, why);
    }

    QPointer<QProcess> m_process;
    QByteArray m_out, m_errText, m_errLine;
    QJsonObject m_result;
    QString m_error;
    bool m_cancelled = false;
    bool m_finished = false;
};

#endif // LETOOLS_H
