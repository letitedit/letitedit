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

#ifndef CONNECTAI_H
#define CONNECTAI_H

#include <QDateTime>
#include <QString>

#include <functional>

class MainWindow;
class QObject;
class QProgressDialog;

// letitedit "Connect your AI": letitedit works through the AI subscription the person already has - Claude (Claude
// Code) or ChatGPT (Codex). This finds either CLI wherever it was installed, checks the tool environment, picks the
// one the chat panel uses, can also give the person's own Claude Code and Codex the letitedit tools and skills, and
// tests the connection with one small real request. Config folders follow the CLIs' own CLAUDE_CONFIG_DIR and
// CODEX_HOME.
namespace ConnectAi {

QString claudeExe();
QString codexExe();
// Where things go, in one line, the same wherever letitedit says it (welcome, Connect Your AI, New video): editing
// and media processing happen on this PC; requests and the transcript text and preview pictures the AI looks at go
// to the AI service the person chose.
QString privacyLine();
// Any AI program on this PC (a test window with a mocked AI counts as having one).
bool anyAi();
// An AI's program in plain text: "Claude Code", "Codex". The makers' names are never used as ours.
QString programName(const QString &engine);
// What letitedit does with the person's AI, for the first time they connect one and in Connect Your AI. The owner's exact words (3 Nov),
// the same for every AI: general text names no AI.
QString firstUseNotice();
// "" unless this AI's program looks installed but can't be found (an npm shim with no program behind it, a saved path that's gone):
// then what happened and how to reinstall it. letitedit never repairs a person's install itself.
QString missingWords(const QString &engine);
// The first such words for any AI, or "".
QString anyMissingWords();
// "" unless the Codex here is too old for New video's way of starting it: then what to do. Asks the program's own --help once per
// copy of the program (no model, no allowance); when it can't tell, it says nothing and New video goes on as usual.
QString newVideoTooOldWords(const QString &engine);
// A connector AI's own notice, from the AI list (it says what its maker does with what's sent, whatever the plan).
QString connectorNotice(const QString &engine);
// engine empty: the general notice; else a connector AI's own.
bool firstUseNoticeSeen(const QString &engine = QString());
void setFirstUseNoticeSeen(const QString &engine = QString());
// Asks the program whether it is signed in, in the background: no model, no allowance, only its answer is read (its status
// command's exit code and the words "logged in"; never a credentials file). done gets 1 yes, 0 no, -1 can't tell: the
// program is missing, its status command says nothing clear, or the person uses their own API key.
void checkSignedIn(const QString &engine, QObject *context, const std::function<void(int)> &done);
// The chat in letitedit talks to Codex (panel.json "engine"), not Claude.
bool chatUsesCodex();

// The person's own Claude Code / Codex have the letitedit tools (Codex: as an MCP server or the letitedit plugin).
bool claudeHasTools();
bool codexHasTools();
// Gives the person's own Claude Code / Codex the letitedit tools. Empty on success, else what went wrong.
QString addToolsToClaude();
QString addToolsToCodex();
QString installSkills();

struct Result
{
    bool ok = false;
    QString text;
};
// One small request through the chosen CLI ("claude" or "codex"), the way the chat panel sends them: it must use an
// editor tool and answer. The result is recorded (record()).
Result test(const QString &engine, QProgressDialog *progress = nullptr);

// What is known about an AI on this PC: "missing" (not found), "untested" (installed, never tested with this
// program), "ready" (its last test or chat answer worked) or "attention" (its last test failed: text says why). when:
// the last time it worked (ready) or was tested (attention).
struct Status
{
    QString state;
    QString exe;
    QDateTime when;
    QString text;
};
Status status(const QString &engine);
// A test result or a real chat answer for "claude" or "codex" (kept in letitedit-choices.ini, for this program).
void record(const QString &engine, bool ok, const QString &text);
// "ready, tested today at 14:02" / "installed, not tested yet" / "needs attention: ..." in plain words.
QString statusWords(const Status &status);

void show(MainWindow *window);
// Adds "Connect Your AI..." to the AI menu.
void install(MainWindow *window);

} // namespace ConnectAi

#endif // CONNECTAI_H
