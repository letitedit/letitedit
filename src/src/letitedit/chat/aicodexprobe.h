/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef AICODEXPROBE_H
#define AICODEXPROBE_H

#include <QDir>
#include <QProcess>
#include <QString>
#include <QStringList>

// The chat asks Codex which models and reply speeds it offers (`codex app-server`, then model/list). Not started yet:
// the caller connects its signals, then starts it. Like every Codex the chat starts, it starts in the chat's own folder
// (`work`), never the folder letitedit was launched from: there Codex would read that folder's AGENTS.md and project
// config (on the build PC, the developers' own; T74, T247).
inline QProcess *aiCodexModelsProbe(const QString &program, const QString &work, QObject *parent)
{
    auto *probe = new QProcess(parent);
    QDir().mkpath(work);
    probe->setWorkingDirectory(work);
    probe->setProgram(program);
    probe->setArguments(QStringList{QStringLiteral("app-server"), QStringLiteral("--stdio"), QStringLiteral("-c"),
                                    QStringLiteral("service_tier=\"default\""), QStringLiteral("-c"),
                                    QStringLiteral("features.fast_mode=true")});
    return probe;
}

#endif // AICODEXPROBE_H
