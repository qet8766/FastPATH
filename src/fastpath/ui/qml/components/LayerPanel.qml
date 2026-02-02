import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property var annotations: []
    property string selectedAnnotationId: ""
    property bool annotationsVisible: true

    signal annotationSelected(string annotationId)
    signal annotationDeleted(string annotationId)
    signal visibilityToggled(bool visible)

    color: Theme.surface
    radius: Theme.radiusNormal
    border.color: Theme.border

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSmall
        spacing: Theme.spacingSmall

        // Header
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            Label {
                text: "Annotations"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
                Layout.fillWidth: true
            }

            Label {
                text: root.annotations.length.toString()
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall

                background: Rectangle {
                    color: Theme.backgroundLight
                    radius: 8
                    anchors.fill: parent
                    anchors.margins: -4
                }
            }

            // Visibility toggle
            Rectangle {
                width: 24
                height: 24
                radius: Theme.radiusSmall
                color: visibilityMouseArea.containsMouse ? Theme.surfaceHover : "transparent"

                Text {
                    anchors.centerIn: parent
                    text: root.annotationsVisible ? "👁" : "👁‍🗨"
                    font.pixelSize: 12
                }

                MouseArea {
                    id: visibilityMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        root.annotationsVisible = !root.annotationsVisible
                        root.visibilityToggled(root.annotationsVisible)
                    }
                }

                ToolTip.visible: visibilityMouseArea.containsMouse
                ToolTip.text: root.annotationsVisible ? "Hide annotations" : "Show annotations"
                ToolTip.delay: 500
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Annotation list
        ListView {
            id: annotationList
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2

            model: root.annotations

            delegate: Rectangle {
                id: annotationItem
                width: annotationList.width
                height: 36
                radius: Theme.radiusSmall
                color: modelData.id === root.selectedAnnotationId ?
                       Theme.surfaceActive :
                       (itemMouseArea.containsMouse ? Theme.surfaceHover : "transparent")

                RowLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingSmall
                    spacing: Theme.spacingSmall

                    // Color indicator
                    Rectangle {
                        width: 12
                        height: 12
                        radius: 2
                        color: modelData.color
                    }

                    // Type icon
                    Text {
                        text: {
                            switch(modelData.type) {
                                case "point": return "•"
                                case "rectangle": return "▢"
                                case "polygon": return "△"
                                case "freehand": return "✎"
                                default: return "?"
                            }
                        }
                        font.pixelSize: 12
                        color: Theme.textMuted
                    }

                    // Label or ID
                    Label {
                        text: modelData.label || modelData.id
                        color: Theme.text
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    // Delete button
                    Rectangle {
                        width: 20
                        height: 20
                        radius: Theme.radiusSmall
                        color: deleteMouseArea.containsMouse ? Theme.error : "transparent"
                        visible: itemMouseArea.containsMouse || modelData.id === root.selectedAnnotationId

                        Text {
                            anchors.centerIn: parent
                            text: "×"
                            font.pixelSize: 14
                            font.bold: true
                            color: deleteMouseArea.containsMouse ? Theme.textBright : Theme.textMuted
                        }

                        MouseArea {
                            id: deleteMouseArea
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: root.annotationDeleted(modelData.id)
                        }
                    }
                }

                MouseArea {
                    id: itemMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    acceptedButtons: Qt.LeftButton
                    propagateComposedEvents: true
                    onClicked: root.annotationSelected(modelData.id)
                }
            }

            // Empty state
            Label {
                visible: root.annotations.length === 0
                anchors.centerIn: parent
                text: "No annotations yet"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Actions
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            ThemedButton {
                text: "Clear All"
                buttonSize: "small"
                enabled: root.annotations.length > 0
                Layout.fillWidth: true
                onClicked: clearConfirmDialog.open()
            }
        }
    }

    // Clear confirmation dialog
    Dialog {
        id: clearConfirmDialog
        title: "Clear Annotations"
        modal: true
        anchors.centerIn: parent
        standardButtons: Dialog.Yes | Dialog.No

        background: Rectangle {
            color: Theme.surface
            radius: Theme.radiusLarge
            border.color: Theme.border
        }

        Label {
            text: "Are you sure you want to delete all annotations?"
            color: Theme.text
        }

        onAccepted: {
            // Emit signal to clear all
            for (let i = root.annotations.length - 1; i >= 0; i--) {
                root.annotationDeleted(root.annotations[i].id)
            }
        }
    }
}
