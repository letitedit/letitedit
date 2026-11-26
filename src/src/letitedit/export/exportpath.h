#ifndef LETITEDIT_EXPORTPATH_H
#define LETITEDIT_EXPORTPATH_H

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QStandardPaths>
#include <QString>

#include <functional>

namespace ExportPath {
inline QString next(const QString &project, const QString &extension,
                    const std::function<bool(const QString &)> &busy)
{
    const QFileInfo source(project);
    QDir folder(project.isEmpty()
                    ? QStandardPaths::writableLocation(QStandardPaths::MoviesLocation) + QStringLiteral("/letitedit")
                    : source.absolutePath());
    if (!folder.mkpath(QStringLiteral(".")))
        return {};
    const QString stem = project.isEmpty() ? QStringLiteral("Untitled") : source.completeBaseName();
    const QString suffix = QLatin1Char('.') + (extension.isEmpty() ? QStringLiteral("mp4") : extension);
    const QString output = folder.filePath(stem + suffix);
    if (!QFileInfo::exists(output) && !busy(output))
        return output;
    int number = 2;
    QString older;
    QString olderReview;
    do {
        const QString version = stem + QStringLiteral(" (%1)").arg(number++);
        older = folder.filePath(version + suffix);
        olderReview = folder.filePath(version + QStringLiteral(" review"));
    } while (QFileInfo::exists(older) || busy(older) || QFileInfo::exists(olderReview));
    if (busy(output) || !QFile::rename(output, older))
        return older;
    const QString review = folder.filePath(stem + QStringLiteral(" review"));
    if (QFileInfo::exists(review) && !folder.rename(review, olderReview)) {
        return QFile::rename(older, output) ? older : QString();
    }
    return output;
}
}

#endif
