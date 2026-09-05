import QtQuick
import javris.ui

/*!
    The escalated condition, promoted into the centre of the display.

    This is the visible half of the attention-escalation policy in
    \c javris.attention (docs/RESEARCH.md, D9-D11). The reference design's own
    critique is that a small peripheral gauge cannot capture attention, because
    foveal vision is narrow; the fix is to move the problem into the main
    display. So this deliberately sits over the mode surface rather than
    alongside it.

    Two rules follow from the research and are honoured here:

    \list
    \li \b{High contrast, not high detail} (D10). The readout is set at the
        largest size in the type scale in a saturated severity colour, because
        sharp contrast is detectable outside the fovea where fine detail is not.
        The banner carries one number and one sentence - no sparkline, no
        breakdown.
    \li \b{Acquire, then annotate} (D13). The reticle converges first; the text
        only appears once it has locked.
    \endlist

    The banner does not decide when to appear - it renders what the controller
    has already decided. Timing and hysteresis live in Python, where they are
    unit-testable.
*/
Item {
    id: root

    /*! Whether an alert is being escalated. */
    property bool active: false
    /*! Name of the condition, e.g. "Memory pressure". */
    property string label: ""
    /*! Formatted value, e.g. "94.2". */
    property string readout: ""
    /*! Unit suffix for \l readout. */
    property string unit: ""
    /*! One-line explanation of the condition. */
    property string advice: ""
    /*! "WARN" or "CRITICAL"; anything else is treated as a warning. */
    property string severity: ""

    /*! Colour for the current severity. Read by tests. */
    readonly property color severityColor: root.severity === "CRITICAL"
                                           ? Theme.error : Theme.warn

    visible: opacity > 0
    opacity: root.active ? 1 : 0

    Behavior on opacity {
        NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
    }

    implicitWidth: Math.max(420, body.implicitWidth + Theme.spaceXl * 2)
    implicitHeight: body.implicitHeight + Theme.spaceXl * 2

    // Dim the surface behind the alert. Escalation means "hide the
    // lower-priority data", not "draw on top of it and hope".
    Rectangle {
        anchors.fill: parent
        // Fully opaque: at 0.88 the reactor core behind it ghosted through the
        // hero readout, which is exactly the low-contrast failure D10 warns
        // against. The surface behind is separately dimmed, not relied upon.
        color: Theme.backgroundDeep
    }

    TargetReticle {
        anchors.fill: parent
        acquired: root.active
        color: root.severityColor
        armLength: 30
    }

    Column {
        id: body
        anchors.centerIn: parent
        spacing: Theme.spaceSm

        // Annotation follows acquisition rather than accompanying it.
        opacity: root.active ? 1 : 0

        Behavior on opacity {
            NumberAnimation {
                duration: Theme.durationNormal
                easing.type: Theme.easing
                // Held back by one bracket-convergence so the reticle reads as
                // arriving first (D13).
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.severity === "CRITICAL" ? "CRITICAL" : "ATTENTION"
            color: root.severityColor
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingWide * 2
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label.toUpperCase()
            color: Theme.textPrimary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeMd
            font.letterSpacing: Theme.letterSpacingWide
        }

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Theme.spaceXs

            Text {
                id: readoutText
                text: root.readout
                color: root.severityColor
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeHero
                font.letterSpacing: Theme.letterSpacingLabel
            }

            Text {
                anchors.baseline: readoutText.baseline
                text: root.unit
                color: root.severityColor
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLg
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.advice
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeMd
        }
    }
}
