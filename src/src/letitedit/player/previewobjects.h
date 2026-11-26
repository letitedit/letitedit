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

#ifndef PREVIEWOBJECTS_H
#define PREVIEWOBJECTS_H

#include <QHash>
#include <QList>
#include <QObject>
#include <QPointer>
#include <QRectF>
#include <QTimer>
#include <QVariantList>
#include <QVariantMap>

class MainWindow;
class QLabel;
class QToolButton;
class QWidget;

// letitedit: the things on the player you can grab - text clips and burned-in spoken captions -
// so the person can click one, drag it, resize it and act on it directly on the video, the way
// creator apps work. Positions are fractions of the frame (0-1). A drag previews live and becomes
// one undo step when released.
class PreviewObjects : public QObject
{
    Q_OBJECT
    // T99: what the person has selected in the video or on the timeline; an AI request carries it.
    // {kind, kindLabel, label, id, track, clip, start, end, range, grab, cue, x, y, w, h, atPlayhead, gone}. Empty when nothing is.
    Q_PROPERTY(QVariantMap target READ target NOTIFY targetChanged)
public:
    explicit PreviewObjects(MainWindow *window);

    QVariantMap target() const { return m_targets.isEmpty() ? QVariantMap() : m_targets.first(); }
    QList<QVariantMap> targets() const { return m_targets; }
    QVariantList choices() const { return m_choices; }
    bool hasTarget() const { return !m_targets.isEmpty(); }
    // The row for the player's top line: what's selected, Choose item here, Ask AI, Clear.
    QWidget *bar() const { return m_bar; }
    // What a click at this point of the picture (fractions of the frame) lands on, topmost first: captions, text,
    // graphics, pictures, whole scenes and video clips on tracks that aren't hidden or locked.
    Q_INVOKABLE QVariantList itemsAt(double x, double y);
    // A click in the player: selects the topmost item there and pauses, or clears the selection on blank picture.
    // Empty when the player isn't showing the project, or nothing is there. "wasTarget": it was already selected.
    Q_INVOKABLE QVariantMap pickAt(double x, double y);
    Q_INVOKABLE void clearTarget();
    // Esc in the window: clears the selection, unless the key is for a text box. True if it did.
    bool escapePressed();
    void choose(int index);
    // The target's line for an AI request, or a plain problem instead when the item has gone.
    QString requestLine(QString *problem);
    // Short words for the chip: Caption "Think frame by frame" 0:04.2-0:05.1. Empty when nothing is selected.
    QString chipText() const;

signals:
    void targetChanged();
    void askAiRequested();

public:

    // Topmost first: {kind: "text"|"caption", track, clip|item, x, y, w, h, angle, size, label}
    Q_INVOKABLE QVariantList objectsAtPlayhead();
    // Every text clip on the timeline ({kind: "text", track, clip, x, y, w, h, start, label}) and every burned-in
    // caption track ({kind: "caption", feed, geometry, valign, size, label}), for the export checklist.
    QVariantList allObjects() const;
    Q_INVOKABLE void select(const QVariantMap &object);
    // Live change while dragging (no undo yet); scale multiplies the text size; angle in degrees.
    Q_INVOKABLE void preview(const QVariantMap &object, double x, double y, double w, double h, double scale,
                             double angle = 0.0);
    // The change as one undo step; the live preview is replaced by it.
    Q_INVOKABLE void commit(const QVariantMap &object, double x, double y, double w, double h, double scale,
                            double angle = 0.0);
    Q_INVOKABLE void edit(const QVariantMap &object);
    Q_INVOKABLE void remove(const QVariantMap &object);

private:
    void setupBar();
    void updateBar();
    void setTargets(const QList<QVariantMap> &targets, const QVariantList &choices);
    void selectInTimeline(const QVariantMap &item);
    void onTimelineSelection();
    void refreshTargets();
    void updateBox();
    QVariantMap clipItem(int track, int clip, const QHash<quint64, QString> &ids) const;
    QHash<quint64, QString> stableIds() const;
    bool resolve(QVariantMap &item, const QHash<quint64, QString> &ids) const;

    MainWindow *m_window;
    QList<QVariantMap> m_targets;
    QVariantList m_choices;
    QString m_project;
    bool m_syncing = false;
    int m_boxPosition = -1;
    QTimer m_boxTimer;
    QTimer m_refreshTimer;
    QPointer<QWidget> m_returnFocus; // the AI's box or screen, when a click in the picture has just taken the keyboard from it
    QWidget *m_bar = nullptr;
    QLabel *m_barLabel = nullptr;
    QToolButton *m_barChoose = nullptr;
};

#endif // PREVIEWOBJECTS_H
