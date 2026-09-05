import QtQuick
import javris.ui

/*!
    One labelled telemetry line: name on the left, value and unit on the right,
    with an optional load bar beneath.

    Both the label and the unit are mandatory in practice - a bare number is
    exactly the failure mode identified in docs/RESEARCH.md (D8).
*/
Item {
    id: root

    /*! Field name, e.g. "MEMORY". */
    property string label: ""
    /*! Formatted value. "--" indicates unavailable. */
    property string value: "--"
    /*! Unit suffix; may be empty when the value is self-describing. */
    property string unit: ""
    /*! Normalised 0.0-1.0 bar fill; negative hides the bar. */
    property real fraction: -1

    readonly property bool available: value !== "--"

    implicitWidth: 200
    implicitHeight: Math.max(labelText.height, valueText.height)
                    + (fraction >= 0 ? Theme.spaceXs + bar.height : 0)

    Text {
        id: labelText
        anchors.left: parent.left
        text: root.label.toUpperCase()
        color: Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.letterSpacing: Theme.letterSpacingLabel
    }

    // A single Text rather than a Row of two: a Row has no baseline of its
    // own, so baseline-anchoring it against the label silently misaligns.
    Text {
        id: valueText
        anchors.right: parent.right
        anchors.baseline: labelText.baseline
        // Never overlap the label: elide instead.
        anchors.left: labelText.right
        anchors.leftMargin: Theme.spaceSm
        horizontalAlignment: Text.AlignRight
        elide: Text.ElideLeft
        text: root.unit.length > 0 ? root.value + " " + root.unit : root.value
        color: root.available ? Theme.textPrimary : Theme.unavailable
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeMd
    }

    Rectangle {
        id: bar
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: labelText.bottom
        anchors.topMargin: Theme.spaceXs
        anchors.leftMargin: 0
        height: 3
        color: Theme.primaryFaint
        visible: root.fraction >= 0

        Rectangle {
            height: parent.height
            width: parent.width * Math.min(1, Math.max(0, root.fraction))
            color: Theme.loadColor(root.fraction)

            Behavior on width {
                NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
            }
        }
    }
}
