import QtQuick
import "../style"

Item {
    id: root

    property real scale: 1.0

    // Tile repeater using the model from App
    Repeater {
        model: App.tileModel

        delegate: Image {
            x: model.tileX * root.scale
            y: model.tileY * root.scale
            width: model.tileWidth * root.scale
            height: model.tileHeight * root.scale

            source: model.tileSource
            asynchronous: false  // Tile already in Rust cache - no delay
            cache: true
            fillMode: Image.Stretch
            smooth: root.scale < 1.0  // Only smooth when zoomed out
            // NO placeholder, NO opacity animation - instant display
        }
    }
}
