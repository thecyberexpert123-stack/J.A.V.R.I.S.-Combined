import QtQuick
import javris.ui

/*!
    A deliberate, click-only button used by the consent prompt.

    Kept separate from any general button style because its requirements are
    unusual: it must not accept Enter or Space, and it must not be reachable by
    tab-focus. Consent has to be a considered pointer action, not something a
    keyboard rhythm can complete by accident.
*/
Rectangle {
    id: root

    /*! Button text. */
    property string label: ""

    /*! Border and text colour, and the fill colour on hover. */
    property color accent: Theme.primary

    signal triggered

    implicitWidth: caption.width + Theme.spaceXl
    implicitHeight: caption.height + Theme.spaceMd * 2
    width: implicitWidth
    height: implicitHeight

    color: mouse.containsMouse
           ? Qt.rgba(root.accent.r, root.accent.g, root.accent.b, 0.16)
           : "transparent"
    border.width: Theme.strokeThin
    border.color: root.accent

    // No focus policy and no Keys handlers: this control is pointer-only by
    // design. See the component docstring.
    activeFocusOnTab: false

    Behavior on color {
        ColorAnimation { duration: Theme.durationFast }
    }

    Text {
        id: caption
        anchors.centerIn: parent
        text: root.label
        color: root.accent
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.letterSpacing: Theme.letterSpacingWide
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.triggered()
    }
}
