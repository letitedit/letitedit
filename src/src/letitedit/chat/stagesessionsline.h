/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef STAGESESSIONSLINE_H
#define STAGESESSIONSLINE_H

#include <QString>

// T194: the line a New video request ends with when the run takes one conversation per stage
// (bridge/new_video_stages.py LINE). Home's Try again sends back the request as it was sent, line and all, so the
// line is taken out first and put back once when this run uses stage sessions: the same request gives the same text,
// and a retry on an AI that can't start fresh conversations (a connector) or in Turbo gets none.
inline QString aiStageSessionsLine()
{
    return QStringLiteral("sessions: one per stage");
}

// T294: a run with lean stage hand-offs (chat/ainewvideolean.h) declares them once, on the line before the sessions
// line. Its first words are the bridge's own (stage_handoff.fresh_request); the rest tells the AI the source ids.
inline QString aiLeanDeclaration()
{
    return QStringLiteral("This run explicitly uses lean stage handoffs. In a lean `handover:` note a decision's ranges name "
                          "each source by its footage file's name (`source_id`; its full path when two files share a name).");
}

// lean false: the text is exactly as before T294.
inline QString aiNewVideoWithSessionsLine(QString message, bool on, bool lean = false)
{
    // exactly what an earlier send added, nothing more: the person's own text and spacing stay as they were
    const QString added = QStringLiteral("\n\n") + aiStageSessionsLine();
    const QString leanAdded = QStringLiteral("\n\n") + aiLeanDeclaration() + QLatin1Char('\n') + aiStageSessionsLine();
    message.remove(leanAdded);
    message.remove(added);
    if (on)
        message += lean ? leanAdded : added;
    return message;
}

#endif // STAGESESSIONSLINE_H
