import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import Shotcut.Controls as Shotcut

// Panel for an overlay attached by letitedit's creator tools. On/off and delete use the standard
// filter-list checkbox and remove button; this panel only explains what it is.
Item {
    width: 350
    height: 140

    function fileName(path) {
        var parts = String(path || '').split(/[\\/]/);
        return parts[parts.length - 1];
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 8
        spacing: 6

        Label {
            text: qsTr('Overlay: %1').arg(filter.get('shotcut:overlay_label') || qsTr('custom'))
            font.bold: true
        }
        Label {
            text: qsTr('File: %1').arg(fileName(filter.get('resource')))
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }
        Label {
            text: qsTr('Made by an AI agent. Untick the box in the filter list to hide it, '
                       + 'use \u2212 to delete it, or Set Filter Start/End to retime it.')
            wrapMode: Text.WordWrap
            opacity: 0.75
            Layout.fillWidth: true
        }
        Item { Layout.fillHeight: true }
    }
}