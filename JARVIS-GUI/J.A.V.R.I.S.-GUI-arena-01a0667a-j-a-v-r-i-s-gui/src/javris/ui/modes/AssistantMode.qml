pragma ComponentBehavior: Bound

import QtQuick
import javris.core
import javris.ui
import javris.ui.components

/*!
    Assistant mode: the orb takes the display.

    Where \c DIAGNOSTICS and \c MONITOR are about the machine, this mode is
    about the assistant itself. It is the counterpart of the modal Voice HUD in
    the user's own project (docs/RESEARCH.md §17-21): the ambient instruments
    recede and one large presence owns the screen.

    The caption below the orb explains, in plain words, what each state means.
    That is the corrective to the documented flaw in the source material, where
    unlabelled telemetry raised cognitive load (D8) — a glowing orb that never
    says what it is doing has exactly that problem.

    \b{No microphone.} This project captures no audio; \c QtMultimedia is not
    even installed. The orb reflects the real assistant state machine and
    nothing else. It is deliberately \e not wired to a fake voice pipeline.
*/
Item {
    id: modeRoot

    /*! The HudController instance. See HudSurface.qml for why this is not required. */
    property var controller: Hud

    /*! Plain-language explanation of the current state. Read by tests. */
    readonly property string caption: {
        switch (modeRoot.controller.state) {
        case "STANDBY":
            return "Standing by. Awaiting a command.";
        case "LISTENING":
            return "Listening for input.";
        case "PROCESSING":
            return "Working out a response.";
        case "EXECUTING":
            return "Carrying out the request.";
        case "SPEAKING":
            return "Responding.";
        case "ERROR":
            return "A fault has occurred. Enter 'help' for available commands.";
        case "OFFLINE":
            return "Offline. No telemetry is being collected.";
        case "BOOTING":
            return "Bringing systems online.";
        default:
            return "";
        }
    }

    AssistantOrb {
        id: orb

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.verticalCenter: parent.verticalCenter
        anchors.verticalCenterOffset: -Theme.spaceXl

        // Generous but bounded, so the orb dominates without overflowing a
        // small window or becoming absurd on a large one.
        width: Math.max(180, Math.min(parent.width * 0.5, parent.height * 0.62, 460))
        height: width

        assistantState: modeRoot.controller.state
    }

    Text {
        id: captionText

        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: orb.bottom
        anchors.topMargin: Theme.spaceXl

        text: modeRoot.caption
        color: modeRoot.controller.state === "ERROR"
               || modeRoot.controller.state === "OFFLINE"
               ? Theme.error : Theme.textSecondary
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeMd
        font.letterSpacing: Theme.letterSpacingLabel

        // Cross-fade on change rather than snapping, so the caption settles
        // with the orb instead of flicking to new text (D17).
        Behavior on text {
            SequentialAnimation {
                NumberAnimation {
                    target: captionText; property: "opacity"
                    to: 0; duration: Theme.durationFast
                }
                PropertyAction { target: captionText; property: "text" }
                NumberAnimation {
                    target: captionText; property: "opacity"
                    to: 1; duration: Theme.durationNormal
                }
            }
        }
    }

    // The one genuinely live figure in this mode. Included so the orb is not
    // the only thing on screen making a claim: this one is measured.
    Text {
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.top: captionText.bottom
        anchors.topMargin: Theme.spaceMd

        text: modeRoot.controller.cpuPercent < 0
              ? "PROCESSOR --" : "PROCESSOR " + modeRoot.controller.cpuText + " %"
        color: Theme.textMuted
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.letterSpacing: Theme.letterSpacingLabel
    }
}
