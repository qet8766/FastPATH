import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property string currentTool: "pan"  // pan, point, rectangle, polygon, freehand
    property string currentColor: Theme.annotationColors[0]
    property string currentLabel: ""

    signal toolChanged(string tool)
    signal colorChanged(string color)
    signal drawingFinished(string toolType, var coordinates)

    color: Theme.surface
    radius: Theme.radiusNormal
    border.color: Theme.border

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSmall
        spacing: Theme.spacingSmall

        // Tool buttons
        Label {
            text: "Tools"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
        }

        GridLayout {
            columns: 3
            rowSpacing: Theme.spacingSmall
            columnSpacing: Theme.spacingSmall

            ToolButton {
                icon: "🖐"
                tooltip: "Pan (P)"
                selected: root.currentTool === "pan"
                onClicked: selectTool("pan")
            }

            ToolButton {
                icon: "•"
                tooltip: "Point (O)"
                selected: root.currentTool === "point"
                onClicked: selectTool("point")
            }

            ToolButton {
                icon: "▢"
                tooltip: "Rectangle (R)"
                selected: root.currentTool === "rectangle"
                onClicked: selectTool("rectangle")
            }

            ToolButton {
                icon: "△"
                tooltip: "Polygon (G)"
                selected: root.currentTool === "polygon"
                onClicked: selectTool("polygon")
            }

            ToolButton {
                icon: "✎"
                tooltip: "Freehand (F)"
                selected: root.currentTool === "freehand"
                onClicked: selectTool("freehand")
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Color selection
        Label {
            text: "Color"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
        }

        GridLayout {
            columns: 4
            rowSpacing: Theme.spacingSmall
            columnSpacing: Theme.spacingSmall

            Repeater {
                model: Theme.annotationColors

                delegate: Rectangle {
                    width: 24
                    height: 24
                    radius: 4
                    color: modelData
                    border.color: root.currentColor === modelData ? Theme.textBright : "transparent"
                    border.width: 2

                    MouseArea {
                        anchors.fill: parent
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            root.currentColor = modelData
                            root.colorChanged(modelData)
                        }
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Label input
        Label {
            text: "Label"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
        }

        TextField {
            id: labelField
            Layout.fillWidth: true
            placeholderText: "Enter label..."
            text: root.currentLabel
            onTextChanged: root.currentLabel = text

            background: Rectangle {
                color: Theme.backgroundLight
                radius: Theme.radiusSmall
                border.color: labelField.focus ? Theme.borderFocus : Theme.border
            }

            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
        }

        Item { Layout.fillHeight: true }
    }

    function selectTool(tool) {
        root.currentTool = tool
        root.toolChanged(tool)
    }

    // Keyboard shortcuts
    Shortcut {
        sequence: "P"
        onActivated: selectTool("pan")
    }

    Shortcut {
        sequence: "O"
        onActivated: selectTool("point")
    }

    Shortcut {
        sequence: "R"
        onActivated: selectTool("rectangle")
    }

    Shortcut {
        sequence: "G"
        onActivated: selectTool("polygon")
    }

    Shortcut {
        sequence: "F"
        onActivated: selectTool("freehand")
    }

    // Tool button component
    component ToolButton: Rectangle {
        property string icon: ""
        property string tooltip: ""
        property bool selected: false

        signal clicked()

        width: 32
        height: 32
        radius: Theme.radiusSmall
        color: selected ? Theme.surfaceActive : (mouseArea.containsMouse ? Theme.surfaceHover : "transparent")

        Text {
            anchors.centerIn: parent
            text: parent.icon
            font.pixelSize: 14
            color: selected ? Theme.textBright : Theme.text
        }

        MouseArea {
            id: mouseArea
            anchors.fill: parent
            hoverEnabled: true
            cursorShape: Qt.PointingHandCursor
            onClicked: parent.clicked()
        }

        ToolTip.visible: mouseArea.containsMouse
        ToolTip.text: tooltip
        ToolTip.delay: 500
    }
}
