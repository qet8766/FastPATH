import QtQuick
import "../style"

Rectangle {
    id: root

    visible: SlideManager.isLoaded
    width: column.width + Theme.spacingLarge
    height: column.height + Theme.spacingNormal
    radius: Theme.radiusNormal
    color: Qt.rgba(0, 0, 0, 0.6)

    Column {
        id: column
        anchors.centerIn: parent
        spacing: Theme.spacingTiny

        Text {
            text: "Cache: " + CacheStats.sizeMb.toFixed(1) + " MB"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
            font.family: "Consolas, monospace"
        }

        Text {
            text: "Hit: " + CacheStats.hitRatio.toFixed(1) + "%"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
            font.family: "Consolas, monospace"
        }
    }

    onVisibleChanged: {
        if (visible) {
            CacheStats.start()
        } else {
            CacheStats.stop()
        }
    }
}
