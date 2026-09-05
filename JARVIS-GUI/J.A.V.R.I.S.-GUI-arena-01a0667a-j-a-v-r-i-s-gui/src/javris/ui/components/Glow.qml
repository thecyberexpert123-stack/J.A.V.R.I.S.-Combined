import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    A soft radial bloom, used to make emissive elements read as lit rather than
    drawn.

    \b{Why not MultiEffect.} Qt's \c MultiEffect is the obvious tool for this
    and it is available in the runtime, but it requires a GPU shader path: with
    \c QT_QUICK_BACKEND=software it renders the source item as *nothing at all*
    rather than degrading to an unblurred copy. An effect that can silently
    blank a element on a machine without working GL is not acceptable in an
    always-on HUD, so the bloom here is built from a radial gradient, which the
    software renderer draws correctly. Verified by rendering both.

    This is purely decorative and never conveys information on its own: a glow
    only ever accompanies an element that is already legible without it, so
    losing the bloom costs atmosphere and no meaning.

    Place it \e behind the element it lights, centred on the same point:

    \qml
    Glow { anchors.centerIn: ring; size: ring.width * 1.8; color: Theme.primary }
    \endqml
*/
Item {
    id: root

    /*! Diameter of the bloom. Typically 1.5-2x the lit element. */
    property real size: 120

    /*! Hue of the light. */
    property color color: Theme.primary

    /*!
        Peak opacity at the centre, 0-1. Kept low by default: bloom accumulates
        wherever glows overlap, and the reference HUD stays dark overall.
    */
    property real intensity: 0.35

    /*!
        Fraction of the radius that stays near-peak before falling off.
        Lower values give a tight hot core; higher values a broad haze.
    */
    property real core: 0.0

    implicitWidth: root.size
    implicitHeight: root.size
    width: root.size
    height: root.size

    // The bloom is light, so it adds to what is beneath it rather than
    // occluding it. This is what stops overlapping glows looking like flat
    // discs of paint.
    layer.enabled: false

    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        // Bloom is never interactive and never a hit target.
        containsMode: Shape.BoundingRectContains

        ShapePath {
            strokeWidth: -1
            fillGradient: RadialGradient {
                centerX: root.width / 2
                centerY: root.height / 2
                centerRadius: root.width / 2
                focalX: root.width / 2
                focalY: root.height / 2

                // Three stops rather than two: a linear fade to transparent
                // reads as a visible disc edge, whereas an eased falloff reads
                // as light. The middle stop is what sells it.
                GradientStop {
                    position: Math.max(0, Math.min(0.9, root.core))
                    color: Qt.rgba(root.color.r, root.color.g, root.color.b,
                                   root.intensity)
                }
                GradientStop {
                    position: 0.5
                    color: Qt.rgba(root.color.r, root.color.g, root.color.b,
                                   root.intensity * 0.28)
                }
                GradientStop {
                    position: 1.0
                    color: Qt.rgba(root.color.r, root.color.g, root.color.b, 0)
                }
            }

            PathAngleArc {
                centerX: root.width / 2
                centerY: root.height / 2
                radiusX: root.width / 2
                radiusY: root.height / 2
                startAngle: 0
                sweepAngle: 360
            }
        }
    }
}
