pragma ComponentBehavior: Bound

import QtQuick
import javris.core
import javris.ui
import javris.ui.components

/*!
    Diagnostics mode: system pressure foregrounded for at-a-glance reading.

    Mode-driven recomposition is a core property of the reference design
    language (docs/RESEARCH.md, D2): the surface reorganises wholesale rather
    than merely swapping a tab. Where monitor mode is for ambient awareness,
    this mode answers "what is loaded right now, and by how much".
*/
Item {
    id: modeRoot

    /*! The HudController instance. See Hud.qml for why this is not required. */
    property var controller: Hud

    Column {
        anchors.centerIn: parent
        width: parent.width
        spacing: Theme.spaceXl

        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Theme.spaceXl

            Gauge {
                width: 148
                height: 148
                label: "CPU"
                unit: "%"
                value: modeRoot.controller.cpuPercent < 0
                       ? -1 : modeRoot.controller.cpuPercent / 100
                readout: modeRoot.controller.cpuText
            }

            Gauge {
                width: 148
                height: 148
                label: "Memory"
                unit: "%"
                value: modeRoot.controller.memoryFraction
                readout: modeRoot.controller.memoryFraction < 0
                         ? "--" : (modeRoot.controller.memoryFraction * 100).toFixed(1)
            }

            Gauge {
                width: 148
                height: 148
                label: "Swap"
                unit: "%"
                value: modeRoot.controller.swapFraction
                readout: modeRoot.controller.swapFraction < 0
                         ? "--" : (modeRoot.controller.swapFraction * 100).toFixed(1)
            }
        }

        // -- per-core utilisation -----------------------------------------
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: Theme.spaceSm
            visible: coreBars.count > 0

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: "PER-CORE UTILISATION"
                color: Theme.textSecondary
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                font.letterSpacing: Theme.letterSpacingWide
            }

            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: Theme.spaceSm

                Repeater {
                    id: coreBars
                    model: modeRoot.controller.coreLoads

                    delegate: Column {
                        id: coreBar

                        required property int index
                        required property var modelData

                        spacing: Theme.spaceXs

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: Math.round(coreBar.modelData * 100)
                            color: Theme.textMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSm
                        }

                        Rectangle {
                            id: barTrack

                            width: 16
                            height: 92
                            color: Theme.primaryFaint

                            Rectangle {
                                anchors.bottom: parent.bottom
                                width: barTrack.width
                                height: barTrack.height
                                        * Math.min(1, Math.max(0, coreBar.modelData))
                                color: Theme.loadColor(coreBar.modelData)

                                Behavior on height {
                                    NumberAnimation {
                                        duration: Theme.durationNormal
                                        easing.type: Theme.easing
                                    }
                                }
                            }
                        }

                        Text {
                            anchors.horizontalCenter: parent.horizontalCenter
                            text: coreBar.index
                            color: Theme.textMuted
                            font.family: Theme.fontFamily
                            font.pixelSize: Theme.fontSizeSm
                        }
                    }
                }
            }
        }

        // -- storage pressure ----------------------------------------------
        Column {
            anchors.horizontalCenter: parent.horizontalCenter
            width: Math.min(parent.width, 560)
            spacing: Theme.spaceMd

            Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: modeRoot.controller.disks.length > 0
                      ? "STORAGE PRESSURE" : "STORAGE UNAVAILABLE"
                color: modeRoot.controller.disks.length > 0
                       ? Theme.textSecondary : Theme.unavailable
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                font.letterSpacing: Theme.letterSpacingWide
            }

            Repeater {
                model: modeRoot.controller.disks

                delegate: TelemetryRow {
                    id: diskRow

                    required property var modelData

                    width: Math.min(modeRoot.width, 560)
                    label: diskRow.modelData.mount
                    value: diskRow.modelData.text
                    fraction: diskRow.modelData.fraction
                }
            }
        }
    }
}
