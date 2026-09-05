pragma ComponentBehavior: Bound

import QtQuick
import javris.ui

/*!
    The owner's decision on a pending action.

    Two different questions arrive here, and the prompt deliberately does not
    treat them alike:

    \list
    \li \b{KERNEL_CONSENT} — the safety kernel refused a tier-2 action and will
        not proceed without explicit approval. Answering yes grants authority
        the kernel does not otherwise have. Rendered in the error colour.
    \li \b{REVERSIBILITY} — the kernel would run this happily, but reports that
        it cannot be undone. Answering yes grants \e{no} new authority; it only
        acknowledges the risk. Rendered in the warning colour.
    \endlist

    Collapsing these into one visual treatment would train the owner to read
    both as the same kind of warning, which would devalue the one that actually
    carries authority.

    Everything else here follows from the fact that this is a consent surface:

    \list
    \li \b{No default action.} Neither button is focused or activated by Enter.
        A dialog that a stray keypress can turn into "yes" is not consent.
    \li \b{The request is quoted verbatim}, and the plan below it shows the
        exact argv that will run. The owner approves what they can see.
    \li \b{Escape declines.} The reflexive exit must be the safe one.
    \li \b{No timeout.} An unattended machine must not drift into either answer.
    \endlist
*/
Item {
    id: root

    /*! The request text awaiting a decision. Empty means no prompt. */
    property string request: ""

    /*! Which gate is asking: "KERNEL_CONSENT" or "REVERSIBILITY". */
    property string gate: ""

    /*! One line stating what is being asked, and why. */
    property string headline: ""

    /*! Supporting detail: the kernel's hint, or its undo reason. */
    property string hint: ""

    /*! Plan steps as "description\x1fargv\x1froot" rows. */
    property var steps: []

    /*! Blast-radius facts as "label\x1fvalue" rows. */
    property var blast: []

    /*! The plan's safety tier, or -1 when unknown. */
    property int tier: -1

    /*! The matched playbook id, or empty. */
    property string playbook: ""

    signal approved
    signal declined

    readonly property bool active: root.request.length > 0

    /*! True when saying yes actually grants the kernel new permission. */
    readonly property bool isAuthority: root.gate === "KERNEL_CONSENT"

    /*! The colour carrying this prompt's severity. */
    readonly property color accent: root.isAuthority ? Theme.error : Theme.warn

    visible: opacity > 0
    opacity: root.active ? 1 : 0

    Behavior on opacity {
        NumberAnimation { duration: Theme.durationNormal; easing.type: Theme.easing }
    }

    // Opaque backdrop. Swallows every click and key that is not one of the two
    // answers, so nothing behind the prompt can be operated while a decision
    // is outstanding.
    Rectangle {
        anchors.fill: parent
        color: Qt.rgba(Theme.backgroundDeep.r, Theme.backgroundDeep.g,
                       Theme.backgroundDeep.b, 0.9)

        MouseArea {
            anchors.fill: parent
            enabled: root.active
            // Dismissing by misclick is neither approval nor informed refusal.
            onClicked: { /* intentionally inert */ }
        }
    }

    FocusScope {
        id: scope

        anchors.centerIn: parent
        width: Math.min(parent.width - Theme.spaceXl * 2, 680)
        height: Math.min(parent.height - Theme.spaceXl * 2,
                         body.height + Theme.spaceXl * 2)
        focus: root.active

        Keys.onEscapePressed: root.declined()

        Rectangle {
            anchors.fill: parent
            color: Theme.panel
            border.width: Theme.strokeMedium
            border.color: root.accent
        }

        CornerBrackets {
            anchors.fill: parent
            inset: -Theme.spaceXs
            armLength: 20
            color: root.accent
            thickness: Theme.strokeMedium
        }

        Column {
            id: body

            anchors.centerIn: parent
            width: parent.width - Theme.spaceXl * 2
            spacing: Theme.spaceMd

            Row {
                spacing: Theme.spaceMd

                Text {
                    text: root.isAuthority ? "CONSENT REQUIRED" : "IRREVERSIBLE ACTION"
                    color: root.accent
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMd
                    font.letterSpacing: Theme.letterSpacingWide
                }

                // The tier badge. Shown only when the kernel reported one:
                // inventing a tier would misstate the kernel's own assessment.
                Rectangle {
                    visible: root.tier >= 0
                    width: tierLabel.width + Theme.spaceSm * 2
                    height: tierLabel.height + Theme.spaceXs
                    anchors.verticalCenter: parent.verticalCenter
                    color: "transparent"
                    border.width: Theme.strokeThin
                    border.color: root.accent

                    Text {
                        id: tierLabel
                        anchors.centerIn: parent
                        text: "T" + root.tier
                        color: root.accent
                        font.family: Theme.fontFamily
                        font.pixelSize: Theme.fontSizeSm
                    }
                }

                Text {
                    visible: root.playbook.length > 0
                    anchors.verticalCenter: parent.verticalCenter
                    text: root.playbook
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSm
                }
            }

            Text {
                width: parent.width
                text: root.headline
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                wrapMode: Text.WordWrap
            }

            // The exact request, quoted and set apart so it cannot be confused
            // with the surrounding explanatory text.
            Rectangle {
                width: parent.width
                height: requestText.height + Theme.spaceMd * 2
                color: Theme.backgroundDeep
                border.width: Theme.strokeThin
                border.color: Theme.primaryFaint

                Text {
                    id: requestText
                    anchors.centerIn: parent
                    width: parent.width - Theme.spaceMd * 2
                    text: root.request
                    color: Theme.textPrimary
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeMd
                    wrapMode: Text.WordWrap
                }
            }

            // What will actually run. The argv is the ground truth here, and
            // it is shown rather than paraphrased.
            Column {
                width: parent.width
                spacing: Theme.spaceXs
                visible: root.steps.length > 0

                Text {
                    text: "WILL RUN"
                    color: Theme.textMuted
                    font.family: Theme.fontFamily
                    font.pixelSize: Theme.fontSizeSm
                    font.letterSpacing: Theme.letterSpacingWide
                }

                Repeater {
                    model: root.steps

                    delegate: Row {
                        id: stepRow

                        required property string modelData

                        readonly property var parts: stepRow.modelData.split("\x1f")

                        width: body.width
                        spacing: Theme.spaceSm

                        Text {
                            text: "\u203a"
                            color: root.accent
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSm
                        }

                        Column {
                            width: stepRow.width - Theme.spaceXl
                            spacing: 1

                            Text {
                                width: parent.width
                                text: stepRow.parts[0]
                                color: Theme.textPrimary
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSm
                                wrapMode: Text.WordWrap
                            }

                            Text {
                                width: parent.width
                                text: stepRow.parts[1]
                                      + (stepRow.parts[2] === "1" ? "   [root]" : "")
                                color: Theme.textMuted
                                font.family: Theme.fontFamily
                                font.pixelSize: Theme.fontSizeSm
                                wrapMode: Text.WrapAnywhere
                            }
                        }
                    }
                }
            }

            // Blast radius, as the kernel reported it.
            Column {
                width: parent.width
                spacing: 1
                visible: root.blast.length > 0

                Repeater {
                    model: root.blast

                    delegate: Row {
                        id: blastRow

                        required property string modelData

                        readonly property var parts: blastRow.modelData.split("\x1f")

                        spacing: Theme.spaceSm

                        Text {
                            width: 84
                            text: blastRow.parts[0]
                            color: Theme.textMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSm
                        }

                        Text {
                            text: blastRow.parts[1]
                            color: Theme.textSecondary
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSm
                        }
                    }
                }
            }

            Text {
                width: parent.width
                text: root.hint
                visible: root.hint.length > 0
                color: Theme.textMuted
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                wrapMode: Text.WordWrap
            }

            Row {
                anchors.right: parent.right
                spacing: Theme.spaceMd

                ConsentButton {
                    label: "DECLINE"
                    accent: Theme.primary
                    onTriggered: root.declined()
                }

                ConsentButton {
                    // The verb states what the answer authorises. "Approve and
                    // run" for the kernel gate is a grant of authority; "run
                    // anyway" for the reversibility gate is an acknowledgement.
                    label: root.isAuthority ? "APPROVE AND RUN" : "RUN ANYWAY"
                    accent: root.accent
                    onTriggered: root.approved()
                }
            }
        }
    }
}
