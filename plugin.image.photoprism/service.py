# -*- coding: utf-8 -*-
"""KodiPrism background service: restores Kodi's pan/zoom slideshow effect after an add-on slideshow."""
import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib import slideshow_fx
from resources.lib.logger import AddonLog


def main():
    addon = xbmcaddon.Addon()
    profile = xbmcvfs.translatePath(addon.getAddonInfo("profile"))
    log = AddonLog(addon.getAddonInfo("id"), profile, addon.getSetting("debug_log") == "true")
    guard = slideshow_fx.Guard(xbmc.executeJSONRPC, profile, log)
    home = xbmcgui.Window(10000)
    home.setProperty(slideshow_fx.SERVICE_PROP, "1")
    try:
        slideshow_fx.service_loop(guard, xbmc.Monitor(),
                                  lambda: xbmc.getCondVisibility("Window.IsActive(slideshow)"))
    finally:
        home.clearProperty(slideshow_fx.SERVICE_PROP)


main()
