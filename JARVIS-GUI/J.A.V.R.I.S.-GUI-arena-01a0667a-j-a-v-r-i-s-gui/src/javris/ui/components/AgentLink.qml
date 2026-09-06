import QtQuick
import javris.ui

/*!
    The agent connection control: a status readout with a single action.

    Connecting spawns (or reaches) a program that can change the machine, so it
    is the owner's decision and never happens on launch. This control is the
    pointer-side of that decision; the console verb \c{agent connect} is the
    keyboard side. Both call the same slot.

    Honesty rules applied:

    \list
    \li The readout names its state in words -- \c OFFLINE, \c LINKED,
        \c UNAVAILABLE -- so colour is never the only channel.
    \li \c UNAVAILABLE (no kernel on this machine) disables the action rather
        than offering a button that would silently do nothing.
    \li The button is a \l ConsentButton: pointer-only, not tab-reachable, no
        Enter binding. Starting the agent is a considered click, not a keyboard
        rhythm -- the same standard the consent prompt is held to.
    \li Nothing here glows. This is structure, not an event.
    \endlist
*/
Row {
    id: root

    /*! True once a transport is ready. */
    property bool connected: false
    /*! True when a kernel can be spawned on demand. */
    property bool available: false
    /*! Kernel version string when connected, otherwise empty. */
    property string version: ""
    /*! Active transport name, \c RESIDENT or \c ON_DEMAND. */
    property string transport: ""

    /*! Emitted when the owner asks to connect. */
    signal connectRequested
    /*! Emitted when the owner asks to disconnect. */
    signal disconnectRequested

    /*! Machine-readable state, for tests and for the readout. */
    readonly property string linkState: connected ? "LINKED"
                                        : (available ? "OFFLINE" : "UNAVAILABLE")

    /*! The readout, always in words. */
    readonly property string readout: {
        if (root.connected) {
            const via = root.transport === "RESIDENT" ? "resident" : "on demand";
            return root.version.length > 0
                   ? "AGENT " + root.version + " · " + via
                   : "AGENT LINKED · " + via;
        }
        return root.available ? "AGENT OFFLINE" : "AGENT UNAVAILABLE";
    }

    /*! Readout colour: a secondary channel behind the words. */
    readonly property color readoutColor: root.connected ? Theme.ok
                                          : (root.available ? Theme.textSecondary
                                                            : Theme.unavailable)

    spacing: Theme.spaceMd

    Text {
        id: status
        anchors.verticalCenter: parent.verticalCenter
        text: root.readout
        color: root.readoutColor
        font.family: Theme.fontFamily
        font.pixelSize: Theme.fontSizeSm
        font.letterSpacing: Theme.letterSpacingLabel

        Behavior on color {
            ColorAnimation { duration: Theme.durationFast }
        }
    }

    ConsentButton {
        id: action
        anchors.verticalCenter: parent.verticalCenter
        // The verb names the effect: LINK opens a connection, UNLINK closes
        // it. Deliberately not "START", which would overstate what the GUI
        // does -- it may only be reaching a doorway the owner already runs.
        label: root.connected ? "UNLINK" : "LINK"
        accent: root.connected ? Theme.textSecondary : Theme.primary
        // An action with nothing behind it is withdrawn, not greyed: a
        // disabled button still invites a click that goes nowhere.
        visible: root.connected || root.available
        onTriggered: {
            if (root.connected) {
                root.disconnectRequested();
            } else {
                root.connectRequested();
            }
        }
    }
}
