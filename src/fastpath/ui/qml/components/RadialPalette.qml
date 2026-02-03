import QtQuick
import "../style"

Item {
    id: root

    // Public properties
    property var items: []  // [{label, color}]
    property string annotationId: ""
    property bool active: false

    // Signals
    signal labelSelected(string label, string color)
    signal cancelled()

    // Geometry
    readonly property real outerRadius: 80
    readonly property real innerRadius: 30
    property int hoveredIndex: -1

    function updateHoveredIndex(mx, my) {
        if (items.length === 0) { hoveredIndex = -1; return }
        let dx = mx - outerRadius
        let dy = my - outerRadius
        let dist = Math.sqrt(dx * dx + dy * dy)
        if (dist < innerRadius || dist > outerRadius) { hoveredIndex = -1; return }
        let angle = Math.atan2(dy, dx)
        if (angle < 0) angle += 2 * Math.PI
        let segmentAngle = 2 * Math.PI / items.length
        hoveredIndex = Math.floor(angle / segmentAngle)
    }

    visible: active
    width: outerRadius * 2
    height: outerRadius * 2

    // Show at screen position
    function show(screenX, screenY, annId) {
        root.x = screenX - outerRadius
        root.y = screenY - outerRadius
        root.annotationId = annId
        root.active = true
        root.forceActiveFocus()
    }

    function hide() {
        root.active = false
        root.annotationId = ""
    }

    Keys.onEscapePressed: {
        hide()
        cancelled()
    }

    // Arc segments
    Canvas {
        id: canvas
        anchors.fill: parent

        onPaint: {
            let ctx = getContext("2d")
            ctx.clearRect(0, 0, width, height)
            let cx = width / 2
            let cy = height / 2
            let n = root.items.length
            if (n === 0) return
            let segmentAngle = 2 * Math.PI / n

            for (let i = 0; i < n; i++) {
                let startAngle = i * segmentAngle
                let endAngle = (i + 1) * segmentAngle
                let isHovered = (root.hoveredIndex === i)

                ctx.beginPath()
                ctx.arc(cx, cy, root.outerRadius - 2, startAngle, endAngle)
                ctx.arc(cx, cy, root.innerRadius, endAngle, startAngle, true)
                ctx.closePath()

                ctx.fillStyle = root.items[i].color
                ctx.globalAlpha = isHovered ? 1.0 : 0.7
                ctx.fill()

                // Segment border
                ctx.globalAlpha = 1.0
                ctx.strokeStyle = isHovered ? "#ffffff" : "rgba(0,0,0,0.3)"
                ctx.lineWidth = isHovered ? 2 : 1
                ctx.stroke()
            }
        }
    }

    // Force repaint when hover changes
    onHoveredIndexChanged: canvas.requestPaint()
    onItemsChanged: canvas.requestPaint()
    onActiveChanged: {
        if (active) canvas.requestPaint()
    }

    // Center label display
    Rectangle {
        anchors.centerIn: parent
        width: root.innerRadius * 2 - 4
        height: root.innerRadius * 2 - 4
        radius: width / 2
        color: Theme.surface
        border.color: Theme.border

        Text {
            anchors.centerIn: parent
            width: parent.width - 4
            text: root.hoveredIndex >= 0 && root.hoveredIndex < root.items.length
                  ? root.items[root.hoveredIndex].label
                  : ""
            color: Theme.text
            font.pixelSize: Theme.fontSizeSmall
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.Wrap
        }
    }

    MouseArea {
        id: mouseArea
        anchors.fill: parent
        hoverEnabled: true

        onPositionChanged: root.updateHoveredIndex(mouseX, mouseY)
        onExited: root.hoveredIndex = -1

        onClicked: {
            if (root.hoveredIndex >= 0 && root.hoveredIndex < root.items.length) {
                let item = root.items[root.hoveredIndex]
                root.labelSelected(item.label, item.color)
            } else {
                hide()
                cancelled()
            }
        }
    }
}
