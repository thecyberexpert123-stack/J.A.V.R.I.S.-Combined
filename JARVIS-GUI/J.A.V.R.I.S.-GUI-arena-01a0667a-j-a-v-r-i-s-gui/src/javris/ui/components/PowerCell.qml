pragma ComponentBehavior: Bound

import QtQuick
import javris.ui

/*!
    Battery charge as a segmented cell.

    Segments rather than a smooth bar: a discrete scale is readable at a glance
    and at an angle, and it does not imply more precision than the kernel's
    integer percentage actually carries.

    The whole component is hidden when the host has no battery. A desktop
    showing a permanently full cell would be decoration pretending to be
    telemetry -- the opposite of what this HUD is for.
*/
Item {
    id: root

    /*! Charge as 0.0-1.0. Negative means unknown. */
    property real fraction: -1

    /*! ``CHARGING``, ``DISCHARGING`` or ``UNKNOWN``. */
    property string cellState: "UNKNOWN"

    /*! Formatted charge, e.g. ``"64 %"``. */
    property string readout: "--"

    /*! Estimated time to empty; empty string when not measurable. */
    property string runtime: ""

    /*! Number of segments in the cell. */
    property int segments: 10

    readonly property bool known: root.fraction >= 0
    readonly property bool charging: root.cellState === "CHARGING"

    /*!
        Low-charge threshold. Below this the cell takes the warning colour --
        the one piece of colour semantics here, because a dying battery is a
        condition the user must notice without reading the number.
    */
    readonly property bool low: root.known && root.fraction <= 0.15 && !root.charging

    readonly property color cellColor: !root.known ? Theme.unavailable
                                       : root.low ? Theme.error
                                       : root.charging ? Theme.ok
                                       : Theme.primary

    implicitWidth: 200
    implicitHeight: label.height + cells.height + Theme.spaceXs * 2

    Row {
        id: label
        width: parent.width
        spacing: Theme.spaceSm

        Text {
            text: "POWER"
            color: Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingLabel
        }

        Text {
            // A charging bolt is the one glyph everyone reads instantly.
            text: root.charging ? "CHARGING" : root.cellState === "UNKNOWN" ? "" : "ON BATTERY"
            color: root.charging ? Theme.ok : Theme.textMuted
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingLabel
        }
    }

    Row {
        id: cells

        anchors.top: label.bottom
        anchors.topMargin: Theme.spaceXs
        width: parent.width
        height: 14
        spacing: 3

        Repeater {
            model: root.segments

            delegate: Rectangle {
                id: segment

                required property int index

                /*
                    A segment lights once the charge reaches its *lower* edge.

                    Using the upper edge meant any charge under 10% lit no
                    segments at all, so a nearly-flat battery looked exactly
                    like a dead one -- the single most important reading on
                    this control was the one it could not express. Rounding
                    down to empty is only honest at literal zero.
                */
                readonly property bool lit:
                    root.known
                    && root.fraction > 0
                    && root.fraction >= segment.index / root.segments
                    && (segment.index === 0
                        || root.fraction > segment.index / root.segments)

                width: (cells.width - cells.spacing * (root.segments - 1)) / root.segments
                height: cells.height
                radius: 1
                color: segment.lit ? root.cellColor : "transparent"
                border.width: Theme.strokeThin
                border.color: segment.lit ? root.cellColor : Theme.primaryFaint
                opacity: segment.lit ? 1.0 : 0.7

                Behavior on color {
                    ColorAnimation { duration: Theme.durationNormal }
                }
            }
        }
    }

    Text {
        anchors.top: cells.bottom
        anchors.topMargin: Theme.spaceXs
        anchors.right: parent.right
        text: root.runtime.length > 0
              ? root.readout + "  \u00b7  " + root.runtime + " remaining"
              : root.readout
        color: root.low ? Theme.error : Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
    }
}
