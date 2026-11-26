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

#ifndef SHARELOOKS_H
#define SHARELOOKS_H

// T190: "Share my learned Looks with letitedit" (Settings > Share learned Looks..., and a line on the Learn screen).
// The sending itself is bridge/look_share.py: it runs in the background when a Look is saved or renamed, and once at
// start-up for Looks not sent yet. The setting is sharing.json ("share_looks", on unless turned off) in the sharing
// folder, the same one look_share.py reads: LETITEDIT_SHARING_DIR, else %LOCALAPPDATA%/letitedit/sharing for the main
// window, else the test profile's appdata/sharing.

#include "letitedit/airoot.h"
#include "letitedit/chat/aichatpanel.h"
#include "settings.h"

#include <QtWidgets>

namespace ShareLooks {

inline QString folder()
{
    const QString named = qEnvironmentVariable("LETITEDIT_SHARING_DIR");
    if (!named.isEmpty())
        return QDir::fromNativeSeparators(named);
    if (qEnvironmentVariable("LETITEDIT_INSTANCE", "main") == QLatin1String("main")) {
        QString local = qEnvironmentVariable("LOCALAPPDATA");
        if (local.isEmpty())
            local = QDir::homePath() + QStringLiteral("/AppData/Local");
        return QDir::fromNativeSeparators(local) + QStringLiteral("/letitedit/sharing");
    }
    return QDir(Settings.appDataLocation()).filePath(QStringLiteral("sharing"));
}

inline QJsonObject settings()
{
    QFile file(folder() + QStringLiteral("/sharing.json"));
    return file.open(QIODevice::ReadOnly) ? QJsonDocument::fromJson(file.readAll()).object() : QJsonObject();
}

inline bool enabled()
{
    return settings().value(QStringLiteral("share_looks")).toBool(true);
}

inline bool setEnabled(bool on)
{
    QJsonObject values = settings();
    values.insert(QStringLiteral("share_looks"), on);
    QDir().mkpath(folder());
    QSaveFile file(folder() + QStringLiteral("/sharing.json"));
    if (!file.open(QIODevice::WriteOnly))
        return false;
    file.write(QJsonDocument(values).toJson());
    return file.commit();
}

inline QString explanation()
{
    return QObject::tr("Sends each Look's settings and recipe, never your videos or the videos you learned from, so "
                       "letitedit can test Looks and add the best ones to letitedit.");
}

// Sends what hasn't been sent, in the background (look_share.py lowers its own priority; no window, nothing shown)
inline void startSync()
{
    if (!enabled())
        return;
    const QString python = aiChatSettings().value(QStringLiteral("python")).toString();
    if (python.isEmpty())
        return;
    QProcess::startDetached(python, {aiRootPath(QStringLiteral("bridge/look_share.py")), QStringLiteral("sync")});
}

inline void showDialog(QWidget *parent)
{
    QDialog dialog(parent);
    dialog.setObjectName(QStringLiteral("shareLooksDialog"));
    dialog.setWindowTitle(QObject::tr("Share learned Looks"));
    dialog.setMinimumWidth(480);
    auto column = new QVBoxLayout(&dialog);
    auto share = new QCheckBox(QObject::tr("Share my learned Looks with letitedit"), &dialog);
    share->setObjectName(QStringLiteral("shareLooksCheck"));
    share->setChecked(enabled());
    column->addWidget(share);
    auto about = new QLabel(explanation(), &dialog);
    about->setObjectName(QStringLiteral("shareLooksAbout"));
    about->setWordWrap(true);
    about->setProperty("studioMuted", true);
    column->addWidget(about);
    auto removeRow = new QHBoxLayout;
    auto remove = new QPushButton(QObject::tr("Remove what I've shared"), &dialog);
    remove->setObjectName(QStringLiteral("shareLooksRemove"));
    remove->setAutoDefault(false);
    remove->setToolTip(QObject::tr("Deletes every Look this PC has sent to letitedit, and turns sharing off."));
    removeRow->addWidget(remove);
    removeRow->addStretch(1);
    column->addLayout(removeRow);
    auto result = new QLabel(&dialog);
    result->setObjectName(QStringLiteral("shareLooksResult"));
    result->setWordWrap(true);
    column->addWidget(result);
    QObject::connect(share, &QCheckBox::toggled, &dialog, [result](bool on) {
        if (!setEnabled(on)) {
            result->setText(QObject::tr("Couldn't save this setting."));
            return;
        }
        result->setText(on ? QObject::tr("Sharing is on.") : QObject::tr("Sharing is off: nothing more is sent."));
        if (on)
            startSync();
    });
    QObject::connect(remove, &QPushButton::clicked, &dialog, [&dialog, share, remove, result]() {
        const QString python = aiChatSettings().value(QStringLiteral("python")).toString();
        auto process = new QProcess(&dialog);
        remove->setEnabled(false);
        result->setText(QObject::tr("Removing..."));
        QObject::connect(process, &QProcess::finished, &dialog, [process, share, remove, result]() {
            const QByteArray out = process->readAllStandardOutput();
            const QJsonObject reply = QJsonDocument::fromJson(out.mid(out.indexOf('{'))).object();
            remove->setEnabled(true);
            const QSignalBlocker quiet(share);
            share->setChecked(enabled());
            if (reply.value(QStringLiteral("ok")).toBool()) {
                const int removed = reply.value(QStringLiteral("removed")).toInt();
                const QString what = removed == 0   ? QObject::tr("Nothing from this PC was left at letitedit.")
                                     : removed == 1 ? QObject::tr("Removed 1 Look from letitedit.")
                                                    : QObject::tr("Removed %1 Looks from letitedit.").arg(removed);
                result->setText(what + ' ' + QObject::tr("Sharing is off now; tick the box to share again."));
            } else {
                result->setText(QObject::tr("Couldn't remove them: %1")
                                    .arg(reply.value(QStringLiteral("error")).toString(QObject::tr("no answer"))));
            }
            process->deleteLater();
        });
        QObject::connect(process, &QProcess::errorOccurred, &dialog, [process, remove, result](QProcess::ProcessError error) {
            if (error != QProcess::FailedToStart)
                return;
            remove->setEnabled(true);
            result->setText(QObject::tr("Couldn't remove them: letitedit's tools didn't start."));
            process->deleteLater();
        });
        process->start(python, {aiRootPath(QStringLiteral("bridge/look_share.py")), QStringLiteral("remove")});
    });
    auto buttons = new QDialogButtonBox(QDialogButtonBox::Close, &dialog);
    buttons->setObjectName(QStringLiteral("shareLooksButtons"));
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    column->addWidget(buttons);
    dialog.exec();
}

// The line on the Learn screen: what is sent, with a way to the setting
inline QString learnLine()
{
    return enabled() ? explanation() + QStringLiteral(" <a href=\"share\">%1</a>").arg(QObject::tr("Change"))
                     : QObject::tr("Sharing your learned Looks with letitedit is off. <a href=\"share\">Change</a>");
}

} // namespace ShareLooks

#endif // SHARELOOKS_H
