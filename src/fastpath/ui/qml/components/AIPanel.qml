import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property var pluginManager: null
    property var selectedRegion: null  // {x, y, width, height}
    property bool isProcessing: false

    signal runPlugin(string pluginName)
    signal regionSelectionRequested()

    color: Theme.surface
    radius: Theme.radiusNormal
    border.color: Theme.border

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.spacingSmall
        spacing: Theme.spacingSmall

        // Header
        Label {
            text: "AI Analysis"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
            font.bold: true
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Plugin list
        Label {
            text: "Plugins"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
        }

        ListView {
            id: pluginList
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(contentHeight, 150)
            clip: true
            spacing: 2

            model: root.pluginManager ? root.pluginManager.getPluginList() : []

            delegate: Rectangle {
                width: pluginList.width
                height: 48
                radius: Theme.radiusSmall
                color: pluginMouseArea.containsMouse ? Theme.surfaceHover : "transparent"

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: Theme.spacingSmall
                    spacing: 2

                    Label {
                        text: modelData.name
                        color: Theme.text
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }

                    Label {
                        text: modelData.description
                        color: Theme.textMuted
                        font.pixelSize: Theme.fontSizeSmall
                        elide: Text.ElideRight
                        Layout.fillWidth: true
                    }
                }

                // Loaded indicator
                Rectangle {
                    anchors.right: parent.right
                    anchors.rightMargin: Theme.spacingSmall
                    anchors.verticalCenter: parent.verticalCenter
                    width: 8
                    height: 8
                    radius: 4
                    color: modelData.isLoaded ? Theme.success : Theme.textMuted
                    visible: modelData.isLoaded
                }

                MouseArea {
                    id: pluginMouseArea
                    anchors.fill: parent
                    hoverEnabled: true
                    cursorShape: Qt.PointingHandCursor
                    onClicked: {
                        pluginList.currentIndex = index
                    }
                }
            }

            highlight: Rectangle {
                color: Theme.surfaceActive
                radius: Theme.radiusSmall
            }

            Label {
                visible: pluginList.count === 0
                anchors.centerIn: parent
                text: "No plugins available"
                color: Theme.textMuted
                font.pixelSize: Theme.fontSizeSmall
            }
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Selected region info
        Label {
            text: "Region"
            color: Theme.textMuted
            font.pixelSize: Theme.fontSizeSmall
        }

        Rectangle {
            Layout.fillWidth: true
            height: 50
            radius: Theme.radiusSmall
            color: Theme.backgroundLight
            border.color: Theme.border

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: Theme.spacingSmall
                spacing: 2

                Label {
                    visible: root.selectedRegion !== null
                    text: root.selectedRegion ?
                          `Position: (${root.selectedRegion.x.toFixed(0)}, ${root.selectedRegion.y.toFixed(0)})` :
                          ""
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                }

                Label {
                    visible: root.selectedRegion !== null
                    text: root.selectedRegion ?
                          `Size: ${root.selectedRegion.width.toFixed(0)} × ${root.selectedRegion.height.toFixed(0)}` :
                          ""
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                }

                Label {
                    visible: root.selectedRegion === null
                    text: "No region selected"
                    color: Theme.textMuted
                    font.pixelSize: Theme.fontSizeSmall
                    Layout.alignment: Qt.AlignHCenter | Qt.AlignVCenter
                }
            }
        }

        ThemedButton {
            text: "Select Region"
            buttonSize: "small"
            Layout.fillWidth: true
            onClicked: root.regionSelectionRequested()
        }

        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
        }

        // Run button
        ThemedButton {
            text: root.isProcessing ? "Processing..." : "Run Analysis"
            variant: "primary"
            Layout.fillWidth: true
            enabled: !root.isProcessing &&
                     root.selectedRegion !== null &&
                     pluginList.currentIndex >= 0

            onClicked: {
                if (pluginList.currentIndex >= 0) {
                    let plugin = pluginList.model[pluginList.currentIndex]
                    root.runPlugin(plugin.name)
                }
            }
        }

        // Progress indicator
        ProgressBar {
            Layout.fillWidth: true
            visible: root.isProcessing
            indeterminate: true
        }

        Item { Layout.fillHeight: true }

        // Results section
        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.minimumHeight: 100
            visible: resultText.text !== ""
            radius: Theme.radiusSmall
            color: Theme.backgroundLight
            border.color: Theme.border

            ScrollView {
                anchors.fill: parent
                anchors.margins: Theme.spacingSmall
                clip: true

                TextArea {
                    id: resultText
                    readOnly: true
                    wrapMode: TextEdit.Wrap
                    color: Theme.text
                    font.pixelSize: Theme.fontSizeSmall
                    font.family: "monospace"
                    background: null
                }
            }
        }
    }

    // Handle results from plugin manager
    Connections {
        target: root.pluginManager

        function onProcessingStarted(pluginName) {
            root.isProcessing = true
            resultText.text = `Running ${pluginName}...`
        }

        function onProcessingFinished(result) {
            root.isProcessing = false
            if (result.success) {
                resultText.text = formatResult(result)
            } else {
                resultText.text = `Error: ${result.message}`
            }
        }

        function onProcessingError(error) {
            root.isProcessing = false
            resultText.text = `Error: ${error}`
        }
    }

    function formatResult(result) {
        let text = ""

        if (result.outputType === "classification" && result.classification) {
            let cls = result.classification
            text += `Classification: ${cls.label}\n`
            text += `Confidence: ${(cls.confidence * 100).toFixed(1)}%\n`

            if (cls.probabilities) {
                text += "\nProbabilities:\n"
                for (let label in cls.probabilities) {
                    text += `  ${label}: ${(cls.probabilities[label] * 100).toFixed(1)}%\n`
                }
            }

            if (cls.statistics) {
                text += "\nStatistics:\n"
                text += `  Brightness: ${(cls.statistics.brightness * 100).toFixed(1)}%\n`
                text += `  Saturation: ${(cls.statistics.saturation * 100).toFixed(1)}%\n`
            }
        }

        text += `\nProcessing time: ${(result.processingTime * 1000).toFixed(0)}ms`
        return text
    }

    function clearResults() {
        resultText.text = ""
    }
}
