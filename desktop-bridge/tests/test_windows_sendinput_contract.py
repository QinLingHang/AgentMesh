from __future__ import annotations

import ctypes
import os

from desktop_bridge import computer


def test_win32_sendinput_structure_contains_complete_native_union():
    # Keep mandatory skip count at zero on non-Windows development hosts.
    if os.name != "nt":
        return

    expected = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28

    assert ctypes.sizeof(computer._INPUT) == expected
    assert ctypes.sizeof(computer._INPUT_UNION) >= ctypes.sizeof(computer._MOUSEINPUT)
    assert ctypes.sizeof(computer._INPUT_UNION) >= ctypes.sizeof(computer._KEYBDINPUT)
    assert ctypes.sizeof(computer._INPUT_UNION) >= ctypes.sizeof(computer._HARDWAREINPUT)


def test_unicode_input_uses_typed_sendinput_contract():
    source = computer.ComputerService._type_unicode_windows.__code__
    names = set(source.co_names)

    assert "_INPUT" in names
    assert "_KEYBDINPUT" in names

    text = __import__("inspect").getsource(
        computer.ComputerService._type_unicode_windows
    )
    assert "SendInput.argtypes" in text
    assert "SendInput.restype" in text
    assert "expected_size = 40" in text
    assert "sent != len(events)" in text
