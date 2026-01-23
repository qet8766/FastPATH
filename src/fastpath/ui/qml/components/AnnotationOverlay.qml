import QtQuick
import QtQuick.Shapes
import "../style"

Item {
    id: root

    property real scale: 1.0
    property var annotations: []
    property string selectedId: ""
    property string hoveredId: ""

    signal annotationClicked(string annotationId)
    signal annotationDoubleClicked(string annotationId)

    // Render each annotation
    Repeater {
        model: root.annotations

        delegate: Item {
            id: annotationItem

            property var annotation: modelData
            property bool isSelected: annotation.id === root.selectedId
            property bool isHovered: annotation.id === root.hoveredId

            // Position based on bounds
            x: annotation.bounds[0] * root.scale
            y: annotation.bounds[1] * root.scale
            width: (annotation.bounds[2] - annotation.bounds[0]) * root.scale
            height: (annotation.bounds[3] - annotation.bounds[1]) * root.scale

            // Shape for rendering
            Shape {
                anchors.fill: parent
                layer.enabled: true
                layer.samples: 4  // Anti-aliasing

                ShapePath {
                    id: shapePath
                    strokeWidth: isSelected ? 3 : (isHovered ? 2 : 1.5)
                    strokeColor: annotation.color
                    fillColor: Qt.rgba(
                        parseInt(annotation.color.substr(1, 2), 16) / 255,
                        parseInt(annotation.color.substr(3, 2), 16) / 255,
                        parseInt(annotation.color.substr(5, 2), 16) / 255,
                        isSelected ? 0.3 : (isHovered ? 0.2 : 0.1)
                    )
                    joinStyle: ShapePath.RoundJoin
                    capStyle: ShapePath.RoundCap

                    // Build path based on annotation type
                    PathPolyline {
                        path: {
                            if (annotation.type === "point") {
                                // Point: draw a small circle marker
                                return []
                            } else if (annotation.type === "rectangle") {
                                // Rectangle: two corner points
                                let x1 = (annotation.coordinates[0][0] - annotation.bounds[0]) * root.scale
                                let y1 = (annotation.coordinates[0][1] - annotation.bounds[1]) * root.scale
                                let x2 = (annotation.coordinates[1][0] - annotation.bounds[0]) * root.scale
                                let y2 = (annotation.coordinates[1][1] - annotation.bounds[1]) * root.scale
                                return [
                                    Qt.point(x1, y1),
                                    Qt.point(x2, y1),
                                    Qt.point(x2, y2),
                                    Qt.point(x1, y2),
                                    Qt.point(x1, y1)
                                ]
                            } else {
                                // Polygon/freehand
                                let pts = []
                                for (let i = 0; i < annotation.coordinates.length; i++) {
                                    let coord = annotation.coordinates[i]
                                    pts.push(Qt.point(
                                        (coord[0] - annotation.bounds[0]) * root.scale,
                                        (coord[1] - annotation.bounds[1]) * root.scale
                                    ))
                                }
                                // Close polygon
                                if (pts.length > 0) {
                                    pts.push(pts[0])
                                }
                                return pts
                            }
                        }
                    }
                }
            }

            // Point marker (circle for point annotations)
            Rectangle {
                visible: annotation.type === "point"
                anchors.centerIn: parent
                width: isSelected ? 16 : (isHovered ? 14 : 12)
                height: width
                radius: width / 2
                color: annotation.color
                border.color: Qt.darker(annotation.color, 1.2)
                border.width: 2
            }

            // Label
            Rectangle {
                visible: annotation.label !== "" && (width > 50 || isSelected || isHovered)
                x: 4
                y: 4
                width: labelText.width + 8
                height: labelText.height + 4
                color: Qt.rgba(0, 0, 0, 0.7)
                radius: 2

                Text {
                    id: labelText
                    anchors.centerIn: parent
                    text: annotation.label
                    color: "white"
                    font.pixelSize: 11
                }
            }

            // Mouse interaction
            MouseArea {
                anchors.fill: parent
                hoverEnabled: true

                onEntered: root.hoveredId = annotation.id
                onExited: {
                    if (root.hoveredId === annotation.id) {
                        root.hoveredId = ""
                    }
                }
                onClicked: root.annotationClicked(annotation.id)
                onDoubleClicked: root.annotationDoubleClicked(annotation.id)
            }
        }
    }
}
