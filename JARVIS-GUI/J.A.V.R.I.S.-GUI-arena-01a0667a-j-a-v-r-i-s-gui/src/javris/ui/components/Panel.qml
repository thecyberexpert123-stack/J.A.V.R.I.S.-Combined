import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    A framed HUD panel with cut corners and a titled header rule.

    The panel sizes itself to its content by default, so callers do not have to
    compute a height from the very children the panel contains (which would be
    a circular binding). Set an explicit \c height to override.

    The frame is a single Shape containing one ShapePath, following the Qt
    guidance to prefer one Shape with several paths over several Shapes, since
    path geometry is triangulated on the CPU.
*/
Item {
    id: root

    /*! Header label, rendered upper-case with wide tracking. */
    property string title: ""
    /*! Optional right-aligned status text in the header. */
    property string status: ""
    /*! Colour of the status text. */
    property color statusColor: Theme.textSecondary
    /*! Frame stroke colour. */
    property color frameColor: Theme.primaryFaint
    /*! Inner padding around the content. */
    property int padding: Theme.spaceMd
    /*! Where child content is placed. */
    default property alias content: contentArea.data

    readonly property bool hasHeader: title.length > 0
    readonly property int headerHeight: hasHeader
                                        ? headerText.height + Theme.spaceSm + Theme.strokeThin
                                        : 0

    implicitWidth: 260
    implicitHeight: headerHeight
                    + (hasHeader ? Theme.spaceSm : 0)
                    + Math.max(contentArea.childrenRect.height, 0)
                    + padding * 2

    /*!
        Attention light.

        Panels do \e not glow by default. Lighting every frame on screen makes
        the bloom uniform, and a uniform signal carries no information -- it
        just raises the noise floor. A panel emits only when it has something
        to say, which makes the light itself meaningful (D18).
    */
    property bool attention: false

    Item {
        anchors.fill: parent
        clip: true
        z: -1
        visible: root.attention

        Glow {
            anchors.horizontalCenter: parent.horizontalCenter
            anchors.top: parent.top
            anchors.topMargin: -parent.height * 0.55
            size: parent.width * 1.5
            color: root.frameColor
            intensity: Theme.glowSubtle * Theme.glowScale * 0.8

            Behavior on intensity {
                NumberAnimation {
                    duration: Theme.durationSlow; easing.type: Theme.easing
                }
            }
        }
    }

    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            strokeColor: root.frameColor
            strokeWidth: Theme.strokeThin
            // Slightly translucent so the ambient field behind reads through
            // and panels sit *in* the scene rather than on top of it.
            fillColor: Qt.rgba(Theme.panel.r, Theme.panel.g, Theme.panel.b, 0.88)
            joinStyle: ShapePath.MiterJoin

            startX: Theme.cornerCut
            startY: 0
            PathLine { x: root.width;  y: 0 }
            PathLine { x: root.width;  y: root.height - Theme.cornerCut }
            PathLine { x: root.width - Theme.cornerCut; y: root.height }
            PathLine { x: 0; y: root.height }
            PathLine { x: 0; y: Theme.cornerCut }
            PathLine { x: Theme.cornerCut; y: 0 }
        }
    }

    Item {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        anchors.margins: root.padding
        height: root.hasHeader ? headerText.height : 0
        visible: root.hasHeader

        Text {
            id: headerText
            text: root.title.toUpperCase()
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingWide
        }

        Text {
            anchors.right: parent.right
            anchors.baseline: headerText.baseline
            text: root.status
            color: root.statusColor
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingLabel
            visible: root.status.length > 0
        }
    }

    Rectangle {
        id: rule
        anchors { top: header.bottom; left: parent.left; right: parent.right }
        anchors.leftMargin: root.padding
        anchors.rightMargin: root.padding
        anchors.topMargin: root.hasHeader ? Theme.spaceSm : 0
        height: root.hasHeader ? Theme.strokeThin : 0
        color: root.frameColor
        visible: root.hasHeader
    }

    Item {
        id: contentArea
        anchors {
            top: rule.bottom
            left: parent.left
            right: parent.right
            bottom: parent.bottom
        }
        anchors.margins: root.padding
        anchors.topMargin: root.hasHeader ? Theme.spaceSm : root.padding
        clip: true
    }
}
