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

#ifndef STICKERSPANEL_H
#define STICKERSPANEL_H

#include <QDockWidget>
#include <QJsonObject>
#include <QPoint>

#include <functional>

class MainWindow;
class LeToolRun;
class QAudioOutput;
class QComboBox;
class QLabel;
class QLineEdit;
class QListWidget;
class QListWidgetItem;
class QMediaPlayer;
class QMovie;
class QPushButton;
class QTimer;
class QWidget;

// letitedit "Stickers & sounds": the whole asset library (bridge/assets.py: Fluent emoji, Tabler icons, Google's
// animated emoji, stickers and CC0 sound effects), searchable by words. Drag one onto the timeline, or pick it and
// press Add at playhead: pictures and moving stickers go on a "Stickers" track, sounds on a "Sound effects" track,
// each one Undo step. The animated emoji are CC BY 4.0: they are marked "needs a credit line", and the line shows
// with a Copy button (the export checklist and the finished export show it again).
class StickersPanel : public QDockWidget
{
public:
    explicit StickersPanel(MainWindow *window);

    // kinds: "" for everything, else one of the panel's choices ("sfx" for sound effects)
    void showKinds(const QString &kinds);
    // For checks: the search, what shows, the chosen item and its credit line, the status line.
    QJsonObject qaState() const;

protected:
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    void search(bool more = false);
    void fill(const QJsonObject &result, bool more);
    void chosen();
    void add();
    void play();
    void ready(QListWidgetItem *item, const std::function<void(const QString &)> &then);
    void place(const QJsonObject &entry, const QString &file);
    void startDrag(QListWidgetItem *item);
    QString xmlFor(const QJsonObject &entry, const QString &file, QString *why);

    MainWindow *m_window;
    QLineEdit *m_search = nullptr;
    QComboBox *m_kind = nullptr;
    QListWidget *m_list = nullptr;
    QPushButton *m_more = nullptr;
    QWidget *m_creditBox = nullptr;
    QLabel *m_credit = nullptr;
    QLabel *m_status = nullptr;
    QPushButton *m_play = nullptr;
    QPushButton *m_add = nullptr;
    QPushButton *m_title = nullptr;
    QMovie *m_movie = nullptr;
    QTimer *m_debounce = nullptr;
    LeToolRun *m_searchRun = nullptr;
    LeToolRun *m_placeRun = nullptr;
    LeToolRun *m_previewRun = nullptr;
    QMediaPlayer *m_player = nullptr;
    QAudioOutput *m_output = nullptr;
    QPoint m_pressAt;
    QString m_resultsFor; // the search the list shows ("words|kind")
    QString m_previewId;
    int m_total = 0;
    int m_shown = 0;
    bool m_adding = false;
};

#endif // STICKERSPANEL_H
