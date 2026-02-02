import QtQuick
import QtQuick.Controls
import "."

Button {
    id: control

    property string variant: "secondary"  // "primary" | "secondary" | "outline" | "danger"
    property string buttonSize: "normal"   // "small" | "normal" | "large"

    implicitHeight: buttonSize === "small" ? Theme.buttonHeightSmall :
                    buttonSize === "large" ? Theme.buttonHeightLarge :
                    Theme.buttonHeightNormal

    background: Rectangle {
        implicitHeight: control.implicitHeight
        radius: control.buttonSize === "small" ? Theme.radiusSmall : Theme.radiusNormal
        color: {
            if (!control.enabled)
                return control.variant === "outline" ? "transparent" : Theme.backgroundLight
            switch (control.variant) {
                case "primary":
                    return control.hovered ? Theme.primaryHover : Theme.primary
                case "danger":
                    return control.hovered ? Theme.dangerHover : Theme.error
                case "outline":
                    return control.hovered ? Theme.surfaceHover : "transparent"
                default: // secondary
                    return control.hovered ? Theme.surfaceHover : Theme.surface
            }
        }
        border.color: {
            if (control.variant === "outline")
                return control.enabled ? Theme.primary : Theme.border
            if (control.variant === "secondary")
                return Theme.border
            return "transparent"
        }
        border.width: control.variant === "outline" ? 2 : (control.variant === "secondary" ? 1 : 0)
    }

    contentItem: Text {
        text: control.text
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        font.pixelSize: control.buttonSize === "small" ? Theme.fontSizeSmall : Theme.fontSizeNormal
        color: {
            if (!control.enabled)
                return Theme.textMuted
            switch (control.variant) {
                case "primary":
                case "danger":
                    return Theme.textBright
                case "outline":
                    return Theme.primary
                default:
                    return Theme.text
            }
        }
    }
}
