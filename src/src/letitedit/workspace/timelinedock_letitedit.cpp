/* Copyright (c) 2026 letitedit
 * SPDX-License-Identifier: GPL-3.0-or-later
 * The timeline's adjustment layer (an effect over everything below it for a stretch).
 * (letitedit's additions to timelinedock.cpp, moved out of Shotcut's file; the
 * declarations stay in its header.)
 */
#include "docks/timelinedock.h"

#include "Logger.h"
#include "abstractproducerwidget.h"
#include "actions.h"
#include "letitedit/chat/aichatpanel.h"
#include "commands/timelinecommands.h"
#include "dialogs/alignaudiodialog.h"
#include "dialogs/durationdialog.h"
#include "dialogs/editmarkerdialog.h"
#include "dialogs/longuitask.h"
#include "dialogs/resourcedialog.h"
#include "jobs/meltjob.h"
#include "mainwindow.h"
#include "models/audiolevelstask.h"
#include "models/multitrackmodel.h"
#include "proxymanager.h"
#include "qmltypes/qmlapplication.h"
#include "qmltypes/qmlutilities.h"
#include "qmltypes/qmlview.h"
#include "qmltypes/thumbnailprovider.h"
#include "settings.h"
#include "shotcut_mlt_properties.h"
#include "util.h"
#include "widgets/blipproducerwidget.h"
#include "widgets/colorbarswidget.h"
#include "widgets/colorproducerwidget.h"
#include "widgets/countproducerwidget.h"
#include "widgets/docktoolbar.h"
#include "widgets/glaxnimateproducerwidget.h"
#include "widgets/noisewidget.h"
#include "widgets/textproducerwidget.h"
#include "widgets/toneproducerwidget.h"

#include <QAction>
#include <QActionGroup>
#include <QClipboard>
#include <QDialogButtonBox>
#include <QGuiApplication>
#include <QInputDialog>
#include <QJsonDocument>
#include <QFile>
#include <QFileInfo>
#include <QMenu>
#include <QProgressBar>
#include <QQmlContext>
#include <QQuickItem>
#include <QQuickWidget>
#include <QSlider>
#include <QToolBar>
#include <QToolButton>
#include <QVBoxLayout>
#include <QWidgetAction>
#include <qlistwidget.h>

// letitedit's way in to the same clip: over the selection or 5 s at the playhead, on a track of its own just above the current
// one, as one undo step, with the block selected and the Filters panel open.
void TimelineDock::addAdjustmentLayer()
{
    if (!m_model.tractor() || m_model.trackList().isEmpty()) {
        emit showStatusMessage(tr("Add a clip to the timeline first."));
        return;
    }
    int start = position();
    int frames = qRound(5.0 * MLT.profile().fps());
    const auto picked = selection();
    int row = currentTrack();
    if (!picked.isEmpty()) {
        int first = INT_MAX, end = 0;
        row = m_model.trackList().size();
        for (const auto &point : picked) {
            row = qMin(row, point.y()); // just above the highest clip chosen
            auto info = m_model.getClipInfo(point.y(), point.x());
            if (info) {
                first = qMin(first, info->start);
                end = qMax(end, info->start + info->frame_count);
            }
        }
        if (end > first) {
            start = first;
            frames = end - first;
        }
    }

    Mlt::Producer producer(MLT.profile(), "color:0");
    if (!producer.is_valid())
        return;
    producer.set("mlt_image_format", "rgba");
    producer.set("meta.fx_cut", 1);
    producer.set(kShotcutProducerProperty, "adjustment");
    producer.set(kShotcutCaptionProperty, tr("Adjustment layer").toUtf8().constData());
    MLT.setDurationFromDefault(&producer);
    producer.set_in_and_out(0, frames - 1);

    // A track holding only blocks, with room here?
    const auto &tracks = m_model.trackList();
    auto roomOn = [&](int row) {
        if (row < 0 || row >= tracks.size() || tracks.at(row).type != VideoTrackType || isTrackLocked(row))
            return false;
        bool any = false;
        for (int i = 0; i < clipCount(row); ++i) {
            if (isBlank(row, i))
                continue;
            auto info = m_model.getClipInfo(row, i);
            if (!info || !info->producer || !info->producer->get_int("meta.fx_cut"))
                return false;
            any = true;
            if (info->start < start + frames && info->start + info->frame_count > start)
                return false;
        }
        return any;
    };
    bool found = roomOn(row);
    if (!found && roomOn(row - 1)) {
        row = row - 1;
        found = true;
    }

    MAIN.undoStack()->beginMacro(tr("Add adjustment layer"));
    if (!found) {
        setSelection();
        if (row <= 0 || row >= tracks.size() || tracks.at(row).type != VideoTrackType) {
            MAIN.undoStack()->push(new Timeline::AddTrackCommand(m_model, true));
            row = 0;
        } else {
            MAIN.undoStack()->push(new Timeline::InsertTrackCommand(m_model, row, VideoTrackType));
        }
        QSet<QString> names;
        for (int r = 0; r < m_model.rowCount(); ++r)
            if (r != row)
                names << m_model.index(r, 0).data(MultitrackModel::NameRole).toString();
        QString name = tr("Adjustment");
        for (int n = 2; names.contains(name); ++n)
            name = tr("Adjustment %1").arg(n);
        MAIN.undoStack()->push(new Timeline::NameTrackCommand(m_model, row, name));
    }
    MAIN.undoStack()->push(new Timeline::OverwriteCommand(m_model, row, start, MLT.XML(&producer), false));
    MAIN.undoStack()->endMacro();

    setCurrentTrack(row);
    setSelection(QList<QPoint>{QPoint(clipIndexAtPosition(row, start), row)}, row);
    QMetaObject::invokeMethod(&MAIN, "onFiltersDockTriggered", Qt::QueuedConnection, Q_ARG(bool, true));
}
