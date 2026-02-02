import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import "../style"

Rectangle {
    id: root

    property string mode: "single"  // "single" | "batch"
    property bool shouldShow: false

    // Single mode properties
    property string resultPath: ""

    // Batch mode properties
    property int processedCount: 0
    property int skippedCount: 0
    property int errorCount: 0
    property string firstResultPath: ""

    signal openResult(string path)
    signal resetBatch()

    Layout.fillWidth: true
    Layout.preferredHeight: contentLayout.implicitHeight + Theme.spacingLarge * 2
    color: Theme.surface
    radius: Theme.radiusNormal
    border.color: Theme.primary
    border.width: 2
    visible: shouldShow

    ColumnLayout {
        id: contentLayout
        anchors.fill: parent
        anchors.margins: Theme.spacingLarge
        spacing: Theme.spacingSmall

        Label {
            text: mode === "single" ? "Preprocessing Complete!" : "Batch Complete!"
            color: Theme.primary
            font.pixelSize: Theme.fontSizeLarge
            font.bold: true
        }

        // Single mode: output path
        Label {
            text: "Output: " + root.resultPath
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            elide: Text.ElideMiddle
            Layout.fillWidth: true
            visible: mode === "single"
        }

        // Batch mode: separator
        Rectangle {
            Layout.fillWidth: true
            height: 1
            color: Theme.border
            visible: mode === "batch"
        }

        // Batch mode: summary stats
        GridLayout {
            columns: 2
            rowSpacing: Theme.spacingSmall
            columnSpacing: Theme.spacingLarge
            visible: mode === "batch"

            Label {
                text: root.processedCount + " processed successfully"
                color: Theme.success
                font.pixelSize: Theme.fontSizeNormal
            }
            Item { Layout.fillWidth: true }

            Label {
                text: root.skippedCount + " skipped (already exist)"
                color: Theme.warning
                font.pixelSize: Theme.fontSizeNormal
                visible: root.skippedCount > 0
            }
            Item { Layout.fillWidth: true; visible: root.skippedCount > 0 }

            Label {
                text: root.errorCount + " failed"
                color: Theme.error
                font.pixelSize: Theme.fontSizeNormal
                visible: root.errorCount > 0
            }
            Item { Layout.fillWidth: true; visible: root.errorCount > 0 }
        }

        // Action buttons
        RowLayout {
            Layout.topMargin: mode === "batch" ? Theme.spacingNormal : Theme.spacingSmall
            spacing: Theme.spacingNormal

            ThemedButton {
                text: mode === "single" ? "Open in Viewer" : "Open First Result"
                variant: "primary"
                implicitWidth: 150
                visible: mode === "single" || root.firstResultPath !== ""
                onClicked: root.openResult(mode === "single" ? root.resultPath : root.firstResultPath)
            }

            ThemedButton {
                text: "Process More"
                visible: mode === "batch"
                implicitWidth: 120
                onClicked: root.resetBatch()
            }
        }
    }
}
