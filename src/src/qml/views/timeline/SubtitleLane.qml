/*
 * Copyright (c) 2024-2026 Meltytech, LLC
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
import QtQuick

// One subtitle track as a lane in the timeline (letitedit). The selection model works on one
// "selected track" at a time, so interacting with a caption first makes this lane's track current.
Item {
    id: lane

    property int trackIndex: 0
    property real timeScale: 1
    readonly property bool isCurrent: subtitlesSelectionModel.selectedTrack() === trackIndex && selectionTick >= 0
    property int selectionTick: 0

    clip: false

    function makeCurrent() {
        if (subtitlesSelectionModel.selectedTrack() !== trackIndex)
            subtitlesDock.selectTrack(trackIndex);
    }

    function startDrag() {
        var selectedItems = subtitlesSelectionModel.selectedItems;
        for (var i = 0; i < selectedItems.length; i++) {
            var subtitle = subtitlesRepeater.itemAt(selectedItems[i]);
            if (!subtitle)
                continue;
            subtitle.dragInProgress = true;
            subtitle.x = subtitle.calculatedX;
            subtitle.z += subtitlesModel.itemCount(trackIndex);
        }
    }

    function setDragDelta(delta) {
        var selectedItems = subtitlesSelectionModel.selectedItems;
        for (var i = 0; i < selectedItems.length; i++) {
            var subtitle = subtitlesRepeater.itemAt(selectedItems[i]);
            if (subtitle)
                subtitle.x = subtitle.calculatedX + delta;
        }
    }

    function endDrag() {
        var selectedItems = subtitlesSelectionModel.selectedItems;
        for (var i = 0; i < selectedItems.length; i++) {
            var subtitle = subtitlesRepeater.itemAt(selectedItems[i]);
            if (!subtitle)
                continue;
            subtitle.dragInProgress = false;
            subtitle.z -= subtitlesModel.itemCount(trackIndex);
        }
    }

    function moveItems(deltaFrames) {
        var selectedRows = subtitlesSelectionModel.selectedRows();
        if (selectedRows.length <= 0)
            return;
        var groupStart = -1;
        for (var i = 0; i < selectedRows.length; i++) {
            var subtitle = subtitlesRepeater.itemAt(selectedRows[i].row);
            if (subtitle && (groupStart == -1 || subtitle.calculatedX < groupStart))
                groupStart = subtitle.calculatedX;
        }
        groupStart = groupStart / timeScale;
        var newStart = (groupStart + deltaFrames) * 1000.0 / profile.fps;
        if (subtitlesModel.validateMove(selectedRows, newStart)) {
            var firstItemIndex = selectedRows[0].row;
            var lastItemIndex = selectedRows[selectedRows.length - 1].row;
            subtitlesModel.moveItems(trackIndex, firstItemIndex, lastItemIndex, newStart);
        } else {
            application.showStatusMessage(qsTr('Unable to move. Subtitles already exist at this time.'));
        }
    }

    // thin separator + faint tint so lanes read as separate tracks
    Rectangle {
        anchors.fill: parent
        color: lane.isCurrent ? Qt.rgba(activePalette.highlight.r, activePalette.highlight.g, activePalette.highlight.b, 0.12) : 'transparent'
        border.width: 0
    }
    Rectangle {
        anchors.bottom: parent.bottom
        width: parent.width
        height: 1
        color: Qt.darker(activePalette.window, 1.3)
    }

    Connections {
        function onSelectedTrackModelIndexChanged() {
            lane.selectionTick++;
            subtitlesSelectionRepeater.model = lane.isCurrent ? subtitlesSelectionModel.selectedItems : [];
        }

        function onSelectedItemsChanged() {
            subtitlesSelectionRepeater.model = lane.isCurrent ? subtitlesSelectionModel.selectedItems : [];
        }

        target: subtitlesSelectionModel
    }

    Connections {
        function onModelReset() {
            // The delegate model drops its root on a reset after this handler runs, so set it again afterwards.
            Qt.callLater(() => {
                subtitlesDelegateModel.rootIndex = subtitlesModel.trackModelIndex(-1);
                subtitlesDelegateModel.rootIndex = subtitlesModel.trackModelIndex(lane.trackIndex);
            });
        }
        function onTracksChanged() {
            subtitlesDelegateModel.rootIndex = subtitlesModel.trackModelIndex(lane.trackIndex);
        }

        target: subtitlesModel
    }

    DelegateModel {
        id: subtitlesDelegateModel

        model: subtitlesModel
        rootIndex: subtitlesModel.trackModelIndex(lane.trackIndex)

        delegate: Subtitle {
            timeScale: lane.timeScale
            height: lane.height - 1
            laneTrack: lane.trackIndex

            onActivated: lane.makeCurrent()
            onDragStarted: lane.startDrag()
            onDragMoved: delta => lane.setDragDelta(delta)
            onDragEnded: lane.endDrag()
            onMoveRequested: deltaFrames => lane.moveItems(deltaFrames)
            onEditRequested: itemIndex => subtitlesDock.editCaption(lane.trackIndex, itemIndex)
        }
    }

    Repeater {
        id: subtitlesRepeater
        model: subtitlesDelegateModel
    }

    Repeater {
        id: subtitlesSelectionRepeater

        Rectangle {
            property var subtitle: subtitlesRepeater.itemAt(modelData)

            x: subtitle ? subtitle.x : 0
            y: subtitle ? subtitle.y : 0
            z: subtitle ? subtitle.z + 1 : 0
            width: subtitle ? subtitle.width : 0
            height: subtitle ? subtitle.height : 0
            color: 'transparent'
            border.color: application.playheadColor
            border.width: 2
        }
    }
}
