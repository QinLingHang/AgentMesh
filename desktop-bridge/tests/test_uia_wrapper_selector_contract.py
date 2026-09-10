from __future__ import annotations

from types import SimpleNamespace

import pytest

from desktop_bridge.computer import ComputerService


class _FakeElement:
    def __init__(self, title: str, control_type: str, automation_id: str = ""):
        self._title = title
        self.element_info = SimpleNamespace(
            control_type=control_type,
            automation_id=automation_id,
        )

    def window_text(self):
        return self._title


class _FakeWindowWrapper:
    """Deliberately has descendants(), but no child_window()."""

    def __init__(self, descendants):
        self._descendants = descendants

    def descendants(self):
        return list(self._descendants)


def _service_with_window(window):
    service = object.__new__(ComputerService)
    service._uia_window = lambda _handle: window
    return service


def test_first_element_searches_selected_uia_wrapper_descendants():
    edit = _FakeElement("", "Edit", "message-input")
    button = _FakeElement("Apply", "Button", "apply-button")
    service = _service_with_window(_FakeWindowWrapper([edit, button]))

    assert service._first_element(
        123,
        name="Apply",
        control_type="Button",
        automation_id="",
    ) is button

    assert service._first_element(
        123,
        name="",
        control_type="Edit",
        automation_id="message-input",
    ) is edit


def test_first_element_fails_closed_for_missing_or_empty_selector():
    service = _service_with_window(
        _FakeWindowWrapper([_FakeElement("Apply", "Button", "apply-button")])
    )

    with pytest.raises(ValueError, match="element selector requires"):
        service._first_element(
            123,
            name="",
            control_type="",
            automation_id="",
        )

    with pytest.raises(FileNotFoundError, match="UI Automation element was not found"):
        service._first_element(
            123,
            name="Missing",
            control_type="Button",
            automation_id="",
        )
