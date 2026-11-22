#!/usr/bin/env python3
"""Render assets/*.svg into the add-on's icon.png (512x512) and fanart.jpg (1920x1080).

Requires: pip install cairosvg pillow   (cairosvg needs the system cairo library)
Kodi's add-on checker rejects icons with transparency, so the icon is flattened
to RGB; the SVG already has a full-bleed background.
"""
import io
import os

import cairosvg
from PIL import Image

ROOT = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
RES = os.path.join(ROOT, "plugin.image.photoprism", "resources")


def render(svg, width, height):
    png = cairosvg.svg2png(url=os.path.join(ROOT, "assets", svg), output_width=width,
                           output_height=height, background_color="#ffffff")
    return Image.open(io.BytesIO(png)).convert("RGB")


if __name__ == "__main__":
    render("icon.svg", 512, 512).save(os.path.join(RES, "icon.png"), optimize=True)
    render("fanart.svg", 1920, 1080).save(os.path.join(RES, "fanart.jpg"), quality=90, optimize=True)
    print("icon.png and fanart.jpg written to", os.path.relpath(RES, ROOT))
