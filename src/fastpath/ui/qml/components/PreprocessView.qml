import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../style"

Item {
    id: root

    signal openResult(string path)

    // File dialog for selecting WSI input files
    FileDialog {
        id: inputFileDialog
        title: "Select WSI File to Preprocess"
        nameFilters: [
            "Whole Slide Images (*.svs *.ndpi *.tif *.tiff *.mrxs *.vms *.vmu *.scn)",
            "Aperio SVS (*.svs)",
            "Hamamatsu (*.ndpi)",
            "TIFF (*.tif *.tiff)",
            "All Files (*)"
        ]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            Preprocess.setInputFile(selectedFile.toString())
        }
    }

    // Folder dialog for selecting output directory
    FolderDialog {
        id: outputDirDialog
        title: "Select Output Directory"
        onAccepted: {
            Preprocess.setOutputDir(selectedFolder.toString())
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingLarge
        spacing: Theme.spacingLarge

        // Header
        Label {
            text: "Preprocess WSI"
            font.pixelSize: Theme.fontSizeTitle
            font.bold: true
            color: Theme.textBright
            Layout.alignment: Qt.AlignHCenter
        }

        Label {
            text: "Convert whole-slide images to FastPATH format"
            font.pixelSize: Theme.fontSizeLarge
            color: Theme.textMuted
            Layout.alignment: Qt.AlignHCenter
        }

        // Main form
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: formLayout.implicitHeight + Theme.spacingLarge * 2
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.border

            ColumnLayout {
                id: formLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingLarge
                spacing: Theme.spacingNormal

                // Input file selection
                Label {
                    text: "Input File"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    TextField {
                        id: inputFileField
                        Layout.fillWidth: true
                        text: Preprocess.inputFile
                        placeholderText: "Select a WSI file (.svs, .ndpi, .tiff, etc.)"
                        readOnly: true
                        color: Theme.text
                        placeholderTextColor: Theme.textMuted

                        background: Rectangle {
                            color: Theme.backgroundLight
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                    }

                    Button {
                        text: "Browse..."
                        enabled: !Preprocess.isProcessing
                        onClicked: inputFileDialog.open()

                        background: Rectangle {
                            color: parent.hovered ? Theme.surfaceHover : Theme.surface
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                        contentItem: Text {
                            text: parent.text
                            color: Theme.text
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // Output directory selection
                Label {
                    text: "Output Directory"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    Layout.topMargin: Theme.spacingSmall
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    TextField {
                        id: outputDirField
                        Layout.fillWidth: true
                        text: Preprocess.outputDir
                        placeholderText: "Select output directory"
                        readOnly: true
                        color: Theme.text
                        placeholderTextColor: Theme.textMuted

                        background: Rectangle {
                            color: Theme.backgroundLight
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                    }

                    Button {
                        text: "Browse..."
                        enabled: !Preprocess.isProcessing
                        onClicked: outputDirDialog.open()

                        background: Rectangle {
                            color: parent.hovered ? Theme.surfaceHover : Theme.surface
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                        contentItem: Text {
                            text: parent.text
                            color: Theme.text
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }

                // Settings
                Label {
                    text: "Settings"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    font.bold: true
                    Layout.topMargin: Theme.spacingNormal
                }

                GridLayout {
                    Layout.fillWidth: true
                    columns: 2
                    rowSpacing: Theme.spacingSmall
                    columnSpacing: Theme.spacingLarge

                    // Extraction method
                    Label {
                        text: "Method"
                        color: Theme.text
                    }
                    ComboBox {
                        id: methodCombo
                        model: ListModel {
                            ListElement { text: "Level 1 Direct (~10x)"; value: "level1" }
                            ListElement { text: "Level 0 → 20x"; value: "level0_resized" }
                        }
                        textRole: "text"
                        currentIndex: 0
                        enabled: !Preprocess.isProcessing
                        Layout.fillWidth: true

                        property string selectedValue: model.get(currentIndex).value

                        background: Rectangle {
                            color: Theme.backgroundLight
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                        contentItem: Text {
                            text: methodCombo.displayText
                            color: Theme.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: Theme.spacingSmall
                        }
                    }

                    // Tile size
                    Label {
                        text: "Tile Size"
                        color: Theme.text
                    }
                    ComboBox {
                        id: tileSizeCombo
                        model: ["256", "512", "1024"]
                        currentIndex: 1
                        enabled: !Preprocess.isProcessing

                        background: Rectangle {
                            color: Theme.backgroundLight
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                        contentItem: Text {
                            text: tileSizeCombo.displayText
                            color: Theme.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: Theme.spacingSmall
                        }
                    }

                    // Quality
                    Label {
                        text: "JPEG Quality"
                        color: Theme.text
                    }
                    RowLayout {
                        Slider {
                            id: qualitySlider
                            from: 70
                            to: 100
                            value: 95
                            stepSize: 1
                            enabled: !Preprocess.isProcessing
                            Layout.preferredWidth: 150
                        }
                        Label {
                            text: qualitySlider.value.toFixed(0)
                            color: Theme.textMuted
                            Layout.preferredWidth: 30
                        }
                    }
                }

                // Info label
                Label {
                    text: methodCombo.currentIndex === 0
                        ? "Extracts level 1 directly from WSI (~10x magnification)"
                        : "Extracts full resolution and resizes to 20x (higher quality, slower)"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                    font.italic: true
                }
            }
        }

        // Progress section
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: progressLayout.implicitHeight + Theme.spacingLarge * 2
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.border
            visible: Preprocess.isProcessing || Preprocess.progress > 0

            ColumnLayout {
                id: progressLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingLarge
                spacing: Theme.spacingSmall

                Label {
                    text: "Progress"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    font.bold: true
                }

                ProgressBar {
                    Layout.fillWidth: true
                    value: Preprocess.progress

                    background: Rectangle {
                        color: Theme.backgroundLight
                        radius: Theme.radiusSmall
                    }

                    contentItem: Item {
                        Rectangle {
                            width: parent.width * Preprocess.progress
                            height: parent.height
                            radius: Theme.radiusSmall
                            color: Theme.primary
                        }
                    }
                }

                Label {
                    text: Preprocess.status
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }
            }
        }

        // Action buttons
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Theme.spacingNormal

            Button {
                text: Preprocess.isProcessing ? "Processing..." : "Start Preprocessing"
                enabled: !Preprocess.isProcessing && Preprocess.inputFile !== ""
                onClicked: {
                    var tileSize = parseInt(tileSizeCombo.currentText)
                    var quality = qualitySlider.value
                    var method = methodCombo.selectedValue
                    Preprocess.startPreprocess(tileSize, quality, method)
                }

                background: Rectangle {
                    color: parent.enabled ? (parent.hovered ? Theme.primaryHover : Theme.primary) : Theme.backgroundLight
                    radius: Theme.radiusNormal
                    implicitWidth: 180
                    implicitHeight: 40
                }

                contentItem: Text {
                    text: parent.text
                    color: parent.enabled ? Theme.textBright : Theme.textMuted
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }

            Button {
                text: "Cancel"
                visible: Preprocess.isProcessing
                onClicked: Preprocess.cancelPreprocess()

                background: Rectangle {
                    color: parent.hovered ? "#c0392b" : "#e74c3c"
                    radius: Theme.radiusNormal
                    implicitWidth: 100
                    implicitHeight: 40
                }

                contentItem: Text {
                    text: parent.text
                    color: Theme.textBright
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                }
            }
        }

        // Result section
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: resultLayout.implicitHeight + Theme.spacingLarge * 2
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.primary
            border.width: 2
            visible: Preprocess.resultPath !== ""

            ColumnLayout {
                id: resultLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingLarge
                spacing: Theme.spacingSmall

                Label {
                    text: "Preprocessing Complete!"
                    color: Theme.primary
                    font.pixelSize: Theme.fontSizeLarge
                    font.bold: true
                }

                Label {
                    text: "Output: " + Preprocess.resultPath
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    elide: Text.ElideMiddle
                    Layout.fillWidth: true
                }

                Button {
                    text: "Open in Viewer"
                    onClicked: root.openResult(Preprocess.resultPath)
                    Layout.topMargin: Theme.spacingSmall

                    background: Rectangle {
                        color: parent.hovered ? Theme.primaryHover : Theme.primary
                        radius: Theme.radiusNormal
                        implicitWidth: 150
                        implicitHeight: 36
                    }

                    contentItem: Text {
                        text: parent.text
                        color: Theme.textBright
                        horizontalAlignment: Text.AlignHCenter
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
