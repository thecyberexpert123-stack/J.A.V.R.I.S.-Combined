import QtQuick
import QtQuick.Window
import javris.core
import javris.ui

/*!
    Top-level window. Frameless and full screen by default, as a HUD should
    occupy the whole field of view; --windowed overrides this for development
    and for tiling window managers.
*/
Window {
    id: window

    // Sized for a windowed session; ignored when shown full screen.
    width: 1440
    height: 900
    minimumWidth: 960
    minimumHeight: 640

    visible: true
    color: Theme.backgroundDeep
    title: "J.A.V.R.I.S."

    flags: Hud.windowed ? Qt.Window : (Qt.Window | Qt.FramelessWindowHint)
    visibility: Hud.windowed ? Window.Windowed : Window.FullScreen

    HudSurface {
        anchors.fill: parent
        controller: Hud
    }
}
