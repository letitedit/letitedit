/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */
#ifndef LETITEDIT_JSONPROCESS_H
#define LETITEDIT_JSONPROCESS_H

#include <QJsonDocument>
#include <QJsonObject>
#include <QProcess>

#include <functional>
#include <memory>

// Start an already configured helper that prints one JSON object, possibly after a log prefix.
// Connections live as long as context. A crash or a failure to start reports -1, exactly once.
// Callers can inspect process->error() to give FailedToStart their own message.
inline QProcess *startJsonProcess(
    QProcess *process, QObject *context,
    const std::function<void(int, const QJsonObject &, const QString &)> &done)
{
    auto finished = std::make_shared<bool>(false);
    QObject::connect(process, &QProcess::finished, context,
                     [process, done, finished](int code, QProcess::ExitStatus status) {
        if (*finished)
            return;
        *finished = true;
        process->deleteLater();
        const QByteArray out = process->readAllStandardOutput();
        const QJsonObject result = QJsonDocument::fromJson(out.mid(out.indexOf('{'))).object();
        const QString err = QString::fromUtf8(process->readAllStandardError()).trimmed();
        if (done)
            done(status == QProcess::NormalExit ? code : -1, result, err);
    });
    QObject::connect(process, &QProcess::errorOccurred, context,
                     [process, done, finished](QProcess::ProcessError error) {
        if (error != QProcess::FailedToStart || *finished)
            return;
        *finished = true;
        process->deleteLater();
        if (done)
            done(-1, QJsonObject(), QString());
    });
    process->start();
    return process;
}

#endif // LETITEDIT_JSONPROCESS_H
