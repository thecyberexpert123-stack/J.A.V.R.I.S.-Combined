import QtQuick
import QtQuick.Controls.Basic
import javris.core
import javris.ui
import javris.ui.components
import javris.ui.modes

/*!
    The HUD shell: background field, header, mode surface, telemetry rail and
    console. Composition only - all data and policy live in HudController.
*/
Item {
    id: hudSurface

    /*!
        The controller backing this HUD.

        Defaults to the registered \c Hud singleton rather than being declared
        \c required: a required property is still unset while the component's
        own bindings are first evaluated, so every child binding would resolve
        against null once at construction. A singleton default is resolvable
        from the first pass, and a test can still override it explicitly.
    */
    property var controller: Hud

    focus: true

    /*! 0.0-1.0 boot trace progress, driven while the controller is BOOTING. */
    property real bootProgress: 0

    Behavior on bootProgress {
        NumberAnimation { duration: Theme.durationBoot; easing.type: Easing.OutCubic }
    }

    /*!
        Pointer parallax offsets in pixels, before per-layer depth scaling.

        The original HUD team's second rule was to let the Z-axis work; their
        supervisor is explicit that the depth came from the way elements
        *moved*, not from perspective (docs/RESEARCH.md, D15). Shifting layers
        by different amounts is that effect, and it costs nothing but a
        translation.

        The excursion is capped at Theme.parallaxRange and eased, because D18
        forbids motion that could startle or displace something being read.
    */
    property real parallaxX: 0
    property real parallaxY: 0

    Behavior on parallaxX {
        NumberAnimation { duration: Theme.durationNormal; easing.type: Easing.OutQuad }
    }
    Behavior on parallaxY {
        NumberAnimation { duration: Theme.durationNormal; easing.type: Easing.OutQuad }
    }

    // Hover-only: no buttons accepted, so this can never swallow a click meant
    // for the console or any future control.
    HoverHandler {
        id: pointer
        enabled: Theme.ambientMotion

        onPointChanged: {
            if (!pointer.hovered) {
                hudSurface.parallaxX = 0;
                hudSurface.parallaxY = 0;
                return;
            }
            const nx = (pointer.point.position.x / Math.max(1, hudSurface.width)) - 0.5;
            const ny = (pointer.point.position.y / Math.max(1, hudSurface.height)) - 0.5;
            // Negated: layers drift *against* the pointer, which is what reads
            // as looking around a scene rather than dragging it.
            hudSurface.parallaxX = -nx * 2 * Theme.parallaxRange;
            hudSurface.parallaxY = -ny * 2 * Theme.parallaxRange;
        }

        onHoveredChanged: {
            if (!pointer.hovered) {
                hudSurface.parallaxX = 0;
                hudSurface.parallaxY = 0;
            }
        }
    }

    /*!
        Entrance factor for an element that should arrive after \a threshold
        of the boot sequence has elapsed.

        Nothing arrives at once - staggering entrances is what makes the HUD
        read as assembling itself rather than as a page appearing (D17), and
        differently-timed layers are what create the sense of depth (D15).

        \a threshold is a bootProgress value in 0.0-1.0; the result ramps from
        0 to 1 over the remainder.
    */
    function entrance(threshold) {
        if (hudSurface.bootProgress >= 1)
            return 1;
        const span = Math.max(0.01, 1 - threshold);
        return Math.max(0, Math.min(1, (hudSurface.bootProgress - threshold) / span));
    }

    Component.onCompleted: bootProgress = 1

    Rectangle {
        anchors.fill: parent
        gradient: Gradient {
            GradientStop { position: 0.0; color: Theme.background }
            GradientStop { position: 1.0; color: Theme.backgroundDeep }
        }
    }

    HudGrid {
        anchors.fill: parent
        scanning: hudSurface.controller.state !== "BOOTING"
        opacity: hudSurface.bootProgress

        // Farthest layer: moves least under parallax (docs/RESEARCH.md, D15).
        x: hudSurface.parallaxX * Theme.parallaxFar
        y: hudSurface.parallaxY * Theme.parallaxFar
    }

    AmbientField {
        anchors.fill: parent
        intensity: hudSurface.bootProgress
        x: hudSurface.parallaxX * Theme.parallaxFar
        y: hudSurface.parallaxY * Theme.parallaxFar
    }

    // Consent prompt. Declared last among the top-level children so it paints
    // above every other layer: while a consent decision is outstanding it must
    // own the display completely.
    ConsentPrompt {
        anchors.fill: parent
        z: 100
        request: hudSurface.controller.pendingConsent
        gate: hudSurface.controller.consentGate
        headline: hudSurface.controller.consentHeadline
        hint: hudSurface.controller.consentHint
        steps: hudSurface.controller.planSteps
        blast: hudSurface.controller.planBlast
        tier: hudSurface.controller.planTier
        playbook: hudSurface.controller.planPlaybook
        onApproved: hudSurface.controller.approveConsent()
        onDeclined: hudSurface.controller.declineConsent()
    }

    // Screen-edge brackets. Drawn at the very edge of the display so the whole
    // surface reads as a framed instrument rather than a page of widgets.
    CornerBrackets {
        anchors.fill: parent
        inset: Theme.spaceMd
        armLength: 34
        color: Theme.primaryDim
        opacity: hudSurface.bootProgress * 0.9

        // Farthest parallax layer, like the grid: the frame is "on the glass".
        x: hudSurface.parallaxX * Theme.parallaxFar
        y: hudSurface.parallaxY * Theme.parallaxFar
    }

    // -- header ------------------------------------------------------------
    Item {
        id: header
        anchors { top: parent.top; left: parent.left; right: parent.right }
        anchors.margins: Theme.spaceLg
        height: titleText.height + Theme.spaceSm

        // Wordmark backlight: makes the title read as an illuminated sign
        // rather than plain text, which is the single most visible "this is a
        // powered system" cue in the top bar.
        Glow {
            anchors.centerIn: titleText
            size: titleText.width * 1.6
            color: Theme.primary
            intensity: Theme.glowNormal * Theme.glowScale
            core: 0.1
        }

        Text {
            id: titleText
            text: "J.A.V.R.I.S."
            color: Theme.primary
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeXl
            font.letterSpacing: Theme.letterSpacingWide * 2
            // The boot overlay renders its own animated title; this one takes
            // over only once that has dissolved, so the name never doubles.
            opacity: hudSurface.entrance(0.9)
        }

        Text {
            anchors.left: titleText.right
            anchors.leftMargin: Theme.spaceMd
            anchors.baseline: titleText.baseline
            text: hudSurface.controller.mode
            opacity: hudSurface.entrance(0.9)
            color: Theme.accent
            font.family: Theme.fontFamily
            font.pixelSize: Theme.fontSizeMd
            font.letterSpacing: Theme.letterSpacingWide
        }

        Row {
            anchors.right: parent.right
            anchors.baseline: titleText.baseline
            spacing: Theme.spaceMd
            opacity: hudSurface.entrance(0.9)

            Text {
                // Escalation outranks the degraded notice, and both outrank
                // NOMINAL. Reporting "NOMINAL" while a critical condition is
                // on screen would be the header contradicting the alert.
                text: hudSurface.controller.alertActive
                      ? hudSurface.controller.alertSeverity
                      : (hudSurface.controller.degraded
                         ? "DEGRADED: " + hudSurface.controller.degradedText : "NOMINAL")
                color: hudSurface.controller.alertActive
                       ? (hudSurface.controller.alertSeverity === "CRITICAL"
                          ? Theme.error : Theme.warn)
                       : (hudSurface.controller.degraded ? Theme.warn : Theme.ok)
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                font.letterSpacing: Theme.letterSpacingLabel
            }

            Text {
                text: hudSurface.controller.state
                color: Theme.textPrimary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                font.letterSpacing: Theme.letterSpacingLabel
            }
        }
    }

    Rectangle {
        id: headerRule
        anchors { top: header.bottom; left: parent.left; right: parent.right }
        anchors.margins: Theme.spaceLg
        anchors.topMargin: 0
        height: Theme.strokeThin
        color: Theme.primaryFaint
        opacity: hudSurface.entrance(0.88)
    }

    // -- mode surface --------------------------------------------------------
    Item {
        id: surface

        // Suppression factor applied to everything the alert is competing
        // with (docs/RESEARCH.md, D9): escalation is as much about hiding
        // lower-priority data as it is about enlarging the problem.
        // Not readonly: a Behavior has to be able to drive the value as it
        // animates towards each new result of the binding.
        property real suppression: (hudSurface.controller.alertActive ? 0.28 : 1.0)
                                   * hudSurface.entrance(0.72)

        Behavior on suppression {
            NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
        }

        anchors {
            top: headerRule.bottom
            bottom: footer.top
            // The stage yields the left gutter to the host panel while that
            // panel is up, so the centre content is centred in the space it
            // actually has rather than underneath a panel.
            // Only DIAGNOSTICS yields the gutter. ASSISTANT is a takeover and
            // must stay optically centred on the full width.
            left: (specs.visible && hudSurface.controller.mode === "DIAGNOSTICS")
                  ? specs.right : parent.left
            right: rail.visible ? rail.left : parent.right
        }
        anchors.margins: Theme.spaceLg

        // Nearest content layer: largest parallax excursion.
        transform: Translate {
            x: hudSurface.parallaxX * Theme.parallaxMid
            y: hudSurface.parallaxY * Theme.parallaxMid
        }

        // Both modes are instantiated and cross-faded rather than swapped
        // through a Loader. A Loader evaluates a component's bindings before
        // its initial properties are applied, so a required 'controller'
        // reads as null on the first pass; instantiating directly binds it
        // correctly from the start. Both modes are inexpensive, and keeping
        // them alive means switching costs no re-layout.
        DiagnosticsMode {
            anchors.fill: parent
            controller: hudSurface.controller
            opacity: (hudSurface.controller.mode === "DIAGNOSTICS" ? 1 : 0) * surface.suppression
            visible: opacity > 0

            Behavior on opacity {
                NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
            }
        }

        MonitorMode {
            anchors.fill: parent
            controller: hudSurface.controller
            bootProgress: hudSurface.bootProgress
            opacity: (hudSurface.controller.mode === "MONITOR" ? 1 : 0) * surface.suppression
            visible: opacity > 0

            Behavior on opacity {
                NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
            }
        }

        AssistantMode {
            anchors.fill: parent
            controller: hudSurface.controller
            opacity: (hudSurface.controller.mode === "ASSISTANT" ? 1 : 0) * surface.suppression
            visible: opacity > 0

            Behavior on opacity {
                NumberAnimation { duration: Theme.durationSlow; easing.type: Theme.easing }
            }
        }

        // -- escalated condition ---------------------------------------------
        // Deliberately a sibling of the modes, drawn over them: escalation
        // means promoting the problem into the main display and suppressing
        // what is less important (docs/RESEARCH.md, D9). Placing it beside the
        // modes instead would just be one more thing competing for attention.
        AlertBanner {
            anchors.centerIn: parent
            width: Math.min(parent.width - Theme.spaceXl * 2, 560)
            height: implicitHeight

            active: hudSurface.controller.alertActive
            label: hudSurface.controller.alertLabel
            readout: hudSurface.controller.alertReadout
            unit: hudSurface.controller.alertUnit
            advice: hudSurface.controller.alertAdvice
            severity: hudSurface.controller.alertSeverity
        }
    }

    // -- clock -----------------------------------------------------------------
    // The time is the one thing a HUD can always state truthfully, and at this
    // size it anchors the composition. Hidden in ASSISTANT mode, where the orb
    // is meant to be the only focus.
    HudClock {
        id: clock

        anchors.top: headerRule.bottom
        anchors.topMargin: Theme.spaceLg
        anchors.left: parent.left
        anchors.leftMargin: Theme.spaceLg

        timeSize: 40
        color: Theme.textPrimary

        readonly property bool relevant: hudSurface.controller.mode !== "ASSISTANT"

        opacity: hudSurface.entrance(0.9) * surface.suppression
                 * (clock.relevant ? 1 : 0)
        visible: opacity > 0

        transform: Translate {
            x: hudSurface.parallaxX * Theme.parallaxMid
            y: hudSurface.parallaxY * Theme.parallaxMid
        }

        Behavior on opacity {
            NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
        }
    }

    // -- telemetry rail ------------------------------------------------------
    Panel {
        id: rail
        anchors {
            top: headerRule.bottom
            bottom: footer.top
            right: parent.right
        }
        anchors.margins: Theme.spaceLg
        width: 250
        title: "Vitals"
        // Lights while a condition is escalated: the rail carries the metric
        // that raised it, so it is where the eye should go.
        attention: hudSurface.controller.alertActive
        // The Panel paints a frame and fill of its own, so opacity alone left
        // a visible edge in ASSISTANT mode. visible is bound below.

        // The suppression half of escalation (docs/RESEARCH.md, D9): while a
        // condition is escalated, lower-priority peripheral detail recedes
        // rather than continuing to compete with it. It is dimmed, not hidden,
        // so the operator can still see that the rest of the system is being
        // watched.
        // Hidden in ASSISTANT mode: that mode is a modal takeover, and leaving
        // the instrument rail up would defeat the point of it.
        readonly property bool relevant: hudSurface.controller.mode !== "ASSISTANT"

        opacity: hudSurface.entrance(0.86) * surface.suppression * (rail.relevant ? 1 : 0)
        visible: opacity > 0

        // Slides in from beyond its own edge: elements arrive from outside the
        // frame rather than materialising in place (D15/D17).
        transform: Translate {
            x: (1 - hudSurface.entrance(0.86)) * Theme.spaceXl
                + hudSurface.parallaxX * Theme.parallaxNear
            y: hudSurface.parallaxY * Theme.parallaxNear
        }

        Behavior on opacity {
            NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
        }

        Column {
            width: parent.width
            spacing: Theme.spaceMd

            TelemetryRow {
                width: parent.width
                label: "Processor"
                value: hudSurface.controller.cpuText
                unit: "%"
                fraction: hudSurface.controller.cpuPercent < 0 ? -1 : hudSurface.controller.cpuPercent / 100
            }

            TelemetryRow {
                width: parent.width
                label: "Memory"
                value: hudSurface.controller.memoryText
                fraction: hudSurface.controller.memoryFraction
            }

            TelemetryRow {
                width: parent.width
                label: "Swap"
                value: hudSurface.controller.swapFraction < 0
                       ? "--" : (hudSurface.controller.swapFraction * 100).toFixed(1)
                unit: hudSurface.controller.swapFraction < 0 ? "" : "%"
                fraction: hudSurface.controller.swapFraction
            }

            TelemetryRow {
                width: parent.width
                label: "Core temp"
                value: hudSurface.controller.temperatureText
                unit: hudSurface.controller.temperatureText === "--" ? "" : "\u00b0C"
            }

            TelemetryRow {
                width: parent.width
                label: "Load avg"
                value: hudSurface.controller.loadText
            }

            TelemetryRow {
                width: parent.width
                label: "Uptime"
                value: hudSurface.controller.uptimeText
            }

            TelemetryRow {
                width: parent.width
                label: "Downlink"
                value: hudSurface.controller.networkRxText
            }

            TelemetryRow {
                width: parent.width
                label: "Uplink"
                value: hudSurface.controller.networkTxText
            }

            // Only present on hardware that actually has a battery. A desktop
            // shows nothing here rather than a permanently full cell.
            PowerCell {
                width: parent.width
                visible: hudSurface.controller.batteryPresent
                height: visible ? implicitHeight : 0
                fraction: hudSurface.controller.batteryFraction
                cellState: hudSurface.controller.batteryState
                readout: hudSurface.controller.batteryText
                runtime: hudSurface.controller.batteryRuntimeText
            }
        }
    }

    // -- host identity ---------------------------------------------------------
    // Static facts, read once from the kernel. This is the honest counterpart
    // to a "PC SPECS" panel: every row here is a real reading, and a host that
    // reports nothing shows an empty panel rather than invented hardware.
    Panel {
        id: specs

        anchors { top: clock.bottom; left: parent.left }
        anchors.topMargin: Theme.spaceLg
        anchors.leftMargin: Theme.spaceLg
        // Wide enough for a real CPU model string; these are long in practice
        // and eliding every one of them defeats the purpose of showing it.
        width: 340
        title: "Host"

        readonly property bool relevant: hudSurface.controller.mode === "DIAGNOSTICS"
                                         && hudSurface.controller.hostFacts.length > 0

        opacity: hudSurface.entrance(0.88) * surface.suppression
                 * (specs.relevant ? 1 : 0)
        visible: opacity > 0

        transform: Translate {
            x: -(1 - hudSurface.entrance(0.88)) * Theme.spaceXl
                + hudSurface.parallaxX * Theme.parallaxNear
            y: hudSurface.parallaxY * Theme.parallaxNear
        }

        Behavior on opacity {
            NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
        }

        FactList {
            width: parent.width
            facts: hudSurface.controller.hostFacts
        }
    }

    // -- console -------------------------------------------------------------
    Panel {
        id: footer
        anchors { bottom: parent.bottom; left: parent.left; right: parent.right }
        anchors.margins: Theme.spaceLg
        height: 168
        title: "Console"
        status: "TAB: cycle mode"

        // The console is the only panel that lights, and only for a moment
        // after it gains a line. This is what makes the bloom informative:
        // it means "something was just said here", not "this is a panel".
        attention: consoleFlash.running

        Timer {
            id: consoleFlash
            interval: Theme.durationSlow * 3
            repeat: false
        }

        Connections {
            target: hudSurface.controller
            function onLogChanged() { consoleFlash.restart(); }
        }
        opacity: hudSurface.entrance(0.92)

        transform: Translate {
            y: (1 - hudSurface.entrance(0.92)) * Theme.spaceXl
                + hudSurface.parallaxY * Theme.parallaxNear
            x: hudSurface.parallaxX * Theme.parallaxNear
        }

        Column {
            anchors.fill: parent
            spacing: Theme.spaceSm

            LogStream {
                id: logView
                width: parent.width
                height: parent.height - inputRow.height - Theme.spaceSm
                lines: hudSurface.controller.log
            }

            Row {
                id: inputRow
                width: parent.width
                spacing: Theme.spaceSm

                Text {
                    anchors.verticalCenter: parent.verticalCenter
                    text: ">"
                    color: Theme.primary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMd
                }

                TextField {
                    id: input
                    width: parent.width - 20 - (micButton.visible ? micButton.width + Theme.spaceSm : 0)
                    placeholderText: "Enter command. Type 'help' for the list."
                    color: Theme.textPrimary
                    placeholderTextColor: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMd
                    // Defence in depth: the router also caps length.
                    maximumLength: 200
                    background: Rectangle {
                        color: "transparent"
                        border.width: Theme.strokeThin
                        border.color: input.activeFocus ? Theme.primary : Theme.primaryFaint
                    }

                    onAccepted: {
                        if (text.trim().length > 0) {
                            hudSurface.controller.submitCommand(text);
                            text = "";
                        }
                    }

                    // A transcript is placed in the field for the owner to
                    // read and submit. It is deliberately NOT auto-accepted:
                    // speech can mishear, and a misheard word must never
                    // become a sent request.
                    Connections {
                        target: hudSurface.controller

                        function onVoiceChanged() {
                            const heard = hudSurface.controller.dictation;
                            if (heard.length > 0 && heard !== input.text) {
                                input.text = heard;
                                input.forceActiveFocus();
                                input.cursorPosition = heard.length;
                            }
                        }
                    }
                }

                // Push-to-talk. Hidden entirely when this machine cannot
                // transcribe: an inert button that silently does nothing is
                // worse than no button, and the reason is available in the
                // tooltip and via the log.
                MicButton {
                    id: micButton
                    anchors.verticalCenter: parent.verticalCenter
                    visible: hudSurface.controller.voiceAvailable
                    listening: hudSurface.controller.state === "LISTENING"
                    onTriggered: {
                        if (listening) {
                            hudSurface.controller.cancelDictation();
                        } else {
                            hudSurface.controller.startDictation();
                        }
                    }
                }
            }
        }
    }

    // -- boot sequence overlay ----------------------------------------------
    // The one theatrical moment (docs/RESEARCH.md, D16): shown over the HUD
    // while the controller is BOOTING, then dissolved. Its own progress is
    // driven by bootProgress, so the whole sequence stays deterministic.
    BootSequence {
        id: bootOverlay

        anchors.fill: parent
        progress: hudSurface.bootProgress
        // Hold until the sequence has essentially finished, then dissolve. The
        // HUD beneath is already fading up, so the two cross over.
        opacity: 1 - Math.max(0, Math.min(1, (hudSurface.bootProgress - 0.8) / 0.2))
        visible: opacity > 0

        // Never intercepts input, even mid-fade.
        enabled: false
    }

    Keys.onPressed: function (event) {
        if (event.key === Qt.Key_Tab) {
            hudSurface.controller.cycleMode();
            event.accepted = true;
        } else if (event.key === Qt.Key_Escape) {
            input.focus = true;
            event.accepted = true;
        }
    }
}
