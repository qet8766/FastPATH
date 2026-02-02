import QtQuick
import QtQuick.Controls
import "."

TextField {
    id: control

    color: Theme.text
    placeholderTextColor: Theme.textMuted

    background: Rectangle {
        color: Theme.backgroundLight
        radius: Theme.radiusSmall
        border.color: control.focus ? Theme.borderFocus : Theme.border
    }
}
