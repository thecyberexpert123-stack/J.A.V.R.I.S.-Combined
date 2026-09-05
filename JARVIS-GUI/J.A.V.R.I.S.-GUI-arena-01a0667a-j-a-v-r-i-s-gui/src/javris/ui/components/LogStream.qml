pragma ComponentBehavior: Bound

import QtQuick
import javris.ui

/*!
    A severity-coloured, auto-scrolling console log.

    Lines arrive as "SEVERITY\x1fmessage" from the controller. Splitting on a
    control character rather than a printable delimiter is safe because the
    router strips control characters from user input, so a message can never
    forge a severity tag.
*/
ListView {
    id: root

    /*! Raw log lines, oldest first. */
    property var lines: []

    model: lines
    clip: true
    spacing: 2
    boundsBehavior: Flickable.StopAtBounds
    // Reuse delegates: the log is bounded but redrawn on every append.
    reuseItems: true

    onCountChanged: positionViewAtEnd()

    delegate: Row {
        required property var modelData
        readonly property var parts: String(modelData).split("\u001f")
        readonly property string severity: parts.length > 1 ? parts[0] : "INFO"
        readonly property string message: parts.length > 1 ? parts[1] : String(modelData)

        width: root.width
        spacing: Theme.spaceSm

        Text {
            width: 42
            text: parent.severity
            color: Theme.severityColor(parent.severity)
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingLabel
        }

        Text {
            width: root.width - 42 - Theme.spaceSm
            text: parent.message
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            wrapMode: Text.WrapAtWordBoundaryOrAnywhere
            elide: Text.ElideRight
            maximumLineCount: 3
        }
    }
}
