import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property string title: "Progress"
    property real progressValue: 0
    property string statusText: ""
    property bool shouldShow: false

    Layout.fillWidth: true
    Layout.preferredHeight: shouldShow ? 100 : 0
    color: Theme.surface
    radius: Theme.radiusNormal
    border.color: Theme.border
    visible: shouldShow
    clip: true

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingLarge
        spacing: Theme.spacingSmall

        Label {
            text: root.title
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            font.bold: true
        }

        ThemedProgressBar {
            Layout.fillWidth: true
            Layout.preferredHeight: 20
            value: root.progressValue
        }

        Label {
            text: root.statusText
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }
    }
}
