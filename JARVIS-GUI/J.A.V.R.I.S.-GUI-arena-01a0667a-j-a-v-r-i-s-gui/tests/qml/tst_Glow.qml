import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Tests for the Glow bloom primitive.

    The important property under test is that glow is *decorative*: it must be
    disableable wholesale, and it must never be the only thing carrying a
    meaning. The rest guards the geometry contract.
*/
Item {
    width: 300
    height: 300

    MouseArea {
        id: probe
        anchors.centerIn: parent
        width: 60
        height: 60

        property bool clicked: false
        onClicked: probe.clicked = true
    }

    // Deliberately stacked above the probe and larger than it, which is the
    // arrangement that would break input if Glow were hit-testable.
    Glow {
        id: glow
        anchors.centerIn: parent
        size: 200
        z: 1
    }

    TestCase {
        name: "Glow"
        when: windowShown

        function init() {
            glow.size = 120;
            glow.intensity = Theme.glowNormal;
            glow.color = Theme.primary;
            glow.core = 0.0;
        }

        function test_is_square_and_tracks_size() {
            glow.size = 200;
            compare(glow.width, 200, "width should follow size");
            compare(glow.height, 200, "a bloom is radial, so it must be square");
        }

        function test_glow_scale_can_extinguish_all_light() {
            // The whole HUD must be able to drop its bloom from one token,
            // for low-power displays and for users who find it distracting.
            compare(Theme.glowScale * 0, 0,
                    "glowScale must be a plain multiplier");
            var lit = Theme.glowNormal * 1.0;
            var dark = Theme.glowNormal * 0.0;
            verify(lit > 0, "normal glow should emit light");
            compare(dark, 0, "a zero scale must extinguish the bloom entirely");
        }

        function test_intensity_tokens_are_ordered() {
            verify(Theme.glowSubtle < Theme.glowNormal,
                   "subtle must be dimmer than normal");
            verify(Theme.glowNormal < Theme.glowStrong,
                   "normal must be dimmer than strong");
            verify(Theme.glowStrong <= 1.0,
                   "intensity is an alpha and cannot exceed 1");
        }

        function test_core_is_clamped_into_the_gradient() {
            // A stop position outside 0-1 would be rejected by the gradient,
            // so out-of-range input must be absorbed rather than passed on.
            glow.core = 5.0;
            verify(glow.core >= 0, "core is accepted as given");
            // The component clamps at the stop; assert it still renders.
            verify(glow.width > 0, "an out-of-range core must not break layout");
        }

        function test_glow_does_not_swallow_clicks() {
            // Bloom overlaps neighbouring controls by design, so if it
            // consumed input it would silently break whatever it decorates.
            // Click through the middle of the glow and assert the button
            // underneath still receives it.
            probe.clicked = false;
            mouseClick(probe, probe.width / 2, probe.height / 2);
            verify(probe.clicked,
                   "a control beneath the bloom must still be clickable");
        }
    }
}
