import QtQuick

Item {
    id: root

    property real scale: 1.0
    property bool annotationsVisible: true

    // Generation counter — incremented on annotationsChanged to bust provider cache
    property int _annotationGeneration: 0

    visible: annotationsVisible

    Connections {
        target: AnnotationManager
        function onAnnotationsChanged() {
            root._annotationGeneration++
        }
    }

    // Reuses the same tile grid as TileLayer
    Repeater {
        model: App.tileModel

        delegate: Image {
            x: model.tileX * root.scale
            y: model.tileY * root.scale
            width: model.tileWidth * root.scale
            height: model.tileHeight * root.scale

            source: "image://annotations/" + model.level + "/" + model.col + "_" + model.row + "?g=" + root._annotationGeneration
            asynchronous: true
            cache: false  // Provider owns the cache; generation in URL handles invalidation
            fillMode: Image.Stretch
            smooth: root.scale < 1.0
        }
    }
}
