import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../style"

ThemedGroupBox {
    title: "View"

    // Viewer properties and functions
    required property real viewerScale
    signal fitRequested()
    signal resetRequested()
    signal zoomRequested(real newScale)

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingSmall

        Label {
            text: "Zoom: " + (viewerScale * 100).toFixed(0) + "%"
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
        }

        Slider {
            Layout.fillWidth: true
            from: Math.log(Theme.minScale)
            to: Math.log(Theme.maxScale)
            value: Math.log(viewerScale)
            onMoved: zoomRequested(Math.exp(value))
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            ThemedButton {
                text: "Fit"
                buttonSize: "small"
                Layout.fillWidth: true
                onClicked: fitRequested()
            }

            ThemedButton {
                text: "1:1"
                buttonSize: "small"
                Layout.fillWidth: true
                onClicked: resetRequested()
            }
        }
    }
}
