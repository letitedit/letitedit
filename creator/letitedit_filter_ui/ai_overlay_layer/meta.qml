import QtQuick
import org.shotcut.qml

// letitedit: an agent-made overlay (caption, picture callout, emoji, lower third...) attached to a
// clip like any other filter. MLT's watermark filter overlays the rendered video (with transparency)
// for exactly the filter's in/out range. Hidden from the Add menu: only an agent creates the file.
Metadata {
    type: Metadata.Filter
    objectName: "aiOverlayLayer"
    name: qsTr("AI Overlay")
    keywords: qsTr('ai overlay callout picture emoji caption lower third', 'search keywords for the AI Overlay filter') + ' ai overlay'
    mlt_service: "watermark"
    qml: "ui.qml"
    icon: "icon.webp"
    isHidden: true
}