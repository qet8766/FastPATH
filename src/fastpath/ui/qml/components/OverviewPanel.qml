import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../style"

ThemedGroupBox {
    title: "Overview"

    // Viewer properties needed for viewport indicator
    required property real viewerViewportX
    required property real viewerViewportY
    required property real viewerViewportWidth
    required property real viewerViewportHeight

    Image {
        anchors.fill: parent
        source: SlideManager.isLoaded ? "image://thumbnail/slide" : ""
        fillMode: Image.PreserveAspectFit
        cache: false

        // Viewport indicator
        Rectangle {
            id: viewportIndicator
            color: "transparent"
            border.color: Theme.primary
            border.width: 2

            // Calculate position based on viewer viewport
            property real imgScale: Math.min(
                parent.paintedWidth / SlideManager.width,
                parent.paintedHeight / SlideManager.height
            )
            property real offsetX: (parent.width - parent.paintedWidth) / 2
            property real offsetY: (parent.height - parent.paintedHeight) / 2

            x: offsetX + viewerViewportX * imgScale
            y: offsetY + viewerViewportY * imgScale
            width: Math.max(4, viewerViewportWidth * imgScale)
            height: Math.max(4, viewerViewportHeight * imgScale)
        }
    }
}
