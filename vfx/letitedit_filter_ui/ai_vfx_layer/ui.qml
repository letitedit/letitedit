import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Shotcut.Controls as Shotcut

// Panel for an AI Effect attached by letitedit's VFX tools. Turning the effect on/off and removing
// it use the standard filter-list checkbox and remove button; this panel only explains what it is.
Item {
    width: 350
    height: 150

    function fileName(path) {
        var parts = String(path || '').split(/[\\/]/);
        return parts[parts.length - 1];
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        Label {
            text: qsTr('Effect: %1').arg(filter.get('shotcut:vfx_effect') || qsTr('custom'))
            font.bold: true
        }
        Label {
            text: filter.get('shotcut:vfx_label') || ''
            visible: text.length > 0
            wrapMode: Text.WordWrap
            Layout.fillWidth: true
        }
        Label {
            text: qsTr('File: %1').arg(fileName(filter.get('resource')))
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }
        Label {
            text: qsTr('Made by an AI agent (VFX beta). Untick the box in the filter list to hide it, '
                       + 'use \u2212 to delete it, or Set Filter Start/End to trim it. Ask the agent to change it.')
            wrapMode: Text.WordWrap
            opacity: 0.75
            Layout.fillWidth: true
        }
        Item { Layout.fillHeight: true }
    }
}
