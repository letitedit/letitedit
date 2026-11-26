/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#include "letitedit/chat/stagesessionsline.h"

#include <QtTest>

// T194: New video's request gets `sessions: one per stage` once; Home's Try again sends back the request as it was
// sent (line and all) and must send exactly the same text (check_no_video).
class TestStageSessionsLine : public QObject
{
    Q_OBJECT

private:
    const QString request = QStringLiteral("Make a first cut from the folder C:\\footage.\n\nSave video in: C:/out\n"
                                           "Keep the project, exports and AI working files in this folder.");

private slots:
    void firstSendAddsTheLineOnce()
    {
        const QString sent = aiNewVideoWithSessionsLine(request, true);
        QCOMPARE(sent, request + QStringLiteral("\n\nsessions: one per stage"));
        QCOMPARE(sent.count(aiStageSessionsLine()), 1);
    }

    void tryAgainSendsExactlyTheSameRequest()
    {
        const QString sent = aiNewVideoWithSessionsLine(request, true);
        QCOMPARE(aiNewVideoWithSessionsLine(sent, true), sent);
        QCOMPARE(aiNewVideoWithSessionsLine(aiNewVideoWithSessionsLine(sent, true), true), sent);
    }

    void withoutStageSessionsTheRequestIsUntouched()
    {
        QCOMPARE(aiNewVideoWithSessionsLine(request, false), request);
    }

    void aRetryThatCannotUseStageSessionsDropsTheLine()
    {
        // the first try had them; the retry runs on a connector or in Turbo: the person's request, without the line
        QCOMPARE(aiNewVideoWithSessionsLine(aiNewVideoWithSessionsLine(request, true), false), request);
    }

    void thePersonsOwnSpacingStays()
    {
        const QString spaced = request + QStringLiteral("\n\n\n");
        const QString sent = aiNewVideoWithSessionsLine(spaced, true);
        QVERIFY(sent.startsWith(spaced));
        QCOMPARE(aiNewVideoWithSessionsLine(sent, true), sent);
        QCOMPARE(aiNewVideoWithSessionsLine(sent, false), spaced);
    }
};

QTEST_GUILESS_MAIN(TestStageSessionsLine)
#include "test_stage_sessions_line.moc"
