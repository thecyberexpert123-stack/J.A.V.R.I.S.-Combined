pragma ComponentBehavior: Bound

import QtQuick
import javris.ui

/*!
    A label/value list of static machine facts.

    Rows arrive as \c{label\x1fvalue} strings from the controller, matching the
    encoding already used by the console log. Only facts the kernel actually
    reports are present: this list gets shorter on a restricted host rather
    than falling back to placeholder text.

    Long values (a CPU model string can be 40+ characters) elide rather than
    wrap, so the row rhythm survives contact with real hardware names.
*/
Item {
    id: root

    /*! Rows as ``label\x1fvalue``. */
    property var facts: []

    /*! Width reserved for the label column. */
    property real labelWidth: 124

    /*! Emitted row height, used for layout by the parent. */
    readonly property real rowHeight: Theme.fontSizeSm + Theme.spaceSm

    implicitHeight: column.height
    implicitWidth: 260

    Column {
        id: column
        width: parent.width
        spacing: Theme.spaceXs

        Repeater {
            model: root.facts

            delegate: Item {
                id: row

                required property string modelData

                readonly property int separator: row.modelData.indexOf("\x1f")
                readonly property string label: row.separator < 0
                    ? row.modelData : row.modelData.substring(0, row.separator)
                readonly property string value: row.separator < 0
                    ? "" : row.modelData.substring(row.separator + 1)

                width: column.width
                height: Theme.fontSizeSm + Theme.spaceXs

                Text {
                    text: row.label
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSm
                    font.letterSpacing: Theme.letterSpacingLabel
                    anchors.verticalCenter: parent.verticalCenter
                }

                Text {
                    text: row.value
                    color: Theme.textSecondary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSm
                    anchors.verticalCenter: parent.verticalCenter
                    anchors.left: parent.left
                    anchors.leftMargin: root.labelWidth
                    anchors.right: parent.right
                    horizontalAlignment: Text.AlignRight
                    // A real CPU model string is long; elide rather than wrap
                    // so every row keeps the same height.
                    elide: Text.ElideRight
                }
            }
        }
    }
}
