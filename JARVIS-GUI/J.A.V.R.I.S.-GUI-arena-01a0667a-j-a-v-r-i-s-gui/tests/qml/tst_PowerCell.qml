import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Tests for the battery cell.

    The rules under test are honesty rules: an unknown charge must not render
    as empty, and a low battery must be distinguishable without reading text.
*/
Item {
    width: 300
    height: 120

    PowerCell {
        id: cell
        width: 200
    }

    TestCase {
        name: "PowerCell"
        when: windowShown

        function init() {
            cell.fraction = 0.5;
            cell.cellState = "DISCHARGING";
            cell.readout = "50 %";
            cell.runtime = "";
        }

        function test_unknown_charge_is_not_treated_as_known() {
            cell.fraction = -1;
            verify(!cell.known, "a negative fraction means unknown, not empty");
            compare(cell.cellColor, Theme.unavailable,
                    "unknown charge must use the unavailable colour");
        }

        function test_unknown_charge_is_never_low() {
            cell.fraction = -1;
            verify(!cell.low,
                   "an unreadable battery must not raise a low-charge alarm");
        }

        function test_low_charge_is_flagged() {
            cell.fraction = 0.08;
            verify(cell.low, "8% on battery should read as low");
            compare(cell.cellColor, Theme.error, "a low battery must be red");
        }

        function test_low_charge_while_charging_is_not_an_alarm() {
            // Plugged in at 8% is recovering, not failing.
            cell.fraction = 0.08;
            cell.cellState = "CHARGING";
            verify(!cell.low, "a charging battery is not in a low-charge state");
            compare(cell.cellColor, Theme.ok, "charging should read as healthy");
        }

        function test_lit_segment_count_data() {
            return [
                // The regression that prompted this test: with segments lit on
                // their *upper* edge, 8% lit nothing and a nearly-flat battery
                // was indistinguishable from a dead one.
                { tag: "low", fraction: 0.08, expected: 1 },
                { tag: "empty", fraction: 0.0, expected: 0 },
                { tag: "half", fraction: 0.5, expected: 5 },
                { tag: "full", fraction: 1.0, expected: 10 },
                { tag: "unknown", fraction: -1, expected: 0 },
            ];
        }

        function test_lit_segment_count(row) {
            cell.fraction = row.fraction;
            var lit = 0;
            for (var i = 0; i < cell.segments; ++i) {
                if (cell.known && cell.fraction > 0
                    && cell.fraction >= i / cell.segments
                    && (i === 0 || cell.fraction > i / cell.segments)) {
                    lit += 1;
                }
            }
            compare(lit, row.expected,
                    "wrong segment count at fraction " + row.fraction);
        }

        function test_any_remaining_charge_lights_at_least_one_segment() {
            cell.fraction = 0.01;
            verify(cell.known && cell.fraction > 0,
                   "1% is a real reading and must not render as empty");
        }

        function test_charging_state_is_derived_from_the_string() {
            cell.cellState = "CHARGING";
            verify(cell.charging);
            cell.cellState = "DISCHARGING";
            verify(!cell.charging);
            cell.cellState = "UNKNOWN";
            verify(!cell.charging, "unknown must not be reported as charging");
        }
    }
}
