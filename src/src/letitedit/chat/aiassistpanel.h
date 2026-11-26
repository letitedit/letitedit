/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The AI menu (Menu > AI): a separate editor window for the AI, the music and sound folders and My style. The AI
 * features add their own items to it (lefeatures.cpp, the How to window, the chat). Managed episodes are retired
 * (29 Oct 2026): their Episode panel and Production guide are gone; old episode folders still open as projects.
 */
#ifndef AIASSISTPANEL_H
#define AIASSISTPANEL_H

#include "mainwindow.h"
#include "letitedit/panels/aiaudiolibrary.h"
#include "actions.h"
#include "letitedit/airoot.h"
#include <QDir>
#include <QMenuBar>
#include <QProcess>
#include <QProcessEnvironment>
#include <QUuid>

inline void installAiAssistPanel(MainWindow *window)
{
    auto menu = window->menuBar()->addMenu(QStringLiteral("AI"));
    menu->setObjectName(QStringLiteral("menuAi"));
    auto newWindow = menu->addAction(QObject::tr("New isolated editor window"));
    newWindow->setObjectName(QStringLiteral("aiAssistNewInstanceAction"));
    QObject::connect(newWindow, &QAction::triggered, window, []() {
        const QString id = QStringLiteral("edit-") + QUuid::createUuid().toString(QUuid::Id128).left(10);
        const QString data = aiRootPath(QStringLiteral("instances/")) + id + QStringLiteral("/appdata");
        QDir().mkpath(data);
        QProcess process;
        auto env = QProcessEnvironment::systemEnvironment();
        env.insert(QStringLiteral("LETITEDIT_INSTANCE"), id);
        env.remove(QStringLiteral("LETITEDIT_OWNER"));
        process.setProcessEnvironment(env);
        process.setProgram(QCoreApplication::applicationFilePath());
        process.setArguments({QStringLiteral("--noupgrade"),QStringLiteral("--appdata"),data});
        process.startDetached();
    });
    installAiAudioLibrary(window, menu);
    // styles are chosen in New video and made your own in My style (never a folder of files)
    auto styles = menu->addAction(QObject::tr("My Looks..."));
    styles->setObjectName(QStringLiteral("aiAssistStylesAction"));
    styles->setToolTip(QObject::tr("Your own style for every video of a series: how they look, sound and feel"));
    QObject::connect(styles, &QAction::triggered, window, []() {
        if (auto myStyle = Actions["myStyleAction"])
            myStyle->trigger();
    });
}

#endif
