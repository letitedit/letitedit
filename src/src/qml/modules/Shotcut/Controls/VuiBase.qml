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

import QtQuick
import QtMultimedia

DropArea {
    clip: true

    property real _zoom: (video.zoom > 0) ? video.zoom : 1

    Component.onCompleted: {
        if (!video.oldVideoOutput)
            video.setVideoSink(videoOutput.videoSink)
    }

    VideoOutput {
        id: videoOutput
        visible: !video.oldVideoOutput

        width: video.rect.width * _zoom
        height: video.rect.height * _zoom
        x: video.rect.x + (video.rect.width - width) / 2 - video.offset.x
        y: video.rect.y + (video.rect.height - height) / 2 - video.offset.y
        fillMode: VideoOutput.Stretch
    }

    Canvas {
        id: grid

        anchors.fill: parent
        opacity: 0.5
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            if (video.grid > 0 && video.grid < 30000) {
                var zoom = (video.zoom > 0) ? video.zoom : 1;
                var rectW = video.rect.width * zoom;
                var rectH = video.rect.height * zoom;
                var zoomOffsetX = (video.rect.width - rectW) / 2;
                var zoomOffsetY = (video.rect.height - rectH) / 2;
                var rectX = video.rect.x - video.offset.x + zoomOffsetX;
                var rectY = video.rect.y - video.offset.y + zoomOffsetY;
                var gridSizeX = (video.grid > 10000) ? rectW / (profile.width / (video.grid - 10000)) : rectW / video.grid;
                var gridSizeY = (video.grid > 10000) ? rectH / (profile.height / (video.grid - 10000)) : rectH / video.grid;
                var gridOffsetX = rectX % gridSizeX;
                var gridOffsetY = rectY % gridSizeY;
                if (video.grid <= 10000 || (video.grid >= 20001 && video.grid <= 29999)) {
                    // Black shadow grid (offset by 1)
                    ctx.lineWidth = 1;
                    ctx.strokeStyle = "#000000";
                    ctx.beginPath();
                    if (video.grid === 8090) {
                        // 80/90% Safe Areas
                        ctx.rect(0.1 * rectW + rectX + 2, 0.1 * rectH + rectY + 2, 0.8 * rectW - 1, 0.8 * rectH - 1);
                        ctx.rect(0.05 * rectW + rectX + 2, 0.05 * rectH + rectY + 2, 0.9 * rectW - 1, 0.9 * rectH - 1);
                    } else if (video.grid == 95) {
                        // EBU R95 Safe Areas
                        ctx.rect(0.05 * rectW + rectX + 2, 0.05 * rectH + rectY + 2, 0.9 * rectW - 1, 0.9 * rectH - 1);
                        ctx.rect(0.035 * rectW + rectX + 2, 0.035 * rectH + rectY + 2, 0.93 * rectW - 1, 0.93 * rectH - 1);
                    } else if (video.grid >= 20001 && video.grid <= 29999) {
                        // Aspect ratio frame overlay
                        let ratioW, ratioH;
                        switch (video.grid) {
                        case 20001:
                            ratioW = 1;
                            ratioH = 1;
                            break;
                        case 20169:
                            ratioW = 16;
                            ratioH = 9;
                            break;
                        case 20043:
                            ratioW = 4;
                            ratioH = 3;
                            break;
                        default:
                            ratioW = 9;
                            ratioH = 16;
                            break;
                        }
                        const targetAspect = ratioW / ratioH;
                        const videoAspect = rectW / rectH;
                        let frameW, frameH;
                        if (targetAspect >= videoAspect) {
                            frameW = rectW;
                            frameH = frameW / targetAspect;
                        } else {
                            frameH = rectH;
                            frameW = frameH * targetAspect;
                        }
                        const frameX = rectX + (rectW - frameW) / 2;
                        const frameY = rectY + (rectH - frameH) / 2;
                        ctx.rect(frameX + 2, frameY + 2, frameW - 1, frameH - 1);
                        if (video.grid === 20916) {
                            // Mobile safe guides: 420px from bottom, 50px from right (1080x1920)
                            const hLineY = frameY + frameH * (1500 / 1920) + 2;
                            const vLineX = frameX + frameW * (1030 / 1080) + 2;
                            ctx.moveTo(frameX + 2, hLineY);
                            ctx.lineTo(frameX + frameW - 1, hLineY);
                            ctx.moveTo(vLineX, frameY + 2);
                            ctx.lineTo(vLineX, frameY + frameH - 1);
                        }
                    } else {
                        // vertical grid lines
                        for (var x = 0; x * gridSizeX < parent.width + gridSizeX; x++) {
                            context.moveTo(gridOffsetX + x * gridSizeX + 1, 0);
                            context.lineTo(gridOffsetX + x * gridSizeX + 1, parent.height);
                        }
                        // horizontal grid lines
                        for (var y = 0; y * gridSizeY < parent.height + gridSizeY; y++) {
                            context.moveTo(0, gridOffsetY + y * gridSizeY + 1);
                            context.lineTo(parent.width, gridOffsetY + y * gridSizeY + 1);
                        }
                    }
                    // draw and close
                    context.stroke();
                    context.closePath();
                }
                // White line grid
                ctx.lineWidth = 1;
                ctx.strokeStyle = "#ffffff";
                ctx.beginPath();
                if (video.grid === 8090) {
                    // 80/90% Safe Areas
                    ctx.rect(0.1 * rectW + rectX + 1, 0.1 * rectH + rectY + 1, 0.8 * rectW - 2, 0.8 * rectH - 2);
                    ctx.rect(0.05 * rectW + rectX + 1, 0.05 * rectH + rectY + 2, 0.9 * rectW - 2, 0.9 * rectH - 2);
                } else if (video.grid == 95) {
                    // EBU R95 Safe Areas
                    ctx.rect(0.05 * rectW + rectX + 1, 0.05 * rectH + rectY + 1, 0.9 * rectW - 2, 0.9 * rectH - 2);
                    ctx.rect(0.035 * rectW + rectX + 1, 0.035 * rectH + rectY + 1, 0.93 * rectW - 2, 0.93 * rectH - 2);
                } else if (video.grid >= 20001 && video.grid <= 29999) {
                    // Aspect ratio frame overlay
                    let ratioW, ratioH;
                    switch (video.grid) {
                    case 20001:
                        ratioW = 1;
                        ratioH = 1;
                        break;
                    case 20169:
                        ratioW = 16;
                        ratioH = 9;
                        break;
                    case 20043:
                        ratioW = 4;
                        ratioH = 3;
                        break;
                    default:
                        ratioW = 9;
                        ratioH = 16;
                        break;
                    }
                    const targetAspect = ratioW / ratioH;
                    const videoAspect = rectW / rectH;
                    let frameW, frameH;
                    if (targetAspect >= videoAspect) {
                        frameW = rectW;
                        frameH = frameW / targetAspect;
                    } else {
                        frameH = rectH;
                        frameW = frameH * targetAspect;
                    }
                    const frameX = rectX + (rectW - frameW) / 2;
                    const frameY = rectY + (rectH - frameH) / 2;
                    ctx.rect(frameX + 1, frameY + 1, frameW - 2, frameH - 2);
                    if (video.grid === 20916) {
                        // Mobile safe guides: 420px from bottom, 50px from right (1080x1920)
                        const hLineY = frameY + frameH * (1500 / 1920) + 1;
                        const vLineX = frameX + frameW * (1030 / 1080) + 1;
                        ctx.moveTo(frameX + 1, hLineY);
                        ctx.lineTo(frameX + frameW - 2, hLineY);
                        ctx.moveTo(vLineX, frameY + 1);
                        ctx.lineTo(vLineX, frameY + frameH - 2);
                    }
                } else {
                    // vertical grid lines
                    for (var x = 0; x * gridSizeX < parent.width + gridSizeX; x++) {
                        context.moveTo(gridOffsetX + x * gridSizeX, 0);
                        context.lineTo(gridOffsetX + x * gridSizeX, parent.height);
                    }
                    // horizontal grid lines
                    for (var y = 0; y * gridSizeY < parent.height + gridSizeY; y++) {
                        context.moveTo(0, gridOffsetY + y * gridSizeY);
                        context.lineTo(parent.width, gridOffsetY + y * gridSizeY);
                    }
                }
                // draw and close
                context.stroke();
                context.closePath();
            }
        }
    }

    // letitedit: where TikTok, Shorts and Reels draw their own buttons, captions and bars over a vertical video.
    // On from the player's grid menu, and on its own while text or a caption is dragged on a vertical video, with a
    // note saying which apps would cover it where it is.
    Canvas {
        id: phoneZoneCanvas

        readonly property bool chosen: video.grid >= 30000 && video.grid <= 30003
        readonly property bool dragging: objectArea.pressed && objectArea.changed && objectArea.obj !== null
                                         && profile.width < profile.height

        // Each app in its own colour, so overlapping boxes stay easy to tell apart.
        readonly property var apps: ['TikTok', 'YouTube Shorts', 'Instagram Reels']
        readonly property var appNames: ['TikTok', 'Shorts', 'Reels']
        readonly property var appColors: ['#25F4EE', '#FF5A4F', '#D57BFF']
        readonly property string safeColor: '#3DDC84'

        // A label: white bold text on a dark pill with a bar in the box's colour. (x, y) is its top-left corner.
        function pill(ctx, text, x, y, color) {
            var w = ctx.measureText(text).width + 14;
            ctx.globalAlpha = 0.78;
            ctx.fillStyle = '#101418';
            ctx.fillRect(x, y, w, 17);
            ctx.globalAlpha = 1.0;
            ctx.fillStyle = color;
            ctx.fillRect(x, y, 3, 17);
            ctx.fillStyle = 'white';
            ctx.fillText(text, x + 8, y + 12.5);
            return w;
        }

        // The same, turned to read upwards (for the tall columns down the sides). (cx, cy) is its centre.
        function pillUp(ctx, text, cx, cy, color) {
            ctx.save();
            ctx.translate(cx, cy);
            ctx.rotate(-Math.PI / 2);
            var w = ctx.measureText(text).width + 14;
            pill(ctx, text, -w / 2, -8.5, color);
            ctx.restore();
        }

        anchors.fill: parent
        visible: chosen || dragging
        onVisibleChanged: requestPaint()
        onWidthChanged: requestPaint()
        onHeightChanged: requestPaint()
        onPaint: {
            var ctx = getContext("2d");
            ctx.reset();
            if (!visible || typeof phoneZones === 'undefined' || !phoneZones)
                return;
            var d = objectArea.displayRect();
            ctx.font = 'bold 11px sans-serif';
            if (profile.width >= profile.height) {
                // the apps' zones are measured on a 9:16 frame; drawn on a wide or square one they would mislead
                pill(ctx, qsTr('Phone app zones are for vertical (9:16) video'), d.x + 6, d.y + 6, '#9aa4ab');
                return;
            }
            var zones = phoneZones.forGrid(chosen ? video.grid : 30000);
            var oneApp = chosen && video.grid !== 30000;
            var safe = {l: 0, t: 0, r: 1, b: 1};
            var i, z, k;
            // The boxes: a light tint and a bold outline in the app's colour.
            for (i = 0; i < zones.length; i++) {
                z = zones[i];
                k = Math.max(0, apps.indexOf(z.app));
                var x = d.x + z.x * d.width, y = d.y + z.y * d.height, w = z.w * d.width, h = z.h * d.height;
                ctx.globalAlpha = 0.13;
                ctx.fillStyle = appColors[k];
                ctx.fillRect(x, y, w, h);
                ctx.globalAlpha = 1.0;
                ctx.lineWidth = 2.5;
                ctx.strokeStyle = appColors[k];
                ctx.strokeRect(x + 1.25, y + 1.25, w - 2.5, h - 2.5);
                if (z.w >= 0.99) {
                    if (z.y < 0.01)
                        safe.t = Math.max(safe.t, z.h);
                    else
                        safe.b = Math.min(safe.b, z.y);
                } else if (z.h >= 0.99) {
                    if (z.x < 0.01)
                        safe.l = Math.max(safe.l, z.w);
                    else
                        safe.r = Math.min(safe.r, z.x);
                }
            }
            // Where nothing covers the video on any of the apps shown: a bold green box.
            var sx = d.x + safe.l * d.width, sy = d.y + safe.t * d.height;
            var sw = (safe.r - safe.l) * d.width, sh = (safe.b - safe.t) * d.height;
            ctx.lineWidth = 3;
            ctx.strokeStyle = safeColor;
            ctx.strokeRect(sx, sy, sw, sh);
            // The labels last, so no outline crosses one. Beside the frame when there is room (a vertical video
            // leaves plenty in the player), stacked so none overlap, each with a line to the edge of its box: bars
            // and the safe area on the left, columns on their own side. Inside the frame when there is no room.
            var labels = [];
            for (i = 0; i < zones.length; i++) {
                z = zones[i];
                k = Math.max(0, apps.indexOf(z.app));
                var label = {text: oneApp ? z.label : appNames[k] + ' ' + z.label, color: appColors[k]};
                if (z.w >= 0.99) {
                    label.side = 'left';
                    label.tx = d.x;
                    label.ty = d.y + (z.y < 0.01 ? z.y + z.h : z.y) * d.height;
                    label.inside = {x: d.x + 6 + (oneApp ? 0 : k * (d.width - 12) / 3),
                                    y: z.y < 0.01 ? label.ty - 20 : label.ty + 4};
                } else {
                    label.side = z.x > 0.5 ? 'right' : 'left';
                    label.tx = d.x + (z.x > 0.5 ? z.x : z.x + z.w) * d.width;
                    label.ty = d.y + d.height * (oneApp ? 0.42 : 0.3 + 0.18 * k);
                    label.up = {x: d.x + (z.x + z.w / 2) * d.width, y: label.ty};
                }
                labels.push(label);
            }
            labels.push({text: oneApp ? qsTr('Safe area') : qsTr('Safe on TikTok, Shorts and Reels'), color: safeColor,
                         side: 'left', tx: sx, ty: sy + 10, inside: {x: sx + 6, y: sy + 6}});
            var widest = {left: 0, right: 0};
            for (i = 0; i < labels.length; i++)
                widest[labels[i].side] = Math.max(widest[labels[i].side], ctx.measureText(labels[i].text).width + 14);
            var outside = {left: d.x - 30 >= widest.left, right: width - (d.x + d.width) - 30 >= widest.right};
            ['left', 'right'].forEach(function(side) {
                var row = labels.filter(function(l) { return l.side === side; });
                row.sort(function(a, b) { return a.ty - b.ty; });
                if (outside[side]) {
                    var next = 2;
                    for (var n = 0; n < row.length; n++) {
                        row[n].y = Math.max(row[n].ty - 8.5, next);
                        next = row[n].y + 20;
                    }
                    var over = next - 2 - height;
                    for (n = row.length - 1; n >= 0 && over > 0; n--)
                        row[n].y -= over;
                }
                for (n = 0; n < row.length; n++) {
                    var l = row[n];
                    if (outside[side]) {
                        var w = ctx.measureText(l.text).width + 14;
                        var px = side === 'left' ? d.x - 18 - w : d.x + d.width + 18;
                        ctx.lineWidth = 1.5;
                        ctx.strokeStyle = l.color;
                        ctx.beginPath();
                        ctx.moveTo(l.tx, l.ty);
                        ctx.lineTo(side === 'left' ? d.x - 8 : d.x + d.width + 8, l.ty);
                        ctx.lineTo(side === 'left' ? px + w : px, l.y + 8.5);
                        ctx.stroke();
                        pill(ctx, l.text, px, l.y, l.color);
                    } else if (l.up) {
                        pillUp(ctx, l.text, l.up.x, l.up.y, l.color);
                    } else {
                        pill(ctx, l.text, l.inside.x, l.inside.y, l.color);
                    }
                }
            });
        }
    }

    Rectangle {
        id: phoneZoneNote

        property string text: ''
        property bool clear: false

        visible: phoneZoneCanvas.dragging && text !== ''
        z: 3
        x: Math.max(4, Math.min(parent.width - width - 4, objectArea.box.x))
        y: Math.max(4, objectArea.box.y - height - 44)
        width: phoneZoneNoteText.implicitWidth + 16
        height: 24
        radius: 6
        color: '#2b3236'
        border.color: clear ? '#5ec8b4' : '#ff7a5c'
        border.width: 1

        Text {
            id: phoneZoneNoteText

            anchors.centerIn: parent
            text: phoneZoneNote.text
            color: 'white'
            font.pixelSize: 12
        }
    }

    // letitedit: a click in the picture selects the topmost thing there and pauses (T99; PreviewObjects
    // keeps what's selected, since this overlay is replaced when a filter's own one shows). Text and
    // burned-in captions can also be grabbed: drag moves one, the corner handle resizes it, double-click
    // edits it, and a small bar offers the same; each finished drag is one undo step. A filter's own
    // controls still get a click on the item that's already selected, and anything nothing here wants.
    MouseArea {
        id: objectArea

        property var obj: null
        property rect box: Qt.rect(0, 0, 0, 0)
        property rect startBox: Qt.rect(0, 0, 0, 0)
        property point start: Qt.point(0, 0)
        property string mode: ''
        property bool changed: false
        property real angle: 0
        property real startAngle: 0

        anchors.fill: parent
        acceptedButtons: Qt.LeftButton
        z: 1

        function available() {
            return typeof previewObjects !== 'undefined' && previewObjects;
        }

        function filterControlsUp() {
            return String(video.source).indexOf('VuiBase.qml') < 0;
        }

        function displayRect() {
            var w = video.rect.width * _zoom;
            var h = video.rect.height * _zoom;
            return Qt.rect(video.rect.x + (video.rect.width - w) / 2 - video.offset.x,
                           video.rect.y + (video.rect.height - h) / 2 - video.offset.y, w, h);
        }

        function boxOf(o) {
            var d = displayRect();
            return Qt.rect(d.x + o.x * d.width, d.y + o.y * d.height, o.w * d.width, o.h * d.height);
        }

        function objectAt(px, py) {
            if (!available())
                return null;
            var list = previewObjects.objectsAtPlayhead();
            for (var i = 0; i < list.length; i++) {
                var r = boxOf(list[i]);
                if (px >= r.x && px <= r.x + r.width && py >= r.y && py <= r.y + r.height)
                    return list[i];
            }
            return null;
        }

        function refresh() {
            if (!obj || !available())
                return;
            var list = previewObjects.objectsAtPlayhead();
            for (var i = 0; i < list.length; i++) {
                if (list[i].kind === obj.kind && list[i].track === obj.track && list[i].clip === obj.clip) {
                    obj = list[i];
                    box = boxOf(obj);
                    angle = obj.angle || 0;
                    return;
                }
            }
            obj = null;
        }

        function onRotateHandle(px, py) {
            return obj !== null && Math.abs(px - (box.x + box.width / 2)) <= 12 && Math.abs(py - (box.y - 30)) <= 12;
        }

        function pointerAngle(px, py) {
            return Math.atan2(py - (box.y + box.height / 2), px - (box.x + box.width / 2)) * 180 / Math.PI;
        }

        function rotateBy(degrees) {
            if (!obj)
                return;
            angle = (angle + degrees) % 360;
            send(true, 1.0);
            refresh();
        }

        function onCorner(px, py) {
            return obj !== null && Math.abs(px - (box.x + box.width)) <= 14 && Math.abs(py - (box.y + box.height)) <= 14;
        }

        function send(final, scale) {
            var d = displayRect();
            var x = (box.x - d.x) / d.width, y = (box.y - d.y) / d.height;
            var w = box.width / d.width, h = box.height / d.height;
            if (final)
                previewObjects.commit(obj, x, y, w, h, scale, angle);
            else
                previewObjects.preview(obj, x, y, w, h, scale, angle);
        }

        function resizeBy(factor) {
            if (!obj)
                return;
            startBox = box;
            var cx = box.x + box.width / 2, cy = box.y + box.height / 2;
            box = Qt.rect(cx - box.width * factor / 2, cy - box.height * factor / 2, box.width * factor, box.height * factor);
            send(true, factor);
            refresh();
        }

        onPressed: mouse => {
            if (onRotateHandle(mouse.x, mouse.y)) {
                mode = 'rotate';
                startAngle = angle - pointerAngle(mouse.x, mouse.y);
            } else if (onCorner(mouse.x, mouse.y)) {
                mode = 'resize';
            } else {
                var d = displayRect();
                var o = available() ? previewObjects.pickAt((mouse.x - d.x) / d.width, (mouse.y - d.y) / d.height) : null;
                if (!o || !o.kind) {
                    obj = null;
                    mouse.accepted = false;
                    return;
                }
                if (!o.grab) {
                    obj = null;
                    if (o.wasTarget && filterControlsUp())
                        mouse.accepted = false;
                    return;
                }
                obj = o;
                box = boxOf(o);
                angle = o.angle || 0;
                mode = 'move';
                application.showStatusMessage(qsTr('Drag to move it, drag the corner to resize, drag the round handle to rotate, double-click to edit'));
            }
            start = Qt.point(mouse.x, mouse.y);
            startBox = box;
            changed = false;
        }
        onPositionChanged: mouse => {
            if (!pressed || !obj)
                return;
            var dx = mouse.x - start.x, dy = mouse.y - start.y;
            if (!changed && Math.abs(dx) + Math.abs(dy) < 3)
                return;
            changed = true;
            if (mode === 'rotate') {
                var a = startAngle + pointerAngle(mouse.x, mouse.y);
                // snap to the nearest 15 degrees when close
                var snap = Math.round(a / 15) * 15;
                angle = Math.abs(a - snap) < 3 ? snap : a;
                send(false, 1.0);
            } else if (mode === 'resize') {
                var s = Math.max(0.2, (startBox.height + dy) / Math.max(1, startBox.height));
                box = Qt.rect(startBox.x, startBox.y, startBox.width * s, startBox.height * s);
                send(false, s);
            } else {
                box = Qt.rect(startBox.x + dx, startBox.y + dy, startBox.width, startBox.height);
                send(false, 1.0);
            }
            if (phoneZoneCanvas.dragging && typeof phoneZones !== 'undefined' && phoneZones) {
                var d = displayRect();
                var apps = phoneZones.coveringApps((box.x - d.x) / d.width, (box.y - d.y) / d.height,
                                                   box.width / d.width, box.height / d.height);
                phoneZoneNote.clear = apps.length === 0;
                phoneZoneNote.text = apps.length ? qsTr('Covered on %1').arg(apps.join(', '))
                                                 : qsTr('Clear on TikTok, Shorts and Reels');
                phoneZoneCanvas.requestPaint();
            }
        }
        onReleased: {
            phoneZoneNote.text = '';
            if (obj && changed) {
                send(true, mode === 'resize' ? box.height / Math.max(1, startBox.height) : 1.0);
                refresh();
            }
            changed = false;
        }
        onDoubleClicked: mouse => {
            var o = objectAt(mouse.x, mouse.y);
            if (o)
                previewObjects.edit(o);
        }
    }

    // What's selected, whatever it is: its bounds and its name. (The player's top line says the same, where a live scene
    // can't cover it: this layer sits under one, so its outline shows only just outside the picture there.)
    Item {
        id: pickedItem

        readonly property var item: objectArea.available() ? previewObjects.target : null
        readonly property bool shown: !!item && !!item.kind && !!item.atPlayhead && !item.gone
        readonly property rect itemBox: shown ? objectArea.boxOf(item) : Qt.rect(0, 0, 0, 0)

        objectName: 'playerSelectionBox'
        visible: shown
        x: itemBox.x - 3
        y: itemBox.y - 3
        width: itemBox.width + 6
        height: itemBox.height + 6
        z: 2

        Rectangle {
            anchors.fill: parent
            color: 'transparent'
            border.color: '#2A8597'
            border.width: 2
            radius: 3
            visible: objectArea.obj === null
        }

        Rectangle {
            x: 3
            y: parent.y >= height + 2 ? -height - 1 : 3
            width: pickedName.implicitWidth + 12
            height: 20
            radius: 3
            color: '#2A8597'
            visible: objectArea.obj === null

            Text {
                id: pickedName

                anchors.centerIn: parent
                text: pickedItem.item && pickedItem.item.kindLabel ? pickedItem.item.kindLabel : ''
                color: 'white'
                font.pixelSize: 12
            }
        }
    }

    Item {
        id: objectSelection

        visible: objectArea.obj !== null
        x: objectArea.box.x
        y: objectArea.box.y
        width: objectArea.box.width
        height: objectArea.box.height
        z: 2

        Item {
            anchors.fill: parent
            rotation: objectArea.angle

            Rectangle {
                anchors.fill: parent
                color: 'transparent'
                border.color: application.playheadColor
                border.width: 2
                radius: 4
            }
        }

        Rectangle {
            x: parent.width - width / 2
            y: parent.height - height / 2
            width: 12
            height: 12
            radius: 3
            color: application.playheadColor
            border.color: 'white'
            border.width: 1
        }

        Rectangle {
            x: parent.width / 2 - 1
            y: -24
            width: 2
            height: 24
            color: application.playheadColor
            visible: objectArea.obj !== null && objectArea.obj.kind === 'text'
        }

        Rectangle {
            x: parent.width / 2 - width / 2
            y: -30 - height / 2
            width: 16
            height: 16
            radius: 8
            color: 'white'
            border.color: application.playheadColor
            border.width: 2
            visible: objectArea.obj !== null && objectArea.obj.kind === 'text'
        }

        Row {
            spacing: 4
            y: objectSelection.height + 10
            x: Math.max(0, (objectSelection.width - width) / 2)
            z: 3

            Repeater {
                model: [
                    {label: qsTr('Edit'), act: 'edit'},
                    {label: qsTr('A-'), act: 'smaller'},
                    {label: qsTr('A+'), act: 'bigger'},
                    {label: qsTr('Rotate'), act: 'rotate'},
                    {label: qsTr('Delete'), act: 'delete'}
                ]

                Rectangle {
                    width: buttonText.implicitWidth + 16
                    height: 26
                    radius: 6
                    color: buttonArea.containsMouse ? '#3d474d' : '#2b3236'
                    border.color: '#5ec8b4'
                    border.width: 1

                    Text {
                        id: buttonText

                        anchors.centerIn: parent
                        text: modelData.label
                        color: 'white'
                        font.pixelSize: 12
                    }

                    MouseArea {
                        id: buttonArea

                        anchors.fill: parent
                        hoverEnabled: true
                        onClicked: {
                            var o = objectArea.obj;
                            if (!o)
                                return;
                            if (modelData.act === 'edit') {
                                previewObjects.edit(o);
                            } else if (modelData.act === 'smaller') {
                                objectArea.resizeBy(1 / 1.15);
                            } else if (modelData.act === 'bigger') {
                                objectArea.resizeBy(1.15);
                            } else if (modelData.act === 'rotate') {
                                if (o.kind === 'text')
                                    objectArea.rotateBy(15);
                                else
                                    application.showStatusMessage(qsTr('Captions stay level; rotate works on text'));
                            } else if (modelData.act === 'delete') {
                                objectArea.obj = null;
                                previewObjects.remove(o);
                            }
                        }
                    }
                }
            }
        }
    }

    Connections {
        function onPositionChanged() {
            objectArea.obj = null;
        }

        target: typeof timeline !== 'undefined' ? timeline : null
        ignoreUnknownSignals: true
    }

    Connections {
        function onRectChanged() {
            grid.requestPaint();
            phoneZoneCanvas.requestPaint();
        }

        function onGridChanged() {
            grid.requestPaint();
            phoneZoneCanvas.requestPaint();
        }

        function onOffsetChanged() {
            grid.requestPaint();
            phoneZoneCanvas.requestPaint();
        }

        function onZoomChanged() {
            grid.requestPaint();
            phoneZoneCanvas.requestPaint();
        }

        target: video
    }
}
