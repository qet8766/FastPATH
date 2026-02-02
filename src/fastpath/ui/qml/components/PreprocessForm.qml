import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property string inputMode: "single"
    property string inputFile: ""
    property string inputFolder: ""
    property string outputDir: ""
    property bool isProcessing: false
    property bool batchComplete: false
    property bool force: false
    property string errorMessage: ""

    property alias selectedTileSize: tileSizeCombo.currentText

    signal browseInputFile()
    signal browseInputFolder()
    signal browseOutputDir()
    signal tileSizeActivated(int tileSize)
    signal workersActivated(int workers)
    signal forceToggled(bool checked)

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

        // Input selection (Single File mode)
        Label {
            text: "Input File"
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            visible: root.inputMode === "single"
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall
            visible: root.inputMode === "single"

            ThemedTextField {
                Layout.fillWidth: true
                text: root.inputFile
                placeholderText: "Select a WSI file (.svs, .ndpi, .tiff, etc.)"
                readOnly: true
            }

            ThemedButton {
                text: "Browse..."
                enabled: !root.isProcessing
                onClicked: root.browseInputFile()
            }
        }

        // Input selection (Folder mode)
        Label {
            text: "Input Folder"
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            visible: root.inputMode === "folder"
        }

        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall
            visible: root.inputMode === "folder"

            ThemedTextField {
                Layout.fillWidth: true
                text: root.inputFolder
                placeholderText: "Select a folder containing WSI files"
                readOnly: true
            }

            ThemedButton {
                text: "Browse..."
                enabled: !root.isProcessing && !root.batchComplete
                onClicked: root.browseInputFolder()
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

            ThemedTextField {
                Layout.fillWidth: true
                text: root.outputDir
                placeholderText: "Select output directory"
                readOnly: true
            }

            ThemedButton {
                text: "Browse..."
                enabled: !root.isProcessing && !root.batchComplete
                onClicked: root.browseOutputDir()
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

            // Tile size
            Label {
                text: "Tile Size"
                color: Theme.text
            }
            ThemedComboBox {
                id: tileSizeCombo
                model: ["256", "512", "1024"]
                enabled: !root.isProcessing && !root.batchComplete

                Component.onCompleted: {
                    currentIndex = Settings.lastTileSize === 256 ? 0 : (Settings.lastTileSize === 1024 ? 2 : 1)
                }

                onActivated: {
                    Settings.lastTileSize = parseInt(currentText)
                }
            }

            // Parallel workers (folder mode only)
            Label {
                text: "Parallel Workers"
                color: Theme.text
                visible: root.inputMode === "folder"
            }
            ThemedComboBox {
                id: workersCombo
                model: ["1", "2", "3", "4", "5", "6", "7", "8"]
                enabled: !root.isProcessing && !root.batchComplete
                visible: root.inputMode === "folder"

                Component.onCompleted: {
                    currentIndex = Settings.parallelWorkers - 1
                }

                onActivated: {
                    var workers = currentIndex + 1
                    Settings.parallelWorkers = workers
                    root.workersActivated(workers)
                }
            }
        }

        // Force rebuild checkbox
        CheckBox {
            id: forceCheckbox
            text: "Force rebuild (ignore existing)"
            enabled: !root.isProcessing && !root.batchComplete

            Component.onCompleted: {
                checked = root.force
            }

            onToggled: root.forceToggled(checked)

            contentItem: Text {
                text: parent.text
                color: Theme.text
                leftPadding: parent.indicator.width + parent.spacing
                verticalAlignment: Text.AlignVCenter
            }
        }

        // Info label
        Label {
            text: "Output: 0.5 MPP (20x equivalent), JPEG Q80"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
            font.italic: true
        }

        // Error message
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: errorLabel.implicitHeight + Theme.spacingNormal
            color: Theme.errorBackground
            radius: Theme.radiusSmall
            border.color: Theme.error
            visible: root.errorMessage !== ""

            Label {
                id: errorLabel
                anchors.centerIn: parent
                width: parent.width - Theme.spacingNormal * 2
                text: root.errorMessage
                color: Theme.error
                font.pixelSize: Theme.fontSizeSmall
                wrapMode: Text.WordWrap
                horizontalAlignment: Text.AlignHCenter
            }
        }
    }
}
