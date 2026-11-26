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

#ifndef LETITEDIT_H
#define LETITEDIT_H

#include "Logger.h"
#include "settings.h"

#include <QCoreApplication>
#include <QElapsedTimer>
#include <QProcess>
#include <QProgressDialog>
#include <QSettings>

// letitedit's own choices (caption look, word list, pause and music settings, styles), kept next to the editor's
// settings in the app data folder so they follow the same --appdata.
inline QSettings &leSettings()
{
    static QSettings settings(Settings.appDataLocation() + QStringLiteral("/letitedit-choices.ini"), QSettings::IniFormat);
    return settings;
}

// Runs a helper program (ffmpeg, whisper-cli, melt...) while the window keeps painting. False when it fails, times
// out or the person presses Cancel on the progress dialog. output, if given, receives everything it printed.
inline bool leRun(const QString &program,
                  const QStringList &args,
                  QProgressDialog *progress = nullptr,
                  QByteArray *output = nullptr,
                  int timeoutMs = -1)
{
    QProcess process;
    process.setProcessChannelMode(QProcess::MergedChannels);
    process.start(program, args);
    if (!process.waitForStarted(10000))
        return false;
    QElapsedTimer clock;
    clock.start();
    while (process.state() != QProcess::NotRunning && !process.waitForFinished(50)) {
        QCoreApplication::processEvents();
        if ((progress && progress->wasCanceled()) || (timeoutMs > 0 && clock.elapsed() > timeoutMs)) {
            process.kill();
            process.waitForFinished(2000);
            return false;
        }
    }
    const QByteArray printed = process.readAll();
    if (output)
        *output = printed;
    if (process.exitStatus() != QProcess::NormalExit || process.exitCode() != 0) {
        LOG_WARNING() << program << "failed:" << printed.right(400);
        return false;
    }
    return true;
}

#endif // LETITEDIT_H
