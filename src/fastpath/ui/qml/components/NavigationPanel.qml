import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../style"

ThemedGroupBox {
    title: "Navigation"

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingSmall

        Label {
            text: "Slide " + (Navigator.currentIndex + 1) + " of " + Navigator.totalSlides
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            Layout.alignment: Qt.AlignHCenter
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            ThemedButton {
                text: "< Prev"
                buttonSize: "small"
                Layout.fillWidth: true
                enabled: Navigator.currentIndex > 0
                onClicked: App.openPreviousSlide()
            }

            ThemedButton {
                text: "Next >"
                buttonSize: "small"
                Layout.fillWidth: true
                enabled: Navigator.currentIndex < Navigator.totalSlides - 1
                onClicked: App.openNextSlide()
            }
        }
    }
}
