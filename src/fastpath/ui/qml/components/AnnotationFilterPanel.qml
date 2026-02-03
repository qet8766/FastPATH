import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../style"

ThemedGroupBox {
    id: root
    title: "Annotation Filters"

    // Public properties
    property var visibleTypes: ({})
    property real annotationOpacity: 1.0
    property var typeCounts: ({})

    // Signals
    signal filtersChanged(var visibleTypes)
    signal filterOpacityChanged(real opacity)

    // Initialize visibility map with all types enabled
    Component.onCompleted: {
        let types = Object.keys(Theme.cellTypeColors)
        let vis = {}
        for (let i = 0; i < types.length; i++) {
            vis[types[i]] = true
        }
        root.visibleTypes = vis
    }

    function updateCounts(annotations) {
        let counts = {}
        let types = Object.keys(Theme.cellTypeColors)
        for (let i = 0; i < types.length; i++) counts[types[i]] = 0
        for (let j = 0; j < annotations.length; j++) {
            let label = annotations[j].label || "Unknown"
            if (counts[label] !== undefined) counts[label]++
        }
        root.typeCounts = counts
    }

    function setAll(value) {
        let vis = {}
        let types = Object.keys(Theme.cellTypeColors)
        for (let i = 0; i < types.length; i++) {
            vis[types[i]] = value
        }
        root.visibleTypes = vis
        root.filtersChanged(root.visibleTypes)
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingSmall

        // Per-type checkboxes
        Repeater {
            model: Object.keys(Theme.cellTypeColors)

            RowLayout {
                Layout.fillWidth: true
                spacing: Theme.spacingSmall

                required property string modelData

                CheckBox {
                    id: typeCheck
                    checked: root.visibleTypes[modelData] !== false
                    onToggled: {
                        let vis = Object.assign({}, root.visibleTypes)
                        vis[modelData] = checked
                        root.visibleTypes = vis
                        root.filtersChanged(root.visibleTypes)
                    }

                    indicator: Rectangle {
                        implicitWidth: 16
                        implicitHeight: 16
                        x: typeCheck.leftPadding
                        y: parent.height / 2 - height / 2
                        radius: Theme.radiusSmall
                        color: typeCheck.checked ? Theme.cellTypeColors[modelData] : "transparent"
                        border.color: Theme.cellTypeColors[modelData]
                        border.width: 2

                        Text {
                            anchors.centerIn: parent
                            text: "\u2713"
                            color: "#ffffff"
                            font.pixelSize: 11
                            font.bold: true
                            visible: typeCheck.checked
                        }
                    }
                }

                Label {
                    text: modelData
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    Layout.fillWidth: true
                }

                Label {
                    text: root.typeCounts[modelData] !== undefined ? root.typeCounts[modelData] : ""
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                }
            }
        }

        // All / None buttons
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            ThemedButton {
                text: "All"
                buttonSize: "small"
                Layout.fillWidth: true
                onClicked: root.setAll(true)
            }

            ThemedButton {
                text: "None"
                buttonSize: "small"
                Layout.fillWidth: true
                onClicked: root.setAll(false)
            }
        }

        // Opacity slider
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            Label {
                text: "Opacity"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
            }

            Slider {
                Layout.fillWidth: true
                from: 0.0
                to: 1.0
                value: root.annotationOpacity
                onMoved: {
                    root.annotationOpacity = value
                    root.filterOpacityChanged(value)
                }
            }
        }
    }
}
