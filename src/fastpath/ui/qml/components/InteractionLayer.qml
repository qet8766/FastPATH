import QtQuick
import QtQuick.Shapes
import "../style"

Item {
    id: root

    // Current interaction mode: "none", "draw", "roi", "measure"
    property string mode: "none"

    // Slide coordinate context (set by SlideViewer)
    property real slideScale: 1.0
    property real contentX: 0
    property real contentY: 0

    // Drawing tool selection (set by SlideViewer)
    property string drawTool: "point"  // point, rectangle, polygon, freehand
    property color drawColor: Theme.primary

    // Signals for each mode to emit results
    signal drawingFinished(string toolType, var coordinates)
    signal roiSelected(rect region)
    signal measurementFinished(var points, real distance)

    function _resetDraw() {
        root._drawDragging = false
        root._drawPoints = []
        root._drawCursorPoint = null
        drawRect.visible = false
        drawRect.width = 0
        drawRect.height = 0
    }

    function _resetMeasure() {
        root._measureActive = false
        root._measureStart = null
        root._measureEnd = null
    }

    onModeChanged: {
        if (root.mode !== "draw") root._resetDraw()
        if (root.mode !== "measure") root._resetMeasure()
        if (root.mode !== "roi") roiRect.visible = false
    }

    onDrawToolChanged: {
        if (root.mode === "draw") root._resetDraw()
    }

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

    // ========================
    // Annotation draw mode
    // ========================

    property real _drawStartX: 0
    property real _drawStartY: 0
    property bool _drawDragging: false
    property var _drawPoints: []          // Qt.point[] in content (scaled) coords
    property var _drawCursorPoint: null   // Qt.point or null

    MouseArea {
        id: drawMouseArea
        anchors.fill: parent
        enabled: root.mode === "draw"
        cursorShape: root.mode === "draw" ? Qt.CrossCursor : Qt.ArrowCursor
        hoverEnabled: true
        acceptedButtons: Qt.LeftButton | Qt.RightButton

        onPressed: (mouse) => {
            if (root.drawTool === "point") {
                let sx = mouse.x / root.slideScale
                let sy = mouse.y / root.slideScale
                root.drawingFinished("point", [[sx, sy]])
                return
            }

            if (root.drawTool === "rectangle") {
                root._drawStartX = mouse.x
                root._drawStartY = mouse.y
                root._drawDragging = true
                drawRect.visible = true
                drawRect.x = mouse.x
                drawRect.y = mouse.y
                drawRect.width = 0
                drawRect.height = 0
                return
            }

            if (root.drawTool === "freehand") {
                root._drawDragging = true
                root._drawPoints = [Qt.point(mouse.x, mouse.y)]
                root._drawCursorPoint = null
                return
            }

            if (root.drawTool === "polygon") {
                if (mouse.button === Qt.RightButton) {
                    // Finish polygon on right-click
                    if (root._drawPoints.length >= 3) {
                        let coords = []
                        for (let i = 0; i < root._drawPoints.length; i++) {
                            coords.push([
                                root._drawPoints[i].x / root.slideScale,
                                root._drawPoints[i].y / root.slideScale
                            ])
                        }
                        root.drawingFinished("polygon", coords)
                    }
                    root._resetDraw()
                    return
                }

                // Left-click: add vertex
                root._drawPoints = root._drawPoints.concat([Qt.point(mouse.x, mouse.y)])
                root._drawCursorPoint = Qt.point(mouse.x, mouse.y)
                return
            }
        }

        onPositionChanged: (mouse) => {
            if (root.drawTool === "rectangle") {
                if (!root._drawDragging) return
                drawRect.x = Math.min(root._drawStartX, mouse.x)
                drawRect.y = Math.min(root._drawStartY, mouse.y)
                drawRect.width = Math.abs(mouse.x - root._drawStartX)
                drawRect.height = Math.abs(mouse.y - root._drawStartY)
                return
            }

            if (root.drawTool === "freehand") {
                if (!root._drawDragging) return
                let last = root._drawPoints.length > 0 ? root._drawPoints[root._drawPoints.length - 1] : null
                if (last === null) {
                    root._drawPoints = [Qt.point(mouse.x, mouse.y)]
                    return
                }
                // Simple decimation to avoid excessive points
                let dx = mouse.x - last.x
                let dy = mouse.y - last.y
                if (dx * dx + dy * dy >= 4) {
                    root._drawPoints = root._drawPoints.concat([Qt.point(mouse.x, mouse.y)])
                }
                return
            }

            if (root.drawTool === "polygon") {
                if (root._drawPoints.length === 0) return
                root._drawCursorPoint = Qt.point(mouse.x, mouse.y)
                return
            }
        }

        onReleased: (mouse) => {
            if (root.drawTool === "rectangle") {
                if (!root._drawDragging) return
                root._drawDragging = false
                drawRect.visible = false

                let x1 = Math.min(root._drawStartX, mouse.x) / root.slideScale
                let y1 = Math.min(root._drawStartY, mouse.y) / root.slideScale
                let x2 = Math.max(root._drawStartX, mouse.x) / root.slideScale
                let y2 = Math.max(root._drawStartY, mouse.y) / root.slideScale

                let w = Math.abs(x2 - x1)
                let h = Math.abs(y2 - y1)
                if (w >= 10 && h >= 10) {
                    root.drawingFinished("rectangle", [[x1, y1], [x2, y2]])
                }
                return
            }

            if (root.drawTool === "freehand") {
                if (!root._drawDragging) return
                root._drawDragging = false
                if (root._drawPoints.length >= 2) {
                    let coords = []
                    for (let i = 0; i < root._drawPoints.length; i++) {
                        coords.push([
                            root._drawPoints[i].x / root.slideScale,
                            root._drawPoints[i].y / root.slideScale
                        ])
                    }
                    root.drawingFinished("freehand", coords)
                }
                root._resetDraw()
                return
            }
        }

        onExited: {
            root._drawCursorPoint = null
        }
    }

    // Rectangle preview for annotation drawing
    Rectangle {
        id: drawRect
        visible: false
        color: Qt.rgba(root.drawColor.r, root.drawColor.g, root.drawColor.b, 0.18)
        border.color: root.drawColor
        border.width: 2
    }

    // Polyline preview for polygon/freehand drawing
    Shape {
        id: drawShape
        anchors.fill: parent
        visible: root.mode === "draw"
                 && (root.drawTool === "polygon" || root.drawTool === "freehand")
                 && root._drawPoints.length > 0

        ShapePath {
            strokeWidth: 2
            strokeColor: root.drawColor
            fillColor: "transparent"
            joinStyle: ShapePath.RoundJoin
            capStyle: ShapePath.RoundCap

            PathPolyline {
                path: root._drawCursorPoint
                      ? root._drawPoints.concat([root._drawCursorPoint])
                      : root._drawPoints
            }
        }
    }

    // ========================
    // Measurement mode
    // ========================

    property bool _measureActive: false
    property var _measureStart: null  // Qt.point in content coords
    property var _measureEnd: null    // Qt.point in content coords

    MouseArea {
        id: measureMouseArea
        anchors.fill: parent
        enabled: root.mode === "measure"
        cursorShape: root.mode === "measure" ? Qt.CrossCursor : Qt.ArrowCursor
        hoverEnabled: true

        onPressed: (mouse) => {
            if (!root._measureActive) {
                root._measureStart = Qt.point(mouse.x, mouse.y)
                root._measureEnd = Qt.point(mouse.x, mouse.y)
                root._measureActive = true
                return
            }

            // Finalize measurement on second click
            root._measureEnd = Qt.point(mouse.x, mouse.y)
            let sx = root._measureStart.x / root.slideScale
            let sy = root._measureStart.y / root.slideScale
            let ex = root._measureEnd.x / root.slideScale
            let ey = root._measureEnd.y / root.slideScale

            let dx = ex - sx
            let dy = ey - sy
            let dist = Math.sqrt(dx * dx + dy * dy)
            root._measureActive = false
            root.measurementFinished([[sx, sy], [ex, ey]], dist)
        }

        onPositionChanged: (mouse) => {
            if (!root._measureActive) return
            root._measureEnd = Qt.point(mouse.x, mouse.y)
        }

        onExited: {
            if (root._measureActive) root._measureEnd = root._measureStart
        }
    }

    Shape {
        id: measureShape
        anchors.fill: parent
        visible: root.mode === "measure" && root._measureStart !== null && root._measureEnd !== null

        ShapePath {
            strokeWidth: 2
            strokeColor: Theme.primary
            fillColor: "transparent"
            joinStyle: ShapePath.RoundJoin
            capStyle: ShapePath.RoundCap

            PathPolyline {
                path: root._measureStart !== null && root._measureEnd !== null
                      ? [root._measureStart, root._measureEnd]
                      : []
            }
        }
    }

    Rectangle {
        id: measureLabel
        visible: measureShape.visible && root._measureStart !== null && root._measureEnd !== null
        radius: Theme.radiusSmall
        color: Theme.overlayBackground
        border.color: Theme.border
        border.width: 1
        x: root._measureStart !== null && root._measureEnd !== null
           ? (root._measureStart.x + root._measureEnd.x) / 2 + 8
           : 0
        y: root._measureStart !== null && root._measureEnd !== null
           ? (root._measureStart.y + root._measureEnd.y) / 2 + 8
           : 0

        property real _distanceSlide: {
            if (root._measureStart === null || root._measureEnd === null) return 0
            let sx = root._measureStart.x / root.slideScale
            let sy = root._measureStart.y / root.slideScale
            let ex = root._measureEnd.x / root.slideScale
            let ey = root._measureEnd.y / root.slideScale
            let dx = ex - sx
            let dy = ey - sy
            return Math.sqrt(dx * dx + dy * dy)
        }

        Text {
            anchors.margins: Theme.spacingSmall
            anchors.fill: parent
            text: measureLabel._distanceSlide.toFixed(0) + " px"
            color: Theme.textBright
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
