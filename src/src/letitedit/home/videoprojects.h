#ifndef VIDEOPROJECTS_H
#define VIDEOPROJECTS_H

#include "settings.h"
#include <QtCore>

namespace VideoProjects {
inline QString create(const QString &title)
{
    QString name = title.simplified();
    name.replace(QRegularExpression(QStringLiteral("[<>:\"/\\\\|?*\\x00-\\x1f]")), QStringLiteral("-"));
    name = name.left(80);
    while (name.endsWith(QLatin1Char('.')) || name.endsWith(QLatin1Char(' ')))
        name.chop(1);
    if (name.isEmpty() || name == QLatin1String(".") || name == QLatin1String(".."))
        name = QStringLiteral("My video");
    if (QRegularExpression(QStringLiteral("^(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\\.|$)"),
                           QRegularExpression::CaseInsensitiveOption).match(name).hasMatch())
        name.prepend(QLatin1Char('_'));
    const QDir root(Settings.videoProjectsFolder());
    if (!QDir().mkpath(root.absolutePath()))
        return {};
    for (int number = 1; number < 10000; ++number) {
        const QString candidate = number == 1 ? name : QStringLiteral("%1 (%2)").arg(name).arg(number);
        if (root.mkdir(candidate))
            return root.filePath(candidate);
    }
    return {};
}
}

#endif
