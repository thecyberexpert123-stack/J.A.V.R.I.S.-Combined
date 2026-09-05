import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Behavioural tests for AssistantOrb.

    These assert the honesty rules as much as the visuals: a fault must be
    still, and no progress arc may appear unless progress was actually
    supplied (docs/RESEARCH.md D20).
*/
Item {
    width: 400
    height: 400

    AssistantOrb {
        id: orb
        // Explicitly sized, not anchor-filled: the clamping test drives width
        // directly, and an anchor would silently override it.
        width: 400
        height: 400
    }

    TestCase {
        name: "AssistantOrb"
        when: windowShown

        function init() {
            orb.assistantState = "STANDBY";
            orb.activity = -1;
            orb.visible = true;
            Theme.ambientMotion = true;
        }

        function test_animates_when_visible_and_motion_enabled() {
            verify(orb.animating, "should animate by default");
        }

        function test_hidden_orb_does_not_animate() {
            orb.visible = false;
            verify(!orb.animating, "an invisible orb must not burn CPU");
            orb.visible = true;
        }

        function test_reduced_motion_stops_animation() {
            Theme.ambientMotion = false;
            verify(!orb.animating, "must honour the reduced-motion setting");
            Theme.ambientMotion = true;
        }

        function test_fault_is_still_data() {
            return [
                { tag: "ERROR", state: "ERROR" },
                { tag: "OFFLINE", state: "OFFLINE" },
            ];
        }

        function test_fault_is_still(row) {
            orb.assistantState = row.state;
            verify(orb.faulted, row.state + " must count as a fault");
            verify(!orb.animating,
                   "a fault must be still: a fault is not a mood");
            compare(orb.tint, Theme.error, "a fault must be red");
        }

        function test_ring_period_by_state_data() {
            return [
                { tag: "PROCESSING", state: "PROCESSING", period: 9000 },
                { tag: "EXECUTING", state: "EXECUTING", period: 12000 },
                { tag: "LISTENING", state: "LISTENING", period: 20000 },
                { tag: "SPEAKING", state: "SPEAKING", period: 20000 },
                { tag: "STANDBY", state: "STANDBY", period: 38000 },
            ];
        }

        function test_ring_period_by_state(row) {
            orb.assistantState = row.state;
            compare(orb.ringPeriod, row.period,
                    row.state + " should revolve at its own pace");
        }

        function test_working_states_turn_faster_than_idle() {
            orb.assistantState = "STANDBY";
            var idle = orb.ringPeriod;
            orb.assistantState = "PROCESSING";
            verify(orb.ringPeriod < idle,
                   "thinking must visibly outpace standing by");
        }

        function test_thinking_swells() {
            orb.assistantState = "PROCESSING";
            // swell is driven by a Behavior, so it eases towards the target
            // rather than arriving on the next line.
            tryVerify(function () { return orb.swell > 1.0; }, 2000,
                      "the assembly should swell while thinking");
            orb.assistantState = "STANDBY";
            tryCompare(orb, "swell", 1.0, 2000);
        }

        function test_bar_count_is_clamped_data() {
            return [
                { tag: "tiny", size: 40, min: 36, max: 36 },
                { tag: "large", size: 2000, min: 120, max: 120 },
            ];
        }

        function test_bar_count_is_clamped(row) {
            var previous = 400;
            orb.width = row.size;
            orb.height = row.size;
            verify(orb.barCount >= row.min && orb.barCount <= row.max,
                   "barCount " + orb.barCount + " out of range at "
                   + row.size + "px");
            orb.width = previous;
            orb.height = previous;
        }

        function test_no_progress_arc_without_measured_progress() {
            orb.assistantState = "EXECUTING";
            orb.activity = -1;
            verify(!orb.showsProgress,
                   "must not imply progress that was never measured (D20)");
        }

        function test_progress_arc_appears_when_supplied() {
            orb.assistantState = "EXECUTING";
            orb.activity = 0.5;
            verify(orb.showsProgress,
                   "real progress should be drawn when it exists");
        }
    }
}
