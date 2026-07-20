"""Animated microphone/equalizer icon for the floating overlay (issue #10).

A native QWidget port of the HTML/SVG animation this design came from:
- wavy, irregular ring outline: several overlaid sine harmonics plus a slowly
  drifting random phase jitter, drawn as a smoothed closed Catmull-Rom curve
- three frequency bands (low/mid/high), each cycling through its own 3-hue
  palette; the share each band gets on the ring (QConicalGradient) follows the
  measured band energy — idle the shares shimmer gently on their own, with
  real input the measured distribution takes over
- soft white glow behind the icon; the whole icon pulses with the volume
  (barely when idle, clearly while voice is coming in)

The widget does NOT capture the microphone itself. Drive it from outside:

    widget.set_recording(True)         # when recording starts
    widget.set_levels(low, mid, high)  # periodically, each 0.0-1.0
    widget.set_recording(False)        # when recording stops -> back to idle

While recording without fresh external levels it falls back to a gentle
simulation so it stays lively even if the level source drops out. set_levels
is a Qt slot, so a worker thread can drive it through a queued
Signal(float, float, float) connection instead of calling it directly.

The pixel amplitudes below were tuned on a 160 px canvas; the tick scales
them with the actual widget size so the overlay can embed the widget smaller.
"""

from __future__ import annotations

import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, QTimer, Slot
from PySide6.QtGui import QColor, QConicalGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .icons import COLORS

_TICK_MS_RECORDING = 16  # ~60 fps while the ring follows the live levels
_TICK_MS_IDLE = 33  # ~30 fps is plenty for the slow idle shimmer
_REFERENCE_SIZE = 160.0  # px canvas the ring/pulse amplitudes were tuned on
_LEVELS_FRESH_SECONDS = 0.35  # external levels older than this -> simulation


def _clamp01(v: float) -> float:
    return 0.0 if v < 0.0 else (1.0 if v > 1.0 else v)


def _lerp_hue(a: float, b: float, t: float) -> float:
    diff = ((b - a + 540.0) % 360.0) - 180.0
    return (a + diff * t) % 360.0


def _cycle_hue(palette: list[float], t: float, period: float) -> float:
    n = len(palette)
    pos = (t / period) % n
    idx = int(math.floor(pos))
    frac = pos - idx
    return _lerp_hue(palette[idx], palette[(idx + 1) % n], frac)


_HARMONICS = (
    # (freq, weight, speed, phase)
    (2, 1.0, 0.45, 0.3),
    (3, 0.8, -0.32, 2.0),
    (5, 0.5, 0.58, 4.1),
    (7, 0.25, -0.7, 1.1),
)
_HARMONIC_WEIGHT_SUM = sum(h[1] for h in _HARMONICS)
_RING_STEPS = 96


def _ring_points(cx: float, cy: float, base_r: float, amp_scale: float,
                 bulk_rotation: float, t: float, jitter: float) -> list[tuple[float, float]]:
    radii = []
    for i in range(_RING_STEPS):
        angle = (i / _RING_STEPS) * 2.0 * math.pi
        s = 0.0
        for freq, w, speed, phase in _HARMONICS:
            s += w * math.sin(freq * angle + t * speed + phase + jitter * freq * 0.25)
        radii.append(base_r + (s / _HARMONIC_WEIGHT_SUM) * amp_scale)

    for _ in range(2):
        smoothed = []
        n = _RING_STEPS
        for i in range(n):
            prev_r = radii[(i - 1) % n]
            cur_r = radii[i]
            next_r = radii[(i + 1) % n]
            smoothed.append(prev_r * 0.25 + cur_r * 0.5 + next_r * 0.25)
        radii = smoothed

    points = []
    for i in range(_RING_STEPS):
        angle = (i / _RING_STEPS) * 2.0 * math.pi
        x = cx + radii[i] * math.cos(angle + bulk_rotation)
        y = cy + radii[i] * math.sin(angle + bulk_rotation)
        points.append((x, y))
    return points


def _smooth_closed_path(points: list[tuple[float, float]]) -> QPainterPath:
    n = len(points)
    path = QPainterPath()
    path.moveTo(QPointF(*points[0]))
    for i in range(n):
        p0 = points[(i - 1) % n]
        p1 = points[i]
        p2 = points[(i + 1) % n]
        p3 = points[(i + 2) % n]
        c1x = p1[0] + (p2[0] - p0[0]) / 6.0
        c1y = p1[1] + (p2[1] - p0[1]) / 6.0
        c2x = p2[0] - (p3[0] - p1[0]) / 6.0
        c2y = p2[1] - (p3[1] - p1[1]) / 6.0
        path.cubicTo(QPointF(c1x, c1y), QPointF(c2x, c2y), QPointF(p2[0], p2[1]))
    path.closeSubpath()
    return path


def _build_mic_glyph_path(unit: float) -> tuple[QPainterPath, QPainterPath]:
    """Return (body path to fill, stand path to stroke) in a local -12..12
    coordinate system, scaled by `unit`."""
    body = QPainterPath()
    body.addRoundedRect(QRectF(-4 * unit, -11 * unit, 8 * unit, 14 * unit), 4 * unit, 4 * unit)

    stand = QPainterPath()
    r = 7 * unit
    cy = -2 * unit
    steps = 16
    first = True
    for i in range(steps + 1):
        a = math.pi * (i / steps)
        x = r * math.cos(a)
        y = cy + r * math.sin(a)
        if first:
            stand.moveTo(QPointF(x, y))
            first = False
        else:
            stand.lineTo(QPointF(x, y))
    stand.lineTo(QPointF(0, 10 * unit))
    stand.moveTo(QPointF(-5 * unit, 10 * unit))
    stand.lineTo(QPointF(5 * unit, 10 * unit))
    return body, stand


class VoiceMicWidget(QWidget):
    """Animated microphone/equalizer icon. See the module doc for integration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        self._t0 = time.perf_counter()
        self._recording = False
        self._processing = False

        self._smooth_volume = 0.0
        self._energy_low = 0.0
        self._energy_mid = 0.0
        self._energy_high = 0.0

        self._ext_low = 0.0
        self._ext_mid = 0.0
        self._ext_high = 0.0
        self._ext_volume = 0.0
        self._last_levels_time = -999.0

        self._phase_jitter = 0.0
        self._phase_jitter_target = 0.0
        self._next_jitter_time = 0.0
        self._jitter_interval = 3.0

        self._palette_low = [250.0, 270.0, 220.0]
        self._palette_mid = [150.0, 175.0, 195.0]
        self._palette_high = [20.0, 45.0, 5.0]

        self._scale = 1.0
        self._ring_path: QPainterPath | None = None
        self._gradient_stops: list[tuple[float, QColor]] = []
        self._shimmer_deg = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._on_tick)

    def sizeHint(self) -> QSize:
        return QSize(160, 160)

    # ------------------------------------------------------------ public API

    def set_recording(self, active: bool) -> None:
        """True when recording starts, False to return to the idle shimmer.
        While recording the mic glyph is tinted red (unless transcribing)."""
        self._recording = active
        if self._timer.isActive():
            self._timer.start(_TICK_MS_RECORDING if active else _TICK_MS_IDLE)

    def set_processing(self, active: bool) -> None:
        """Tint the mic glyph in the processing color while transcribing."""
        self._processing = active

    @Slot(float, float, float)
    def set_levels(self, low: float, mid: float, high: float) -> None:
        """Feed the current band energy, 0.0-1.0 per frequency band.
        Being a slot, it can be connected to a Signal(float, float, float)."""
        self.set_levels_full(low, mid, high, (low + mid + high) / 3.0)

    def set_levels_full(self, low: float, mid: float, high: float, volume: float) -> None:
        self._ext_low = _clamp01(low)
        self._ext_mid = _clamp01(mid)
        self._ext_high = _clamp01(high)
        self._ext_volume = _clamp01(volume)
        self._last_levels_time = time.perf_counter()

    # ------------------------------------------------------ internal animation

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._timer.start(_TICK_MS_RECORDING if self._recording else _TICK_MS_IDLE)

    def hideEvent(self, event) -> None:
        super().hideEvent(event)
        self._timer.stop()

    def _on_tick(self) -> None:
        now = time.perf_counter()
        t = now - self._t0

        external_fresh = (now - self._last_levels_time) < _LEVELS_FRESH_SECONDS
        if self._recording:
            if external_fresh:
                target_volume = self._ext_volume
                t_low, t_mid, t_high = self._ext_low, self._ext_mid, self._ext_high
            else:
                # gentle simulation so the widget stays testable/lively even
                # without a connected level source
                target_volume = 0.35 + 0.3 * abs(math.sin(t * 1.8))
                t_low = 0.4 + 0.3 * math.sin(t * 1.1)
                t_mid = 0.4 + 0.3 * math.sin(t * 1.6 + 1)
                t_high = 0.4 + 0.3 * math.sin(t * 2.3 + 2)
        else:
            target_volume = t_low = t_mid = t_high = 0.0

        self._smooth_volume += (target_volume - self._smooth_volume) * 0.2
        self._energy_low += (t_low - self._energy_low) * 0.15
        self._energy_mid += (t_mid - self._energy_mid) * 0.15
        self._energy_high += (t_high - self._energy_high) * 0.15

        idle_pulse = 1.0 + 0.015 * math.sin(t * 1.3)
        voice_pulse = 1.0 + self._smooth_volume * 0.253
        self._scale = voice_pulse if self._recording else idle_pulse

        if t > self._next_jitter_time:
            self._phase_jitter_target = (random.random() - 0.5) * 4.0
            self._jitter_interval = 2.5 + random.random() * 3.5
            self._next_jitter_time = t + self._jitter_interval
        self._phase_jitter += (self._phase_jitter_target - self._phase_jitter) * 0.01

        size = min(self.width(), self.height()) or 160
        size_scale = size / _REFERENCE_SIZE

        noise = (math.sin(t * 0.37) * 0.5 + math.sin(t * 0.71 + 1.3) * 0.3
                 + math.sin(t * 1.53 + 2.1) * 0.2)
        if self._recording:
            amp_scale = (5.0 + self._smooth_volume * 16.0 * (0.75 + 0.25 * (noise + 1.0))) * size_scale
        else:
            amp_scale = 3.0 * size_scale
        bulk_rotation = t * 0.28

        cx, cy = self.width() / 2.0, self.height() / 2.0
        base_r = size * 0.275

        # Cap the deflection so ring + volume pulse + pen never leave the
        # widget — at full volume the tuned amplitudes would otherwise clip a
        # couple of pixels at the window edge.
        pen_half = max(2.0, size * 0.019) / 2.0
        max_amp = (min(cx, cy) - pen_half - 0.5) / self._scale - base_r
        amp_scale = min(amp_scale, max(0.0, max_amp))

        points = _ring_points(cx, cy, base_r, amp_scale, bulk_rotation, t, self._phase_jitter)
        self._ring_path = _smooth_closed_path(points)
        self._shimmer_deg = t * 40.0

        hue_low = _cycle_hue(self._palette_low, t, 19.0)
        hue_mid = _cycle_hue(self._palette_mid, t, 23.0)
        hue_high = _cycle_hue(self._palette_high, t, 27.0)

        mix = _clamp01(self._smooth_volume / 0.12)
        mix = mix * mix * (3.0 - 2.0 * mix)

        idle_amp = 0.06
        share_low_idle = 1.0 / 3.0 + idle_amp * math.sin(t * (2 * math.pi / 15) + 0.4)
        share_mid_idle = 1.0 / 3.0 + idle_amp * math.sin(t * (2 * math.pi / 18) + 2.8)

        eps = 0.08
        raw_low = self._energy_low + eps
        raw_mid = self._energy_mid + eps
        raw_high = self._energy_high + eps
        sum_e = raw_low + raw_mid + raw_high
        real_share_low = raw_low / sum_e
        real_share_mid = raw_mid / sum_e

        share_low = share_low_idle * (1 - mix) + real_share_low * mix
        share_mid = share_mid_idle * (1 - mix) + real_share_mid * mix

        l_low_idle = 52 + 12 * math.sin(t * 0.9 + 0.4)
        l_mid_idle = 52 + 12 * math.sin(t * 0.75 + 2.5)
        l_high_idle = 52 + 12 * math.sin(t * 1.05 + 4.8)
        l_low = l_low_idle * (1 - mix) + (45 + self._energy_low * 30) * mix
        l_mid = l_mid_idle * (1 - mix) + (45 + self._energy_mid * 30) * mix
        l_high = l_high_idle * (1 - mix) + (45 + self._energy_high * 30) * mix

        color_low = QColor.fromHslF((hue_low % 360) / 360.0, 0.75, _clamp01(l_low / 100.0))
        color_mid = QColor.fromHslF((hue_mid % 360) / 360.0, 0.75, _clamp01(l_mid / 100.0))
        color_high = QColor.fromHslF((hue_high % 360) / 360.0, 0.75, _clamp01(l_high / 100.0))

        b1raw = share_low * 100.0
        b2raw = (share_low + share_mid) * 100.0
        tw = max(1.5, min(9.0, b1raw * 0.4, (b2raw - b1raw) * 0.4, (100.0 - b2raw) * 0.4))
        b1a = max(0.1, b1raw - tw)
        b1b = min(99.8, b1raw + tw)
        b2a = max(b1b + 0.1, b2raw - tw)
        b2b = min(99.9, b2raw + tw)
        wrap_start = min(99.95, 100.0 - tw)

        self._gradient_stops = [
            (0.0, color_low),
            (b1a / 100.0, color_low),
            (b1b / 100.0, color_mid),
            (b2a / 100.0, color_mid),
            (b2b / 100.0, color_high),
            (wrap_start / 100.0, color_high),
            (1.0, color_low),
        ]

        self.update()

    # -------------------------------------------------------------- painting

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx, cy = self.width() / 2.0, self.height() / 2.0
        size = min(self.width(), self.height()) or 160

        painter.translate(cx, cy)
        painter.scale(self._scale, self._scale)
        painter.translate(-cx, -cy)

        glow_r = size * 0.325
        glow = QRadialGradient(QPointF(cx, cy), glow_r)
        glow.setColorAt(0.0, QColor(255, 255, 255, 71))
        glow.setColorAt(0.45, QColor(255, 255, 255, 26))
        glow.setColorAt(0.72, QColor(255, 255, 255, 0))
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glow)
        painter.drawEllipse(QPointF(cx, cy), glow_r, glow_r)

        if self._ring_path is not None and self._gradient_stops:
            gradient = QConicalGradient(QPointF(cx, cy), self._shimmer_deg)
            for pos, color in self._gradient_stops:
                gradient.setColorAt(_clamp01(pos), color)
            pen = QPen()
            pen.setBrush(gradient)
            pen.setWidthF(max(2.0, size * 0.019))
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            painter.setPen(pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.setOpacity(0.92)
            painter.drawPath(self._ring_path)
            painter.setOpacity(1.0)

        mic_r = size * 0.2
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(28, 28, 30))
        painter.drawEllipse(QPointF(cx, cy), mic_r, mic_r)
        border_pen = QPen(QColor(58, 58, 60))
        border_pen.setWidthF(1.0)
        painter.setPen(border_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawEllipse(QPointF(cx, cy), mic_r, mic_r)

        # Tint the mic glyph per state: yellow while transcribing, red while
        # recording (mirrors the tray/icon COLORS), plain white when idle.
        if self._processing:
            glyph_color = QColor(COLORS["processing"])
        elif self._recording:
            glyph_color = QColor(COLORS["recording"])
        else:
            glyph_color = QColor(242, 242, 242)
        unit = mic_r / 12.0
        body, stand = _build_mic_glyph_path(unit)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(glyph_color)
        painter.translate(cx, cy)
        painter.drawPath(body)
        glyph_pen = QPen(glyph_color)
        glyph_pen.setWidthF(max(1.2, unit * 1.6))
        glyph_pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        painter.setPen(glyph_pen)
        painter.drawPath(stand)
        painter.translate(-cx, -cy)

        painter.end()
