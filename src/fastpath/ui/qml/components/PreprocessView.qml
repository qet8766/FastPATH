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

                // Input selection (Single File mode)
                Label {
                    text: "Input File"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    visible: Preprocess.inputMode === "single"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall
                    visible: Preprocess.inputMode === "single"

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

                // Input selection (Folder mode)
                Label {
                    text: "Input Folder"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    visible: Preprocess.inputMode === "folder"
                }

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall
                    visible: Preprocess.inputMode === "folder"

                    TextField {
                        id: inputFolderField
                        Layout.fillWidth: true
                        text: Preprocess.inputFolder
                        placeholderText: "Select a folder containing WSI files"
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
                        enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
                        onClicked: inputFolderDialog.open()

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
                        enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
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
                            ListElement { text: "Level 0 -> 20x"; value: "level0_resized" }
                        }
                        textRole: "text"
                        enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
                        Layout.fillWidth: true

                        property string selectedValue: model.get(currentIndex).value

                        Component.onCompleted: {
                            currentIndex = Settings.lastMethod === "level0_resized" ? 1 : 0
                        }

                        onActivated: {
                            Settings.lastMethod = selectedValue
                        }

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
                        enabled: !Preprocess.isProcessing && !Preprocess.batchComplete

                        Component.onCompleted: {
                            currentIndex = Settings.lastTileSize === 256 ? 0 : (Settings.lastTileSize === 1024 ? 2 : 1)
                        }

                        onActivated: {
                            Settings.lastTileSize = parseInt(currentText)
                        }

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
                            stepSize: 1
                            enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
                            Layout.preferredWidth: 150

                            Component.onCompleted: {
                                value = Settings.lastQuality
                            }

                            onMoved: {
                                Settings.lastQuality = value
                            }
                        }
                        Label {
                            text: qualitySlider.value.toFixed(0)
                            color: Theme.textMuted
                            Layout.preferredWidth: 30
                        }
                    }

                    // Parallel workers (folder mode only)
                    Label {
                        text: "Parallel Workers"
                        color: Theme.text
                        visible: Preprocess.inputMode === "folder"
                    }
                    ComboBox {
                        id: workersCombo
                        model: ["1", "2", "3", "4", "5", "6", "7", "8"]
                        enabled: !Preprocess.isProcessing && !Preprocess.batchComplete
                        visible: Preprocess.inputMode === "folder"

                        Component.onCompleted: {
                            currentIndex = Settings.parallelWorkers - 1
                        }

                        onActivated: {
                            var workers = currentIndex + 1
                            Settings.parallelWorkers = workers
                            Preprocess.setParallelWorkers(workers)
                        }

                        background: Rectangle {
                            color: Theme.backgroundLight
                            radius: Theme.radiusSmall
                            border.color: Theme.border
                        }
                        contentItem: Text {
                            text: workersCombo.displayText
                            color: Theme.text
                            verticalAlignment: Text.AlignVCenter
                            leftPadding: Theme.spacingSmall
                        }
                    }
                }

                // Force rebuild checkbox
                CheckBox {
                    id: forceCheckbox
                    text: "Force rebuild (ignore existing)"
                    enabled: !Preprocess.isProcessing && !Preprocess.batchComplete

                    Component.onCompleted: {
                        checked = Preprocess.force
                    }

                    onToggled: Preprocess.setForce(checked)

                    contentItem: Text {
                        text: parent.text
                        color: Theme.text
                        leftPadding: parent.indicator.width + parent.spacing
                        verticalAlignment: Text.AlignVCenter
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

                // Error message
                Rectangle {
                    Layout.fillWidth: true
                    Layout.preferredHeight: errorLabel.implicitHeight + Theme.spacingNormal
                    color: "#3de74c3c"
                    radius: Theme.radiusSmall
                    border.color: "#e74c3c"
                    visible: errorMessage !== ""

                    Label {
                        id: errorLabel
                        anchors.centerIn: parent
                        width: parent.width - Theme.spacingNormal * 2
                        text: errorMessage
                        color: "#e74c3c"
                        font.pixelSize: Theme.fontSizeSmall
                        wrapMode: Text.WordWrap
                        horizontalAlignment: Text.AlignHCenter
                    }
                }
            }
        }

        // File list (folder mode only)
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 150
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.border
            visible: Preprocess.inputMode === "folder" && Preprocess.fileListModel.rowCount() > 0

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacingNormal
                spacing: Theme.spacingSmall

                Label {
                    text: "Files to Process (" + Preprocess.fileListModel.rowCount() + ")"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    font.bold: true
                }

                ListView {
                    id: fileListView
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: Preprocess.fileListModel

                    delegate: Rectangle {
                        width: fileListView.width
                        height: 36
                        color: index % 2 === 0 ? "transparent" : Qt.rgba(255, 255, 255, 0.02)

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: Theme.spacingSmall
                            anchors.rightMargin: Theme.spacingSmall
                            spacing: Theme.spacingSmall

                            // Status icon
                            Label {
                                text: {
                                    switch(model.status) {
                                        case "pending": return "○"
                                        case "processing": return "⟳"
                                        case "done": return "✓"
                                        case "skipped": return "⊘"
                                        case "error": return "✕"
                                        default: return "○"
                                    }
                                }
                                color: {
                                    switch(model.status) {
                                        case "pending": return Theme.textMuted
                                        case "processing": return Theme.primary
                                        case "done": return "#27ae60"
                                        case "skipped": return "#f39c12"
                                        case "error": return "#e74c3c"
                                        default: return Theme.textMuted
                                    }
                                }
                                font.pixelSize: Theme.fontSizeLarge
                                Layout.preferredWidth: 24
                            }

                            // File name
                            Label {
                                text: model.fileName
                                color: Theme.text
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }

                            // Progress bar or status text
                            Item {
                                Layout.preferredWidth: 100
                                Layout.preferredHeight: 20

                                ProgressBar {
                                    id: fileProgressBar
                                    anchors.fill: parent
                                    value: model.progress
                                    visible: model.status === "processing"

                                    background: Rectangle {
                                        color: Theme.backgroundLight
                                        radius: Theme.radiusSmall
                                    }

                                    contentItem: Item {
                                        Rectangle {
                                            width: parent.width * fileProgressBar.visualPosition
                                            height: parent.height
                                            radius: Theme.radiusSmall
                                            color: Theme.primary
                                        }
                                    }
                                }

                                Label {
                                    anchors.centerIn: parent
                                    text: {
                                        switch(model.status) {
                                            case "done": return "Done"
                                            case "skipped": return "Skipped"
                                            case "error": return "Error"
                                            default: return ""
                                        }
                                    }
                                    color: {
                                        switch(model.status) {
                                            case "done": return "#27ae60"
                                            case "skipped": return "#f39c12"
                                            case "error": return "#e74c3c"
                                            default: return Theme.textMuted
                                        }
                                    }
                                    font.pixelSize: Theme.fontSizeSmall
                                    visible: model.status !== "processing" && model.status !== "pending"
                                }
                            }
                        }
                    }

                    ScrollBar.vertical: ScrollBar {
                        active: true
                    }
                }
            }
        }

        // Single file progress section
        Rectangle {
            id: singleProgressSection
            property bool shouldShow: Preprocess.inputMode === "single" && (Preprocess.isProcessing || Preprocess.progress > 0)
            Layout.fillWidth: true
            Layout.preferredHeight: shouldShow ? 100 : 0
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.border
            visible: shouldShow
            clip: true

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
                    id: singleProgressBar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 20
                    value: Preprocess.progress

                    background: Rectangle {
                        implicitHeight: 20
                        color: Theme.backgroundLight
                        radius: Theme.radiusSmall
                    }

                    contentItem: Item {
                        implicitHeight: 20
                        Rectangle {
                            width: parent.width * singleProgressBar.visualPosition
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

        // Batch overall progress section
        Rectangle {
            id: batchProgressSection
            property bool shouldShow: Preprocess.inputMode === "folder" && Preprocess.isProcessing
            Layout.fillWidth: true
            Layout.preferredHeight: shouldShow ? 100 : 0
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.border
            visible: shouldShow
            clip: true

            ColumnLayout {
                id: batchProgressLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingLarge
                spacing: Theme.spacingSmall

                Label {
                    text: "Overall Progress"
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    font.bold: true
                }

                ProgressBar {
                    id: batchProgressBar
                    Layout.fillWidth: true
                    Layout.preferredHeight: 20
                    value: Preprocess.overallProgress

                    background: Rectangle {
                        implicitHeight: 20
                        color: Theme.backgroundLight
                        radius: Theme.radiusSmall
                    }

                    contentItem: Item {
                        implicitHeight: 20
                        Rectangle {
                            width: parent.width * batchProgressBar.visualPosition
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
            visible: !Preprocess.batchComplete

            Button {
                text: Preprocess.isProcessing ? "Processing..." : "Start Preprocessing"
                enabled: !Preprocess.isProcessing && (
                    (Preprocess.inputMode === "single" && Preprocess.inputFile !== "") ||
                    (Preprocess.inputMode === "folder" && Preprocess.fileListModel.rowCount() > 0)
                )
                onClicked: {
                    var tileSize = parseInt(tileSizeCombo.currentText)
                    var quality = qualitySlider.value
                    var method = methodCombo.selectedValue

                    if (Preprocess.inputMode === "single") {
                        Preprocess.startPreprocess(tileSize, quality, method)
                    } else {
                        Preprocess.startBatchPreprocess(tileSize, quality, method)
                    }
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

        // Single file result section
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: resultLayout.implicitHeight + Theme.spacingLarge * 2
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.primary
            border.width: 2
            visible: Preprocess.inputMode === "single" && Preprocess.resultPath !== ""

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

        // Batch complete summary section
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: summaryLayout.implicitHeight + Theme.spacingLarge * 2
            color: Theme.surface
            radius: Theme.radiusNormal
            border.color: Theme.primary
            border.width: 2
            visible: Preprocess.batchComplete

            ColumnLayout {
                id: summaryLayout
                anchors.fill: parent
                anchors.margins: Theme.spacingLarge
                spacing: Theme.spacingSmall

                Label {
                    text: "Batch Complete!"
                    color: Theme.primary
                    font.pixelSize: Theme.fontSizeLarge
                    font.bold: true
                }

                Rectangle {
                    Layout.fillWidth: true
                    height: 1
                    color: Theme.border
                }

                // Summary stats
                GridLayout {
                    columns: 2
                    rowSpacing: Theme.spacingSmall
                    columnSpacing: Theme.spacingLarge

                    Label {
                        text: Preprocess.processedCount + " processed successfully"
                        color: "#27ae60"
                        font.pixelSize: Theme.fontSizeNormal
                    }
                    Item { Layout.fillWidth: true }

                    Label {
                        text: Preprocess.skippedCount + " skipped (already exist)"
                        color: "#f39c12"
                        font.pixelSize: Theme.fontSizeNormal
                        visible: Preprocess.skippedCount > 0
                    }
                    Item { Layout.fillWidth: true; visible: Preprocess.skippedCount > 0 }

                    Label {
                        text: Preprocess.errorCount + " failed"
                        color: "#e74c3c"
                        font.pixelSize: Theme.fontSizeNormal
                        visible: Preprocess.errorCount > 0
                    }
                    Item { Layout.fillWidth: true; visible: Preprocess.errorCount > 0 }
                }

                // Action buttons
                RowLayout {
                    Layout.topMargin: Theme.spacingNormal
                    spacing: Theme.spacingNormal

                    Button {
                        text: "Open First Result"
                        visible: Preprocess.firstResultPath !== ""
                        onClicked: root.openResult(Preprocess.firstResultPath)

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

                    Button {
                        text: "Process More"
                        onClicked: Preprocess.resetBatch()

                        background: Rectangle {
                            color: parent.hovered ? Theme.surfaceHover : Theme.surface
                            radius: Theme.radiusNormal
                            border.color: Theme.border
                            implicitWidth: 120
                            implicitHeight: 36
                        }

                        contentItem: Text {
                            text: parent.text
                            color: Theme.text
                            horizontalAlignment: Text.AlignHCenter
                            verticalAlignment: Text.AlignVCenter
                        }
                    }
                }
            }
        }

        Item { Layout.fillHeight: true }
    }
}
