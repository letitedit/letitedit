/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "letitedit/chat/aicodexprobe.h"

#include <QtTest>

// T247: the chat asks Codex for its models (T228's reply-speed tiers) as soon as the chat shows. That probe is the first
// Codex the editor starts, and it started in whatever folder letitedit was launched from: on the build PC C:\LetItEdit,
// whose developer AGENTS.md and project config a customer's Codex must never read (T74). It starts in the chat's own
// folder, as Claude and every chat turn do. A stand-in Codex records the folder it was started in.
class TestCodexStartFolder : public QObject
{
    Q_OBJECT

private:
    QTemporaryDir temp;
    QString launch;
    QString chat;
    QString standIn;
    QString log;
    QString before;

    static QString same(const QString &path)
    {
        return QDir::cleanPath(QDir::fromNativeSeparators(path)).toLower();
    }

    QString runProbe()
    {
        QFile::remove(log);
        std::unique_ptr<QProcess> probe(aiCodexModelsProbe(standIn, chat, nullptr));
        probe->start();
        if (!probe->waitForStarted(10000))
            return QStringLiteral("(did not start: %1)").arg(probe->errorString());
        probe->closeWriteChannel();
        probe->waitForFinished(10000);
        QFile file(log);
        if (!file.open(QIODevice::ReadOnly))
            return QStringLiteral("(nothing recorded)");
        return QString::fromLocal8Bit(file.readAll()).trimmed();
    }

private slots:
    void initTestCase()
    {
        QVERIFY(temp.isValid());
        launch = temp.filePath(QStringLiteral("launched-from"));
        chat = temp.filePath(QStringLiteral("home/AppData/Local/letitedit/chat"));
        log = temp.filePath(QStringLiteral("started-in.txt"));
        standIn = temp.filePath(QStringLiteral("codex.cmd"));
        QVERIFY(QDir().mkpath(launch));
        QFile cmd(standIn);
        QVERIFY(cmd.open(QIODevice::WriteOnly));
        cmd.write("@echo off\r\necho %CD%> \"%T247_LOG%\"\r\n");
        cmd.close();
        qputenv("T247_LOG", QDir::toNativeSeparators(log).toLocal8Bit());
        before = QDir::currentPath();
        QVERIFY(QDir::setCurrent(launch)); // the folder letitedit was launched from
    }

    void cleanupTestCase()
    {
        QDir::setCurrent(before);
    }

    void theModelsProbeStartsInTheChatsOwnFolder()
    {
        QVERIFY(!QFileInfo::exists(chat)); // a new install: nothing has made the chat's folder yet
        const QString startedIn = runProbe();
        QVERIFY2(same(startedIn) != same(launch), qPrintable(QStringLiteral("started in the launch folder: ") + startedIn));
        QCOMPARE(same(startedIn), same(chat));
    }

    void theProbeAsksCodexTheSameThing()
    {
        std::unique_ptr<QProcess> probe(aiCodexModelsProbe(QStringLiteral("codex.exe"), chat, nullptr));
        QCOMPARE(probe->program(), QStringLiteral("codex.exe"));
        QCOMPARE(probe->arguments(),
                 (QStringList{QStringLiteral("app-server"), QStringLiteral("--stdio"), QStringLiteral("-c"),
                              QStringLiteral("service_tier=\"default\""), QStringLiteral("-c"),
                              QStringLiteral("features.fast_mode=true")}));
    }
};

QTEST_GUILESS_MAIN(TestCodexStartFolder)
#include "test_codex_start_folder.moc"
