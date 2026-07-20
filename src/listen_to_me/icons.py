"""Microphone icons drawn with Pillow — no binary assets needed."""

from __future__ import annotations

COLORS = {
    "idle": "#9aa0a6",
    "recording": "#e5484d",
    "processing": "#f2a33c",
    "app": "#3d8bfd",
}


def _draw_mic(draw, color, scale: float, dx: float = 0.0, dy: float = 0.0) -> None:
    """Draw the microphone glyph (designed on a 64x64 grid) scaled/offset."""
    stroke = max(2, round(5 * scale))

    def box(*values):
        # Alternating x/y coordinates: even indices are x, odd are y.
        return [v * scale + (dx if i % 2 == 0 else dy) for i, v in enumerate(values)]

    # capsule body
    draw.rounded_rectangle(box(23, 6, 41, 38), radius=9 * scale, fill=color)
    # pickup arc
    draw.arc(box(15, 18, 49, 48), start=0, end=180, fill=color, width=stroke)
    # stem and base
    draw.line(box(32, 48, 32, 56), fill=color, width=stroke)
    draw.line(box(22, 57, 42, 57), fill=color, width=stroke)


def mic_image(state: str = "idle", size: int = 64):
    from PIL import Image, ImageDraw

    color = COLORS.get(state, COLORS["idle"])
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    _draw_mic(ImageDraw.Draw(image), color, size / 64.0)
    return image
