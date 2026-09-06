import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Tests for the agent link control.

    The rules under test are the honesty rules: the state is always named in
    words, an action with nothing behind it is withdrawn rather than offered,
    and the control is pointer-only -- a keyboard rhythm must not be able to
    start the agent.
*/
TestCase {
    id: testCase

    name: "AgentLink"
    width: 600
    height: 200
    visible: true
    when: windowShown

    Component {
        id: linkComponent

        AgentLink {}
    }

    function findButton(link) {
        // The single ConsentButton child. Located structurally so the test
        // does not depend on an id that is private to the component.
        for (let i = 0; i < link.children.length; ++i) {
            const child = link.children[i];
            if (child.hasOwnProperty("label") && child.hasOwnProperty("triggered"))
                return child;
        }
        return null;
    }

    function test_offline_with_a_kernel_offers_link() {
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: false, available: true
        });
        compare(link.linkState, "OFFLINE");
        compare(link.readout, "AGENT OFFLINE");
        let button = findButton(link);
        verify(button !== null);
        compare(button.visible, true, "a reachable kernel must be offered");
        compare(button.label, "LINK");
    }

    function test_no_kernel_withdraws_the_action() {
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: false, available: false
        });
        compare(link.linkState, "UNAVAILABLE");
        compare(link.readout, "AGENT UNAVAILABLE");
        compare(link.readoutColor, Theme.unavailable);
        let button = findButton(link);
        compare(button.visible, false,
                "a button with nothing behind it invites a click that goes nowhere");
    }

    function test_linked_names_the_version_and_transport() {
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: true, available: true, version: "1.20.0", transport: "ON_DEMAND"
        });
        compare(link.linkState, "LINKED");
        compare(link.readout, "AGENT 1.20.0 · on demand");
        compare(link.readoutColor, Theme.ok);
        compare(findButton(link).label, "UNLINK");
    }

    function test_linked_without_a_version_still_says_linked() {
        // The kernel may not report a version; the readout must not go blank.
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: true, available: true, version: "", transport: "RESIDENT"
        });
        compare(link.readout, "AGENT LINKED · resident");
    }

    function test_click_requests_connect_when_offline() {
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: false, available: true
        });
        let connects = 0, disconnects = 0;
        link.connectRequested.connect(function () { connects += 1; });
        link.disconnectRequested.connect(function () { disconnects += 1; });
        let button = findButton(link);
        mouseClick(button, button.width / 2, button.height / 2);
        compare(connects, 1);
        compare(disconnects, 0);
    }

    function test_click_requests_disconnect_when_linked() {
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: true, available: true
        });
        let connects = 0, disconnects = 0;
        link.connectRequested.connect(function () { connects += 1; });
        link.disconnectRequested.connect(function () { disconnects += 1; });
        let button = findButton(link);
        mouseClick(button, button.width / 2, button.height / 2);
        compare(connects, 0);
        compare(disconnects, 1);
    }

    function test_action_is_not_reachable_by_tab() {
        let link = createTemporaryObject(linkComponent, testCase, {
            connected: false, available: true
        });
        let button = findButton(link);
        compare(button.activeFocusOnTab, false,
                "starting the agent must be a considered pointer action");
    }
}
