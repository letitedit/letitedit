/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 */

#ifndef NEWVIDEOTOOLS_H
#define NEWVIDEOTOOLS_H

#include "letitedit/chat/aichatpanel.h"
#include "letitedit/chat/aichatsettings.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QSet>
#include <QString>
#include <QStringList>

// T322 P2 (the owner's pipeline rule 5, 21 Nov): an editing session starts Claude Code without the built-in tools it never
// uses (agents, workflows, scheduling, worktrees, notebooks, the web), whose descriptions every step re-reads. The list
// is bridge/ai_list.json's "editing_tools" on the claude entry, read here and by bridge/ai_clis.py (editing_tool_args):
// - "keep" stays (Bash, Read, Write, Edit, Grep, Glob, Skill, ToolSearch); "drop" goes, and so does every other tool the
//   probe saw this PC's Claude Code offer (ai_clis.probe_editing_tools writes claude-tools.json beside the chat's
//   history; it is used while the program it probed is unchanged);
// - "shell_fallback" (PowerShell) is Claude Code's only shell on a Windows PC without Git Bash, so it goes only when
//   the probe saw Bash offered. With no probe it stays.
// One argument, --disallowedTools=<names>: every Claude Code version takes it, a name a version doesn't have is
// ignored, and the = form can't take in the argument after it. The letitedit tools are never touched.
// The switch, on by default (T365): LETITEDIT_EDITING_BUILTINS_OFF (1 or 0) wins, else settings.json
// editing_builtins_off (false turns it off).
inline bool aiEditingBuiltinsOff()
{
    const QString forced = qEnvironmentVariable("LETITEDIT_EDITING_BUILTINS_OFF").trimmed().toLower();
    if (forced == QLatin1String("1") || forced == QLatin1String("true") || forced == QLatin1String("on")
        || forced == QLatin1String("yes"))
        return true;
    if (forced == QLatin1String("0") || forced == QLatin1String("false") || forced == QLatin1String("off")
        || forced == QLatin1String("no"))
        return false;
    const QString path = qEnvironmentVariableIsSet("LETITEDIT_SETTINGS") ? qEnvironmentVariable("LETITEDIT_SETTINGS")
                                                                        : QDir(aiRoot()).filePath(QStringLiteral("settings.json"));
    QFile file(path);
    if (!file.open(QIODevice::ReadOnly))
        return true;
    QByteArray data = file.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    return QJsonDocument::fromJson(data).object().value(QStringLiteral("editing_builtins_off")).toBool(true);
}

// The built-in tools the last probe saw Claude Code offer; *known is false with no probe, or when the program it
// probed has changed or gone since.
inline QStringList aiClaudeOfferedTools(bool *known)
{
    *known = false;
    QFile f(QFileInfo(aiChatHistoryPath()).absolutePath() + QStringLiteral("/claude-tools.json"));
    if (!f.open(QIODevice::ReadOnly))
        return {};
    QByteArray data = f.readAll();
    if (data.startsWith("\xEF\xBB\xBF"))
        data.remove(0, 3);
    const QJsonObject seen = QJsonDocument::fromJson(data).object();
    const QFileInfo program(seen.value(QStringLiteral("exe")).toString());
    if (!seen.value(QStringLiteral("tools")).isArray() || !program.isFile()
        || program.size() != qint64(seen.value(QStringLiteral("size")).toDouble(-1))
        || program.lastModified().toSecsSinceEpoch() != qint64(seen.value(QStringLiteral("mtime")).toDouble(-1)))
        return {};
    QStringList tools;
    for (const QJsonValue &v : seen.value(QStringLiteral("tools")).toArray())
        tools << v.toString();
    *known = true;
    return tools;
}

// The names an editing session turns off (the same rule as ai_clis.editing_tool_names).
inline QStringList aiClaudeEditingToolNames(const QJsonObject &spec, const QStringList &offered, bool offeredKnown)
{
    QSet<QString> keep;
    for (const QJsonValue &v : spec.value(QStringLiteral("keep")).toArray())
        keep << v.toString();
    const QString fallback = spec.value(QStringLiteral("shell_fallback")).toString();
    QStringList out;
    for (const QJsonValue &v : spec.value(QStringLiteral("drop")).toArray()) {
        const QString name = v.toString();
        if (!name.isEmpty() && !keep.contains(name) && name != fallback && !out.contains(name))
            out << name;
    }
    QStringList extra;
    for (const QString &name : offered) {
        if (!name.isEmpty() && !keep.contains(name) && name != fallback && !out.contains(name) && !extra.contains(name)
            && !name.startsWith(QLatin1String("mcp__")))
            extra << name;
    }
    extra.sort();
    out << extra;
    if (!fallback.isEmpty() && offeredKnown && offered.contains(QStringLiteral("Bash")) && !keep.contains(fallback))
        out << fallback;
    return out;
}

inline QStringList aiClaudeEditingToolArgs()
{
    if (!aiEditingBuiltinsOff())
        return {};
    const QJsonObject spec = aiEntry(QStringLiteral("claude")).value(QStringLiteral("editing_tools")).toObject();
    bool known = false;
    const QStringList offered = aiClaudeOfferedTools(&known);
    const QStringList names = aiClaudeEditingToolNames(spec, offered, known);
    if (names.isEmpty())
        return {};
    const QString flag = spec.value(QStringLiteral("flag")).toString(QStringLiteral("--disallowedTools"));
    return {flag + QLatin1Char('=') + names.join(QLatin1Char(','))};
}

// T240 (the owner, 17 Nov: "if an agent is just making new video then it should not need the other connectors"): New
// video's and Learn's own chat starts Claude Code with only the tool servers the app gives it (--mcp-config: letitedit),
// not the person's other MCP servers or claude.ai connectors, whose tool names and instructions every step of a run
// re-reads. Skills are untouched (they come from the person's skills folder). Every turn of that chat counts: the first,
// the app's carry-ons, Continue the edit and anything typed into it (all run with its unattended settings,
// autonomousNewVideo with newVideoChat). Live Review's round (unattended, but not New video's chat) and every chat the
// person starts keep their connectors. A person whose only server is letitedit starts the same as before.
// T322 P2: the same chat, with its switch on, also leaves out the built-in tools above.
inline QStringList aiClaudeNewVideoToolArgs(bool autonomousNewVideo, bool newVideoChat)
{
    if (autonomousNewVideo && newVideoChat)
        return QStringList{QStringLiteral("--strict-mcp-config")} + aiClaudeEditingToolArgs();
    return {};
}

#endif // NEWVIDEOTOOLS_H
