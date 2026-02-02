import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property var fileListModel
    property bool shouldShow: false

    Layout.fillWidth: true
    Layout.fillHeight: true
    Layout.minimumHeight: 150
    color: Theme.surface
    radius: Theme.radiusNormal
    border.color: Theme.border
    visible: shouldShow

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingNormal
        spacing: Theme.spacingSmall

        Label {
            text: "Files to Process (" + root.fileListModel.rowCount() + ")"
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            font.bold: true
        }

        ListView {
            id: fileListView
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            model: root.fileListModel

            delegate: Rectangle {
                width: fileListView.width
                height: 36
                color: index % 2 === 0 ? "transparent" : Qt.rgba(1, 1, 1, 0.02)

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: Theme.spacingSmall
                    anchors.rightMargin: Theme.spacingSmall
                    spacing: Theme.spacingSmall

                    // Status icon
                    Label {
                        text: {
                            switch(model.status) {
                                case "pending": return "\u25CB"
                                case "processing": return "\u27F3"
                                case "done": return "\u2713"
                                case "skipped": return "\u2298"
                                case "error": return "\u2715"
                                default: return "\u25CB"
                            }
                        }
                        color: {
                            switch(model.status) {
                                case "pending": return Theme.textMuted
                                case "processing": return Theme.primary
                                case "done": return Theme.success
                                case "skipped": return Theme.warning
                                case "error": return Theme.error
                                default: return Theme.textMuted
                            }
                        }
                        font.pixelSize: Theme.fontSizeLarge
                        Layout.preferredWidth: 24
                    }

                    // File name
                    Label {
                        text: model.fileName
                        color: Theme.text
                        elide: Text.ElideMiddle
                        Layout.fillWidth: true
                    }

                    // Progress bar or status text
                    Item {
                        Layout.preferredWidth: 100
                        Layout.preferredHeight: 20

                        ThemedProgressBar {
                            anchors.fill: parent
                            value: model.progress
                            visible: model.status === "processing"
                        }

                        Label {
                            anchors.centerIn: parent
                            text: {
                                switch(model.status) {
                                    case "done": return "Done"
                                    case "skipped": return "Skipped"
                                    case "error": return "Error"
                                    default: return ""
                                }
                            }
                            color: {
                                switch(model.status) {
                                    case "done": return Theme.success
                                    case "skipped": return Theme.warning
                                    case "error": return Theme.error
                                    default: return Theme.textMuted
                                }
                            }
                            font.pixelSize: Theme.fontSizeSmall
                            visible: model.status !== "processing" && model.status !== "pending"
                        }
                    }
                }
            }

            ScrollBar.vertical: ScrollBar {
                active: true
            }
        }
    }
}
