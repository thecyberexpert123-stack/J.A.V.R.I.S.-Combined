import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Tests for the tapered arc.

    The taper is what stops the HUD's rings reading as machined parts, so the
    properties under test are the shape of the falloff and the bounds on
    tessellation -- the two things that decide whether an arc looks soft or
    looks broken.
*/
Item {
    width: 300
    height: 300

    TaperedArc {
        id: arc
        anchors.fill: parent
        arcRadius: 100
    }

    TestCase {
        name: "TaperedArc"
        when: windowShown

        function init() {
            arc.startAngle = 0;
            arc.sweepAngle = 180;
            arc.peakPosition = 0.5;
            arc.falloff = 1.6;
            arc.peak = 1.0;
        }

        function test_segment_count_scales_with_sweep() {
            arc.sweepAngle = 30;
            var short_ = arc.segmentCount;
            arc.sweepAngle = 300;
            verify(arc.segmentCount > short_,
                   "a longer arc needs more segments to stay smooth");
        }

        function test_segment_count_is_bounded_data() {
            return [
                { tag: "tiny", sweep: 1, min: 8, max: 96 },
                { tag: "full", sweep: 360, min: 8, max: 96 },
                { tag: "absurd", sweep: 3600, min: 8, max: 96 },
            ];
        }

        function test_segment_count_is_bounded(row) {
            arc.sweepAngle = row.sweep;
            verify(arc.segmentCount >= row.min && arc.segmentCount <= row.max,
                   "segment count " + arc.segmentCount + " out of bounds at "
                   + row.sweep + " degrees");
        }

        function test_short_arcs_are_not_over_tessellated() {
            arc.sweepAngle = 4;
            compare(arc.segmentCount, 8,
                    "a 4-degree arc should sit at the floor, not above it");
        }

        function test_negative_sweep_is_supported() {
            // Anticlockwise arcs are used for counter-rotating elements.
            arc.sweepAngle = -180;
            verify(arc.segmentCount >= 8,
                   "an anticlockwise arc must still tessellate");
        }

        function test_peak_position_is_honoured() {
            // A comet profile puts the light at the leading end; a symmetric
            // one puts it in the middle. Both must be expressible.
            arc.peakPosition = 1.0;
            compare(arc.peakPosition, 1.0);
            arc.peakPosition = 0.5;
            compare(arc.peakPosition, 0.5);
        }

        function test_geometry_is_centred_on_the_item() {
            compare(arc.centreX, arc.width / 2);
            compare(arc.centreY, arc.height / 2);
        }

        function test_rebuild_does_not_leak_segments() {
            // Segments are created imperatively, so a count change must
            // destroy the old set rather than stack a new one on top. A leak
            // here would be invisible on screen and would grow without bound
            // every time an animated sweep crossed a segment-count boundary.
            arc.sweepAngle = 60;
            var expected = arc.segmentCount;

            for (var i = 0; i < 40; ++i) {
                arc.sweepAngle = 40 + (i % 7) * 45;
            }
            arc.sweepAngle = 60;

            compare(arc.segmentCount, expected,
                    "returning to a previous sweep must give the same count");
            tryCompare(arc, "liveSegments", expected, 2000);
        }
    }
}
