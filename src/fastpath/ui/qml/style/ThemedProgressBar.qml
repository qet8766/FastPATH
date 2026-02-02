import QtQuick
import QtQuick.Controls
import "."

ProgressBar {
    id: control

    background: Rectangle {
        implicitHeight: 20
        color: Theme.backgroundLight
        radius: Theme.radiusSmall
    }

    contentItem: Item {
        implicitHeight: 20

        Rectangle {
            width: parent.width * control.visualPosition
            height: parent.height
            radius: Theme.radiusSmall
            color: Theme.primary
        }
    }
}
