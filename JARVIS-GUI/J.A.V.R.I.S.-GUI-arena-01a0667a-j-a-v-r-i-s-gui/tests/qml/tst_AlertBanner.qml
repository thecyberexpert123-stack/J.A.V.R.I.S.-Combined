import QtQuick
import QtTest
import javris.ui
import javris.ui.components

/*!
    Property assertions for AlertBanner and TargetReticle - the visible half of
    attention escalation (docs/RESEARCH.md, D9-D13).

    These check computed properties rather than comparing bitmaps, per Qt's
    testing guidance.
*/
TestCase {
    id: testCase

    name: "AlertBanner"
    width: 600
    height: 400
    visible: true
    when: windowShown

    Component {
        id: bannerComponent

        AlertBanner {
            width: 480
        }
    }

    Component {
        id: reticleComponent

        TargetReticle {
            width: 200
            height: 120
        }
    }

    function test_inactive_banner_is_invisible() {
        let banner = createTemporaryObject(bannerComponent, testCase);
        verify(banner !== null);
        compare(banner.active, false);
        compare(banner.visible, false, "an unescalated banner must not occupy the display");
    }

    function test_active_banner_becomes_visible() {
        let banner = createTemporaryObject(bannerComponent, testCase, { active: true });
        tryVerify(function () { return banner.visible; });
        tryCompare(banner, "opacity", 1);
    }

    function test_critical_uses_the_error_colour() {
        let banner = createTemporaryObject(bannerComponent, testCase, {
            active: true, severity: "CRITICAL"
        });
        compare(banner.severityColor, Theme.error);
    }

    function test_warn_uses_the_warn_colour() {
        let banner = createTemporaryObject(bannerComponent, testCase, {
            active: true, severity: "WARN"
        });
        compare(banner.severityColor, Theme.warn);
    }

    function test_unknown_severity_degrades_to_warn_not_to_calm() {
        // An alert is on screen, so it must never render in a calm colour.
        let banner = createTemporaryObject(bannerComponent, testCase, {
            active: true, severity: ""
        });
        compare(banner.severityColor, Theme.warn);
        verify(banner.severityColor !== Theme.primary);
    }

    function test_banner_reserves_room_for_the_hero_readout() {
        // D10: escalation is carried by contrast and size, not extra detail.
        let banner = createTemporaryObject(bannerComponent, testCase, {
            active: true, readout: "97.4", unit: "%", label: "Memory pressure"
        });
        verify(Theme.fontSizeHero > Theme.fontSizeXl);
        verify(banner.implicitHeight > Theme.fontSizeHero);
    }

    function test_reticle_starts_retracted_and_distant() {
        let reticle = createTemporaryObject(reticleComponent, testCase);
        compare(reticle.acquired, false);
        compare(reticle.locked, false);
        compare(reticle.opacity, 0);
    }

    function test_reticle_locks_after_acquiring() {
        // D13: acquire, then annotate. The brackets converge from a larger
        // scale before the annotation is considered attached.
        let reticle = createTemporaryObject(reticleComponent, testCase);
        verify(reticle.approachScale > 1, "reticle must arrive from depth, not fade in place");
        reticle.acquired = true;
        tryVerify(function () { return reticle.locked; });
        tryCompare(reticle, "opacity", 1);
    }

    function test_reticle_retracts_when_released() {
        let reticle = createTemporaryObject(reticleComponent, testCase, { acquired: true });
        tryVerify(function () { return reticle.locked; });
        reticle.acquired = false;
        compare(reticle.locked, false);
        tryCompare(reticle, "opacity", 0);
    }
}
