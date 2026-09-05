import QtQuick
import javris.ui

/*!
    Push-to-talk control for the console input.

    Shown only when this machine can actually transcribe speech. The recording
    state is unmistakable — a filled, pulsing element rather than a subtle tint
    — because a control that captures the microphone must never leave the owner
    unsure whether it is listening.

    The pulse runs only while listening, so the HUD has no perpetual animation
    competing for attention when nothing is happening.
*/
Item {
    id: root

    /*! True while audio is being captured. */
    property bool listening: false

    signal triggered

    implicitWidth: 26
    implicitHeight: 26
    width: implicitWidth
    height: implicitHeight

    // Halo, visible only while recording.
    Rectangle {
        id: halo

        anchors.centerIn: parent
        width: parent.width
        height: parent.height
        radius: width / 2
        color: "transparent"
        border.width: Theme.strokeThin
        border.color: Theme.error
        opacity: root.listening ? 1 : 0
        visible: opacity > 0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durationFast }
        }

        SequentialAnimation on scale {
            running: root.listening
            loops: Animation.Infinite
            // Returns to exactly 1.0 so stopping never leaves a stuck scale.
            NumberAnimation { from: 1.0; to: 1.35; duration: 700; easing.type: Easing.OutQuad }
            NumberAnimation { from: 1.35; to: 1.0; duration: 700; easing.type: Easing.InQuad }
        }
    }

    // The capsule body of a microphone, drawn rather than iconified so it
    // scales with the HUD and needs no asset.
    Rectangle {
        id: capsule

        anchors.horizontalCenter: parent.horizontalCenter
        y: 4
        width: 8
        height: 11
        radius: 4
        color: root.listening ? Theme.error : "transparent"
        border.width: Theme.strokeThin
        border.color: root.listening
                      ? Theme.error
                      : (mouse.containsMouse ? Theme.primary : Theme.primaryDim)

        Behavior on color {
            ColorAnimation { duration: Theme.durationFast }
        }
    }

    // Stand.
    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: capsule.y + capsule.height + 2
        width: 1
        height: 4
        color: capsule.border.color
    }

    Rectangle {
        anchors.horizontalCenter: parent.horizontalCenter
        y: capsule.y + capsule.height + 6
        width: 9
        height: 1
        color: capsule.border.color
    }

    MouseArea {
        id: mouse
        anchors.fill: parent
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: root.triggered()
    }
}
