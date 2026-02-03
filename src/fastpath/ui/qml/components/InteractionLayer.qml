import QtQuick

Item {
    id: root

    // Current interaction mode: "none", "draw", "roi", "measure"
    property string mode: "none"

    // Slide coordinate context (set by SlideViewer)
    property real slideScale: 1.0
    property real contentX: 0
    property real contentY: 0

    // Signals for each mode to emit results
    signal drawingFinished(string toolType, var coordinates)
    signal roiSelected(rect region)
    signal measurementFinished(var points, real distance)

    // Feature branches extend this component to handle their modes.
    // Each branch adds mouse handling and visual feedback for its mode(s),
    // keeping additions in separate code sections for clean merges.
}
