pragma ComponentBehavior: Bound

import QtQuick
import javris.ui

/*!
    The background field: a faint grid with a slow vertical scan line.

    Drawn with Repeater over thin Rectangles rather than a shader, for the
    reason given in ReactorCore.qml. Line count is bounded by spacing so the
    item cost stays proportional to window size, not to zoom level.
*/
Item {
    id: root

    /*! Distance between grid lines, in pixels. */
    property int cellSize: 44
    /*! Whether the scan line sweeps. Disabled during boot. */
    property bool scanning: true

    readonly property int _columns: Math.max(0, Math.ceil(width / cellSize))
    readonly property int _rows: Math.max(0, Math.ceil(height / cellSize))

    Repeater {
        model: root._columns
        delegate: Rectangle {
            required property int index
            x: index * root.cellSize
            width: Theme.strokeThin
            height: root.height
            color: Theme.grid
            opacity: 0.55
        }
    }

    Repeater {
        model: root._rows
        delegate: Rectangle {
            required property int index
            y: index * root.cellSize
            width: root.width
            height: Theme.strokeThin
            color: Theme.grid
            opacity: 0.55
        }
    }

    Rectangle {
        id: scanLine
        width: root.width
        height: 2
        visible: root.scanning
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.5; color: Theme.primaryDim }
            GradientStop { position: 1.0; color: "transparent" }
        }
        opacity: 0.35

        NumberAnimation on y {
            running: root.scanning && root.height > 0
            from: 0
            to: root.height
            duration: 7000
            loops: Animation.Infinite
        }
    }
}
