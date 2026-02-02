import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "style"
import "components"

ApplicationWindow {
    id: window
    visible: true
    width: 1400
    height: 900
    minimumWidth: 800
    minimumHeight: 600
    title: {
        if (preprocessMode) {
            return "FastPATH - Preprocess"
        } else if (SlideManager.isLoaded) {
            return SlideManager.sourceFile + " - FastPATH"
        }
        return "FastPATH"
    }
    color: Theme.background

    // Mode: false = viewer, true = preprocess
    property bool preprocessMode: false

    // Menu bar
    menuBar: MenuBar {
        background: Rectangle {
            color: Theme.backgroundLight
        }

        Menu {
            title: qsTr("&File")

            Action {
                text: qsTr("&Open Slide...")
                shortcut: StandardKey.Open
                enabled: !preprocessMode
                onTriggered: fileDialog.open()
            }

            Action {
                text: qsTr("&Preprocess WSI...")
                shortcut: "Ctrl+P"
                onTriggered: {
                    preprocessMode = true
                }
            }

            Action {
                text: qsTr("&Close")
                shortcut: StandardKey.Close
                enabled: SlideManager.isLoaded || preprocessMode
                onTriggered: {
                    if (preprocessMode) {
                        preprocessMode = false
                    } else {
                        App.closeSlide()
                    }
                }
            }

            MenuSeparator {}

            Action {
                text: qsTr("E&xit")
                shortcut: StandardKey.Quit
                onTriggered: Qt.quit()
            }
        }

        Menu {
            title: qsTr("&View")
            enabled: !preprocessMode

            Action {
                text: qsTr("Zoom &In")
                shortcut: StandardKey.ZoomIn
                enabled: SlideManager.isLoaded && !preprocessMode
                onTriggered: viewer.zoomIn()
            }

            Action {
                text: qsTr("Zoom &Out")
                shortcut: StandardKey.ZoomOut
                enabled: SlideManager.isLoaded && !preprocessMode
                onTriggered: viewer.zoomOut()
            }

            Action {
                text: qsTr("&Fit to Window")
                shortcut: "Ctrl+0"
                enabled: SlideManager.isLoaded && !preprocessMode
                onTriggered: viewer.fitToWindow()
            }

            Action {
                text: qsTr("&Reset View")
                shortcut: "Ctrl+1"
                enabled: SlideManager.isLoaded && !preprocessMode
                onTriggered: viewer.resetView()
            }
        }

        Menu {
            title: qsTr("&Help")

            Action {
                text: qsTr("&About FastPATH")
                onTriggered: aboutDialog.open()
            }
        }
    }

    // Folder dialog for .fastpath directories
    FolderDialog {
        id: fileDialog
        title: "Open .fastpath Slide Directory"
        onAccepted: {
            App.openSlide(selectedFolder.toString())
        }
    }

    // About dialog
    Dialog {
        id: aboutDialog
        title: "About FastPATH"
        modal: true
        anchors.centerIn: parent
        width: 400
        height: 200
        standardButtons: Dialog.Ok

        background: Rectangle {
            color: Theme.surface
            radius: Theme.radiusLarge
            border.color: Theme.border
        }

        ColumnLayout {
            anchors.fill: parent
            anchors.margins: Theme.spacingLarge
            spacing: Theme.spacingNormal

            Label {
                text: "FastPATH"
                font.pixelSize: Theme.fontSizeTitle
                font.bold: true
                color: Theme.textBright
            }

            Label {
                text: "Preprocessing-First Pathology Viewer"
                color: Theme.text
            }

            Label {
                text: "Version 0.1.0"
                color: Theme.textMuted
            }

            Item { Layout.fillHeight: true }
        }
    }

    // Main content
    RowLayout {
        anchors.fill: parent
        spacing: 0

        // Main viewer area
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.viewerBackground

            // Welcome screen when no slide loaded
            Item {
                anchors.fill: parent
                visible: !SlideManager.isLoaded && !preprocessMode

                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: Theme.spacingLarge

                    Label {
                        text: "FastPATH"
                        font.pixelSize: 48
                        font.bold: true
                        color: Theme.textMuted
                        Layout.alignment: Qt.AlignHCenter
                    }

                    Label {
                        text: "Open a .fastpath slide or preprocess a WSI"
                        font.pixelSize: Theme.fontSizeLarge
                        color: Theme.textMuted
                        Layout.alignment: Qt.AlignHCenter
                    }

                    RowLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: Theme.spacingNormal

                        ThemedButton {
                            text: "Open Slide..."
                            variant: "primary"
                            buttonSize: "large"
                            implicitWidth: 150
                            onClicked: fileDialog.open()
                        }

                        ThemedButton {
                            text: "Preprocess WSI..."
                            variant: "outline"
                            buttonSize: "large"
                            implicitWidth: 150
                            onClicked: preprocessMode = true
                        }
                    }
                }
            }

            // Preprocess mode view
            PreprocessView {
                anchors.fill: parent
                visible: preprocessMode
                onOpenResult: function(path) {
                    preprocessMode = false
                    App.openSlide(path)
                }
            }

            // Slide viewer
            SlideViewer {
                id: viewer
                anchors.fill: parent
                visible: SlideManager.isLoaded && !preprocessMode
            }
        }

        // Sidebar (collapsed when no slide or in preprocess mode)
        Rectangle {
            Layout.preferredWidth: SlideManager.isLoaded && !preprocessMode ? 280 : 0
            Layout.fillHeight: true
            color: Theme.backgroundLight
            visible: SlideManager.isLoaded && !preprocessMode

            Behavior on Layout.preferredWidth {
                NumberAnimation { duration: Theme.animationNormal }
            }

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacingNormal
                spacing: Theme.spacingNormal

                // Slide info
                ThemedGroupBox {
                    Layout.fillWidth: true
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

                // Thumbnail / minimap
                ThemedGroupBox {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 200
                    title: "Overview"

                    Image {
                        anchors.fill: parent
                        source: SlideManager.isLoaded ? "image://thumbnail/slide" : ""
                        fillMode: Image.PreserveAspectFit
                        cache: false

                        // Viewport indicator
                        Rectangle {
                            id: viewportIndicator
                            color: "transparent"
                            border.color: Theme.primary
                            border.width: 2

                            // Calculate position based on viewer viewport
                            property real imgScale: Math.min(
                                parent.paintedWidth / SlideManager.width,
                                parent.paintedHeight / SlideManager.height
                            )
                            property real offsetX: (parent.width - parent.paintedWidth) / 2
                            property real offsetY: (parent.height - parent.paintedHeight) / 2

                            x: offsetX + viewer.viewportX * imgScale
                            y: offsetY + viewer.viewportY * imgScale
                            width: Math.max(4, viewer.viewportWidth * imgScale)
                            height: Math.max(4, viewer.viewportHeight * imgScale)
                        }
                    }
                }

                // View controls
                ThemedGroupBox {
                    Layout.fillWidth: true
                    title: "View"

                    ColumnLayout {
                        anchors.fill: parent
                        spacing: Theme.spacingSmall

                        Label {
                            text: "Zoom: " + (viewer.scale * 100).toFixed(0) + "%"
                            color: Theme.text
                            font.pixelSize: Theme.fontSizeSmall
                        }

                        Slider {
                            Layout.fillWidth: true
                            from: Math.log(Theme.minScale)
                            to: Math.log(Theme.maxScale)
                            value: Math.log(viewer.scale)
                            onMoved: viewer.scale = Math.exp(value)
                        }

                        RowLayout {
                            Layout.fillWidth: true
                            spacing: Theme.spacingSmall

                            ThemedButton {
                                text: "Fit"
                                buttonSize: "small"
                                Layout.fillWidth: true
                                onClicked: viewer.fitToWindow()
                            }

                            ThemedButton {
                                text: "1:1"
                                buttonSize: "small"
                                Layout.fillWidth: true
                                onClicked: viewer.resetView()
                            }
                        }
                    }
                }

                // Navigation (only shown with multiple slides)
                ThemedGroupBox {
                    Layout.fillWidth: true
                    title: "Navigation"
                    visible: Navigator.hasMultipleSlides

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

                Item { Layout.fillHeight: true }
            }
        }
    }

    // Status bar
    footer: Rectangle {
        height: 24
        color: Theme.backgroundDark

        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: Theme.spacingNormal
            anchors.rightMargin: Theme.spacingNormal
            spacing: Theme.spacingLarge

            Label {
                text: {
                    if (preprocessMode) {
                        return Preprocess.isProcessing ? Preprocess.status : "Preprocess Mode"
                    } else if (SlideManager.isLoaded) {
                        return "Position: " + viewer.viewportX.toFixed(0) + ", " + viewer.viewportY.toFixed(0)
                    }
                    return "Ready"
                }
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
            }

            Item { Layout.fillWidth: true }

            Label {
                text: {
                    if (preprocessMode && Preprocess.isProcessing) {
                        return (Preprocess.progress * 100).toFixed(0) + "%"
                    } else if (SlideManager.isLoaded && !preprocessMode) {
                        return "Level: " + viewer.currentLevel + " | Tiles: " + App.tileModel.rowCount()
                    }
                    return ""
                }
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
            }
        }
    }

    // Keyboard shortcuts
    Shortcut {
        sequence: "Home"
        enabled: SlideManager.isLoaded
        onActivated: viewer.fitToWindow()
    }

    Shortcut {
        sequences: ["Up", "W"]
        enabled: SlideManager.isLoaded
        onActivated: viewer.pan(0, -100)
    }

    Shortcut {
        sequences: ["Down", "S"]
        enabled: SlideManager.isLoaded
        onActivated: viewer.pan(0, 100)
    }

    Shortcut {
        sequences: ["Left", "A"]
        enabled: SlideManager.isLoaded
        onActivated: viewer.pan(-100, 0)
    }

    Shortcut {
        sequences: ["Right", "D"]
        enabled: SlideManager.isLoaded
        onActivated: viewer.pan(100, 0)
    }

    // Multi-slide navigation shortcuts
    Shortcut {
        sequences: ["Ctrl+Right", "PgDown"]
        enabled: SlideManager.isLoaded && Navigator.hasMultipleSlides && Navigator.currentIndex < Navigator.totalSlides - 1
        onActivated: App.openNextSlide()
    }

    Shortcut {
        sequences: ["Ctrl+Left", "PgUp"]
        enabled: SlideManager.isLoaded && Navigator.hasMultipleSlides && Navigator.currentIndex > 0
        onActivated: App.openPreviousSlide()
    }

    // Drag and drop
    DropArea {
        anchors.fill: parent
        onDropped: (drop) => {
            if (drop.hasUrls && drop.urls.length > 0) {
                App.openSlide(drop.urls[0].toString())
            }
        }
    }
}
