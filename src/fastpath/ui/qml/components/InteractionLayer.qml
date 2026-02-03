import QtQuick
import "../style"

Item {
    id: root

    // Current interaction mode: "none", "draw", "roi", "measure"
    property string mode: "none"

    // Slide coordinate context (set by SlideViewer)
    property real slideScale: 1.0
    property real contentX: 0
    property real contentY: 0

    // Signals for each mode to emit results
    signal drawingFinished(string toolType, var coordinates)
    signal roiSelected(rect region)
    signal measurementFinished(var points, real distance)

    // Feature branches extend this component to handle their modes.
    // Each branch adds mouse handling and visual feedback for its mode(s),
    // keeping additions in separate code sections for clean merges.

    // ========================
    // ROI selection mode
    // ========================

    property real _roiStartX: 0
    property real _roiStartY: 0
    property bool _roiDragging: false

    MouseArea {
        id: roiMouseArea
        anchors.fill: parent
        enabled: root.mode === "roi"
        cursorShape: root.mode === "roi" ? Qt.CrossCursor : Qt.ArrowCursor
        hoverEnabled: false

        onPressed: (mouse) => {
            root._roiStartX = mouse.x
            root._roiStartY = mouse.y
            root._roiDragging = true
            roiRect.visible = true
        }

        onPositionChanged: (mouse) => {
            if (!root._roiDragging) return
            roiRect.x = Math.min(root._roiStartX, mouse.x)
            roiRect.y = Math.min(root._roiStartY, mouse.y)
            roiRect.width = Math.abs(mouse.x - root._roiStartX)
            roiRect.height = Math.abs(mouse.y - root._roiStartY)
        }

        onReleased: (mouse) => {
            if (!root._roiDragging) return
            root._roiDragging = false
            roiRect.visible = false

            // Compute region in slide coordinates
            let x1 = Math.min(root._roiStartX, mouse.x) / root.slideScale
            let y1 = Math.min(root._roiStartY, mouse.y) / root.slideScale
            let w = Math.abs(mouse.x - root._roiStartX) / root.slideScale
            let h = Math.abs(mouse.y - root._roiStartY) / root.slideScale

            // Minimum size threshold (10px in slide space)
            if (w >= 10 && h >= 10) {
                root.roiSelected(Qt.rect(x1, y1, w, h))
            }
        }
    }

    // ROI visual feedback rectangle
    Rectangle {
        id: roiRect
        visible: false
        color: Qt.rgba(Theme.primary.r, Theme.primary.g, Theme.primary.b, 0.2)
        border.color: Theme.primary
        border.width: 2
    }
}
