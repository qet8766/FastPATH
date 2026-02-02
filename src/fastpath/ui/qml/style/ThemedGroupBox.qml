import QtQuick
import QtQuick.Controls
import "."

GroupBox {
    id: control

    background: Rectangle {
        color: Theme.surface
        radius: Theme.radiusNormal
        border.color: Theme.border
        y: control.topPadding - control.padding
        height: control.height - control.topPadding + control.padding
    }

    label: Label {
        text: control.title
        color: Theme.textMuted
        font.pixelSize: Theme.fontSizeSmall
        padding: Theme.spacingSmall
    }
}
