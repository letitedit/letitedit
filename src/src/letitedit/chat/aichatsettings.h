/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The settings helpers aichatsettings.cpp shares with the chat panel (aichatpanel.cpp). What the rest of the editor
 * calls is in aichatpanel.h.
 */
#ifndef AICHATSETTINGS_H
#define AICHATSETTINGS_H

#include "letitedit/chat/aichatpanel.h"

// The chat's settings file (panel.json, or the one LETITEDIT_CHAT_SETTINGS names) and its history file.
QString aiChatSettingsPath();
QString aiChatHistoryPath();
// Whether an AI in the list can do something ("terminal": show its own program screen).
bool aiEngineCan(const QString &id, const QString &what);
// The chat shows the AI's real program screen, not chat bubbles.
bool aiTerminalMode();
// The short name of the AI the chat talks to now.
QString aiChatEngineName();
// A top-level value from Codex's own config.toml.
QString aiCodexConfigValue(const QString &key);
// An effort in words ("Extra high").
QString aiChatEffortWord(const QString &effort);
// Where the chat keeps Codex's list of models.
QString aiCodexModelsPath();
// The efforts a Codex model takes, whether a list holds a value, and the nearest effort a model takes to the one chosen.
QList<AiChatChoice> aiCodexEffortChoicesFor(const QString &model);
bool aiChatHasChoice(const QList<AiChatChoice> &choices, const QString &value);
QString aiNearestEffort(const QList<AiChatChoice> &takes, const QString &chosen);
// What Codex's speed choice passes: its service tier and the extra config settings.
QString aiCodexSpeedTier(const QJsonObject &settings);
QStringList aiCodexSpeedConfigArgs();
// Auto model routing (bridge/ai_list.json "routing", as bridge ai_clis.choice reads it). aiAutoRouting: the switch, on
// by default (T365; LETITEDIT_AUTO_ROUTING, 1 or 0, wins, else settings.json auto_routing, false turns it off): with
// it on, the model row offers Auto and Auto is the choice of anyone who never chose. aiResolvedChoice: the settings
// with a saved "auto" model turned into the planning role's model and effort (the gear's routing_max: the max row),
// for the AI's command line.
bool aiAutoRouting();
QJsonObject aiRouting(const QString &engine);
bool aiModelIsAuto(const QString &model);
QJsonObject aiResolvedChoice(const QJsonObject &settings);
// PATH for the AI process, or an empty string when the inherited PATH should be used.
QString aiChatPythonPath(const QJsonObject &settings);

#endif // AICHATSETTINGS_H
