pragma ComponentBehavior: Bound

import QtQuick
import javris.core
import javris.ui
import javris.ui.components

/*!
    Monitor mode: the reactor core foregrounded, with storage and network
    detail. Where diagnostics mode is for reading pressure, monitor mode is
    for sustained ambient awareness.
*/
Item {
    id: modeRoot

    /*! The HudController instance. See Hud.qml for why this is not required. */
    property var controller: Hud
    /*! Boot progress 0.0-1.0, forwarded to the core. */
    property real bootProgress: 1

    ReactorCore {
        id: core
        anchors.centerIn: parent
        width: Math.min(parent.width - 2 * (260 + Theme.spaceXl), parent.height) * 0.9
        height: width
        coreState: modeRoot.controller.state
        load: modeRoot.controller.cpuPercent < 0 ? -1 : modeRoot.controller.cpuPercent / 100
        bootProgress: modeRoot.bootProgress
    }

    Panel {
        anchors.left: parent.left
        anchors.verticalCenter: parent.verticalCenter
        width: 260
        title: "Storage"
        status: modeRoot.controller.disks.length === 0 ? "UNAVAILABLE" : ""
        statusColor: Theme.unavailable

        Column {
            id: storageColumn
            width: parent.width
            spacing: Theme.spaceMd

            Repeater {
                model: modeRoot.controller.disks

                delegate: TelemetryRow {
                    id: diskRow

                    required property var modelData

                    width: storageColumn.width
                    label: diskRow.modelData.mount
                    value: diskRow.modelData.text
                    fraction: diskRow.modelData.fraction
                }
            }

            Text {
                text: "No storage reporting"
                color: Theme.unavailable
                font.family: Theme.fontFamily
                font.pixelSize: Theme.fontSizeSm
                visible: modeRoot.controller.disks.length === 0
            }
        }
    }

    Panel {
        anchors.right: parent.right
        anchors.verticalCenter: parent.verticalCenter
        width: 260
        title: "Network"

        Column {
            id: networkColumn
            width: parent.width
            spacing: Theme.spaceMd

            TelemetryRow {
                width: networkColumn.width
                label: "Downlink"
                value: modeRoot.controller.networkRxText
            }

            TelemetryRow {
                width: networkColumn.width
                label: "Uplink"
                value: modeRoot.controller.networkTxText
            }

            TelemetryRow {
                width: networkColumn.width
                label: "Load avg"
                value: modeRoot.controller.loadText
            }
        }
    }
}
