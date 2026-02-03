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
        let suffix = IsDebugBuild ? " [DEBUG BUILD]" : ""
        if (preprocessMode) {
            return "FastPATH - Preprocess" + suffix
        } else if (SlideManager.isLoaded) {
            return SlideManager.sourceFile + " - FastPATH" + suffix
        }
        return "FastPATH" + suffix
    }
    color: Theme.background

    // Mode: false = viewer, true = preprocess
    property bool preprocessMode: false

    function restoreInteractionMode(tool) {
        if (tool === "pan") {
            viewer.interactionMode = "none"
        } else if (tool === "measure") {
            viewer.interactionMode = "measure"
        } else {
            viewer.interactionMode = "draw"
        }
    }

    Component.onCompleted: {
        restoreInteractionMode(Settings.annotationTool)
    }

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
                text: qsTr("Open &Project...")
                shortcut: "Ctrl+Shift+O"
                enabled: !preprocessMode
                onTriggered: projectOpenDialog.open()
            }

            Action {
                text: qsTr("&Save Project")
                shortcut: StandardKey.Save
                enabled: SlideManager.isLoaded && !preprocessMode
                onTriggered: {
                    if (!App.saveProject()) {
                        projectSaveDialog.open()
                    }
                }
            }

            Action {
                text: qsTr("Save Project &As...")
                shortcut: StandardKey.SaveAs
                enabled: SlideManager.isLoaded && !preprocessMode
                onTriggered: projectSaveDialog.open()
            }

            MenuSeparator {}

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
            title: qsTr("&Annotations")
            enabled: SlideManager.isLoaded && !preprocessMode

            Action {
                text: qsTr("&Export Annotations...")
                shortcut: "Ctrl+E"
                enabled: SlideManager.isLoaded && AnnotationManager.count > 0
                onTriggered: menuExportDialog.open()
            }

            Action {
                text: qsTr("&Import Annotations...")
                shortcut: "Ctrl+I"
                enabled: SlideManager.isLoaded
                onTriggered: menuImportDialog.open()
            }

            MenuSeparator {}

            Action {
                text: qsTr("&Clear All Annotations")
                enabled: SlideManager.isLoaded && AnnotationManager.count > 0
                onTriggered: menuClearConfirmDialog.open()
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
        currentFolder: Settings.lastSlideDirUrl
        onAccepted: {
            App.openSlide(selectedFolder.toString())
        }
    }

    FileDialog {
        id: projectOpenDialog
        title: "Open FastPATH Project"
        nameFilters: ["FastPATH Projects (*.fpproj)", "All Files (*)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            App.openProject(selectedFile.toString())
        }
    }

    FileDialog {
        id: projectSaveDialog
        title: "Save FastPATH Project"
        nameFilters: ["FastPATH Projects (*.fpproj)", "All Files (*)"]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "fpproj"
        onAccepted: {
            App.saveProjectAs(selectedFile.toString())
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

    // Annotation menu dialogs
    FileDialog {
        id: menuExportDialog
        title: "Export Annotations"
        nameFilters: ["GeoJSON Files (*.geojson)", "All Files (*)"]
        fileMode: FileDialog.SaveFile
        defaultSuffix: "geojson"
        onAccepted: {
            AnnotationManager.save(selectedFile.toString())
        }
    }

    FileDialog {
        id: menuImportDialog
        title: "Import Annotations"
        nameFilters: ["GeoJSON Files (*.geojson)", "All Files (*)"]
        fileMode: FileDialog.OpenFile
        onAccepted: {
            AnnotationManager.load(selectedFile.toString())
        }
    }

    Dialog {
        id: menuClearConfirmDialog
        title: "Clear Annotations"
        modal: true
        anchors.centerIn: parent
        width: 300
        standardButtons: Dialog.Ok | Dialog.Cancel

        background: Rectangle {
            color: Theme.surface
            radius: Theme.radiusLarge
            border.color: Theme.border
        }

        Label {
            text: "Remove all " + AnnotationManager.count + " annotations?"
            color: Theme.text
            wrapMode: Text.WordWrap
            width: parent.width
        }

        onAccepted: AnnotationManager.clear()
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

                    // Recent slides
                    ColumnLayout {
                        Layout.alignment: Qt.AlignHCenter
                        spacing: Theme.spacingSmall
                        visible: App.recentFiles.rowCount() > 0

                        Label {
                            text: "Recent"
                            color: Theme.textMuted
                            font.pixelSize: Theme.fontSizeSmall
                            Layout.alignment: Qt.AlignHCenter
                        }

                        Repeater {
                            model: App.recentFiles

                            ThemedButton {
                                required property string fileName
                                required property string filePath
                                text: fileName
                                buttonSize: "normal"
                                implicitWidth: 420
                                onClicked: App.openSlide(filePath)
                            }
                        }

                        ThemedButton {
                            text: "Clear Recent"
                            variant: "outline"
                            buttonSize: "small"
                            implicitWidth: 140
                            onClicked: App.clearRecentSlides()
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
                annotationsVisible: Settings.annotationsVisible
                drawTool: Settings.annotationTool
                drawLabel: annotationTools.currentLabel
                drawColor: annotationTools.currentColor
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

                SlideInfoPanel {
                    Layout.fillWidth: true
                }

                OverviewPanel {
                    Layout.fillWidth: true
                    Layout.preferredHeight: 200
                    viewerViewportX: viewer.viewportX
                    viewerViewportY: viewer.viewportY
                    viewerViewportWidth: viewer.viewportWidth
                    viewerViewportHeight: viewer.viewportHeight
                }

                ViewControlsPanel {
                    Layout.fillWidth: true
                    viewerScale: viewer.scale
                    onFitRequested: viewer.fitToWindow()
                    onResetRequested: viewer.resetView()
                    onZoomRequested: (newScale) => { viewer.scale = newScale }
                }

                NavigationPanel {
                    Layout.fillWidth: true
                    visible: Navigator.hasMultipleSlides
                }

                // Feature branches add new panels here as single lines
                AnnotationPanel {
                    Layout.fillWidth: true
                    annotationsVisible: viewer.annotationsVisible
                    onVisibilityToggled: (visible) => { Settings.annotationsVisible = visible }
                    onExportRequested: menuExportDialog.open()
                    onImportRequested: menuImportDialog.open()
                    onClearRequested: menuClearConfirmDialog.open()
                }

                AnnotationTools {
                    id: annotationTools
                    Layout.fillWidth: true
                    currentTool: Settings.annotationTool
                    onToolChanged: (tool) => {
                        Settings.annotationTool = tool
                        restoreInteractionMode(tool)
                    }
                }

                PluginPanel {
                    id: pluginPanel
                    Layout.fillWidth: true
                }

                AnnotationFilterPanel {
                    id: annotationFilterPanel
                    Layout.fillWidth: true
                }

                Item { Layout.fillHeight: true }
            }
        }

        // Plugin panel ROI wiring
        Connections {
            target: pluginPanel
            function onRoiSelectionRequested() { viewer.interactionMode = "roi" }
        }

        Connections {
            target: viewer
            function onRoiSelected(region) {
                pluginPanel.selectedRegion = {
                    x: region.x, y: region.y,
                    width: region.width, height: region.height
                }
                restoreInteractionMode(Settings.annotationTool)
            }
        }

        Connections {
            target: App
            function onProjectViewStateReady(x, y, scale) {
                viewer.setViewState(x, y, scale)
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

            Rectangle {
                visible: IsDebugBuild
                color: "#cc0000"
                radius: 2
                implicitWidth: debugLabel.implicitWidth + 8
                implicitHeight: debugLabel.implicitHeight + 2
                Layout.alignment: Qt.AlignVCenter

                Label {
                    id: debugLabel
                    anchors.centerIn: parent
                    text: "DEBUG BUILD"
                    color: "#ffffff"
                    font.pixelSize: Theme.fontSizeSmall
                    font.bold: true
                }
            }

            Item { Layout.fillWidth: true }

            Label {
                text: {
                    if (preprocessMode && Preprocess.isProcessing) {
                        return (Preprocess.progress * 100).toFixed(0) + "%"
                    } else if (SlideManager.isLoaded && !preprocessMode) {
                        let info = "Level: " + viewer.currentLevel + " | Tiles: " + App.tileModel.rowCount()
                        if (AnnotationManager.count > 0) {
                            info += " | Annotations: " + AnnotationManager.count
                        }
                        if (viewer.hasMeasurement) {
                            info += " | Measure: " + viewer.lastMeasurementDistance.toFixed(0) + " px"
                        }
                        return info
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
