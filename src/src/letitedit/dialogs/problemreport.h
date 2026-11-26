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

#ifndef PROBLEMREPORT_H
#define PROBLEMREPORT_H

// T368: problem reports the person sends on purpose (Help > Report a problem..., a button on the error screens), the
// crash report offered at the next start, and the setup problem the installer leaves behind. The report window shows
// every part that would be sent as editable text with a tick box; only what it shows is sent, and only on Send.
// Never in a report: footage, pictures, project files, the chat's text, a sign-in or key, the person's name, e-mail,
// Windows user name, the PC's name or a file path (clean() replaces them before the window shows the text).
//
// Where reports go: LETITEDIT_REPORTS_URL when set ("off": nowhere), else the built-in address, used only by the main
// profile (test and Studio windows never reach the internet). The built-in address is empty until the deploy is
// approved: until then the window offers Save as a file instead of Send.

#include <QJsonObject>
#include <QString>

class QWidget;
class QMenu;

namespace ProblemReport {

// Where a report window was opened from, and what it adds.
struct Context
{
    QString from = QStringLiteral("help-menu"); // help-menu, welcome-error, export-error, after-crash, after-setup
    QString kind = QStringLiteral("problem");   // problem, crash, setup
    QString screen;                             // what the error screen said
};

// The cleaning every part goes through: paths, names, e-mail addresses, keys and links' paths replaced.
QString clean(const QString &text);
// The parts a report would hold, cleaned: about, log, ai, and screen / crash / setup when they apply.
QJsonObject parts(const Context &context);
// The report as sent: format, kind, from, report id and the ticked parts (words first).
QJsonObject report(const Context &context, const QJsonObject &parts, const QString &reportId);
// The reports server's address ("" when this window can't send).
QString reportsUrl();
// This build's name, from the exe's file name ("20261124.1"), else the file's base name.
QString buildName();

void showDialog(QWidget *parent, const Context &context = Context());
// Help menu: Report a problem...
void addMenuItems(QWidget *window, QMenu *help);
// 2 s after the window is up: the note about last time's crash, or about a setup that went wrong.
void checkAtStart(QWidget *window);

// The watchdog parent: the window's process ended. Records a crash note when it crashed (an exception code, or 3 for
// an internal abort) or hung at start-up; an ordinary close, End task or taskkill (exit code 1) is not a crash.
void recordChildEnd(const QString &appData, bool crashExit, int exitCode, qint64 ranMs, bool hungAtStart);
// The window's process (release builds): a last-chance handler that writes the exception and its frames as module +
// offset into <appData>/crash/detail.txt, then ends the process with the same code.
void installCrashHandler(const QString &appData);

// For the checks (test windows only): builds a report with the real cleaning from given texts, without a window.
QJsonObject qaReport(const QJsonObject &params);
// For the checks: a real access violation (test windows only).
void qaCrash();

} // namespace ProblemReport

#endif // PROBLEMREPORT_H
