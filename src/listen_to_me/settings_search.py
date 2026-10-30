"""Find a setting by name: the field above the settings window's sidebar.

Indexed off the pages' own widgets, so a new option needs no registration, and
rebuilt on every focus-in: which rows a page shows depends on values edited
meanwhile (the OpenVINO rows), and a hit on a hidden row would lead nowhere."""

from __future__ import annotations

import logging
from typing import Callable

from PySide6.QtCore import QEvent, QObject, QStringListModel, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QCompleter, QGroupBox, QLabel, QLineEdit, QRadioButton, QWidget,
)

from .qtutil import clear_on_escape, keep_return_in_field

log = logging.getLogger(__name__)

SEPARATOR = " — "  # between the option and its page, in every row


def setting_label(widget) -> tuple[str, QWidget] | None:
    """(name, widget to focus) for a card title, a checkbox / radio button or a
    form row's label (the one with a buddy) — never a hint or a push button."""
    if isinstance(widget, QGroupBox):
        text, target = widget.title(), widget
    elif isinstance(widget, (QCheckBox, QRadioButton)):
        text, target = widget.text(), widget
    elif isinstance(widget, QLabel) and widget.buddy() is not None:
        text, target = widget.text(), widget.buddy()
    else:
        return None
    text = " ".join(text.replace("&&", "\0").replace("&", "").replace("\0", "&").split())
    text = text.rstrip(":").strip()
    return (text, target) if text else None


def build_index(pages) -> dict[str, tuple[str, QWidget]]:
    """`{"<option> — <page>": (page title, widget)}` for every option shown on
    `pages`, (title, page) pairs in sidebar order; hidden rows are left out."""
    index: dict[str, tuple[str, QWidget]] = {}
    for title, page in pages:
        for widget in page.findChildren(QWidget):
            found = setting_label(widget)
            if found is not None and widget.isVisibleTo(page):
                index.setdefault(f"{found[0]}{SEPARATOR}{title}", (title, found[1]))
    return index


def match_entries(query: str, keys) -> list[str]:
    """The `keys` containing every word of `query`, ignoring case, in order."""
    words = str(query or "").casefold().split()
    if not words:
        return []
    return [key for key in keys if all(word in key.casefold() for word in words)]


class SettingsSearch(QObject):
    """Wires the field: a popup of the matches, Enter opens the first one (and
    never reaches the dialog's default button, Save), Escape clears.
    `go_to(title, widget)` opens a page and focuses the widget on it."""

    def __init__(self, edit: QLineEdit, pages: Callable[[], list], go_to: Callable):
        super().__init__(edit)
        self._edit, self._pages, self._go_to = edit, pages, go_to
        self._index: dict[str, tuple[str, QWidget]] = {}
        self._model = QStringListModel(self)
        # setWidget, not QLineEdit.setCompleter: the popup lists exactly what
        # `match_entries` returns, so it and Enter never disagree — the
        # completer's own matching is a single prefix or substring.
        self.completer = QCompleter(self._model, self)
        self.completer.setCompletionMode(QCompleter.CompletionMode.UnfilteredPopupCompletion)
        self.completer.setWidget(edit)
        self.completer.activated[str].connect(self.open)
        edit.textEdited.connect(self._filter)
        edit.installEventFilter(self)
        keep_return_in_field(edit, self._open_first)
        clear_on_escape(edit)

    def refresh(self) -> None:
        try:
            self._index = build_index(self._pages())
        except Exception:  # a page torn down mid-walk costs the search, not the window
            log.debug("could not index the settings pages", exc_info=True)
            return
        # No complete(): focus returns here as the popup closes, re-opening it would trap it.
        self._model.setStringList(match_entries(self._edit.text(), self._index))

    def _filter(self, text: str) -> None:
        matches = match_entries(text, self._index)
        self._model.setStringList(matches)
        if matches and self._edit.hasFocus():
            self.completer.complete()
        else:
            self.completer.popup().hide()

    def eventFilter(self, obj, event) -> bool:  # noqa: N802 (Qt naming)
        if obj is self._edit and event.type() == QEvent.Type.FocusIn:
            self.refresh()
        return super().eventFilter(obj, event)

    def open(self, key: str) -> bool:
        """Go to the option `key` names; False for a key not in the index."""
        entry = self._index.get(key)
        if entry is None:
            return False
        self.completer.popup().hide()
        self._edit.clear()
        # Next event-loop turn: a closing popup hands the focus back to this
        # field, which would otherwise take it straight off the option.
        QTimer.singleShot(0, self, lambda: self._go_to(*entry))
        return True

    def _open_first(self) -> None:
        matches = match_entries(self._edit.text(), self._index)
        if matches:
            self.open(matches[0])
