import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*! Tests for the wall clock. */
Item {
    width: 400
    height: 120

    HudClock {
        id: clock
        anchors.centerIn: parent
    }

    TestCase {
        name: "HudClock"
        when: windowShown

        function test_time_is_formatted_as_a_full_24_hour_clock() {
            clock.now = new Date(2026, 8, 4, 9, 3, 28);
            compare(clock.timeText, "09:03:28",
                    "hours must be zero-padded and seconds shown");
        }

        function test_date_and_weekday_are_derived_from_the_same_instant() {
            clock.now = new Date(2026, 8, 4, 9, 3, 28);
            compare(clock.dayText, "4 SEP");
            compare(clock.weekdayText, "FRIDAY");
        }

        function test_digits_do_not_change_width_across_values() {
            // A proportional face would make the clock jitter every second.
            clock.now = new Date(2026, 8, 4, 11, 11, 11);
            var narrow = clock.width;
            clock.now = new Date(2026, 8, 4, 20, 48, 56);
            compare(clock.width, narrow,
                    "the clock must not resize as the digits change");
        }

        function test_clock_advances() {
            var before = clock.timeText;
            clock.now = new Date(2026, 8, 4, 9, 3, 29);
            verify(clock.timeText !== before, "the clock must track its date");
        }
    }
}
