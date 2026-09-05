import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    Four corner brackets that acquire a region, arriving from depth.

    Implements the reference design's context-awareness behaviour
    (docs/RESEARCH.md, D13): the interface first \e brackets the object of
    interest and only then attaches information, and reticles "expand and
    arrive from different depths" rather than simply fading in.

    Depth is simulated by scale: the brackets start oversized and converge onto
    the target box. That is a 2D approximation - there is no real Z axis here -
    which is the honest way to get the read on a flat monitor without pulling
    in Qt Quick 3D.

    Set \l acquired true to run the acquisition; the \l locked flag reports when
    the convergence has finished, which is the cue for a caller to reveal its
    annotation.
*/
Item {
    id: root

    /*! Drives acquisition. Set false to retract the brackets. */
    property bool acquired: false
    /*! Bracket stroke colour. */
    property color color: Theme.primary
    /*! Arm length of each corner bracket, in pixels. */
    property real armLength: 22
    /*! Scale the brackets start from, expressing distance from the viewer. */
    property real approachScale: 1.6

    /*! True once the brackets have finished converging. Read by tests. */
    readonly property bool locked: root.acquired && root._progress >= 1.0

    /*! 0.0 = fully distant, 1.0 = locked onto the target. Read by tests. */
    property real _progress: 0

    Behavior on _progress {
        NumberAnimation {
            duration: Theme.durationNormal
            easing.type: Easing.OutBack
        }
    }

    onAcquiredChanged: root._progress = root.acquired ? 1 : 0

    opacity: root._progress

    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer

        // A single Shape holding all four brackets: path geometry is
        // triangulated on the CPU, so fewer Shape items is materially cheaper
        // than one per corner.
        scale: root.approachScale + (1 - root.approachScale) * root._progress
        transformOrigin: Item.Center

        ShapePath {
            strokeColor: root.color
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: 0
            startY: root.armLength
            PathLine { x: 0; y: 0 }
            PathLine { x: root.armLength; y: 0 }
        }

        ShapePath {
            strokeColor: root.color
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.width - root.armLength
            startY: 0
            PathLine { x: root.width; y: 0 }
            PathLine { x: root.width; y: root.armLength }
        }

        ShapePath {
            strokeColor: root.color
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.width
            startY: root.height - root.armLength
            PathLine { x: root.width; y: root.height }
            PathLine { x: root.width - root.armLength; y: root.height }
        }

        ShapePath {
            strokeColor: root.color
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.armLength
            startY: root.height
            PathLine { x: 0; y: root.height }
            PathLine { x: 0; y: root.height - root.armLength }
        }
    }
}
