import QtQuick
import QtQuick.Shapes
import "../style"

Item {
    id: root

    // Set by SlideViewer when an annotation is selected
    property var selectedAnnotation: null  // AnnotationDict or null
    property real slideScale: 1.0

    visible: selectedAnnotation !== null

    Shape {
        id: shape
        anchors.fill: parent
        visible: root.selectedAnnotation !== null

        ShapePath {
            id: shapePath
            strokeWidth: 3
            strokeColor: root.selectedAnnotation ? root.selectedAnnotation.color || Theme.primary : Theme.primary
            fillColor: root.selectedAnnotation ? Qt.rgba(
                _parseColor(root.selectedAnnotation.color || Theme.primary).r,
                _parseColor(root.selectedAnnotation.color || Theme.primary).g,
                _parseColor(root.selectedAnnotation.color || Theme.primary).b,
                0.3
            ) : "transparent"
            joinStyle: ShapePath.RoundJoin

            PathPolyline {
                id: polyline
                path: root._computePath()
            }
        }
    }

    function _parseColor(hex) {
        return Qt.color(hex)
    }

    function _computePath() {
        if (!root.selectedAnnotation) return []

        let ann = root.selectedAnnotation
        let coords = ann.coordinates
        let type = ann.type
        let s = root.slideScale

        if (!coords || coords.length === 0) return []

        if (type === "point" && coords.length >= 1) {
            // Approximate circle with 16 segments
            let cx = coords[0][0] * s
            let cy = coords[0][1] * s
            let r = 8  // pixels in screen space
            let points = []
            for (let i = 0; i <= 16; i++) {
                let angle = (i / 16) * 2 * Math.PI
                points.push(Qt.point(cx + r * Math.cos(angle), cy + r * Math.sin(angle)))
            }
            return points
        }

        if (type === "rectangle" && coords.length >= 2) {
            let x1 = coords[0][0] * s
            let y1 = coords[0][1] * s
            let x2 = coords[1][0] * s
            let y2 = coords[1][1] * s
            return [
                Qt.point(x1, y1),
                Qt.point(x2, y1),
                Qt.point(x2, y2),
                Qt.point(x1, y2),
                Qt.point(x1, y1)
            ]
        }

        // Polygon or freehand
        if (coords.length >= 3) {
            let points = coords.map(c => Qt.point(c[0] * s, c[1] * s))
            // Close the polygon
            points.push(Qt.point(coords[0][0] * s, coords[0][1] * s))
            return points
        }

        return []
    }
}
