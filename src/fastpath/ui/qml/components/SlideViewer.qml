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

            // Interaction overlay (mode-based: draw, roi, measure)
            InteractionLayer {
                id: interactionLayer
                anchors.fill: parent
                slideScale: root.scale
                contentX: flickable.contentX
                contentY: flickable.contentY
                z: 2
            }
        }

        onContentXChanged: updateViewport()
        onContentYChanged: updateViewport()

        // Smooth scrolling
        flickDeceleration: 3000
        maximumFlickVelocity: 3000
    }

    // Velocity tracking timer for prefetch optimization
    Timer {
        id: velocityTimer
        interval: 16  // ~60fps sampling
        repeat: true
        running: flickable.moving || flickable.flicking
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

    // Mouse area for zoom
    MouseArea {
        anchors.fill: parent
        acceptedButtons: Qt.NoButton
        propagateComposedEvents: true

        onWheel: (wheel) => {
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
            let newScale = Math.max(Theme.minScale, Math.min(Theme.maxScale, root.scale * zoomFactor))
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
        minimumScale: Theme.minScale / root.scale
        maximumScale: Theme.maxScale / root.scale

        onScaleChanged: {
            let newScale = root.scale * pinchHandler.activeScale
            newScale = Math.max(Theme.minScale, Math.min(Theme.maxScale, newScale))
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

        newScale = Math.max(Theme.minScale, Math.min(Theme.maxScale, newScale))
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

        root.scale = Math.max(Theme.minScale, Math.min(Theme.maxScale, fitScale))

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

    // Handle resize
    onWidthChanged: Qt.callLater(updateViewport)
    onHeightChanged: Qt.callLater(updateViewport)
}
