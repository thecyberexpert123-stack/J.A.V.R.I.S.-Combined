import QtQuick
import QtQuick.Particles
import javris.ui

/*!
    The atmosphere layer: drifting motes, a slow scanline and a vignette.

    This is the "the machine is alive and running" layer. It carries no data
    whatsoever, which is precisely why it is bound by strict rules
    (docs/RESEARCH.md, D18-D19): the source material's own critique is that the
    reference HUD is "a massive distraction", with 87% of its elements moving
    without being asked and several risking startle by expanding in place.

    So everything here is:

    \list
    \li \b slow — periods of several seconds, never a twitch;
    \li \b{low contrast} — motes sit near the background luminance;
    \li \b{behind everything} — it never overlaps a readout;
    \li \b interruptible — the whole layer stops on \c Theme.ambientMotion, and
        stops itself when not \c visible so an unseen HUD burns no cycles.
    \endlist

    Particle count scales with area rather than being a fixed number, so a
    small window is not saturated and a large one is not sparse.
*/
Item {
    id: root

    /*! Master enable. Combined with \c Theme.ambientMotion. */
    property bool active: true
    /*! 0.0-1.0 fade-in used during boot. */
    property real intensity: 1

    /*! True when the layer should actually be animating. Read by tests. */
    readonly property bool running: root.active && Theme.ambientMotion
                                    && root.visible && root.intensity > 0

    /*! Motes scale with area: roughly one per 14000 square pixels, capped. */
    readonly property int moteCount: Math.max(
        12, Math.min(90, Math.round(width * height / 14000)))

    clip: true

    ParticleSystem {
        id: system
        // Pausing rather than stopping keeps the existing motes in place, so
        // toggling ambient motion does not visibly re-seed the field.
        paused: !root.running
    }

    ImageParticle {
        system: system
        color: Theme.primary
        colorVariation: 0.25
        alpha: 0
        entryEffect: ImageParticle.Fade
    }

    Emitter {
        system: system
        anchors.fill: parent
        emitRate: root.moteCount / 9
        lifeSpan: Theme.periodDrift
        lifeSpanVariation: Theme.periodDrift / 2
        size: 2
        sizeVariation: 2
        endSize: 1

        // A gentle, mostly-upward drift with lateral variation: convection,
        // not wind. Magnitudes are a few pixels per second.
        velocity: AngleDirection {
            angle: 270
            angleVariation: 55
            magnitude: 5
            magnitudeVariation: 4
        }
    }

    // -- scanline ----------------------------------------------------------
    // A single soft band traversing the surface. One band, not a raster of
    // them: a full scanline overlay reduces legibility of every glyph beneath
    // it, which D14 rules out for a tool that must stay readable.
    Rectangle {
        id: scanline

        width: parent.width
        height: Math.max(60, parent.height * 0.12)
        opacity: 0.5 * root.intensity
        visible: root.running

        gradient: Gradient {
            GradientStop { position: 0.0; color: "transparent" }
            GradientStop { position: 0.5; color: Theme.grid }
            GradientStop { position: 1.0; color: "transparent" }
        }

        NumberAnimation on y {
            running: root.running
            from: -scanline.height
            to: root.height
            duration: Theme.periodScanline
            loops: Animation.Infinite
        }
    }

    // -- vignette ----------------------------------------------------------
    // Darkened edges. This is not only atmosphere: it raises the relative
    // contrast of the centre, which is where escalated alerts appear (D10).
    // Static, so it costs nothing per frame.
    Rectangle {
        anchors.fill: parent
        opacity: 0.55 * root.intensity

        gradient: Gradient {
            orientation: Gradient.Vertical
            GradientStop { position: 0.0; color: Theme.backgroundDeep }
            GradientStop { position: 0.35; color: "transparent" }
            GradientStop { position: 0.65; color: "transparent" }
            GradientStop { position: 1.0; color: Theme.backgroundDeep }
        }
    }
}
