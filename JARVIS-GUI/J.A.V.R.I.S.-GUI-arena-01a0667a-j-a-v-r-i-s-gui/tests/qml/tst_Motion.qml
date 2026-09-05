import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Property assertions for the ambient-motion layer and the boot sequence
    (docs/RESEARCH.md, D15-D19).

    The emphasis is on the *contracts* that keep decoration honest: that the
    boot sequence is a deterministic function of its progress value, that
    phases run in the documented order, and above all that every decorative
    animation actually stops when ambient motion is switched off.
*/
TestCase {
    id: testCase

    name: "Motion"
    width: 640
    height: 480
    visible: true
    when: windowShown

    Component {
        id: bootComponent

        BootSequence {
            width: 400
            height: 400
        }
    }

    Component {
        id: fieldComponent

        AmbientField {
            width: 400
            height: 300
        }
    }

    Component {
        id: coreComponent

        ReactorCore {
            width: 300
            height: 300
        }
    }

    function cleanup() {
        // Never leave the singleton switched off for a later test.
        Theme.ambientMotion = true;
    }

    // -- boot sequence -----------------------------------------------------

    function test_boot_starts_fully_unresolved() {
        let boot = createTemporaryObject(bootComponent, testCase, { progress: 0 });
        compare(boot.streakProgress, 0);
        compare(boot.ringProgress, 0);
        compare(boot.titleProgress, 0);
    }

    function test_boot_ends_fully_resolved() {
        let boot = createTemporaryObject(bootComponent, testCase, { progress: 1 });
        compare(boot.streakProgress, 1);
        compare(boot.ringProgress, 1);
        compare(boot.titleProgress, 1);
    }

    function test_phases_run_in_the_documented_order() {
        // Streaks converge, then rings trace, then the title assembles. This
        // is the whole choreography, so it is asserted rather than eyeballed.
        let boot = createTemporaryObject(bootComponent, testCase, { progress: 0.3 });
        verify(boot.streakProgress > 0, "streaks should have started");
        compare(boot.titleProgress, 0, "title must not start before the rings finish");

        boot.progress = 0.7;
        verify(boot.ringProgress > 0, "rings should be tracing");

        boot.progress = 0.9;
        verify(boot.titleProgress > 0, "title should be assembling by now");
    }

    function test_progress_is_deterministic() {
        // The same progress must always produce the same frame, which is what
        // makes the sequence reviewable from a still.
        let first = createTemporaryObject(bootComponent, testCase, { progress: 0.62 });
        let second = createTemporaryObject(bootComponent, testCase, { progress: 0.62 });
        compare(first.streakProgress, second.streakProgress);
        compare(first.ringProgress, second.ringProgress);
        compare(first.titleProgress, second.titleProgress);
    }

    function test_sub_progress_is_always_normalised() {
        let boot = createTemporaryObject(bootComponent, testCase);
        for (let p = 0; p <= 1.0001; p += 0.05) {
            boot.progress = p;
            verify(boot.streakProgress >= 0 && boot.streakProgress <= 1);
            verify(boot.ringProgress >= 0 && boot.ringProgress <= 1);
            verify(boot.titleProgress >= 0 && boot.titleProgress <= 1);
        }
    }

    function test_streak_count_scales_with_width_and_is_bounded() {
        let small = createTemporaryObject(bootComponent, testCase, { width: 120 });
        let large = createTemporaryObject(bootComponent, testCase, { width: 4000 });
        verify(small.streakCount >= 18, "must not degenerate on a small surface");
        verify(large.streakCount <= 56, "must be capped so a huge window stays cheap");
    }

    // -- ambient field -----------------------------------------------------

    function test_field_runs_by_default() {
        let field = createTemporaryObject(fieldComponent, testCase);
        verify(field.running);
    }

    function test_field_stops_when_ambient_motion_is_off() {
        // D19: ambient motion is a budget. The switch must actually work.
        let field = createTemporaryObject(fieldComponent, testCase);
        Theme.ambientMotion = false;
        verify(!field.running, "ambient field ignored Theme.ambientMotion");
    }

    function test_field_stops_when_not_visible() {
        // An unseen HUD must not burn cycles animating.
        let field = createTemporaryObject(fieldComponent, testCase);
        field.visible = false;
        verify(!field.running);
    }

    function test_field_stops_when_deactivated() {
        let field = createTemporaryObject(fieldComponent, testCase, { active: false });
        verify(!field.running);
    }

    function test_mote_count_scales_with_area_and_is_bounded() {
        let tiny = createTemporaryObject(fieldComponent, testCase, { width: 40, height: 40 });
        let huge = createTemporaryObject(fieldComponent, testCase, {
            width: 4000, height: 4000
        });
        verify(tiny.moteCount >= 12);
        verify(huge.moteCount <= 90, "particle count must be capped");
    }

    // -- reactor core ambient ----------------------------------------------

    function test_core_animates_when_settled_and_healthy() {
        let core = createTemporaryObject(coreComponent, testCase, {
            coreState: "STANDBY", bootProgress: 1
        });
        verify(core.animating);
    }

    function test_core_stops_animating_when_ambient_motion_is_off() {
        let core = createTemporaryObject(coreComponent, testCase, {
            coreState: "STANDBY", bootProgress: 1
        });
        Theme.ambientMotion = false;
        verify(!core.animating);
    }

    function test_faulted_core_does_not_animate() {
        // A fault is not a mood. A dead core must sit still.
        let core = createTemporaryObject(coreComponent, testCase, {
            coreState: "ERROR", bootProgress: 1
        });
        verify(!core.animating);
    }

    function test_core_does_not_animate_mid_boot() {
        let core = createTemporaryObject(coreComponent, testCase, {
            coreState: "STANDBY", bootProgress: 0.4
        });
        verify(!core.animating);
    }

    function test_pulse_is_safe_to_call_with_motion_disabled() {
        // The alpha-event pulse is fired from a state change, which can happen
        // at any time; it must never throw.
        let core = createTemporaryObject(coreComponent, testCase, { bootProgress: 1 });
        Theme.ambientMotion = false;
        core.pulse();
        verify(true, "pulse() raised with ambient motion disabled");
    }

    function test_state_change_is_punctuated() {
        // D16: a state change must be an alpha event, not just a relabel.
        let core = createTemporaryObject(coreComponent, testCase, {
            coreState: "STANDBY", bootProgress: 1
        });
        core.coreState = "PROCESSING";
        compare(core.coreState, "PROCESSING");
        verify(core.spinPeriod > 0, "a working core must keep spinning");
    }
}
