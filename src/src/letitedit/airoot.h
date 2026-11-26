/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * letitedit: where letitedit is installed (the folder holding bridge/letitedit_mcp.py, chat/, instances/, appdata/,
 * command-reference.json). LETITEDIT_ROOT when it names such a folder; else the editor's own folder or one of the
 * two above it (an install keeps the editor in <root>/app); else C:/LetItEdit (the build PC). The value found is
 * put into LETITEDIT_ROOT for every process the editor starts (the tool server reads it too).
 */
#ifndef AIROOT_H
#define AIROOT_H

#include <QCoreApplication>
#include <QDir>
#include <QFileInfo>
#include <QString>

inline QString aiRoot()
{
    static const QString root = []() {
        const auto isRoot = [](const QString &d) {
            return QFileInfo::exists(d + QStringLiteral("/bridge/letitedit_mcp.py"));
        };
        QString found;
        const QString env = QDir::cleanPath(QDir::fromNativeSeparators(qEnvironmentVariable("LETITEDIT_ROOT")));
        if (!qEnvironmentVariable("LETITEDIT_ROOT").isEmpty() && isRoot(env))
            found = env;
        if (found.isEmpty() && QCoreApplication::instance()) {
            QDir d(QCoreApplication::applicationDirPath());
            for (int i = 0; i < 3 && found.isEmpty(); ++i) {
                if (isRoot(d.absolutePath()))
                    found = d.absolutePath();
                else if (!d.cdUp())
                    break;
            }
        }
        if (found.isEmpty())
            found = QStringLiteral("C:/LetItEdit");
        qputenv("LETITEDIT_ROOT", QDir::toNativeSeparators(found).toUtf8());
        return found;
    }();
    return root;
}

// <root>/<relative>, with forward slashes (Qt accepts them everywhere).
inline QString aiRootPath(const QString &relative)
{
    return aiRoot() + QLatin1Char('/') + relative;
}

#endif // AIROOT_H
