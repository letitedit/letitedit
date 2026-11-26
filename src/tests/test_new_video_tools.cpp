/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "letitedit/chat/newvideotools.h"

#include <QtTest>

// T240: New video's and Learn's own chat starts Claude Code with only the app's tool servers (--strict-mcp-config, as
// the critic and New hook's title call run); Live Review's round and the person's own chats keep their connectors.
class TestNewVideoTools : public QObject
{
    Q_OBJECT

private slots:
    void newVideoAndLearnTurnsUseOnlyTheAppsServers()
    {
        // the first turn, the carry-ons, Continue the edit and a message typed into New video's or Learn's chat
        QCOMPARE(aiClaudeNewVideoToolArgs(true, true), QStringList{QStringLiteral("--strict-mcp-config")});
    }

    void liveReviewKeepsTheConnectors()
    {
        // Live Review's round runs unattended but isn't New video's chat (newVideoChat = !liveReviewHold)
        QVERIFY(aiClaudeNewVideoToolArgs(true, false).isEmpty());
    }

    void aChatThePersonStartsKeepsTheConnectors()
    {
        QVERIFY(aiClaudeNewVideoToolArgs(false, false).isEmpty());
    }

    void aNewVideoChatBetweenRunsStartsNothingDifferent()
    {
        // after its run ends and before the next turn sets it again: no start is built in between, and none narrows
        QVERIFY(aiClaudeNewVideoToolArgs(false, true).isEmpty());
    }

    void onlyTheOneFlag()
    {
        // nothing that would hide the person's skills or settings (the critic's --setting-sources local would)
        const QStringList args = aiClaudeNewVideoToolArgs(true, true);
        QCOMPARE(args.size(), 1);
        QVERIFY(!args.join(QLatin1Char(' ')).contains(QStringLiteral("setting-sources")));
    }
};

QTEST_MAIN(TestNewVideoTools)
#include "test_new_video_tools.moc"
