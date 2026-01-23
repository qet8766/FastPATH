import QtQuick
import "../style"

Item {
    id: root
    property real scale: 1.0

    Repeater {
        model: App.fallbackTileModel

        delegate: Image {
            x: model.tileX * root.scale
            y: model.tileY * root.scale
            width: model.tileWidth * root.scale
            height: model.tileHeight * root.scale

            source: model.tileSource
            asynchronous: true
            cache: true
            fillMode: Image.Stretch
            smooth: true
        }
    }
}
