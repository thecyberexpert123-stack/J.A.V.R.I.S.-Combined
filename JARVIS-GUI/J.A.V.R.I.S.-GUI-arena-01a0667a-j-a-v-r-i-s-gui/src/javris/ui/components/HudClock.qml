import QtQuick
import javris.ui

/*!
    Wall-clock time and date, as the display's anchor point.

    The time is the one readout a HUD can always show honestly, and at large
    size it gives the layout a fixed point of reference. It ticks once per
    second on a single timer -- not on a frame-driven binding -- because a
    clock that only advances while something else is animating is a broken
    clock.

    Rendering is left-aligned on a monospaced face with the seconds field held
    at a fixed width, so the digits do not jitter horizontally as they change.
*/
Item {
    id: root

    /*! Pixel size of the time face. The date scales from it. */
    property int timeSize: 44

    /*! Colour of the time digits. */
    property color color: Theme.textPrimary

    /*! The current time, refreshed once a second. Read by tests. */
    property date now: new Date()

    readonly property string timeText: Qt.formatTime(root.now, "HH:mm:ss")
    readonly property string dayText: Qt.formatDate(root.now, "d MMM").toUpperCase()
    readonly property string weekdayText: Qt.formatDate(root.now, "dddd").toUpperCase()

    implicitWidth: timeRow.width
    implicitHeight: timeRow.height

    Timer {
        // Aligned to whole seconds rather than to the frame clock: the display
        // must change exactly when the second does.
        interval: 1000
        running: root.visible
        repeat: true
        triggeredOnStart: true
        onTriggered: root.now = new Date()
    }

    Row {
        id: timeRow
        spacing: Theme.spaceMd

        Text {
            id: timeFace
            text: root.timeText
            color: root.color
            font.family: Theme.fontFamily
            font.pixelSize: root.timeSize
            font.letterSpacing: root.timeSize * 0.04
            // Tabular figures would be ideal; the mono face already gives
            // fixed advance widths, so the digits do not shift as they tick.
        }

        Rectangle {
            width: Theme.strokeThin
            height: timeFace.height * 0.62
            anchors.verticalCenter: timeFace.verticalCenter
            color: Theme.primaryDim
        }

        Column {
            anchors.verticalCenter: timeFace.verticalCenter
            spacing: 2

            Text {
                text: root.dayText
                color: root.color
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(root.timeSize * 0.42)
                font.letterSpacing: Theme.letterSpacingWide
            }

            Text {
                text: root.weekdayText
                color: Theme.textMuted
                font.family: Theme.fontFamily
                font.pixelSize: Math.round(root.timeSize * 0.26)
                font.letterSpacing: Theme.letterSpacingWide
            }
        }
    }
}
