import QtQuick
import QtTest
import javris.ui.components

/*!
    Property assertions for Gauge.

    Per Qt's testing guidance these check computed properties rather than
    comparing bitmaps, which would be flaky across resolutions, themes and
    font availability.
*/
TestCase {
    id: testCase

    name: "Gauge"
    width: 200
    height: 200
    visible: true
    when: windowShown

    Component {
        id: gaugeComponent

        Gauge {
            width: 120
            height: 120
        }
    }

    function test_sweep_is_zero_at_zero() {
        const gauge = createTemporaryObject(gaugeComponent, testCase, { value: 0 });
        verify(gauge);
        compare(gauge.sweepAngle, 0);
        verify(gauge.available);
    }

    function test_sweep_is_half_range_at_midpoint() {
        const gauge = createTemporaryObject(gaugeComponent, testCase, { value: 0.5 });
        compare(gauge.sweepAngle, gauge.sweepRange * 0.5);
    }

    function test_sweep_is_full_range_at_one() {
        const gauge = createTemporaryObject(gaugeComponent, testCase, { value: 1.0 });
        compare(gauge.sweepAngle, gauge.sweepRange);
    }

    function test_sweep_is_clamped_above_one() {
        // A miscomputed fraction must not wrap the arc past its own track.
        const gauge = createTemporaryObject(gaugeComponent, testCase, { value: 4.2 });
        compare(gauge.sweepAngle, gauge.sweepRange);
    }

    function test_negative_value_reads_as_unavailable() {
        const gauge = createTemporaryObject(gaugeComponent, testCase, { value: -1 });
        verify(!gauge.available);
        compare(gauge.sweepAngle, 0);
    }

    function test_label_and_unit_are_exposed() {
        const gauge = createTemporaryObject(gaugeComponent, testCase, {
            value: 0.25,
            label: "CPU",
            readout: "25.0",
            unit: "%"
        });
        compare(gauge.label, "CPU");
        compare(gauge.unit, "%");
        compare(gauge.readout, "25.0");
    }

    function test_sweep_tracks_value_changes() {
        const gauge = createTemporaryObject(gaugeComponent, testCase, { value: 0 });
        gauge.value = 0.25;
        compare(gauge.sweepAngle, gauge.sweepRange * 0.25);
        gauge.value = 0.75;
        compare(gauge.sweepAngle, gauge.sweepRange * 0.75);
    }
}
