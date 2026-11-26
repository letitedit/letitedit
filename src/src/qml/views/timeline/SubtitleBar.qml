/*
 * Copyright (c) 2024-2025 Meltytech, LLC
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

// letitedit: every subtitle track is shown at once, stacked as lanes (one lane per track).
// Clicking a caption selects it (and makes its lane the current subtitle track), double-click
// opens the caption editor, Delete removes the selected captions.
Column {
    id: subtitlebar

    property real timeScale: 1
    readonly property int laneHeight: 22

    height: subtitlesModel.trackCount * laneHeight

    Repeater {
        model: subtitlesModel.trackCount

        SubtitleLane {
            trackIndex: index
            width: subtitlebar.width
            height: subtitlebar.laneHeight
            timeScale: subtitlebar.timeScale
        }
    }
}
