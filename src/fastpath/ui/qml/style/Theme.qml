pragma Singleton
import QtQuick

QtObject {
    // Colors - Dark theme
    readonly property color background: "#1e1e1e"
    readonly property color backgroundLight: "#252526"
    readonly property color backgroundDark: "#161616"
    readonly property color surface: "#2d2d30"
    readonly property color surfaceHover: "#3e3e42"
    readonly property color surfaceActive: "#094771"

    readonly property color primary: "#0078d4"
    readonly property color primaryHover: "#1a8ad4"
    readonly property color primaryActive: "#006cbe"

    readonly property color text: "#cccccc"
    readonly property color textMuted: "#808080"
    readonly property color textBright: "#ffffff"

    readonly property color border: "#3c3c3c"
    readonly property color borderFocus: "#007acc"

    readonly property color error: "#f44747"
    readonly property color warning: "#ff8c00"
    readonly property color success: "#4ec9b0"

    // Status color variants
    readonly property color errorBackground: Qt.rgba(error.r, error.g, error.b, 0.24)
    readonly property color dangerHover: "#d32f2f"

    // Button sizes
    readonly property int buttonHeightSmall: 28
    readonly property int buttonHeightNormal: 36
    readonly property int buttonHeightLarge: 40

    // Annotation colors
    readonly property var annotationColors: [
        "#ff6b6b",  // Red
        "#4ecdc4",  // Teal
        "#45b7d1",  // Blue
        "#96ceb4",  // Green
        "#ffeaa7",  // Yellow
        "#dfe6e9",  // Gray
        "#fd79a8",  // Pink
        "#a29bfe",  // Purple
    ]

    // Typography
    readonly property int fontSizeSmall: 11
    readonly property int fontSizeNormal: 13
    readonly property int fontSizeLarge: 16
    readonly property int fontSizeTitle: 20

    readonly property string fontFamily: "Segoe UI, system-ui, sans-serif"

    // Spacing
    readonly property int spacingTiny: 2
    readonly property int spacingSmall: 4
    readonly property int spacingNormal: 8
    readonly property int spacingLarge: 16
    readonly property int spacingXLarge: 24

    // Border radius
    readonly property int radiusSmall: 2
    readonly property int radiusNormal: 4
    readonly property int radiusLarge: 8

    // Animation
    readonly property int animationFast: 100
    readonly property int animationNormal: 200
    readonly property int animationSlow: 300

    // Overlay
    readonly property color overlayBackground: Qt.rgba(0, 0, 0, 0.7)

    // Viewer
    readonly property color viewerBackground: "#2a2a2a"
    readonly property color tileBackground: "#333333"
    readonly property real minScale: 0.01
    readonly property real maxScale: 1.2

    // Cell type colors (for AI plugin annotation groups)
    readonly property var cellTypeColors: ({
        "tumor": "#ff6b6b",
        "stroma": "#4ecdc4",
        "immune": "#45b7d1",
        "necrosis": "#96ceb4",
        "normal": "#ffeaa7",
        "other": "#dfe6e9"
    })
}
