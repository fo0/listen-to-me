"""Key naming, both directions: Qt key code → pynput token for the hotkey
capture dialog, and pynput combo → human key caps for everything that shows a
hotkey to the user (Home page, tray, floating icon).

Kept apart from widgets.py (which needs QtWidgets/QtGui) so this pure mapping
imports only QtCore — it stays unit-testable on a headless machine.
"""

from __future__ import annotations

from PySide6.QtCore import Qt

# pynput modifier tokens, in the canonical order used to render a combo.
MOD_ORDER = ["<ctrl>", "<alt>", "<shift>", "<cmd>"]

# The physical modifier keys, mapped to their pynput token. The Windows/Super
# key arrives as Qt.Key_Meta and is pynput's <cmd>; AltGr counts as <alt>.
MODIFIER_KEY_TOKENS = {
    int(Qt.Key.Key_Control): "<ctrl>",
    int(Qt.Key.Key_Alt): "<alt>",
    int(Qt.Key.Key_AltGr): "<alt>",
    int(Qt.Key.Key_Shift): "<shift>",
    int(Qt.Key.Key_Meta): "<cmd>",
    int(Qt.Key.Key_Super_L): "<cmd>",
    int(Qt.Key.Key_Super_R): "<cmd>",
}

# Named (non-printable) keys → pynput token.
_NAMED_KEYS = {
    int(Qt.Key.Key_Space): "<space>",
    int(Qt.Key.Key_Return): "<enter>",
    int(Qt.Key.Key_Enter): "<enter>",
    int(Qt.Key.Key_Tab): "<tab>",
    int(Qt.Key.Key_Backspace): "<backspace>",
    int(Qt.Key.Key_Delete): "<delete>",
    int(Qt.Key.Key_Insert): "<insert>",
    int(Qt.Key.Key_Home): "<home>",
    int(Qt.Key.Key_End): "<end>",
    int(Qt.Key.Key_PageUp): "<page_up>",
    int(Qt.Key.Key_PageDown): "<page_down>",
    int(Qt.Key.Key_Up): "<up>",
    int(Qt.Key.Key_Down): "<down>",
    int(Qt.Key.Key_Left): "<left>",
    int(Qt.Key.Key_Right): "<right>",
    int(Qt.Key.Key_Pause): "<pause>",
    int(Qt.Key.Key_Print): "<print_screen>",
    int(Qt.Key.Key_ScrollLock): "<scroll_lock>",
    int(Qt.Key.Key_NumLock): "<num_lock>",
    int(Qt.Key.Key_CapsLock): "<caps_lock>",
    int(Qt.Key.Key_Menu): "<menu>",
}

# Printable punctuation keys → the literal character pynput expects.
_PUNCT_KEYS = {
    int(Qt.Key.Key_Comma): ",",
    int(Qt.Key.Key_Period): ".",
    int(Qt.Key.Key_Minus): "-",
    int(Qt.Key.Key_Plus): "+",
    int(Qt.Key.Key_Equal): "=",
    int(Qt.Key.Key_Slash): "/",
    int(Qt.Key.Key_Backslash): "\\",
    int(Qt.Key.Key_Semicolon): ";",
    int(Qt.Key.Key_Apostrophe): "'",
    int(Qt.Key.Key_QuoteLeft): "`",
    int(Qt.Key.Key_BracketLeft): "[",
    int(Qt.Key.Key_BracketRight): "]",
    int(Qt.Key.Key_NumberSign): "#",
    int(Qt.Key.Key_Less): "<",
}

_F1 = int(Qt.Key.Key_F1)
_F35 = int(Qt.Key.Key_F35)
_A, _Z = int(Qt.Key.Key_A), int(Qt.Key.Key_Z)
_0, _9 = int(Qt.Key.Key_0), int(Qt.Key.Key_9)

# Non-text keys that are safe to bind on their own (they don't fire during
# ordinary typing or text editing, unlike letters/digits/space/arrows/etc.).
_STANDALONE_OK = {"<pause>", "<print_screen>", "<scroll_lock>", "<menu>"}


def key_token(key: int, text: str = "") -> str | None:
    """Map a Qt key code (+ optional event text) to a pynput key token, or None
    if the key can't be used in a hotkey."""
    key = int(key)
    if key in _NAMED_KEYS:
        return _NAMED_KEYS[key]
    if key in _PUNCT_KEYS:
        return _PUNCT_KEYS[key]
    if _F1 <= key <= _F35:
        # pynput's Key enum only defines f1..f20.
        n = key - _F1 + 1
        return f"<f{n}>" if 1 <= n <= 20 else None
    if _A <= key <= _Z:
        return chr(ord("a") + (key - _A))
    if _0 <= key <= _9:
        return chr(ord("0") + (key - _0))
    # Fallback for layout-specific printable keys not in the tables above.
    if text and len(text) == 1 and text.isprintable() and not text.isspace():
        return text.lower()
    return None


def is_function_key(token: str) -> bool:
    return token.startswith("<f") and token[2:-1].isdigit()


def allowed_standalone(token: str) -> bool:
    """Whether `token` is safe to bind without any modifier."""
    return is_function_key(token) or token in _STANDALONE_OK


# pynput token → the label shown on a key cap / in a status line.
_PRETTY_KEYS = {
    "ctrl": "Ctrl",
    "ctrl_l": "Ctrl",
    "ctrl_r": "Ctrl",
    "alt": "Alt",
    "alt_l": "Alt",
    "alt_r": "Alt",
    "alt_gr": "AltGr",
    "shift": "Shift",
    "shift_l": "Shift",
    "shift_r": "Shift",
    "cmd": "Win",
    "cmd_l": "Win",
    "cmd_r": "Win",
    "space": "Space",
    "enter": "Enter",
    "tab": "Tab",
    "esc": "Esc",
    "backspace": "Backspace",
    "caps_lock": "Caps",
    "plus": "+",
    # The remaining named-key tokens — the caps/underscore fallback below
    # would render these as "UP", "Page_up" or "Print_screen", and the four
    # standalone-safe PTT keys (Pause/PrtScr/ScrLk/Menu) are exactly the ones
    # a user is most likely to see on the Home page, tray and overlay.
    "up": "Up",
    "down": "Down",
    "left": "Left",
    "right": "Right",
    "home": "Home",
    "end": "End",
    "page_up": "PgUp",
    "page_down": "PgDn",
    "delete": "Del",
    "insert": "Ins",
    "print_screen": "PrtScr",
    "scroll_lock": "ScrLk",
    "num_lock": "NumLk",
    "pause": "Pause",
    "menu": "Menu",
}


def pretty_keys(combo: str) -> list[str]:
    """Human key-cap labels for a pynput combo ("<ctrl>+<alt>+<space>" →
    ["Ctrl", "Alt", "Space"]). Unknown tokens pass through readably."""
    combo = str(combo)
    if not combo.strip():
        return []
    caps: list[str] = []
    # A literal plus key is spelled "+" in pynput combos ("<ctrl>++" =
    # Ctrl+Plus) — mask it before splitting on the "+" separator, or it would
    # vanish from the key caps. A combo that is just "+" hits the fallback.
    for part in combo.replace("++", "+<plus>").split("+"):
        token = part.strip()
        if token.startswith("<") and token.endswith(">"):
            token = token[1:-1].strip()
        if not token:
            continue
        caps.append(_PRETTY_KEYS.get(token.lower(), token.upper() if len(token) <= 3 else token.capitalize()))
    return caps or [str(combo)]


def hotkey_label(combo: str) -> str:
    """`combo` as one readable combination ("Ctrl+Alt+Space"), or "" when it is
    empty/unusable — callers fall back to generic wording then, never to a raw
    pynput token in a sentence."""
    try:
        caps = pretty_keys(combo)
    except Exception:  # a combo from an untrusted config.json
        return ""
    return "+".join(caps) if caps else ""
