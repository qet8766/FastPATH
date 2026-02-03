import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import QtQuick.Dialogs
import "../style"

ThemedGroupBox {
    id: root
    title: "Annotations (" + AnnotationManager.count + ")"

    property bool annotationsVisible: true
    signal visibilityToggled(bool visible)
    signal exportRequested(string path)
    signal importRequested(string path)
    signal clearRequested()

    FileDialog {
        id: exportDialog
        title: "Export Annotations"
        nameFilters: ["GeoJSON Files (*.geojson)", "All Files (*)"]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "geojson"
        onAccepted: {
            let path = selectedFile.toString()
            // Normalize file:/// URL for Windows
            if (path.startsWith("file:///")) {
                path = path.substring(8)
            }
            root.exportRequested(path)
        }
    }

    FileDialog {
        id: importDialog
        title: "Import Annotations"
        nameFilters: ["GeoJSON Files (*.geojson)", "All Files (*)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            let path = selectedFile.toString()
            if (path.startsWith("file:///")) {
                path = path.substring(8)
            }
            root.importRequested(path)
        }
    }

    Dialog {
        id: clearConfirmDialog
        title: "Clear Annotations"
        modal: true
        anchors.centerIn: Overlay.overlay
        width: 300
        standardButtons: Dialog.Ok | Dialog.Cancel

        background: Rectangle {
            color: Theme.surface
            radius: Theme.radiusLarge
            border.color: Theme.border
        }

        Label {
            text: "Remove all " + AnnotationManager.count + " annotations?"
            color: Theme.text
            wrapMode: Text.WordWrap
            width: parent.width
        }

        onAccepted: root.clearRequested()
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingSmall

        // Visibility toggle row
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            Switch {
                id: visibilitySwitch
                checked: root.annotationsVisible
                onCheckedChanged: {
                    root.annotationsVisible = checked
                    root.visibilityToggled(checked)
                }
            }

            Label {
                text: visibilitySwitch.checked ? "Visible" : "Hidden"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
                Layout.fillWidth: true
            }
        }

        // Group list
        ListView {
            id: groupList
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, 150)
            clip: true
            model: _groupModel

            delegate: RowLayout {
                width: groupList.width
                spacing: Theme.spacingSmall

                Rectangle {
                    width: 8
                    height: 8
                    radius: 4
                    color: Theme.annotationColors[index % Theme.annotationColors.length]
                }

                Label {
                    text: modelData.name
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    elide: Text.ElideRight
                    Layout.fillWidth: true
                }

                Label {
                    text: modelData.count
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                }

                Button {
                    text: "X"
                    flat: true
                    implicitWidth: 20
                    implicitHeight: 20
                    font.pixelSize: Theme.fontSizeSmall
                    contentItem: Label {
                        text: "X"
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeSmall
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                    background: Rectangle {
                        color: parent.hovered ? Theme.errorBackground : "transparent"
                        radius: Theme.radiusSmall
                    }
                    onClicked: AnnotationManager.removeAnnotationsByGroup(modelData.name)
                }
            }
        }

        // No annotations message
        Label {
            visible: AnnotationManager.count === 0
            text: "No annotations"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
            font.italic: true
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
        }

        // Action buttons
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            Button {
                text: "Export"
                flat: true
                enabled: AnnotationManager.count > 0
                font.pixelSize: Theme.fontSizeSmall
                contentItem: Label {
                    text: parent.text
                    color: parent.enabled ? Theme.primary : Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                }
                background: Rectangle {
                    color: parent.hovered ? Theme.surfaceHover : "transparent"
                    radius: Theme.radiusSmall
                }
                onClicked: exportDialog.open()
            }

            Button {
                text: "Import"
                flat: true
                font.pixelSize: Theme.fontSizeSmall
                contentItem: Label {
                    text: parent.text
                    color: Theme.primary
                    font.pixelSize: Theme.fontSizeSmall
                }
                background: Rectangle {
                    color: parent.hovered ? Theme.surfaceHover : "transparent"
                    radius: Theme.radiusSmall
                }
                onClicked: importDialog.open()
            }

            Item { Layout.fillWidth: true }

            Button {
                text: "Clear"
                flat: true
                enabled: AnnotationManager.count > 0
                font.pixelSize: Theme.fontSizeSmall
                contentItem: Label {
                    text: parent.text
                    color: parent.enabled ? Theme.error : Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                }
                background: Rectangle {
                    color: parent.hovered ? Theme.errorBackground : "transparent"
                    radius: Theme.radiusSmall
                }
                onClicked: clearConfirmDialog.open()
            }
        }
    }

    // Internal: group model rebuilt from AnnotationManager signals
    property var _groupModel: []

    function _refreshGroups() {
        let groups = AnnotationManager.getGroups()
        let model = []
        for (let i = 0; i < groups.length; i++) {
            model.push({
                "name": groups[i],
                "count": AnnotationManager.getGroupCount(groups[i])
            })
        }
        root._groupModel = model
    }

    Connections {
        target: AnnotationManager
        function onAnnotationsChanged() { root._refreshGroups() }
    }

    Component.onCompleted: _refreshGroups()
}
