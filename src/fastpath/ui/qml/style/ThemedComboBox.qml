import QtQuick
import QtQuick.Controls
import "."

ComboBox {
    id: control

    background: Rectangle {
        color: Theme.backgroundLight
        radius: Theme.radiusSmall
        border.color: Theme.border
    }

    contentItem: Text {
        text: control.displayText
        color: Theme.text
        verticalAlignment: Text.AlignVCenter
        leftPadding: Theme.spacingSmall
    }
}
