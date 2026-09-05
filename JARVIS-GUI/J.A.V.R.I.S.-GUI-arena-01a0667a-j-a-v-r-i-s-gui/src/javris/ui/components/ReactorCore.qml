pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    The central core: concentric rings whose motion and colour encode the
    assistant state and the current system load.

    This is an instrument, not an ornament (docs/RESEARCH.md, D6). Each ring
    carries meaning:
      - outer counter-rotating arcs: rotation rate encodes assistant state;
      - tick ring: fixed scale against which the load arc is read;
      - load arc: sweep and colour encode aggregate CPU load;
      - inner ring: pulse amplitude encodes load, for peripheral awareness.

    Glow is achieved by layering translucent strokes rather than with a shader.
    Qt 6 requires shaders pre-baked to .qsb and that toolchain is unavailable
    in the development sandbox (see AGENT-EXPERIENCE.md); layered strokes are
    fully supported by the scene graph and need no shader compilation.
*/
Item {
    id: root

    /*! Assistant state name, e.g. "STANDBY". */
    property string coreState: "BOOTING"
    /*! Aggregate load as a 0.0-1.0 fraction; negative means unavailable. */
    property real load: 0
    /*! Boot progress 0.0-1.0, used to trace the rings in on startup. */
    property real bootProgress: 1
    /*! Number of ticks on the scale ring. */
    property int tickCount: 60

    implicitWidth: 300
    implicitHeight: 300

    readonly property bool active: coreState === "LISTENING" || coreState === "PROCESSING"
                                   || coreState === "EXECUTING" || coreState === "SPEAKING"
    readonly property bool faulted: coreState === "ERROR" || coreState === "OFFLINE"
    readonly property bool available: load >= 0
    readonly property real safeLoad: Math.max(0, Math.min(1, load))

    readonly property color coreColor: faulted ? Theme.error
                                               : (active ? Theme.primary : Theme.primaryDim)

    readonly property real centreX: width / 2
    readonly property real centreY: height / 2
    readonly property real outerRadius: Math.min(width, height) / 2 - Theme.strokeThick

    /*! Milliseconds per revolution; 0 means stationary. Faster when working. */
    readonly property int spinPeriod: {
        if (faulted)
            return 0;
        switch (coreState) {
        case "PROCESSING":
            return 2600;
        case "EXECUTING":
            return 3400;
        case "LISTENING":
            return 5200;
        case "SPEAKING":
            return 4200;
        case "BOOTING":
            return 1800;
        default:
            return 14000;
        }
    }

    /*! True while ambient decorative motion should run. Read by tests. */
    readonly property bool animating: Theme.ambientMotion && !root.faulted
                                      && root.bootProgress >= 1

    /*!
        Fires a one-shot "alpha event" pulse.

        The original HUD team's third rule was that every shot carries an alpha
        event - a graphic that punctuates the moment (docs/RESEARCH.md, D16).
        Here a state change is that moment: the core emits a single expanding
        ring so the transition is *felt*, not merely relabelled.

        Deliberately a ring travelling outward rather than the core expanding
        in place: D18 forbids expand-in-place, which the source critique flags
        as a startle risk.
    */
    function pulse() {
        if (!Theme.ambientMotion)
            return;
        alphaPulse.restart();
    }

    onCoreStateChanged: root.pulse()

    // -- alpha-event pulse ---------------------------------------------------
    Rectangle {
        id: alphaRing

        anchors.centerIn: parent
        width: root.outerRadius * 2 * alphaRing.expansion
        height: width
        radius: width / 2
        color: "transparent"
        border.width: Theme.strokeMedium
        border.color: root.coreColor
        opacity: 0
        visible: opacity > 0

        property real expansion: 0.35

        SequentialAnimation {
            id: alphaPulse

            ParallelAnimation {
                NumberAnimation {
                    target: alphaRing; property: "expansion"
                    from: 0.35; to: 1.15
                    duration: Theme.durationSlow * 2
                    easing.type: Easing.OutCubic
                }
                SequentialAnimation {
                    NumberAnimation {
                        target: alphaRing; property: "opacity"
                        from: 0; to: 0.7
                        duration: Theme.durationFast
                    }
                    NumberAnimation {
                        target: alphaRing; property: "opacity"
                        to: 0
                        duration: Theme.durationSlow * 2 - Theme.durationFast
                        easing.type: Easing.InCubic
                    }
                }
            }
        }
    }

    // -- breathing halo ------------------------------------------------------
    // A slow luminance swell. Peripheral vision detects contrast change far
    // better than detail (D10), so this is how the core signals "alive"
    // without demanding a direct look.
    // A flat-colour circle read as a grey disc rather than light; a radial
    // falloff reads as emission. Same breathing behaviour, real bloom.
    Glow {
        id: breath

        anchors.centerIn: parent
        size: root.outerRadius * 2.4
        color: root.coreColor
        core: 0.05
        opacity: root.bootProgress
        intensity: Theme.glowSubtle * Theme.glowScale
        visible: Theme.ambientMotion

        // Drives intensity, not opacity: opacity now carries bootProgress, and
        // an animation on it would overwrite that binding outright.
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

    // -- processing sweep ----------------------------------------------------
    // A radar-style sweep shown only while the assistant is actually working.
    // Motion that means something: when it is turning, JARVIS is thinking.
    Item {
        id: sweep

        anchors.fill: parent
        visible: root.coreState === "PROCESSING" && Theme.ambientMotion
        opacity: root.bootProgress

        NumberAnimation on rotation {
            running: sweep.visible
            from: 0; to: 360
            duration: Theme.periodSweep
            loops: Animation.Infinite
        }

        Shape {
            anchors.fill: parent
            asynchronous: true
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                strokeColor: Theme.accent
                strokeWidth: Theme.strokeThin
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap

                PathAngleArc {
                    centerX: root.centreX; centerY: root.centreY
                    radiusX: root.outerRadius * 0.94
                    radiusY: root.outerRadius * 0.94
                    startAngle: -8
                    sweepAngle: 34
                }
            }
        }
    }

    // -- outer arcs, clockwise -------------------------------------------
    Item {
        anchors.fill: parent
        opacity: root.bootProgress

        NumberAnimation on rotation {
            running: root.spinPeriod > 0 && Theme.ambientMotion
            from: 0
            to: 360
            duration: root.spinPeriod
            loops: Animation.Infinite
        }

        Shape {
            anchors.fill: parent
            asynchronous: true
            preferredRendererType: Shape.CurveRenderer

            ShapePath {
                strokeColor: root.coreColor
                strokeWidth: Theme.strokeMedium
                fillColor: "transparent"
                capStyle: ShapePath.FlatCap

                PathAngleArc {
                    centerX: root.centreX; centerY: root.centreY
                    radiusX: root.outerRadius; radiusY: root.outerRadius
                    startAngle: -68
                    sweepAngle: 96 * root.bootProgress
                }
            }

            ShapePath {
                strokeColor: root.coreColor
                strokeWidth: Theme.strokeMedium
                fillColor: "transparent"
                capStyle: ShapePath.FlatCap

                PathAngleArc {
                    centerX: root.centreX; centerY: root.centreY
                    radiusX: root.outerRadius; radiusY: root.outerRadius
                    startAngle: 112
                    sweepAngle: 96 * root.bootProgress
                }
            }
        }
    }

    // -- inner arcs, counter-clockwise ------------------------------------
    Item {
        anchors.fill: parent
        opacity: root.bootProgress * 0.75

        NumberAnimation on rotation {
            running: root.spinPeriod > 0 && Theme.ambientMotion
            from: 360
            to: 0
            duration: root.spinPeriod * 1.7
            loops: Animation.Infinite
        }

        // Comet-profiled: brightest at the leading end and fading back along
        // the tail, so the direction of rotation is legible from the stroke
        // itself rather than only from watching it move.
        TaperedArc {
            anchors.fill: parent
            arcRadius: root.outerRadius * 0.86
            startAngle: 20
            sweepAngle: 140 * root.bootProgress
            color: root.coreColor
            thickness: Theme.strokeThin
            peakPosition: 0.92
            falloff: 1.9
        }

        TaperedArc {
            anchors.fill: parent
            arcRadius: root.outerRadius * 0.86
            startAngle: 200
            sweepAngle: 140 * root.bootProgress
            color: root.coreColor
            thickness: Theme.strokeThin
            peakPosition: 0.92
            falloff: 1.9
        }
    }

    // -- fixed tick scale ---------------------------------------------------
    Item {
        anchors.fill: parent
        opacity: root.bootProgress

        Repeater {
            model: root.tickCount

            delegate: Rectangle {
                required property int index

                // Every fifth tick is a major graduation.
                readonly property bool major: index % 5 === 0
                readonly property real fraction: index / root.tickCount
                readonly property real angleRadians: fraction * 2 * Math.PI - Math.PI / 2
                // Not named 'radius': that would shadow Rectangle.radius.
                readonly property real orbit: root.outerRadius * 0.74

                width: major ? 7 : 3
                height: Theme.strokeThin
                color: major ? Theme.primaryDim : Theme.primaryFaint
                x: root.centreX + Math.cos(angleRadians) * orbit - width / 2
                y: root.centreY + Math.sin(angleRadians) * orbit - height / 2
                rotation: fraction * 360
            }
        }
    }

    // -- load arc ------------------------------------------------------------
    Shape {
        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer
        opacity: root.bootProgress

        // Unfilled track, so the scale is legible even at zero load.
        ShapePath {
            strokeColor: Theme.primaryFaint
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"

            PathAngleArc {
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.outerRadius * 0.62; radiusY: root.outerRadius * 0.62
                startAngle: 130
                sweepAngle: 280
            }
        }

        // Wide translucent stroke beneath a narrow bright one reads as bloom.
        ShapePath {
            strokeColor: Theme.loadColor(root.load)
            strokeWidth: Theme.strokeThick * 3
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                id: loadArc
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.outerRadius * 0.62; radiusY: root.outerRadius * 0.62
                startAngle: 130
                sweepAngle: root.available ? 280 * root.safeLoad : 0

                Behavior on sweepAngle {
                    NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
                }
            }
        }

        ShapePath {
            strokeColor: Theme.textPrimary
            strokeWidth: Theme.strokeMedium
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap

            PathAngleArc {
                centerX: root.centreX; centerY: root.centreY
                radiusX: root.outerRadius * 0.62; radiusY: root.outerRadius * 0.62
                startAngle: 130
                sweepAngle: loadArc.sweepAngle
            }
        }
    }

    // -- inner ring and pulse -------------------------------------------------
    Rectangle {
        id: halo
        anchors.centerIn: parent
        width: root.outerRadius * 0.92
        height: width
        radius: width / 2
        color: "transparent"
        border.width: Theme.strokeThick * 2
        border.color: root.coreColor
        opacity: 0.10 * root.bootProgress
    }

    Rectangle {
        id: innerRing
        anchors.centerIn: parent
        width: root.outerRadius * 0.62
        height: width
        radius: width / 2
        color: "transparent"
        border.width: Theme.strokeMedium
        border.color: root.coreColor
        opacity: 0.55 * root.bootProgress

        SequentialAnimation on scale {
            running: root.animating
            loops: Animation.Infinite
            NumberAnimation {
                to: 1.0 + 0.12 * (0.3 + root.safeLoad)
                duration: 1100
                easing.type: Easing.InOutSine
            }
            NumberAnimation { to: 1.0; duration: 1100; easing.type: Easing.InOutSine }
        }
    }

    // Hot aperture behind the centre, so the middle of the reactor is the
    // brightest point on the display.
    Glow {
        anchors.centerIn: parent
        size: root.outerRadius * 1.1
        color: root.coreColor
        opacity: root.bootProgress
        intensity: Theme.glowStrong * Theme.glowScale
    }

    // The lit centre. Kept as a ring-with-core rather than a flat disc so it
    // reads as a depth-lit aperture instead of a sticker.
    Rectangle {
        anchors.centerIn: parent
        width: root.outerRadius * 0.42
        height: width
        radius: width / 2
        opacity: root.bootProgress
        // Translucent so the aperture glow behind shows through. A solid fill
        // made this a painted ball sitting on top of the light rather than the
        // source of it.
        gradient: Gradient {
            GradientStop {
                position: 0.0
                color: Qt.rgba(root.coreColor.r, root.coreColor.g,
                               root.coreColor.b, 0.30)
            }
            GradientStop {
                position: 1.0
                color: Qt.rgba(Theme.backgroundDeep.r, Theme.backgroundDeep.g,
                               Theme.backgroundDeep.b, 0.55)
            }
        }
        border.width: Theme.strokeThin
        border.color: root.coreColor
    }

    Text {
        anchors.centerIn: parent
        text: root.coreState
        color: Theme.textPrimary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.letterSpacing: Theme.letterSpacingLabel
        opacity: root.bootProgress
    }

    // Load readout beneath the core: the arc shows magnitude, this gives the
    // exact figure, with its unit (docs/RESEARCH.md, D8).
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: parent.verticalCenter
        anchors.topMargin: root.outerRadius * 0.68
        text: root.available ? (root.safeLoad * 100).toFixed(1) + " %" : "LOAD UNAVAILABLE"
        color: root.available ? Theme.textSecondary : Theme.unavailable
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.letterSpacing: Theme.letterSpacingLabel
        opacity: root.bootProgress
    }
}
