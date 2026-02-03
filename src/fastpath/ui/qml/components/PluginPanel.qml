import QtQuick
import QtQuick.Layouts
import QtQuick.Controls
import "../style"

ThemedGroupBox {
    id: root
    title: "Plugins"

    // State
    property var selectedRegion: null
    property bool isProcessing: false
    property var resultAnnotationIds: []
    property var resultBreakdown: ({})
    property int resultTotal: 0

    // Signals
    signal roiSelectionRequested()

    function addAnnotationsFromResult(annotations) {
        if (!annotations || !annotations.length) return
        let ids = []
        let breakdown = {}
        for (let i = 0; i < annotations.length; i++) {
            let feat = annotations[i]
            if (!feat || !feat.geometry || !feat.geometry.coordinates) continue
            let props = feat.properties || {}
            let label = props.label || "Unknown"
            let color = props.color || Theme.cellTypeColors[label] || "#808080"
            let coords = feat.geometry.coordinates
            let type = feat.geometry.type
            let annId = AnnotationManager.addAnnotation(type, coords, label, color)
            if (!annId) continue
            ids.push(annId)
            if (!breakdown[label]) breakdown[label] = 0
            breakdown[label]++
        }
        root.resultAnnotationIds = ids
        root.resultBreakdown = breakdown
        root.resultTotal = ids.length
    }

    function clearPluginAnnotations() {
        for (let i = 0; i < resultAnnotationIds.length; i++) {
            AnnotationManager.removeAnnotation(resultAnnotationIds[i])
        }
        resultAnnotationIds = []
        resultBreakdown = {}
        resultTotal = 0
    }

    function refreshPluginList() {
        let all = PluginManager.getPluginList()
        let filtered = []
        for (let i = 0; i < all.length; i++) {
            if (all[i].outputTypes && all[i].outputTypes.indexOf("annotations") >= 0)
                filtered.push(all[i])
        }
        pluginCombo.model = filtered
    }

    Component.onCompleted: refreshPluginList()

    Connections {
        target: PluginManager

        function onProcessingStarted() {
            root.isProcessing = true
        }

        function onProcessingProgress(value) {
            progressBar.value = value / 100.0
        }

        function onProcessingFinished(result) {
            root.isProcessing = false
            progressBar.value = 0
            if (result.success && result.outputType === "annotations" && result.annotations) {
                root.addAnnotationsFromResult(result.annotations)
            }
        }

        function onProcessingError(message) {
            root.isProcessing = false
            progressBar.value = 0
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: Theme.spacingSmall

        // Plugin selector
        ThemedComboBox {
            id: pluginCombo
            Layout.fillWidth: true
            textRole: "name"
            enabled: !root.isProcessing
        }

        // Region display
        Rectangle {
            Layout.fillWidth: true
            height: 28
            color: Theme.backgroundLight
            radius: Theme.radiusSmall
            border.color: Theme.border

            Label {
                anchors.centerIn: parent
                text: root.selectedRegion
                      ? root.selectedRegion.width.toFixed(0) + " x " + root.selectedRegion.height.toFixed(0) + " px"
                      : "No region selected"
                color: root.selectedRegion ? Theme.text : Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
            }
        }

        // ROI + Run buttons
        RowLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingSmall

            ThemedButton {
                text: "Select ROI"
                buttonSize: "small"
                Layout.fillWidth: true
                enabled: !root.isProcessing
                onClicked: root.roiSelectionRequested()
            }

            ThemedButton {
                text: "Run"
                variant: "primary"
                buttonSize: "small"
                Layout.fillWidth: true
                enabled: !root.isProcessing && root.selectedRegion !== null
                         && pluginCombo.model && pluginCombo.currentIndex >= 0
                         && pluginCombo.currentIndex < pluginCombo.model.length
                onClicked: {
                    let plugin = pluginCombo.model[pluginCombo.currentIndex]
                    if (!plugin) return
                    let r = root.selectedRegion
                    PluginManager.processRegion(
                        plugin.name, App.currentPath,
                        r.x, r.y, r.width, r.height,
                        SlideManager.mpp
                    )
                }
            }
        }

        // Progress bar
        ThemedProgressBar {
            id: progressBar
            Layout.fillWidth: true
            visible: root.isProcessing
            from: 0
            to: 1
            value: 0
        }

        // Results section
        ColumnLayout {
            Layout.fillWidth: true
            spacing: Theme.spacingTiny
            visible: root.resultTotal > 0

            Rectangle {
                Layout.fillWidth: true
                height: 1
                color: Theme.border
            }

            Label {
                text: "Results: " + root.resultTotal + " annotations"
                color: Theme.text
                font.pixelSize: Theme.fontSizeSmall
                font.bold: true
            }

            Repeater {
                model: Object.keys(root.resultBreakdown)

                RowLayout {
                    Layout.fillWidth: true
                    spacing: Theme.spacingSmall

                    required property string modelData

                    Rectangle {
                        width: 10
                        height: 10
                        radius: 5
                        color: Theme.cellTypeColors[modelData] || "#808080"
                    }

                    Label {
                        text: modelData
                        color: Theme.text
                        font.pixelSize: Theme.fontSizeSmall
                        Layout.fillWidth: true
                    }

                    Label {
                        text: root.resultBreakdown[modelData]
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeSmall
                    }
                }
            }

            ThemedButton {
                text: "Clear Results"
                buttonSize: "small"
                variant: "outline"
                Layout.fillWidth: true
                onClicked: root.clearPluginAnnotations()
            }
        }
    }
}
