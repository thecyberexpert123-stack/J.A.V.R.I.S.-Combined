pragma ComponentBehavior: Bound

import QtQuick
import QtQuick.Shapes
import javris.ui

/*!
    An arc whose stroke fades along its own length.

    A \c PathAngleArc drawn with a single \c strokeColor has the same weight at
    both ends, which is what makes a Qt Quick HUD look rigid: every ring reads
    as a hard mechanical part, and where an arc begins and ends is arbitrary but
    unmissable. Real emissive displays -- and the reference material -- taper
    their arcs so a stroke emerges from nothing, peaks, and dissolves again.
    The eye reads the taper as motion direction and depth rather than as an
    edge, which is exactly the softness the solid version lacks.

    Qt Quick has no per-length gradient along a stroke. This builds the effect
    from short segments whose opacity follows an eased profile, which the
    software renderer draws correctly and which needs no shader.

    Segment count is bounded and scales with sweep, so a short arc is not
    over-tessellated and a long one does not band visibly.
*/
Item {
    id: root

    /*! Radius of the arc's centre line. */
    property real arcRadius: 100

    /*! Where the arc begins, in degrees. 0 is 3 o'clock, increasing clockwise. */
    property real startAngle: 0

    /*! Angular length, in degrees. Negative sweeps anticlockwise. */
    property real sweepAngle: 120

    /*! Stroke colour at full strength. */
    property color color: Theme.primary

    /*! Stroke thickness. */
    property real thickness: Theme.strokeMedium

    /*! Peak opacity at the arc's brightest point. */
    property real peak: 1.0

    /*!
        Where along the arc the stroke is brightest, 0-1.

        0.5 gives a symmetrical arc that fades at both ends. Values near 1.0
        give a comet profile: dim at the tail, brightest at the leading end,
        which is what makes a rotating scanner read as travelling rather than
        merely spinning.
    */
    property real peakPosition: 0.5

    /*!
        How sharply the stroke falls away from the peak. Higher concentrates
        the light into a shorter length.
    */
    property real falloff: 1.6

    /*! Round the bright end. Reads as a leading tip on comet profiles. */
    property bool roundCap: true

    //! Segments used to build the taper. Bounded so short arcs stay cheap.
    readonly property int segmentCount: Math.max(
        8, Math.min(96, Math.round(Math.abs(root.sweepAngle) / 2)))

    /*!
        Number of segment objects this component currently owns.

        Tracked explicitly rather than read from \c Shape.data.length, for two
        reasons: \c data is not notifiable, so a binding on it silently goes
        stale; and \c destroy() is deferred to the next event-loop pass, so
        \c data still lists the outgoing segments immediately after a rebuild.
        Counting what we created is the only reading that is true at the
        instant it is taken.
    */
    readonly property int liveSegments: root._segments.length

    //! Segment objects owned by this arc. Internal.
    property var _segments: []

    readonly property real centreX: width / 2
    readonly property real centreY: height / 2

    /*
        Built imperatively rather than with a Repeater.

        A Repeater can only produce Item delegates, and ShapePath is not an
        Item -- it silently emits "Delegate must be of Item type" and draws
        nothing. Instantiating the paths into Shape.data sidesteps that, and
        rebuilding only when the geometry actually changes keeps it off the
        animation path.
    */
    Shape {
        id: shape

        anchors.fill: parent
        asynchronous: true
        preferredRendererType: Shape.CurveRenderer
    }

    Component {
        id: segmentComponent

        ShapePath {
            id: piece

            property int index: 0

            //! Normalised position of this segment's midpoint, 0-1.
            readonly property real position: (piece.index + 0.5) / root.segmentCount

            //! Distance from the bright point, normalised to the longer side.
            readonly property real distance: {
                const delta = piece.position - root.peakPosition;
                const reach = delta >= 0
                    ? Math.max(0.0001, 1 - root.peakPosition)
                    : Math.max(0.0001, root.peakPosition);
                return Math.abs(delta) / reach;
            }

            //! Eased falloff, clamped so no segment goes negative.
            readonly property real strength:
                Math.max(0, root.peak
                            * Math.pow(1 - Math.min(1, piece.distance), root.falloff))

            readonly property real segmentSweep: root.sweepAngle / root.segmentCount

            // Overlap each segment slightly into the next. Butt-jointed
            // segments leave hairline gaps once antialiasing rounds the
            // endpoints, which reads as a dashed arc rather than a smooth one.
            // The final segment is not extended, so the arc ends exactly where
            // it was asked to.
            readonly property real overlap:
                piece.index === root.segmentCount - 1
                ? 0 : Math.abs(piece.segmentSweep) * 0.5

            strokeColor: Qt.rgba(root.color.r, root.color.g, root.color.b,
                                 piece.strength)
            strokeWidth: root.thickness
            fillColor: "transparent"
            capStyle: root.roundCap ? ShapePath.RoundCap : ShapePath.FlatCap

            PathAngleArc {
                centerX: root.centreX
                centerY: root.centreY
                radiusX: root.arcRadius
                radiusY: root.arcRadius
                startAngle: root.startAngle + piece.segmentSweep * piece.index
                sweepAngle: piece.segmentSweep
                            + piece.overlap * Math.sign(piece.segmentSweep)
            }
        }
    }

    function rebuild() {
        // Only the count forces a rebuild; every other property is bound
        // inside the segments and updates without re-instantiating them.
        const previous = root._segments;
        for (let i = 0; i < previous.length; ++i) {
            if (previous[i] !== null) {
                previous[i].destroy();
            }
        }

        const created = [];
        for (let i = 0; i < root.segmentCount; ++i) {
            const segment = segmentComponent.createObject(shape, { index: i });
            if (segment !== null) {
                created.push(segment);
            }
        }
        // Assigned once rather than pushed into: _segments is a var property,
        // and mutating the existing array in place would not emit a change.
        root._segments = created;
    }

    Component.onDestruction: {
        for (let i = 0; i < root._segments.length; ++i) {
            if (root._segments[i] !== null) {
                root._segments[i].destroy();
            }
        }
    }

    onSegmentCountChanged: root.rebuild()
    Component.onCompleted: root.rebuild()
}
