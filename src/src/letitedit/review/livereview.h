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

#ifndef LIVEREVIEW_H
#define LIVEREVIEW_H

#include <QImage>
#include <QJsonArray>
#include <QJsonObject>
#include <QObject>
#include <QPointer>
#include <QString>
#include <QStringList>
#include <QTimer>
#include <QVector>

#include <functional>

class MainWindow;
class QProcess;

// Live Review's notes once they are sent (T53). The AI takes them one at a time, one turn each, and works on a copy of
// the project (<stem>.letitedit/review/live/work.mlt), so what the person is watching never changes under them. Each
// finished note leaves a copy of the timeline (after-<id>.mlt); loading brings them into the open window in order, one
// Undo step each (bridge/live_review.py land). The session belongs to the main window, not to Review: closing Review
// doesn't lose notes the AI is working on. It says nothing about the screen; Review and the player's banner show it.
namespace LiveReview {

enum class State { Waiting, Working, Done, NotAnEdit, CouldNot, Cancelled, Undone };

struct Item
{
    int id = 0;
    int frame = -1;       // on the version being watched when it was made; -1: about the whole video
    int takesBack = 0;    // a request to take back this note's change
    QString when;         // its moment, in plain text
    QString words;        // what was said or typed, as written down
    QString body;         // the note's part of the request
    QString folder;       // its pictures and recording
    QString picture;      // a picture for the list
    QString watched;      // the version it was made on
    QJsonArray strokes;   // what was drawn, to show on its frame again
    QImage thumb;
    State state = State::Waiting;
    QString what;         // what the AI changed
    QString why;          // why it couldn't, or what happened
    QString after;        // the timeline after this note
    QString label;        // its Undo step
    bool landed = false;  // in the open window
    bool cancelAsked = false;
    double changeAt = -1; // where its change is on the version loaded
    int request = 0;
    qint64 sentMs = 0;
    double tookS = 0;
};

class Session : public QObject
{
    Q_OBJECT
public:
    // The session of the project open in this window (made and read back from its folder the first time).
    static Session *of(MainWindow *window);
    // Only one that already exists and has something in it.
    static Session *existing(MainWindow *window);

    const QVector<Item> &items() const { return m_items; }
    const Item *item(int id) const;
    int waiting() const;      // not started
    int working() const;      // the AI has it now
    int ready() const;        // finished, and not in the window yet
    bool loading() const { return m_loading; }
    QString loadProblem() const { return m_loadProblem; }
    bool empty() const { return m_items.isEmpty(); }
    QString folder() const { return m_folder; }
    QString project() const { return m_project; }
    QString aiBusyNote() const { return m_aiBusyNote; }

    // A new number and the folder for a note about to be sent.
    int reserve(QString *folder);
    void add(Item item);
    void cancel(int id);      // not started: it never reaches the AI; working: the AI is stopped and its work thrown away
    void undo(int id);        // takes a finished note's change back (at once when nothing is built on it, else the AI does it)
    void again(int id);       // one that couldn't be done, or was cancelled, goes again
    void clear(int id);       // off the list

    // Every finished note into the open window. done(first change in seconds, what went wrong or empty).
    void load(const std::function<void(double, const QString &)> &done);

    QJsonObject state() const;

signals:
    void changed();

private:
    Session(MainWindow *window, const QString &project, QObject *parent);
    Item *find(int id);
    void restore();
    void save();
    void pump();
    void beginRound(const std::function<void(bool)> &then);
    void sendNext(int id);
    void compose(int id, const QJsonObject &moment);
    void finish(int id, const QJsonObject &outcome);
    void failRest(const QString &why);
    void writeActive(bool on);
    void touch();
    QString tipBefore(int id) const;
    QProcess *helper(const QStringList &args, const std::function<void(int, const QJsonObject &, const QString &)> &done);

    QPointer<MainWindow> m_window;
    QString m_project;
    QString m_folder;
    QString m_tip;     // the timeline with every finished note so far
    QString m_base;    // what this round started from
    QString m_watched; // the version in the window
    QVector<Item> m_items;
    int m_nextId = 1;
    int m_watchedNumber = 0;
    int m_idleTicks = 0;
    qint64 m_shownMinutes = 0;
    bool m_preparing = false;
    bool m_loading = false;
    bool m_keptVersion = false;
    QString m_aiBusyNote;
    QString m_loadProblem; // why the last load stopped: it isn't tried again by itself
    QTimer m_tick;
    QTimer m_endRound;
};

} // namespace LiveReview

#endif // LIVEREVIEW_H
