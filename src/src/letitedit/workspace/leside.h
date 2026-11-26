/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit: a project's own folder beside it, <stem>.letitedit (the Opening panel's hooks.json, Review's notes, a
 * version's version.json, the AI's journal and history). Before 30 Oct 2026 it was named <stem>.shotcut: an old one
 * is moved to the new name on first use, or merged into it when both exist (a file both have stays in the old folder,
 * so nothing is lost). bridge/project_journal.py does the same for the tools.
 */
#ifndef LESIDE_H
#define LESIDE_H

#include <QDir>
#include <QFileInfo>
#include <QString>

// Moves what `old` has and `fresh` lacks into `fresh` (folders merged the same way). True when `old` ended up empty.
inline bool leMergeFolder(const QString &old, const QString &fresh)
{
    bool empty = true;
    const QDir from(old);
    for (const QFileInfo &entry : from.entryInfoList(QDir::AllEntries | QDir::NoDotAndDotDot | QDir::Hidden)) {
        const QString target = QDir(fresh).filePath(entry.fileName());
        const QFileInfo there(target);
        if (!there.exists()) {
            if (!QDir().rename(entry.absoluteFilePath(), target))
                empty = false;
        } else if (entry.isDir() && there.isDir()) {
            if (leMergeFolder(entry.absoluteFilePath(), target))
                QDir().rmdir(entry.absoluteFilePath());
            else
                empty = false;
        } else {
            empty = false; // the new folder's file wins; the old one stays where it is
        }
    }
    return empty;
}

// The project's own folder. migrate: move an old <stem>.shotcut there first (false: only read, nothing moved - for
// lists of other projects). Returns the old folder while it can't be moved (a file in it is open elsewhere).
inline QString leSideFolder(const QString &project, bool migrate = true)
{
    if (project.isEmpty())
        return QString();
    const QFileInfo f(project);
    const QString base = f.dir().filePath(f.completeBaseName());
    const QString fresh = base + QStringLiteral(".letitedit");
    const QString old = base + QStringLiteral(".shotcut");
    if (!QFileInfo(old).isDir())
        return fresh;
    if (!migrate)
        return QFileInfo(fresh).isDir() ? fresh : old;
    if (!QFileInfo::exists(fresh))
        QDir().rename(old, fresh);
    else if (leMergeFolder(old, fresh))
        QDir().rmdir(old);
    return QFileInfo(fresh).isDir() || !QFileInfo(old).isDir() ? fresh : old;
}

// A file in the project's own folder, read from the old folder while the new one lacks it (nothing moved).
inline QString leSideFile(const QString &project, const QString &name)
{
    const QString fresh = leSideFolder(project, false);
    const QFileInfo f(project);
    const QString base = f.dir().filePath(f.completeBaseName());
    const QString inFresh = base + QStringLiteral(".letitedit/") + name;
    if (QFileInfo::exists(inFresh))
        return inFresh;
    const QString inOld = base + QStringLiteral(".shotcut/") + name;
    return QFileInfo::exists(inOld) ? inOld : QDir(fresh).filePath(name);
}

#endif // LESIDE_H
