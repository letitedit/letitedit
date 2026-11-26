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

#include "letitedit/export/chapters.h"

#include "letitedit/chat/aichatpanel.h"
#include "docks/timelinedock.h"
#include "mainwindow.h"
#include "mltcontroller.h"
#include "models/markersmodel.h"
#include "models/multitrackmodel.h"
#include "settings.h"

#include <QClipboard>
#include <QDialog>
#include <QDialogButtonBox>
#include <QDir>
#include <QDockWidget>
#include <QGuiApplication>
#include <QHeaderView>
#include <QLabel>
#include <QPointer>
#include <QPushButton>
#include <QTableWidget>
#include <QVBoxLayout>

#include <algorithm>

namespace Chapters {

namespace {

const QString kPrefix = QStringLiteral("chapter:");

QString stamp(double seconds)
{
    // YouTube reads whole seconds: drop the fraction (a chapter must not start late), but not frame rounding.
    const int s = qMax(0, int(seconds + 0.05));
    if (s >= 3600)
        return QStringLiteral("%1:%2:%3")
            .arg(s / 3600)
            .arg(s / 60 % 60, 2, 10, QLatin1Char('0'))
            .arg(s % 60, 2, 10, QLatin1Char('0'));
    return QStringLiteral("%1:%2").arg(s / 60).arg(s % 60, 2, 10, QLatin1Char('0'));
}

double videoSeconds(MainWindow *window)
{
    auto model = window->timelineDock()->model();
    return model->tractor() ? model->tractor()->get_playtime() / MLT.profile().fps() : 0.0;
}

} // namespace

QList<Chapter> fromTimeline(MainWindow *window)
{
    QList<Chapter> chapters;
    if (!window->isMultitrackValid())
        return chapters;
    const auto markers = window->timelineDock()->markersModel()->getMarkers();
    for (int i = 0; i < markers.size(); ++i) {
        const QString text = markers[i].text.trimmed();
        if (text.startsWith(kPrefix, Qt::CaseInsensitive))
            chapters.append({markers[i].start, text.mid(kPrefix.size()).trimmed(), i});
    }
    std::sort(chapters.begin(), chapters.end(), [](const Chapter &a, const Chapter &b) { return a.frame < b.frame; });
    return chapters;
}

QList<Chapter> forYouTube(const QList<Chapter> &chapters)
{
    QList<Chapter> list = chapters;
    if (!list.isEmpty() && list.first().frame > 0)
        list.prepend({0, QObject::tr("Intro"), -1});
    return list;
}

QString youtubeText(const QList<Chapter> &chapters, double fps)
{
    QStringList lines;
    for (const auto &c : forYouTube(chapters))
        lines << stamp(c.frame / fps) + ' ' + (c.title.isEmpty() ? QObject::tr("Chapter") : c.title);
    return lines.join('\n');
}

QStringList problems(const QList<Chapter> &chapters, double fps, double seconds)
{
    QStringList found;
    const QList<Chapter> list = forYouTube(chapters);
    if (list.size() < 3)
        found << QObject::tr("YouTube needs at least 3 chapters (%1 now).").arg(list.size());
    for (int i = 0; i < list.size(); ++i) {
        const double start = list[i].frame / fps;
        const double end = i + 1 < list.size() ? list[i + 1].frame / fps : seconds;
        if (end - start < 10.0)
            found << QObject::tr("“%1” at %2 lasts %3 s; each chapter needs at least 10 s.")
                         .arg(list[i].title, stamp(start))
                         .arg(qMax(0.0, end - start), 0, 'f', 1);
        if (list[i].title.isEmpty())
            found << QObject::tr("The chapter at %1 has no title.").arg(stamp(start));
    }
    return found;
}

void show(MainWindow *window)
{
    static QPointer<QDialog> open;
    if (open) {
        open->raise();
        open->activateWindow();
        return;
    }
    if (!window->isMultitrackValid()) {
        window->showStatusMessage(QObject::tr("Open a timeline first."));
        return;
    }
    const double fps = MLT.profile().fps();
    auto markers = window->timelineDock()->markersModel();

    auto *dialog = new QDialog(window);
    dialog->setAttribute(Qt::WA_DeleteOnClose);
    dialog->setObjectName(QStringLiteral("chaptersDialog"));
    dialog->setWindowTitle(QObject::tr("YouTube Chapters"));
    open = dialog;
    auto *layout = new QVBoxLayout(dialog);
    auto *intro = new QLabel(QObject::tr("Chapters are the timeline's markers named chapter: and a title. Move one by "
                                         "dragging its marker; change a title here."));
    intro->setWordWrap(true);
    layout->addWidget(intro);
    auto *table = new QTableWidget(0, 2);
    table->setObjectName(QStringLiteral("chaptersTable"));
    table->setHorizontalHeaderLabels({QObject::tr("Starts"), QObject::tr("Title")});
    table->horizontalHeader()->setSectionResizeMode(0, QHeaderView::ResizeToContents);
    table->horizontalHeader()->setSectionResizeMode(1, QHeaderView::Stretch);
    table->verticalHeader()->hide();
    table->setSelectionBehavior(QAbstractItemView::SelectRows);
    layout->addWidget(table, 1);
    auto *rules = new QLabel;
    rules->setObjectName(QStringLiteral("chaptersRules"));
    rules->setWordWrap(true);
    rules->setTextFormat(Qt::RichText);
    layout->addWidget(rules);

    auto *buttons = new QDialogButtonBox(QDialogButtonBox::Close);
    auto *add = buttons->addButton(QObject::tr("Add at Playhead"), QDialogButtonBox::ActionRole);
    add->setObjectName(QStringLiteral("chaptersAdd"));
    auto *ask = buttons->addButton(QObject::tr("Ask My AI..."), QDialogButtonBox::ActionRole);
    ask->setObjectName(QStringLiteral("chaptersAsk"));
    ask->setToolTip(QObject::tr("Your AI finds the chapters from what is said and adds them as markers"));
    auto *copy = buttons->addButton(QObject::tr("Copy for YouTube"), QDialogButtonBox::ActionRole);
    copy->setObjectName(QStringLiteral("chaptersCopy"));
    copy->setDefault(true);
    QObject::connect(buttons, &QDialogButtonBox::rejected, dialog, &QDialog::close);
    layout->addWidget(buttons);

    auto filling = std::make_shared<bool>(false);
    const auto refresh = [=]() {
        const QList<Chapter> chapters = fromTimeline(window);
        *filling = true;
        table->setRowCount(0);
        for (const auto &c : forYouTube(chapters)) {
            const int row = table->rowCount();
            table->insertRow(row);
            auto *time = new QTableWidgetItem(stamp(c.frame / fps));
            time->setFlags(Qt::ItemIsEnabled | Qt::ItemIsSelectable);
            time->setData(Qt::UserRole, c.marker);
            auto *title = new QTableWidgetItem(c.title);
            if (c.marker < 0) {
                title->setFlags(Qt::ItemIsEnabled);
                title->setToolTip(QObject::tr("Added for YouTube, which needs a chapter at 0:00. Add your own "
                                              "chapter at the start to name it."));
            }
            table->setItem(row, 0, time);
            table->setItem(row, 1, title);
        }
        *filling = false;
        if (chapters.isEmpty()) {
            rules->setText(QObject::tr("No chapters yet. Add one at the playhead, or ask your AI to find them."));
            copy->setEnabled(false);
            return;
        }
        copy->setEnabled(true);
        const QStringList found = problems(chapters, fps, videoSeconds(window));
        if (found.isEmpty())
            rules->setText(QStringLiteral("<span style='color:#5ec8b4'>✓</span> ")
                           + QObject::tr("Follows YouTube's rules: starts at 0:00, at least 3 chapters, each 10 s or "
                                         "longer."));
        else {
            QStringList lines;
            for (const auto &problem : found)
                lines << QStringLiteral("<span style='color:#ffb347'>⚠</span> ") + problem.toHtmlEscaped();
            rules->setText(lines.join(QStringLiteral("<br>")));
        }
    };
    QObject::connect(table, &QTableWidget::itemChanged, dialog, [=](QTableWidgetItem *item) {
        if (*filling || item->column() != 1)
            return;
        const int marker = table->item(item->row(), 0)->data(Qt::UserRole).toInt();
        if (marker < 0)
            return;
        Markers::Marker m = markers->getMarker(marker);
        m.text = kPrefix + item->text().trimmed();
        markers->update(marker, m);
    });
    // Queued: a title edit changes the marker, and the table must not be rebuilt while it is still handling that edit.
    QObject::connect(markers, &MarkersModel::modified, dialog, refresh, Qt::QueuedConnection);
    QObject::connect(markers, &QAbstractItemModel::modelReset, dialog, refresh, Qt::QueuedConnection);
    QObject::connect(add, &QPushButton::clicked, dialog, [=]() {
        Markers::Marker m;
        m.text = kPrefix + QObject::tr("New chapter");
        m.start = m.end = qMax(0, window->timelineDock()->position());
        m.color = Settings.markerColor();
        markers->append(m);
        refresh();
        table->editItem(table->item(table->rowCount() - 1, 1));
    });
    QObject::connect(copy, &QPushButton::clicked, dialog, [=]() {
        const QList<Chapter> chapters = fromTimeline(window);
        QGuiApplication::clipboard()->setText(youtubeText(chapters, fps));
        window->showStatusMessage(
            QObject::tr("Copied %1 chapters. Paste them into the YouTube description.").arg(forYouTube(chapters).size()));
    });
    QObject::connect(ask, &QPushButton::clicked, dialog, [=]() {
        const QString project = window->fileName();
        if (project.isEmpty()) {
            rules->setText(QObject::tr("Save your video first, so your AI can read it."));
            return;
        }
        const double seconds = videoSeconds(window);
        const QString request
            = QObject::tr("YouTube chapters, please, for the open letitedit project \"%1\" (%2 long). Use what is said "
                          "(letitedit_words on the project). Pick 3 to 8 chapters: the first at 0:00, each at least 10 "
                          "seconds, each starting where a new part begins, with a title of two to five words that says "
                          "what happens. Add each as a marker named chapter:<title> at its start with letitedit_bin, "
                          "after removing any chapter: markers already there. Then list them as YouTube lines.")
                  .arg(QDir::toNativeSeparators(project), stamp(seconds));
        if (!aiChatRequest(window, request, QObject::tr("Write YouTube chapters for this video"))) {
            rules->setText(QObject::tr("Your AI is still busy with the last request. Try again when it has answered."));
            return;
        }
        if (auto chat = window->findChild<QDockWidget *>(QStringLiteral("aiChatDock"))) {
            chat->show();
            chat->raise();
        }
        rules->setText(QObject::tr("Your AI is finding the chapters. They appear here when it adds the markers."));
    });
    refresh();
    dialog->resize(520, 420);
    dialog->show();
}

} // namespace Chapters
