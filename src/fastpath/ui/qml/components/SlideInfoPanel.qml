import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../style"

ThemedGroupBox {
    title: "Slide Info"

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingSmall

        Label {
            text: "File: " + SlideManager.sourceFile
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideMiddle
            Layout.fillWidth: true
        }

        Label {
            text: "Size: " + SlideManager.width + " x " + SlideManager.height
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
        }

        Label {
            text: "Magnification: " + SlideManager.magnification + "x"
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
        }

        Label {
            text: "MPP: " + SlideManager.mpp.toFixed(3)
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
        }

        Label {
            text: "Levels: " + SlideManager.numLevels
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
        }
    }
}
