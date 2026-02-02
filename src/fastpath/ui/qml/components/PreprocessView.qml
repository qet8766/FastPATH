import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Dialogs
import "../style"

Item {
    id: root

    signal openResult(string path)

    // Error message display
    property string errorMessage: ""

    // Handle errors from preprocessing backend
    Connections {
        target: Preprocess
        function onErrorOccurred(message) {
            errorMessage = message
            errorTimer.restart()
        }
        function onPreprocessingFinished(path) {
            if (path !== "" && Preprocess.inputMode === "single") {
                openResult(path)
            }
        }
    }

    // Auto-clear error message after 5 seconds
    Timer {
        id: errorTimer
        interval: 5000
        onTriggered: errorMessage = ""
    }

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

    // Folder dialog for selecting input folder (batch mode)
    FolderDialog {
        id: inputFolderDialog
        title: "Select Folder with WSI Files"
        onAccepted: {
            Preprocess.setInputFolder(selectedFolder.toString())
        }
    }

    // Folder dialog for selecting output directory
    FolderDialog {
        id: outputDirDialog
        title: "Select Output Directory"
        onAccepted: {
            Preprocess.setOutputDir(selectedFolder.toString())
            // Save as default
            Settings.defaultOutputDir = Preprocess.outputDir
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

        // Mode toggle
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: modeRow.implicitHeight + Theme.spacingNormal * 2
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.border

            RowLayout {
                id: modeRow
                anchors.centerIn: parent
                spacing: Theme.spacingLarge

                RadioButton {
                    id: singleModeRadio
                    text: "Single File"
                    checked: Preprocess.inputMode === "single"
                    enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
                    onClicked: Preprocess.setInputMode("single")

                    contentItem: Text {
                        text: parent.text
                        color: Theme.text
                        leftPadding: parent.indicator.width + parent.spacing
                        verticalAlignment: Text.AlignVCenter
                    }
                }

                RadioButton {
                    id: folderModeRadio
                    text: "Folder (Batch)"
                    checked: Preprocess.inputMode === "folder"
                    enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
                    onClicked: Preprocess.setInputMode("folder")

                    contentItem: Text {
                        text: parent.text
                        color: Theme.text
                        leftPadding: parent.indicator.width + parent.spacing
                        verticalAlignment: Text.AlignVCenter
                    }
                }
            }
        }

        // Main form
        PreprocessForm {
            id: preprocessForm
            inputMode: Preprocess.inputMode
            inputFile: Preprocess.inputFile
            inputFolder: Preprocess.inputFolder
            outputDir: Preprocess.outputDir
            isProcessing: Preprocess.isProcessing
            batchComplete: Preprocess.batchComplete
            force: Preprocess.force
            errorMessage: root.errorMessage

            onBrowseInputFile: inputFileDialog.open()
            onBrowseInputFolder: inputFolderDialog.open()
            onBrowseOutputDir: outputDirDialog.open()
            onWorkersActivated: (workers) => Preprocess.setParallelWorkers(workers)
            onForceToggled: (checked) => Preprocess.setForce(checked)
        }

        // File list (folder mode only)
        PreprocessFileList {
            fileListModel: Preprocess.fileListModel
            shouldShow: Preprocess.inputMode === "folder" && Preprocess.fileListModel.rowCount() > 0
        }

        // Single file progress
        PreprocessProgress {
            title: "Progress"
            progressValue: Preprocess.progress
            statusText: Preprocess.status
            shouldShow: Preprocess.inputMode === "single" && (Preprocess.isProcessing || Preprocess.progress > 0)
        }

        // Batch overall progress
        PreprocessProgress {
            title: "Overall Progress"
            progressValue: Preprocess.overallProgress
            statusText: Preprocess.status
            shouldShow: Preprocess.inputMode === "folder" && Preprocess.isProcessing
        }

        // Action buttons
        RowLayout {
            Layout.alignment: Qt.AlignHCenter
            spacing: Theme.spacingNormal
            visible: !Preprocess.batchComplete

            ThemedButton {
                text: Preprocess.isProcessing ? "Processing..." : "Start Preprocessing"
                variant: "primary"
                buttonSize: "large"
                implicitWidth: 180
                enabled: !Preprocess.isProcessing && (
                    (Preprocess.inputMode === "single" && Preprocess.inputFile !== "") ||
                    (Preprocess.inputMode === "folder" && Preprocess.fileListModel.rowCount() > 0)
                )
                onClicked: {
                    var tileSize = parseInt(preprocessForm.selectedTileSize)
                    if (Preprocess.inputMode === "single") {
                        Preprocess.startPreprocess(tileSize)
                    } else {
                        Preprocess.startBatchPreprocess(tileSize)
                    }
                }
            }

            ThemedButton {
                text: "Cancel"
                variant: "danger"
                buttonSize: "large"
                implicitWidth: 100
                visible: Preprocess.isProcessing
                onClicked: Preprocess.cancelPreprocess()
            }
        }

        // Single file result
        PreprocessResult {
            mode: "single"
            shouldShow: Preprocess.inputMode === "single" && Preprocess.resultPath !== ""
            resultPath: Preprocess.resultPath
            onOpenResult: (path) => root.openResult(path)
        }

        // Batch complete summary
        PreprocessResult {
            mode: "batch"
            shouldShow: Preprocess.batchComplete
            processedCount: Preprocess.processedCount
            skippedCount: Preprocess.skippedCount
            errorCount: Preprocess.errorCount
            firstResultPath: Preprocess.firstResultPath
            onOpenResult: (path) => root.openResult(path)
            onResetBatch: Preprocess.resetBatch()
        }

        Item { Layout.fillHeight: true }
    }
}
