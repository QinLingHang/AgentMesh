from __future__ import annotations

import base64
import ctypes
from ctypes import wintypes
import io
import os
import secrets
import time
from dataclasses import dataclass
from typing import Any

from .audit import AuditLogger
from .config import Settings
from .policy import DesktopPermissionError


_PYWIN32_DLL_DIRECTORY_HANDLES: list[Any] = []


def _prepare_windows_uia_runtime() -> None:
    """Make pip-installed pywin32 DLLs discoverable before importing pywinauto.

    Conda/base environments can have pywin32 Python modules installed while the
    matching pywintypes/pythoncom DLL directory is not part of the extension
    module DLL search path. Importing pywinauto then fails in win32api before
    any UI Automation code runs.

    Python 3.8+ intentionally restricts DLL lookup for extension dependencies,
    so add the active interpreter's pywin32_system32 directory explicitly and
    retain the returned directory handles for the lifetime of the process.
    """

    if os.name != "nt":
        return

    import site
    import sys
    from pathlib import Path

    roots: list[str] = []

    try:
        roots.extend(str(value) for value in site.getsitepackages())
    except Exception:
        pass

    try:
        user_site = site.getusersitepackages()
        if isinstance(user_site, str):
            roots.append(user_site)
        else:
            roots.extend(str(value) for value in user_site)
    except Exception:
        pass

    # Virtual environments and Conda environments normally expose
    # site-packages on sys.path even if site.getsitepackages() behaves
    # differently. Include those paths as a fallback.
    roots.extend(
        str(value)
        for value in sys.path
        if value and str(value).lower().endswith("site-packages")
    )

    seen: set[str] = set()
    for root in roots:
        dll_dir = Path(root) / "pywin32_system32"
        try:
            resolved = str(dll_dir.resolve())
        except OSError:
            resolved = str(dll_dir)

        key = resolved.casefold()
        if key in seen or not dll_dir.is_dir():
            continue
        seen.add(key)

        # Preserve PATH compatibility for dependencies that still use the
        # process search path, but prefer add_dll_directory on modern Python.
        current_path = os.environ.get("PATH", "")
        path_parts = [part.casefold() for part in current_path.split(os.pathsep) if part]
        if key not in path_parts:
            os.environ["PATH"] = resolved + os.pathsep + current_path

        add_directory = getattr(os, "add_dll_directory", None)
        if add_directory is not None:
            try:
                handle = add_directory(resolved)
                _PYWIN32_DLL_DIRECTORY_HANDLES.append(handle)
            except OSError:
                # Import below remains authoritative and produces an actionable
                # failure if this environment's pywin32 installation is broken.
                pass


# Win32 SendInput ABI.
#
# INPUT contains a union whose size is determined by MOUSEINPUT on 64-bit
# Windows. Defining only KEYBDINPUT makes ctypes.sizeof(INPUT) too small
# (32 bytes instead of the required 40 on Win64), causing SendInput to return 0
# with ERROR_INVALID_PARAMETER. Keep the complete union even though Desktop
# Agent currently emits only keyboard input.
class _MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class _HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD),
    ]


class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", _MOUSEINPUT),
        ("ki", _KEYBDINPUT),
        ("hi", _HARDWAREINPUT),
    ]


class _INPUT(ctypes.Structure):
    _anonymous_ = ("union",)
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION),
    ]


_BLOCKED_HOTKEYS = {
    ("alt", "f4"),
    ("ctrl", "alt", "delete"),
    ("win", "r"),
    ("winleft", "r"),
    ("winright", "r"),
    ("win", "x"),
    ("winleft", "x"),
    ("winright", "x"),
}


@dataclass(slots=True)
class ComputerSession:
    session_id: str
    started_at: float
    expires_at: float


class ComputerSessionManager:
    def __init__(self, settings: Settings, audit: AuditLogger | None = None):
        self.settings = settings
        self.audit = audit or AuditLogger(settings.audit_file)
        self._session: ComputerSession | None = None

    def start(self, duration_seconds: int | None = None) -> dict[str, Any]:
        if not self.settings.computer_use_enabled:
            raise DesktopPermissionError("computer use is disabled; set DESKTOP_COMPUTER_USE_ENABLED=true")
        ttl = min(
            max(60, int(duration_seconds or self.settings.computer_session_ttl_seconds)),
            self.settings.computer_session_ttl_seconds,
        )
        now = time.time()
        self._session = ComputerSession(secrets.token_urlsafe(24), now, now + ttl)
        self.audit.write("ui.session.start", ok=True, detail={"ttlSeconds": ttl})
        return {"sessionId": self._session.session_id, "active": True, "expiresAt": self._session.expires_at}

    def status(self, session_id: str) -> dict[str, Any]:
        active = self._active()
        if active is None or not secrets.compare_digest(str(session_id or ""), active.session_id):
            return {"active": False}
        return {"active": True, "expiresAt": active.expires_at}

    def stop(self, session_id: str) -> dict[str, Any]:
        self.require(session_id)
        self._session = None
        self.audit.write("ui.session.stop", ok=True)
        return {"active": False, "stopped": True}

    def require(self, session_id: str) -> ComputerSession:
        active = self._active()
        if active is None or not secrets.compare_digest(str(session_id or ""), active.session_id):
            raise DesktopPermissionError("an active approved computer-use session is required")
        return active

    def _active(self) -> ComputerSession | None:
        value = self._session
        if value is None:
            return None
        if time.time() >= value.expires_at:
            self._session = None
            self.audit.write("ui.session.expired", ok=True)
            return None
        return value


class ComputerService:
    def __init__(self, settings: Settings, sessions: ComputerSessionManager, audit: AuditLogger | None = None):
        self.settings = settings
        self.sessions = sessions
        self.audit = audit or AuditLogger(settings.audit_file)

    @staticmethod
    def _pyautogui():
        try:
            import pyautogui
        except ImportError as exc:
            raise RuntimeError("pyautogui is required for screen/mouse/keyboard computer use") from exc
        pyautogui.PAUSE = 0.05
        pyautogui.FAILSAFE = True
        return pyautogui

    def capture(self, session_id: str) -> dict[str, Any]:
        self.sessions.require(session_id)
        pyautogui = self._pyautogui()
        image = pyautogui.screenshot()
        width, height = image.size
        max_width = max(320, self.settings.screenshot_max_width)
        if width > max_width:
            ratio = max_width / float(width)
            image = image.resize((max_width, max(1, int(height * ratio))))
            width, height = image.size
        buffer = io.BytesIO()
        image.save(buffer, format="PNG", optimize=True)
        payload = buffer.getvalue()
        if len(payload) > self.settings.screenshot_max_bytes:
            raise ValueError("screenshot exceeds configured transport limit")
        self.audit.write("ui.screen.capture", ok=True, detail={"width": width, "height": height, "sizeBytes": len(payload)})
        return {
            "mediaType": "image/png",
            "width": width,
            "height": height,
            "sizeBytes": len(payload),
            "imageBase64": base64.b64encode(payload).decode("ascii"),
        }

    def mouse_move(self, session_id: str, x: int, y: int, duration_ms: int = 0) -> dict[str, Any]:
        self.sessions.require(session_id)
        py = self._pyautogui()
        self._validate_point(py, x, y)
        py.moveTo(x, y, duration=max(0.0, min(duration_ms, 5000) / 1000.0))
        self.audit.write("ui.mouse.move", ok=True, detail={"x": x, "y": y})
        return {"moved": True, "x": x, "y": y}

    def mouse_click(self, session_id: str, x: int, y: int, *, button: str = "left", clicks: int = 1) -> dict[str, Any]:
        self.sessions.require(session_id)
        py = self._pyautogui()
        self._validate_point(py, x, y)
        button = str(button).lower()
        if button not in {"left", "right", "middle"}:
            raise ValueError("mouse button must be left, right, or middle")
        py.click(x=x, y=y, clicks=max(1, min(int(clicks), 2)), interval=0.12, button=button)
        self.audit.write("ui.mouse.click", ok=True, detail={"x": x, "y": y, "button": button, "clicks": clicks})
        return {"clicked": True, "x": x, "y": y, "button": button, "clicks": clicks}

    def mouse_drag(self, session_id: str, start_x: int, start_y: int, end_x: int, end_y: int, duration_ms: int = 300) -> dict[str, Any]:
        self.sessions.require(session_id)
        py = self._pyautogui()
        self._validate_point(py, start_x, start_y)
        self._validate_point(py, end_x, end_y)
        py.moveTo(start_x, start_y)
        py.dragTo(end_x, end_y, duration=max(0.05, min(duration_ms, 5000) / 1000.0), button="left")
        self.audit.write("ui.mouse.drag", ok=True, detail={"start": [start_x, start_y], "end": [end_x, end_y]})
        return {"dragged": True}

    def mouse_scroll(self, session_id: str, amount: int, x: int | None = None, y: int | None = None) -> dict[str, Any]:
        self.sessions.require(session_id)
        py = self._pyautogui()
        if x is not None and y is not None:
            self._validate_point(py, x, y)
            py.moveTo(x, y)
        amount = max(-20, min(20, int(amount)))
        py.scroll(amount)
        self.audit.write("ui.mouse.scroll", ok=True, detail={"amount": amount})
        return {"scrolled": True, "amount": amount}

    def keyboard_type(self, session_id: str, text: str, interval_ms: int = 0) -> dict[str, Any]:
        self.sessions.require(session_id)
        value = str(text)
        if len(value) > 4000:
            raise ValueError("typed text exceeds 4000 characters")
        if os.name == "nt":
            self._type_unicode_windows(value, max(0, min(interval_ms, 500)) / 1000.0)
        else:
            self._pyautogui().write(value, interval=max(0, min(interval_ms, 500)) / 1000.0)
        self.audit.write("ui.keyboard.type", ok=True, detail={"characters": len(value)})
        return {"typed": True, "characters": len(value)}

    def keyboard_press(self, session_id: str, key: str, presses: int = 1) -> dict[str, Any]:
        self.sessions.require(session_id)
        py = self._pyautogui()
        key = str(key).lower().strip()
        if key not in py.KEYBOARD_KEYS:
            raise ValueError("unsupported keyboard key")
        presses = max(1, min(int(presses), 20))
        py.press(key, presses=presses, interval=0.05)
        self.audit.write("ui.keyboard.press", ok=True, detail={"key": key, "presses": presses})
        return {"pressed": True, "key": key, "presses": presses}

    def keyboard_hotkey(self, session_id: str, keys: list[str]) -> dict[str, Any]:
        self.sessions.require(session_id)
        py = self._pyautogui()
        normalized = tuple(str(key).lower().strip() for key in keys)
        if not normalized or len(normalized) > 4:
            raise ValueError("hotkey requires 1 to 4 keys")
        if normalized in _BLOCKED_HOTKEYS:
            raise DesktopPermissionError("this system-level hotkey is blocked; use an explicit governed tool instead")
        if any(key not in py.KEYBOARD_KEYS for key in normalized):
            raise ValueError("unsupported hotkey key")
        py.hotkey(*normalized)
        self.audit.write("ui.keyboard.hotkey", ok=True, detail={"keys": list(normalized)})
        return {"hotkey": list(normalized), "sent": True}

    def wait(self, session_id: str, milliseconds: int) -> dict[str, Any]:
        self.sessions.require(session_id)
        milliseconds = max(0, min(int(milliseconds), 10_000))
        time.sleep(milliseconds / 1000.0)
        return {"waitedMs": milliseconds}

    @staticmethod
    def _validate_point(py, x: int, y: int) -> None:
        width, height = py.size()
        if int(x) < 0 or int(y) < 0 or int(x) >= width or int(y) >= height:
            raise ValueError("mouse coordinates are outside the current desktop")

    @staticmethod
    def _type_unicode_windows(value: str, interval: float) -> None:
        user32 = ctypes.WinDLL("user32", use_last_error=True)
        INPUT_KEYBOARD = 1
        KEYEVENTF_UNICODE = 0x0004
        KEYEVENTF_KEYUP = 0x0002

        user32.SendInput.argtypes = [
            wintypes.UINT,
            ctypes.POINTER(_INPUT),
            ctypes.c_int,
        ]
        user32.SendInput.restype = wintypes.UINT

        # Win32 requires cbSize to match the platform INPUT ABI exactly.
        # This guard makes future ctypes structure regressions fail loudly.
        expected_size = 40 if ctypes.sizeof(ctypes.c_void_p) == 8 else 28
        input_size = ctypes.sizeof(_INPUT)
        if input_size != expected_size:
            raise RuntimeError(
                f"Windows INPUT ABI size mismatch: got {input_size}, "
                f"expected {expected_size}"
            )

        for char in value:
            codepoint = ord(char)
            units = [codepoint] if codepoint <= 0xFFFF else [
                0xD800 + ((codepoint - 0x10000) >> 10),
                0xDC00 + ((codepoint - 0x10000) & 0x3FF),
            ]

            for unit in units:
                events = (_INPUT * 2)(
                    _INPUT(
                        type=INPUT_KEYBOARD,
                        ki=_KEYBDINPUT(
                            0,
                            unit,
                            KEYEVENTF_UNICODE,
                            0,
                            0,
                        ),
                    ),
                    _INPUT(
                        type=INPUT_KEYBOARD,
                        ki=_KEYBDINPUT(
                            0,
                            unit,
                            KEYEVENTF_UNICODE | KEYEVENTF_KEYUP,
                            0,
                            0,
                        ),
                    ),
                )

                ctypes.set_last_error(0)
                sent = int(
                    user32.SendInput(
                        len(events),
                        events,
                        input_size,
                    )
                )
                if sent != len(events):
                    error = ctypes.get_last_error()
                    if error:
                        raise OSError(
                            error,
                            f"Windows SendInput failed after injecting "
                            f"{sent}/{len(events)} keyboard events",
                        )
                    raise RuntimeError(
                        "Windows SendInput was blocked before all keyboard "
                        "events were injected; target integrity may be higher "
                        "than Desktop Bridge"
                    )

            if interval:
                time.sleep(interval)

    def window_list(self, session_id: str, limit: int = 100) -> dict[str, Any]:
        self.sessions.require(session_id)
        handles = self._enumerate_window_handles()
        items = []
        for handle in handles:
            try:
                items.append(self._window_meta_from_handle(handle))
            except Exception:
                continue
            if len(items) >= max(1, min(int(limit), 100)):
                break
        return {"windows": items}

    def window_info(self, session_id: str, handle: int) -> dict[str, Any]:
        self.sessions.require(session_id)
        return self._window_meta_from_handle(handle)

    def window_focus(self, session_id: str, handle: int) -> dict[str, Any]:
        self.sessions.require(session_id)
        meta = self._window_meta_from_handle(handle)
        user32 = self._user32()
        hwnd = wintypes.HWND(int(handle))

        # Do not depend on a full UIA desktop enumeration just to focus a
        # window. Enumerating every top-level UIA provider can fail when the
        # interactive desktop contains higher-integrity or broken providers.
        try:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
        except Exception:
            pass
        try:
            user32.BringWindowToTop(hwnd)
        except Exception:
            pass
        try:
            user32.SetForegroundWindow(hwnd)
        except Exception:
            # A later mouse click can still establish foreground focus.
            pass

        self.audit.write("ui.window.focus", ok=True, detail={"handle": int(handle), "pid": meta["pid"]})
        return {"focused": True, **meta}

    def window_close(self, session_id: str, handle: int) -> dict[str, Any]:
        self.sessions.require(session_id)
        meta = self._window_meta_from_handle(handle)
        user32 = self._user32()
        hwnd = wintypes.HWND(int(handle))
        WM_CLOSE = 0x0010
        if not user32.PostMessageW(hwnd, WM_CLOSE, 0, 0):
            raise OSError("Windows refused the close request")
        self.audit.write("ui.window.close", ok=True, detail={"handle": int(handle), "pid": meta["pid"]})
        return {"closed": True, "handle": int(handle), "pid": meta["pid"]}

    def element_find(self, session_id: str, handle: int, *, name: str = "", control_type: str = "", automation_id: str = "", limit: int = 20) -> dict[str, Any]:
        self.sessions.require(session_id)
        window = self._uia_window(handle)
        name_cf = name.casefold().strip()
        control_cf = control_type.casefold().strip()
        automation_cf = automation_id.casefold().strip()
        matches = []
        try:
            descendants = window.descendants()
        except Exception as exc:
            raise RuntimeError("Windows UI Automation could not inspect the selected window") from exc

        for element in descendants:
            try:
                info = element.element_info
                title = str(element.window_text() or "")
                control = str(getattr(info, "control_type", "") or "")
                auto_id = str(getattr(info, "automation_id", "") or "")
                if name_cf and name_cf not in title.casefold():
                    continue
                if control_cf and control_cf != control.casefold():
                    continue
                if automation_cf and automation_cf != auto_id.casefold():
                    continue
                rect = element.rectangle()
                matches.append({
                    "runtimeId": list(getattr(info, "runtime_id", ()) or ()),
                    "name": title[:240],
                    "controlType": control,
                    "automationId": auto_id[:240],
                    "rectangle": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
                })
                if len(matches) >= max(1, min(int(limit), 50)):
                    break
            except Exception:
                # A single inaccessible provider must not poison the target
                # window's otherwise healthy automation tree.
                continue
        return {"elements": matches}

    def element_action(self, session_id: str, handle: int, *, name: str = "", control_type: str = "", automation_id: str = "", action: str, value: str = "") -> dict[str, Any]:
        self.sessions.require(session_id)
        element = self._first_element(handle, name=name, control_type=control_type, automation_id=automation_id)
        if action == "click":
            element.click_input()
        elif action == "invoke":
            try:
                element.invoke()
            except Exception:
                element.click_input()
        elif action == "set_text":
            if len(value) > 4000:
                raise ValueError("element text exceeds 4000 characters")
            try:
                element.set_edit_text(value)
            except Exception:
                element.set_focus()
                self.keyboard_hotkey(session_id, ["ctrl", "a"])
                self.keyboard_type(session_id, value)
        elif action == "select":
            try:
                element.select(value) if value else element.select()
            except TypeError:
                element.select()
        else:
            raise ValueError("unsupported UI Automation action")
        self.audit.write(f"ui.element.{action}", ok=True, detail={"handle": int(handle), "nameLength": len(name), "controlType": control_type})
        return {"action": action, "completed": True}

    def _first_element(self, handle: int, *, name: str, control_type: str, automation_id: str):
        # `_uia_window()` intentionally returns a wrapper for the already
        # validated target HWND. pywinauto WindowSpecification exposes
        # `child_window()`, but UIAWrapper does not. Searching the selected
        # wrapper's descendants keeps UIA scoped to the requested HWND and uses
        # the same selector semantics as `element_find()`.
        window = self._uia_window(handle)

        name_cf = name.casefold().strip()
        control_cf = control_type.casefold().strip()
        automation_cf = automation_id.casefold().strip()

        if not (name_cf or control_cf or automation_cf):
            raise ValueError("element selector requires name, controlType, or automationId")

        try:
            descendants = window.descendants()
        except Exception as exc:
            raise RuntimeError(
                "Windows UI Automation could not inspect the selected window"
            ) from exc

        for element in descendants:
            try:
                info = element.element_info
                title = str(element.window_text() or "")
                control = str(getattr(info, "control_type", "") or "")
                auto_id = str(getattr(info, "automation_id", "") or "")

                if name_cf and name_cf not in title.casefold():
                    continue
                if control_cf and control_cf != control.casefold():
                    continue
                if automation_cf and automation_cf != auto_id.casefold():
                    continue

                return element
            except Exception:
                # A single inaccessible descendant must not poison the selected
                # window's otherwise healthy automation tree.
                continue

        raise FileNotFoundError("UI Automation element was not found")

    @staticmethod
    def _user32():
        if os.name != "nt":
            raise RuntimeError("Windows desktop control is supported only on Windows")
        return ctypes.windll.user32

    @staticmethod
    def _hwnd_value(hwnd: Any) -> int:
        if isinstance(hwnd, int):
            return int(hwnd)
        value = getattr(hwnd, "value", None)
        return int(value or 0)

    def _enumerate_window_handles(self) -> list[int]:
        user32 = self._user32()
        handles: list[int] = []

        # Native EnumWindows is intentionally used for top-level discovery.
        # A global pywinauto UIA enumeration may fail with COMError merely
        # because some unrelated elevated/provider window is not accessible.
        callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

        @callback_type
        def callback(hwnd, _lparam):
            try:
                if user32.IsWindowVisible(hwnd):
                    handle = self._hwnd_value(hwnd)
                    if handle:
                        handles.append(handle)
            except Exception:
                pass
            return True

        if not user32.EnumWindows(callback, 0):
            raise OSError("Windows top-level window enumeration failed")
        return handles

    def _window_meta_from_handle(self, handle: int) -> dict[str, Any]:
        user32 = self._user32()
        hwnd_value = int(handle)
        hwnd = wintypes.HWND(hwnd_value)
        if not user32.IsWindow(hwnd):
            raise FileNotFoundError("desktop window was not found")

        length = max(0, int(user32.GetWindowTextLengthW(hwnd)))
        title_buffer = ctypes.create_unicode_buffer(length + 1)
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))

        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))

        rect = wintypes.RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(rect)):
            raise OSError("Windows could not read the window rectangle")

        return {
            "handle": hwnd_value,
            "title": str(title_buffer.value or "")[:240],
            "pid": int(pid.value),
            "rectangle": {"left": rect.left, "top": rect.top, "right": rect.right, "bottom": rect.bottom},
        }

    def _uia_window(self, handle: int):
        # Validate the native handle first, then ask UIA only for that exact
        # target. This avoids traversing unrelated desktop providers and makes
        # UI Automation stable in mixed-integrity Windows desktops.
        self._window_meta_from_handle(handle)
        if os.name != "nt":
            raise RuntimeError("Windows UI Automation is supported only on Windows")

        _prepare_windows_uia_runtime()

        try:
            from pywinauto import Desktop
        except ImportError as exc:
            raise RuntimeError(
                "Windows UI Automation dependencies are unavailable or broken. "
                "Reinstall this Desktop Bridge environment's Windows dependencies "
                "(pywin32 + pywinauto) with the same Python interpreter."
            ) from exc

        last_error: Exception | None = None
        for _ in range(3):
            try:
                return Desktop(backend="uia").window(handle=int(handle)).wrapper_object()
            except Exception as exc:
                last_error = exc
                time.sleep(0.1)
        raise RuntimeError("Windows UI Automation could not attach to the selected window") from last_error

