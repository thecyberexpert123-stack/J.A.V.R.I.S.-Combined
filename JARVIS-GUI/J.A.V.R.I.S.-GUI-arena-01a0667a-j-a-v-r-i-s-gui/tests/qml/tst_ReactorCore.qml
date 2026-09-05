import QtQuick
import QtTest
import javris.ui.components

/*!
    Property assertions for ReactorCore's state encoding.

    The visual design promises that motion and colour carry meaning; these
    tests hold that promise to account.
*/
TestCase {
    id: testCase

    name: "ReactorCore"
    width: 400
    height: 400
    visible: true
    when: windowShown

    Component {
        id: coreComponent

        ReactorCore {
            width: 300
            height: 300
        }
    }

    function test_working_states_are_active() {
        const core = createTemporaryObject(coreComponent, testCase);
        const working = ["LISTENING", "PROCESSING", "EXECUTING", "SPEAKING"];
        for (let i = 0; i < working.length; ++i) {
            core.coreState = working[i];
            verify(core.active, working[i] + " should read as active");
            verify(!core.faulted, working[i] + " should not read as faulted");
        }
    }

    function test_fault_states_are_faulted() {
        const core = createTemporaryObject(coreComponent, testCase);
        const faults = ["ERROR", "OFFLINE"];
        for (let i = 0; i < faults.length; ++i) {
            core.coreState = faults[i];
            verify(core.faulted, faults[i] + " should read as faulted");
            verify(!core.active, faults[i] + " should not read as active");
        }
    }

    function test_faulted_core_does_not_spin() {
        // A stopped ring is the signal that the system is not working.
        const core = createTemporaryObject(coreComponent, testCase, { coreState: "ERROR" });
        compare(core.spinPeriod, 0);
    }

    function test_busier_states_spin_faster() {
        const core = createTemporaryObject(coreComponent, testCase);
        core.coreState = "STANDBY";
        const idlePeriod = core.spinPeriod;
        core.coreState = "PROCESSING";
        verify(core.spinPeriod < idlePeriod,
               "processing should spin faster than standby");
    }

    function test_load_is_clamped() {
        const core = createTemporaryObject(coreComponent, testCase);
        core.load = 3.5;
        compare(core.safeLoad, 1.0);
        core.load = -2;
        compare(core.safeLoad, 0.0);
    }

    function test_negative_load_reads_as_unavailable() {
        const core = createTemporaryObject(coreComponent, testCase, { load: -1 });
        verify(!core.available);
    }

    function test_zero_load_is_available() {
        // Zero load is a real reading and must not be confused with no reading.
        const core = createTemporaryObject(coreComponent, testCase, { load: 0 });
        verify(core.available);
    }
}
