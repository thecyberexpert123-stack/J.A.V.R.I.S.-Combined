import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    Four L-shaped brackets marking the corners of a region.

    A full rectangular border encloses and separates; brackets imply a frame
    without drawing one, which keeps the display feeling like an overlay on the
    world rather than a window sitting on top of it. This is the single most
    recognisable structural motif in the reference material.

    The brackets are deliberately \e not symmetrical in weight with the content
    they surround: they are dim by default and brighten only when the region
    they mark becomes relevant, so they frame without competing (D18).
*/
Item {
    id: root

    /*! Arm length of each bracket, in pixels. */
    property real armLength: 26

    /*! Stroke colour. */
    property color color: Theme.primaryDim

    /*! Stroke thickness. */
    property real thickness: Theme.strokeMedium

    /*!
        Inset from the item's own bounds. Positive values pull the brackets
        inward, which is usually what you want when filling a parent.
    */
    property real inset: 0

    /*!
        Which corners to draw. Omitting a corner is how a bracket set marks a
        region that runs off the edge of the display.
    */
    property bool topLeft: true
    property bool topRight: true
    property bool bottomLeft: true
    property bool bottomRight: true

    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer

        // One ShapePath per corner rather than one path with jumps: a single
        // path would draw connecting lines between the corners.

        ShapePath {
            strokeColor: root.topLeft ? root.color : "transparent"
            strokeWidth: root.thickness
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.inset
            startY: root.inset + root.armLength
            PathLine { x: root.inset; y: root.inset }
            PathLine { x: root.inset + root.armLength; y: root.inset }
        }

        ShapePath {
            strokeColor: root.topRight ? root.color : "transparent"
            strokeWidth: root.thickness
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.width - root.inset - root.armLength
            startY: root.inset
            PathLine { x: root.width - root.inset; y: root.inset }
            PathLine { x: root.width - root.inset; y: root.inset + root.armLength }
        }

        ShapePath {
            strokeColor: root.bottomRight ? root.color : "transparent"
            strokeWidth: root.thickness
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.width - root.inset
            startY: root.height - root.inset - root.armLength
            PathLine { x: root.width - root.inset; y: root.height - root.inset }
            PathLine {
                x: root.width - root.inset - root.armLength
                y: root.height - root.inset
            }
        }

        ShapePath {
            strokeColor: root.bottomLeft ? root.color : "transparent"
            strokeWidth: root.thickness
            fillColor: "transparent"
            capStyle: ShapePath.FlatCap
            joinStyle: ShapePath.MiterJoin

            startX: root.inset + root.armLength
            startY: root.height - root.inset
            PathLine { x: root.inset; y: root.height - root.inset }
            PathLine { x: root.inset; y: root.height - root.inset - root.armLength }
        }
    }
}
