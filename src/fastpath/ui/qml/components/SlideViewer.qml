import QtQuick
import QtQuick.Controls
import "../style"

Item {
    id: root

    // Public properties
    property real scale: 0.1
    property real viewportX: 0
    property real viewportY: 0
    property real viewportWidth: width / scale
    property real viewportHeight: height / scale
    property int currentLevel: SlideManager.getLevelForScale(scale)

    // Annotation properties
    property bool annotationsVisible: true
    property string selectedAnnotationId: ""
    property alias interactionMode: interactionLayer.mode
    property string drawTool: "pan"
    property string drawLabel: ""
    property string drawColor: Theme.annotationColors[0]

    // Measurement state (slide pixels)
    property bool hasMeasurement: false
    property real lastMeasurementDistance: 0

    // Forward ROI signal from InteractionLayer
    signal roiSelected(rect region)

    // Dynamic zoom-out limit: allow 30% margin beyond the full slide fitting in the viewport
    property real minScale: {
        var sw = SlideManager.width
        var sh = SlideManager.height
        if (sw > 0 && sh > 0 && width > 0 && height > 0)
            return Math.min(width / sw, height / sh) / 1.3
        return 0.01
    }

    // Internal
    property real contentWidth: SlideManager.width
    property real contentHeight: SlideManager.height

    // Velocity tracking for prefetching
    property real lastContentX: 0
    property real lastContentY: 0
    property real velocityX: 0
    property real velocityY: 0

    clip: true

    // Background
    Rectangle {
        anchors.fill: parent
        color: Theme.viewerBackground
    }

    // Flickable for pan
    Flickable {
        id: flickable
        anchors.fill: parent

        contentWidth: contentContainer.width
        contentHeight: contentContainer.height
        boundsBehavior: Flickable.StopAtBounds

        // Content container scaled by current zoom
        Item {
            id: contentContainer
            width: root.contentWidth * root.scale
            height: root.contentHeight * root.scale
            transformOrigin: Item.TopLeft

            // Fallback tile layer (shows previous zoom level during transitions)
            FallbackTileLayer {
                id: fallbackLayer
                anchors.fill: parent
                scale: root.scale
                z: 0
            }

            // Main tile layer
            TileLayer {
                id: tileLayer
                anchors.fill: parent
                scale: root.scale
                z: 1
            }

            // Annotation tile layer (rasterized overlay)
            AnnotationTileLayer {
                id: annotationTileLayer
                anchors.fill: parent
                scale: root.scale
                annotationsVisible: root.annotationsVisible
                z: 1.5
            }

            // Selected annotation highlight overlay
            SelectedAnnotationOverlay {
                id: selectedAnnotationOverlay
                anchors.fill: parent
                slideScale: root.scale
                selectedAnnotation: root.selectedAnnotationId !== "" ? AnnotationManager.getAnnotation(root.selectedAnnotationId) : null
                z: 1.6
            }

            // Interaction overlay (mode-based: draw, roi, measure)
            InteractionLayer {
                id: interactionLayer
                anchors.fill: parent
                slideScale: root.scale
                contentX: flickable.contentX
                contentY: flickable.contentY
                drawTool: root.drawTool
                drawColor: root.drawColor
                z: 2
            }
        }

        onContentXChanged: updateViewport()
        onContentYChanged: updateViewport()

        // Cancel built-in flick and replace with custom momentum (preserves throw direction)
        onFlickStarted: {
            // Capture velocity before canceling (content pixels per second)
            let vx = root.velocityX * root.scale
            let vy = root.velocityY * root.scale
            cancelFlick()
            let speed = Math.sqrt(vx * vx + vy * vy)
            if (speed > 50)
                momentumTimer.startMomentum(vx, vy)
        }
    }

    // Velocity tracking timer for prefetch optimization
    Timer {
        id: velocityTimer
        interval: 16  // ~60fps sampling
        repeat: true
        running: flickable.moving || flickable.flicking || momentumTimer.running
        onTriggered: {
            // Calculate velocity in slide coordinates per second
            let dt = interval / 1000.0
            root.velocityX = (flickable.contentX - root.lastContentX) / dt / root.scale
            root.velocityY = (flickable.contentY - root.lastContentY) / dt / root.scale
            root.lastContentX = flickable.contentX
            root.lastContentY = flickable.contentY
        }
        onRunningChanged: {
            if (running) {
                // Initialize position tracking
                root.lastContentX = flickable.contentX
                root.lastContentY = flickable.contentY
            } else {
                // Clear velocity when movement stops
                root.velocityX = 0
                root.velocityY = 0
            }
        }
    }

    // Custom momentum: decelerates speed uniformly so throw direction is preserved
    Timer {
        id: momentumTimer
        interval: 16
        repeat: true
        property real vx: 0
        property real vy: 0

        function startMomentum(initialVX, initialVY) {
            // Cap initial speed
            let speed = Math.sqrt(initialVX * initialVX + initialVY * initialVY)
            if (speed > 8000) {
                let ratio = 8000 / speed
                initialVX *= ratio
                initialVY *= ratio
            }
            vx = initialVX
            vy = initialVY
            start()
        }

        onTriggered: {
            // Stop if user started dragging again
            if (flickable.dragging) {
                stop()
                return
            }

            let speed = Math.sqrt(vx * vx + vy * vy)
            if (speed < 30) {
                stop()
                vx = 0
                vy = 0
                return
            }

            let dt = interval / 1000.0

            // Apply velocity
            let newX = flickable.contentX + vx * dt
            let newY = flickable.contentY + vy * dt

            // Clamp to bounds
            let maxX = Math.max(0, contentContainer.width - flickable.width)
            let maxY = Math.max(0, contentContainer.height - flickable.height)
            newX = Math.max(0, Math.min(maxX, newX))
            newY = Math.max(0, Math.min(maxY, newY))

            // Zero out axis velocity if it hit a bound
            if ((newX <= 0 && vx < 0) || (newX >= maxX && vx > 0)) vx = 0
            if ((newY <= 0 && vy < 0) || (newY >= maxY && vy > 0)) vy = 0

            flickable.contentX = newX
            flickable.contentY = newY

            // Uniform deceleration of speed magnitude (preserves direction)
            speed = Math.sqrt(vx * vx + vy * vy)
            if (speed > 0) {
                let newSpeed = Math.max(0, speed - 3000 * dt)
                let ratio = newSpeed / speed
                vx *= ratio
                vy *= ratio
            }
        }
    }

    // Mouse area for zoom
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        propagateComposedEvents: true

        onWheel: (wheel) => {
            momentumTimer.stop()
            let zoomFactor = wheel.angleDelta.y > 0 ? 1.4 : (1 / 1.4)

            // Zoom toward mouse position
            let mouseX = wheel.x
            let mouseY = wheel.y

            // Current position in content coordinates
            let contentX = flickable.contentX + mouseX
            let contentY = flickable.contentY + mouseY

            // Position in slide coordinates before zoom
            let slideX = contentX / root.scale
            let slideY = contentY / root.scale

            // Apply zoom
            let newScale = Math.max(root.minScale, Math.min(Theme.maxScale, root.scale * zoomFactor))
            root.scale = newScale

            // Adjust content position to keep mouse over same slide position
            let newContentX = slideX * newScale - mouseX
            let newContentY = slideY * newScale - mouseY

            flickable.contentX = Math.max(0, Math.min(contentContainer.width - flickable.width, newContentX))
            flickable.contentY = Math.max(0, Math.min(contentContainer.height - flickable.height, newContentY))

            updateViewport()
        }
    }

    // Pinch handler for touch zoom
    PinchHandler {
        id: pinchHandler
        target: null
        minimumScale: root.minScale / root.scale
        maximumScale: Theme.maxScale / root.scale

        onScaleChanged: {
            momentumTimer.stop()
            let newScale = root.scale * pinchHandler.activeScale
            newScale = Math.max(root.minScale, Math.min(Theme.maxScale, newScale))
            root.scale = newScale
            updateViewport()
        }
    }

    // Cache stats HUD
    CacheStatsOverlay {
        anchors.top: parent.top
        anchors.right: parent.right
        anchors.margins: Theme.spacingNormal
        z: 10
    }

    // Forward ROI selection from InteractionLayer
    Connections {
        target: interactionLayer
        function onRoiSelected(region) { root.roiSelected(region) }

        function onDrawingFinished(toolType, coordinates) {
            // Create annotation in slide coordinates (level 0)
            let annId = AnnotationManager.addAnnotation(
                toolType,
                coordinates,
                root.drawLabel,
                root.drawColor
            )
            if (annId) {
                root.selectedAnnotationId = annId
            }
        }

        function onMeasurementFinished(points, distance) {
            root.hasMeasurement = true
            root.lastMeasurementDistance = distance
        }
    }

    // Dismiss backdrop for RadialPalette
    MouseArea {
        anchors.fill: parent
        visible: radialPalette.active
        z: 19
        onClicked: radialPalette.hide()
    }

    // Radial label picker overlay
    RadialPalette {
        id: radialPalette
        z: 20
        items: {
            let result = []
            let keys = Object.keys(Theme.cellTypeColors)
            for (let i = 0; i < keys.length; i++) {
                result.push({ label: keys[i], color: Theme.cellTypeColors[keys[i]] })
            }
            return result
        }
        onLabelSelected: (label, color) => {
            if (radialPalette.annotationId !== "")
                AnnotationManager.updateProperties(radialPalette.annotationId, label, color)
            radialPalette.hide()
        }
    }

    // Update viewport when loaded
    Component.onCompleted: {
        if (SlideManager.isLoaded) {
            fitToWindow()
        }
    }

    Connections {
        target: SlideManager
        function onSlideLoaded() {
            root.fitToWindow()
        }
    }

    // Public functions
    function showRadialPaletteAt(annotationId, screenX, screenY) {
        radialPalette.show(screenX, screenY, annotationId)
    }

    function updateViewport() {
        root.viewportX = flickable.contentX / root.scale
        root.viewportY = flickable.contentY / root.scale
        root.viewportWidth = flickable.width / root.scale
        root.viewportHeight = flickable.height / root.scale

        // Update tile model with velocity for prefetching
        App.updateViewportWithVelocity(
            root.viewportX,
            root.viewportY,
            root.viewportWidth,
            root.viewportHeight,
            root.scale,
            root.velocityX,
            root.velocityY
        )
    }

    function zoomIn() {
        zoomTo(root.scale * 1.5)
    }

    function zoomOut() {
        zoomTo(root.scale / 1.5)
    }

    function zoomTo(newScale: real) {
        // Zoom toward center
        let centerX = flickable.contentX + flickable.width / 2
        let centerY = flickable.contentY + flickable.height / 2

        let slideX = centerX / root.scale
        let slideY = centerY / root.scale

        newScale = Math.max(root.minScale, Math.min(Theme.maxScale, newScale))
        root.scale = newScale

        flickable.contentX = Math.max(0, slideX * newScale - flickable.width / 2)
        flickable.contentY = Math.max(0, slideY * newScale - flickable.height / 2)

        updateViewport()
    }

    function fitToWindow() {
        if (!SlideManager.isLoaded) return

        let scaleX = root.width / root.contentWidth
        let scaleY = root.height / root.contentHeight
        let fitScale = Math.min(scaleX, scaleY) * 0.95

        root.scale = Math.max(root.minScale, Math.min(Theme.maxScale, fitScale))

        // Center the content
        flickable.contentX = Math.max(0, (contentContainer.width - flickable.width) / 2)
        flickable.contentY = Math.max(0, (contentContainer.height - flickable.height) / 2)

        updateViewport()
    }

    function resetView() {
        root.scale = 1.0
        flickable.contentX = 0
        flickable.contentY = 0
        updateViewport()
    }

    function setViewState(viewX: real, viewY: real, viewScale: real) {
        if (!SlideManager.isLoaded) return

        let newScale = Math.max(root.minScale, Math.min(Theme.maxScale, viewScale))
        root.scale = newScale

        let maxX = Math.max(0, contentContainer.width - flickable.width)
        let maxY = Math.max(0, contentContainer.height - flickable.height)

        flickable.contentX = Math.max(0, Math.min(maxX, viewX * newScale))
        flickable.contentY = Math.max(0, Math.min(maxY, viewY * newScale))
        updateViewport()
    }

    function pan(dx: real, dy: real) {
        flickable.contentX = Math.max(0, Math.min(contentContainer.width - flickable.width,
                                                   flickable.contentX + dx))
        flickable.contentY = Math.max(0, Math.min(contentContainer.height - flickable.height,
                                                   flickable.contentY + dy))
        updateViewport()
    }

    function centerOn(slideX: real, slideY: real) {
        flickable.contentX = slideX * root.scale - flickable.width / 2
        flickable.contentY = slideY * root.scale - flickable.height / 2
        updateViewport()
    }

    function selectAnnotation(annotationId) {
        root.selectedAnnotationId = annotationId || ""
    }

    function clearRoi() {
        interactionLayer.clearRoi()
    }

    // Handle resize
    onWidthChanged: Qt.callLater(updateViewport)
    onHeightChanged: Qt.callLater(updateViewport)
}
