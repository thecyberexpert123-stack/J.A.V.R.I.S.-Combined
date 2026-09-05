import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    A labelled radial gauge.

    Every gauge carries a name, a value and a unit. This is a deliberate
    correction of the documented flaw in the source material, where unlabelled
    telemetry raised the operator's cognitive load (docs/RESEARCH.md, D8).

    A negative \l value means "unavailable": the arc is not drawn and the
    readout shows a dash. The gauge never displays a fabricated number.
*/
Item {
    id: root

    /*! Normalised value in 0.0-1.0; negative means unavailable. */
    property real value: 0
    /*! Short label, e.g. "CPU". */
    property string label: ""
    /*! Formatted reading, e.g. "42.5". */
    property string readout: "--"
    /*! Unit suffix, e.g. "%". */
    property string unit: ""
    /*! Angle at which the arc begins, degrees, 0 = 3 o'clock. */
    property real startAngle: 130
    /*! Total angular span of the track, degrees. */
    property real sweepRange: 280

    /*! Arc sweep for the current value. Read by tests. */
    readonly property real sweepAngle: value <= 0 ? 0 : Math.min(1, value) * sweepRange
    readonly property bool available: value >= 0

    implicitWidth: 108
    implicitHeight: 108

    readonly property real _radius: Math.min(width, height) / 2 - Theme.strokeThick
    readonly property color _color: Theme.loadColor(value)

    // Backlight behind the dial, brightening with load. A gauge at 90% should
    // feel hot before the number is read -- peripheral vision registers
    // luminance change long before it resolves digits (D10).
    Glow {
        anchors.centerIn: parent
        size: root._radius * 2.1
        color: root._color
        visible: root.available && root.value > 0
        intensity: Theme.glowSubtle * Theme.glowScale
                   * Math.min(1, Math.max(0, root.value)) * 1.4
        core: 0.25

        Behavior on intensity {
            NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
        }
    }

    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer

        // Background track: always drawn, so an unavailable gauge still reads
        // as an instrument that is present but not reporting.
        ShapePath {
            strokeColor: Theme.primaryFaint
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.width / 2
                centerY: root.height / 2
                radiusX: root._radius
                radiusY: root._radius
                startAngle: root.startAngle
                sweepAngle: root.sweepRange
            }
        }

        ShapePath {
            strokeColor: root._color
            strokeWidth: Theme.strokeThick
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.width / 2
                centerY: root.height / 2
                radiusX: root._radius
                radiusY: root._radius
                startAngle: root.startAngle
                sweepAngle: root.available ? root.sweepAngle : 0

                Behavior on sweepAngle {
                    NumberAnimation {
                        duration: Theme.durationNormal
                        easing.type: Theme.easing
                    }
                }
            }
        }
    }

    Column {
        anchors.centerIn: parent
        spacing: 1

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 2

            Text {
                text: root.available ? root.readout : "--"
                color: root.available ? Theme.textPrimary : Theme.unavailable
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeLg
            }

            Text {
                anchors.baseline: parent.children[0].baseline
                text: root.unit
                color: Theme.textMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
            }
        }

        Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.label.toUpperCase()
            color: Theme.textSecondary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeSm
            font.letterSpacing: Theme.letterSpacingLabel
        }
    }
}
