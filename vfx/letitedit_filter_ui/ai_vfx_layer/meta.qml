import QtQuick
import org.shotcut.qml

// letitedit (VFX beta): an agent-rendered effect attached to a clip like any other filter.
// The rendered effect (a video with transparency, or full frames) is overlaid with MLT's watermark
// filter for exactly the filter's in/out range. Toggle it with the checkbox, delete it with "-",
// trim it with Set Filter Start/End. Hidden from the Add menu: only an agent can create the effect file.
Metadata {
    type: Metadata.Filter
    objectName: "aiVfxLayer"
    name: qsTr("AI Effect (VFX beta)")
    keywords: qsTr('ai effect vfx overlay 3d explosion popup', 'search keywords for the AI Effect filter') + ' ai vfx'
    mlt_service: "watermark"
    qml: "ui.qml"
    icon: "icon.webp"
    isHidden: true
}
