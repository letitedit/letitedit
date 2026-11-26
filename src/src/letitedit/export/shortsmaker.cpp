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

#include "letitedit/export/shortsmaker.h"

#include "letitedit/chat/aichatpanel.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/multitrackmodel.h"

#include <QCheckBox>
#include <QComboBox>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QDockWidget>
#include <QFileInfo>
#include <QFormLayout>
#include <QLabel>
#include <QLineEdit>
#include <QMessageBox>
#include <QPushButton>
#include <QSpinBox>
#include <QVBoxLayout>

namespace {

QString clock(double seconds)
{
    const int s = qRound(seconds);
    return s >= 3600 ? QStringLiteral("%1:%2:%3")
                           .arg(s / 3600)
                           .arg(s / 60 % 60, 2, 10, QLatin1Char('0'))
                           .arg(s % 60, 2, 10, QLatin1Char('0'))
                     : QStringLiteral("%1:%2").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0'));
}

} // namespace

QString shortsRequest(const QString &project, double seconds, int count, int length, const QString &about,
                      bool exportThem)
{
    const QString base = QFileInfo(project).completeBaseName();
    QString text = QStringLiteral("Make %1 vertical %2 of about %3 seconds from the long video in the open letitedit "
                                  "project \"%4\" (%5 long). Use the letitedit skills (the `letitedit-shorts` pack). "
                                  "Find moments that make sense on their own: a hook in the first 3 seconds and the "
                                  "payoff at the end, no loose \"it\" or \"like I said\" at the start.\n")
                       .arg(count)
                       .arg(count == 1 ? QStringLiteral("short") : QStringLiteral("shorts"))
                       .arg(length)
                       .arg(QDir::toNativeSeparators(project), clock(seconds));
    if (!about.trimmed().isEmpty())
        text += QStringLiteral("What they should be about: %1\n").arg(about.trimmed());
    text += QStringLiteral("\nLeave this project as it is. Make each short its own project next to it, named \"%1 short "
                           "1.mlt\", \"%1 short 2.mlt\" and so on: vertical 1080x1920, the footage used where it is "
                           "(never copied), captions on inside the phone apps' safe area.\n")
                .arg(base);
    if (exportThem)
        text += QStringLiteral("Export each one to an MP4 next to its project, with even volume.\n");
    text += QStringLiteral("\nThen tell me for each: the file, its first line (the hook), and where in the long video "
                           "it comes from.");
    return text;
}

void showShortsDialog(MainWindow *window)
{
    if (!window->isMultitrackValid()) {
        window->showStatusMessage(QObject::tr("Open the long video first."));
        return;
    }
    if (window->fileName().isEmpty() || window->isWindowModified()) {
        if (QMessageBox::question(window,
                                  QObject::tr("Make Shorts"),
                                  QObject::tr("Save your video first, so your AI works from your latest edit?"),
                                  QMessageBox::Save | QMessageBox::Cancel,
                                  QMessageBox::Save)
            != QMessageBox::Save)
            return;
        if (auto save = window->findChild<QAction *>(QStringLiteral("actionSave")))
            save->trigger();
        if (window->fileName().isEmpty() || window->isWindowModified())
            return;
    }
    const double seconds = window->timelineDock()->model()->tractor()->get_playtime() / MLT.profile().fps();

    QDialog dialog(window);
    dialog.setObjectName(QStringLiteral("shortsDialog"));
    dialog.setWindowTitle(QObject::tr("Make Shorts from This Video"));
    dialog.setMinimumWidth(500);
    auto *column = new QVBoxLayout(&dialog);
    auto *intro = new QLabel(QObject::tr("Your AI finds the moments of this %1 video that work on their own and makes "
                                         "each one a vertical short with captions, as its own project next to this "
                                         "one. This video stays as it is.")
                                 .arg(clock(seconds)));
    intro->setWordWrap(true);
    column->addWidget(intro);
    auto *form = new QFormLayout;
    auto *count = new QSpinBox;
    count->setObjectName(QStringLiteral("shortsCount"));
    count->setRange(1, 5);
    count->setValue(qBound(1, int(seconds / 120.0) + 1, 3));
    form->addRow(QObject::tr("How many"), count);
    auto *length = new QComboBox;
    length->setObjectName(QStringLiteral("shortsLength"));
    length->addItem(QObject::tr("About 30 seconds"), 30);
    length->addItem(QObject::tr("About 45 seconds"), 45);
    length->addItem(QObject::tr("Up to a minute"), 60);
    length->setCurrentIndex(1);
    form->addRow(QObject::tr("Each"), length);
    auto *about = new QLineEdit;
    about->setObjectName(QStringLiteral("shortsAbout"));
    about->setPlaceholderText(QObject::tr("Optional, e.g. the moment it works, the price, the mistake"));
    form->addRow(QObject::tr("About"), about);
    column->addLayout(form);
    auto *exportThem = new QCheckBox(QObject::tr("Export each one to MP4 too"));
    exportThem->setObjectName(QStringLiteral("shortsExport"));
    exportThem->setChecked(true);
    column->addWidget(exportThem);
    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Cancel);
    auto *go = buttons->addButton(QObject::tr("Make Shorts"), QDialogButtonBox::AcceptRole);
    go->setObjectName(QStringLiteral("shortsGo"));
    go->setDefault(true);
    QObject::connect(buttons, &QDialogButtonBox::accepted, &dialog, &QDialog::accept);
    QObject::connect(buttons, &QDialogButtonBox::rejected, &dialog, &QDialog::reject);
    column->addWidget(buttons);
    if (dialog.exec() != QDialog::Accepted)
        return;

    const QString request = shortsRequest(window->fileName(),
                                          seconds,
                                          count->value(),
                                          length->currentData().toInt(),
                                          about->text(),
                                          exportThem->isChecked());
    if (!aiChatRequest(window,
                       request,
                       count->value() == 1 ? QObject::tr("Make a short from this video")
                                           : QObject::tr("Make %1 shorts from this video").arg(count->value()))) {
        QMessageBox::information(window,
                                 QObject::tr("Make Shorts"),
                                 QObject::tr("Your AI is still busy with the last request. Try again when it has "
                                             "answered."));
        return;
    }
    if (auto chat = window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
        chat->show();
        chat->raise();
    }
    window->showStatusMessage(QObject::tr("Your AI is making the shorts. Follow along in the chat."), 10);
}
