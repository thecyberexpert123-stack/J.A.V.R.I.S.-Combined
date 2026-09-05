pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    The assistant orb: one large presence whose behaviour encodes what the
    assistant is currently doing.

    Adapted from the Voice HUD in the user's own JARVIS_GUI project
    (docs/RESEARCH.md §17-21), reimplemented natively in QML. Each state gets a
    distinct visual signature so the mode is readable at a glance, from across
    a room, without reading the caption:

    \list
    \li \c STANDBY — rings only, slow.
    \li \c LISTENING — radial bars around the rim, running as a travelling wave.
    \li \c PROCESSING — two counter-rotating scanner lines; everything speeds up.
    \li \c EXECUTING — a determinate progress arc: deciding versus doing.
    \li \c SPEAKING — ripples expanding outward on a stagger.
    \li \c ERROR / \c OFFLINE — still and red. A fault is not a mood.
    \endlist

    \b{Honesty contract (D20).} The rim bars are a \e{state} visualiser, not an
    audio meter. They are driven by a phase clock and the bar's index — exactly
    as in the source design, where each bar has a fixed CSS delay and never
    touches the microphone. This project has no audio capture at all
    (QtMultimedia is not even installed), and no element here implies a signal
    that is not being measured.
*/
Item {
    id: root

    /*! Assistant state name, e.g. "LISTENING". */
    property string assistantState: "STANDBY"
    /*! 0.0-1.0 progress used by the EXECUTING arc; negative hides it. */
    property real activity: -1
    /*! Number of bars around the rim. Scales down on small surfaces. */
    property int barCount: Math.max(36, Math.min(120, Math.round(width / 4)))

    readonly property bool listening: root.assistantState === "LISTENING"
    readonly property bool thinking: root.assistantState === "PROCESSING"
    readonly property bool executing: root.assistantState === "EXECUTING"
    readonly property bool speaking: root.assistantState === "SPEAKING"
    readonly property bool faulted: root.assistantState === "ERROR"
                                    || root.assistantState === "OFFLINE"

    /*!
        True only when there is real progress to draw.

        Named rather than inlined so it is directly assertable: the rule that
        the arc never appears without a measured value is the point, not an
        implementation detail (D20).
    */
    readonly property bool showsProgress: root.executing && root.activity >= 0

    /*!
        Brightness multiplier on the hot core: the assistant burns brighter
        while it is actually doing something. Not readonly, so a Behavior can
        ease it (a readonly property cannot be animated -- see
        AGENT-EXPERIENCE.md Round 4).
    */
    property real coreLift: (root.thinking || root.executing) ? 1.45
                            : (root.speaking || root.listening) ? 1.2 : 1.0

    Behavior on coreLift {
        NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
    }

    /*! True when the orb should be animating at all. Read by tests. */
    readonly property bool animating: Theme.ambientMotion && root.visible && !root.faulted

    /*!
        Quiet companion to \c tint for the standing arcs.

        Hardcoding those arcs to primaryDim left two cyan arcs sitting inside
        an otherwise red orb during a fault, which read as "partly fine". A
        fault must be coherent across the whole assembly. Derived from
        Theme.error rather than adding a theme token used in exactly one place.
    */
    readonly property color tintDim: root.faulted
                                     ? Qt.darker(Theme.error, 1.7) : Theme.primaryDim

    readonly property color tint: root.faulted ? Theme.error
                                               : (root.listening || root.speaking
                                                  ? Theme.accent : Theme.primary)

    /*! Ring revolution period in ms; shorter when working. Read by tests. */
    readonly property int ringPeriod: {
        if (root.thinking)
            return 9000;
        if (root.executing)
            return 12000;
        if (root.listening || root.speaking)
            return 20000;
        return 38000;
    }

    /*!
        The assembly swells slightly while thinking, as in the source design.

        Not readonly: a Behavior must be able to drive the value as it animates
        towards each new result of the binding.
    */
    property real swell: root.thinking ? 1.05 : 1.0

    implicitWidth: 320
    implicitHeight: 320

    readonly property real centreX: width / 2
    readonly property real centreY: height / 2
    readonly property real radius: Math.min(width, height) / 2

    Behavior on swell {
        NumberAnimation { duration: Theme.durationSlow * 2; easing.type: Theme.easing }
    }

    // A single phase clock, 0.0-1.0, drives every derived animation. One
    // animator for the whole component is far cheaper than one per bar, and it
    // keeps every element in a fixed relationship to the others.
    QtObject {
        id: clock
        property real phase: 0
    }

    NumberAnimation {
        target: clock
        property: "phase"
        running: root.animating
        from: 0
        to: 1
        duration: 1500
        loops: Animation.Infinite
    }

    // -- ambient rings -------------------------------------------------------
    Item {
        anchors.fill: parent
        scale: root.swell

        Item {
            anchors.fill: parent

            NumberAnimation on rotation {
                running: root.animating
                from: 0; to: 360
                duration: root.ringPeriod
                loops: Animation.Infinite
            }

            Shape {
                anchors.fill: parent
                asynchronous: true
                preferredRendererType: Shape.CurveRenderer

                ShapePath {
                    // Kept dashed and uniform: this is the outermost boundary
                    // and it is the one element that should read as a fixed
                    // reference. Everything inside it moves and fades against
                    // it, so tapering this too would leave nothing steady.
                    strokeColor: root.tint
                    strokeWidth: Theme.strokeThin
                    fillColor: "transparent"
                    strokeStyle: ShapePath.DashLine
                    dashPattern: [3, 6]

                    PathAngleArc {
                        centerX: root.centreX; centerY: root.centreY
                        radiusX: root.radius * 0.96; radiusY: root.radius * 0.96
                        startAngle: 0; sweepAngle: 360
                    }
                }
            }
        }

        Item {
            anchors.fill: parent

            NumberAnimation on rotation {
                running: root.animating
                from: 360; to: 0
                duration: root.ringPeriod * 1.6
                loops: Animation.Infinite
            }

            // Tapered rather than uniform: a hard-ended arc reads as a solid
            // mechanical part and makes the start and end points arbitrarily
            // conspicuous. Fading each arc into and out of nothing is what
            // stops the ring looking machined.
            TaperedArc {
                anchors.fill: parent
                arcRadius: root.radius * 0.80
                startAngle: 24
                sweepAngle: 132
                // Full tint, not tintDim: the taper already supplies the
                // falloff, and dimming the colour on top of it left these
                // arcs invisible against the core bloom. One dimming factor,
                // not two.
                color: root.tint
                thickness: Theme.strokeMedium
                peak: 0.85
                peakPosition: 0.62
                falloff: 1.2
            }

            TaperedArc {
                anchors.fill: parent
                arcRadius: root.radius * 0.80
                startAngle: 204
                sweepAngle: 132
                // Full tint, not tintDim: the taper already supplies the
                // falloff, and dimming the colour on top of it left these
                // arcs invisible against the core bloom. One dimming factor,
                // not two.
                color: root.tint
                thickness: Theme.strokeMedium
                peak: 0.85
                peakPosition: 0.62
                falloff: 1.2
            }
        }
    }

    // -- LISTENING: radial rim bars -----------------------------------------
    // A travelling wave around the rim. Amplitude comes from the bar's angular
    // position and the phase clock - never from audio, which is not captured
    // (D20). This mirrors the source design, whose bars are likewise driven by
    // a fixed per-index delay.
    Item {
        anchors.fill: parent
        visible: root.listening && Theme.ambientMotion
        opacity: root.listening ? 1 : 0

        Behavior on opacity {
            NumberAnimation { duration: Theme.durationNormal }
        }

        Repeater {
            model: root.barCount

            delegate: Rectangle {
                id: bar

                required property int index

                readonly property real fraction: bar.index / root.barCount
                readonly property real angle: bar.fraction * 2 * Math.PI - Math.PI / 2
                // Three lobes travelling around the rim, so the motion reads as
                // circulating rather than as every bar pulsing in unison.
                readonly property real wave:
                    0.5 + 0.5 * Math.sin((bar.fraction * 3 - clock.phase) * 2 * Math.PI)
                readonly property real orbit: root.radius * 0.88

                width: 2
                height: 4 + 12 * bar.wave
                radius: 1
                color: Theme.accent
                opacity: 0.35 + 0.65 * bar.wave
                antialiasing: true

                x: root.centreX + Math.cos(bar.angle) * bar.orbit - width / 2
                y: root.centreY + Math.sin(bar.angle) * bar.orbit - height / 2
                transformOrigin: Item.Center
                rotation: bar.fraction * 360
            }
        }
    }

    // -- PROCESSING: counter-rotating scanners -------------------------------
    Item {
        anchors.fill: parent
        visible: root.thinking && Theme.ambientMotion

        Repeater {
            model: 2

            delegate: Item {
                id: scanner

                required property int index

                anchors.fill: parent

                NumberAnimation on rotation {
                    running: scanner.visible && root.animating
                    from: scanner.index === 0 ? 0 : 360
                    to: scanner.index === 0 ? 360 : 0
                    duration: Theme.periodSweep + scanner.index * 900
                    loops: Animation.Infinite
                }

                Rectangle {
                    width: Theme.strokeThin
                    height: root.radius * 0.62
                    x: root.centreX - width / 2
                    y: scanner.index === 0
                       ? root.centreY - height : root.centreY
                    gradient: Gradient {
                        GradientStop {
                            position: 0.0
                            color: scanner.index === 0 ? "transparent" : Theme.accent
                        }
                        GradientStop {
                            position: 1.0
                            color: scanner.index === 0 ? Theme.accent : "transparent"
                        }
                    }
                }
            }
        }
    }

    // -- EXECUTING: determinate progress arc ---------------------------------
    // Our addition, not in the source design: their pipeline has no execution
    // stage. Shown only when a real 0.0-1.0 figure exists, so it never invents
    // progress it does not have.
    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer
        visible: root.showsProgress

        ShapePath {
            strokeColor: Theme.primary
            strokeWidth: Theme.strokeThick
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.radius * 0.88; radiusY: root.radius * 0.88
                startAngle: -90
                sweepAngle: 360 * Math.max(0, Math.min(1, root.activity))

                Behavior on sweepAngle {
                    NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
                }
            }
        }
    }

    // -- SPEAKING: staggered ripples -----------------------------------------
    Item {
        anchors.fill: parent
        visible: root.speaking && Theme.ambientMotion

        Repeater {
            model: 3

            delegate: Rectangle {
                id: ripple

                required property int index

                // Each ripple is the same animation offset in phase, which is
                // what produces the outward-rolling cadence.
                readonly property real local:
                    (clock.phase + ripple.index / 3) % 1.0
                readonly property real span: root.radius * 2 * (0.45 + 0.75 * ripple.local)

                anchors.centerIn: parent
                width: ripple.span
                height: ripple.span
                radius: width / 2
                color: "transparent"
                border.width: Theme.strokeMedium
                border.color: Theme.accent
                opacity: (1 - ripple.local) * 0.55
            }
        }
    }

    // -- core ----------------------------------------------------------------

    // Ambient bloom filling the whole assembly. This is the single biggest
    // contributor to the orb reading as *lit* rather than *drawn*, and it sits
    // behind everything so the wireframe stays crisp on top of it.
    Glow {
        id: ambientBloom

        anchors.centerIn: parent
        size: root.radius * 2.5
        color: root.tint
        intensity: Theme.glowSubtle * Theme.glowScale
        core: 0.05

        // Breathes even at rest, so the orb never looks like a frozen image.
        SequentialAnimation on intensity {
            running: root.animating
            loops: Animation.Infinite
            NumberAnimation {
                to: Theme.glowNormal * Theme.glowScale
                duration: Theme.periodBreath / 2
                easing.type: Easing.InOutSine
            }
            NumberAnimation {
                to: Theme.glowSubtle * Theme.glowScale
                duration: Theme.periodBreath / 2
                easing.type: Easing.InOutSine
            }
        }
    }

    Rectangle {
        id: halo

        anchors.centerIn: parent
        width: root.radius * 0.92
        height: width
        radius: width / 2
        color: root.tint
        opacity: 0.06

        SequentialAnimation on opacity {
            running: root.animating
            loops: Animation.Infinite
            NumberAnimation {
                to: 0.16; duration: Theme.periodBreath / 2; easing.type: Easing.InOutSine
            }
            NumberAnimation {
                to: 0.06; duration: Theme.periodBreath / 2; easing.type: Easing.InOutSine
            }
        }
    }

    // Tight hot core: this is the "power source" read. Brighter and much
    // smaller than the ambient bloom, so the centre has a definite source
    // rather than an evenly-lit fog.
    Glow {
        anchors.centerIn: parent
        size: root.radius * 1.15
        color: root.tint
        intensity: (root.faulted ? Theme.glowSubtle : Theme.glowStrong)
                   * Theme.glowScale * root.coreLift
        core: 0.0
    }

    Rectangle {
        anchors.centerIn: parent
        width: root.radius * 0.56
        height: width
        radius: width / 2
        border.width: Theme.strokeMedium
        border.color: root.tint
        // Translucent, not opaque: an opaque disc punched a black hole in the
        // middle of its own bloom, which is exactly backwards for something
        // meant to read as a light source. Letting the glow through makes the
        // core the brightest point instead of the darkest.
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(0, 0, 0, 0) }
            GradientStop {
                position: 1.0
                color: Qt.rgba(Theme.backgroundDeep.r, Theme.backgroundDeep.g,
                               Theme.backgroundDeep.b, 0.55)
            }
        }
    }

    Text {
        anchors.centerIn: parent
        text: root.assistantState
        color: root.faulted ? Theme.error : Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeMd
        font.letterSpacing: Theme.letterSpacingWide
    }
}
