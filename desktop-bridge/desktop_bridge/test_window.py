"""Deterministic native Win32 UI used only by Desktop Agent automated acceptance."""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes


WINDOW_TITLE = "AgentMesh Desktop Test"
WINDOW_CLASS = "AgentMeshDesktopTestWindow"
EDIT_ID = 1001
APPLY_ID = 1002


def main() -> None:
    if os.name != "nt":
        raise RuntimeError("the deterministic Desktop Agent test window is Windows-only")

    # IMPORTANT:
    # ctypes defaults function return values to c_int. On 64-bit Windows that
    # truncates HWND/HMODULE values. The previous test window was therefore
    # created with a real 64-bit HWND but ShowWindow/child creation received a
    # truncated handle, leaving the deterministic window hidden or causing the
    # process to exit before EnumWindows could discover it.
    #
    # Define the Win32 ABI explicitly for every pointer-sized API used here.
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    LRESULT = ctypes.c_ssize_t
    WPARAM = ctypes.c_size_t
    LPARAM = ctypes.c_ssize_t
    WNDPROC = ctypes.WINFUNCTYPE(
        LRESULT,
        wintypes.HWND,
        wintypes.UINT,
        WPARAM,
        LPARAM,
    )

    class WNDCLASSW(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT),
            ("lpfnWndProc", WNDPROC),
            ("cbClsExtra", ctypes.c_int),
            ("cbWndExtra", ctypes.c_int),
            ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HANDLE),
            ("hCursor", wintypes.HANDLE),
            ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR),
            ("lpszClassName", wintypes.LPCWSTR),
        ]

    kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
    kernel32.GetModuleHandleW.restype = wintypes.HMODULE

    user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
    user32.RegisterClassW.restype = wintypes.WORD

    user32.CreateWindowExW.argtypes = [
        wintypes.DWORD,
        wintypes.LPCWSTR,
        wintypes.LPCWSTR,
        wintypes.DWORD,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        ctypes.c_int,
        wintypes.HWND,
        wintypes.HANDLE,
        wintypes.HINSTANCE,
        wintypes.LPVOID,
    ]
    user32.CreateWindowExW.restype = wintypes.HWND

    user32.DefWindowProcW.argtypes = [
        wintypes.HWND,
        wintypes.UINT,
        WPARAM,
        LPARAM,
    ]
    user32.DefWindowProcW.restype = LRESULT

    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.ShowWindow.restype = wintypes.BOOL

    user32.UpdateWindow.argtypes = [wintypes.HWND]
    user32.UpdateWindow.restype = wintypes.BOOL

    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetWindowTextLengthW.restype = ctypes.c_int

    user32.GetWindowTextW.argtypes = [
        wintypes.HWND,
        wintypes.LPWSTR,
        ctypes.c_int,
    ]
    user32.GetWindowTextW.restype = ctypes.c_int

    user32.SetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPCWSTR]
    user32.SetWindowTextW.restype = wintypes.BOOL

    user32.PostQuitMessage.argtypes = [ctypes.c_int]
    user32.PostQuitMessage.restype = None

    user32.GetMessageW.argtypes = [
        ctypes.POINTER(wintypes.MSG),
        wintypes.HWND,
        wintypes.UINT,
        wintypes.UINT,
    ]
    user32.GetMessageW.restype = wintypes.BOOL

    user32.TranslateMessage.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.TranslateMessage.restype = wintypes.BOOL

    user32.DispatchMessageW.argtypes = [ctypes.POINTER(wintypes.MSG)]
    user32.DispatchMessageW.restype = LRESULT

    WM_DESTROY = 0x0002
    WM_COMMAND = 0x0111
    WS_OVERLAPPEDWINDOW = 0x00CF0000
    WS_VISIBLE = 0x10000000
    WS_CHILD = 0x40000000
    WS_TABSTOP = 0x00010000
    WS_BORDER = 0x00800000
    ES_AUTOHSCROLL = 0x0080
    BS_PUSHBUTTON = 0x00000000
    SW_SHOW = 5
    COLOR_WINDOW = 5

    hinstance = kernel32.GetModuleHandleW(None)
    if not hinstance:
        raise OSError(ctypes.get_last_error(), "GetModuleHandleW failed")

    edit_handle = wintypes.HWND()
    status_handle = wintypes.HWND()

    @WNDPROC
    def wndproc(hwnd, msg, wparam, lparam):
        if msg == WM_COMMAND and (int(wparam) & 0xFFFF) == APPLY_ID:
            length = int(user32.GetWindowTextLengthW(edit_handle))
            buffer = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(edit_handle, buffer, len(buffer))
            if not user32.SetWindowTextW(
                status_handle,
                f"Status: {buffer.value}",
            ):
                raise OSError(
                    ctypes.get_last_error(),
                    "SetWindowTextW failed",
                )
            return 0

        if msg == WM_DESTROY:
            user32.PostQuitMessage(0)
            return 0

        return user32.DefWindowProcW(
            hwnd,
            msg,
            wparam,
            lparam,
        )

    wc = WNDCLASSW()
    wc.lpfnWndProc = wndproc
    wc.hInstance = hinstance
    wc.hbrBackground = wintypes.HBRUSH(COLOR_WINDOW + 1)
    wc.lpszClassName = WINDOW_CLASS

    atom = user32.RegisterClassW(ctypes.byref(wc))
    if not atom:
        error = ctypes.get_last_error()
        # ERROR_CLASS_ALREADY_EXISTS. Harmless if the class has already been
        # registered in this process.
        if error != 1410:
            raise OSError(error, "RegisterClassW failed")

    hwnd = user32.CreateWindowExW(
        0,
        WINDOW_CLASS,
        WINDOW_TITLE,
        # WS_VISIBLE is intentional in addition to ShowWindow. This makes the
        # mandatory test fail-safe against a future presentation-call mistake.
        WS_OVERLAPPEDWINDOW | WS_VISIBLE,
        120,
        120,
        500,
        290,
        None,
        None,
        hinstance,
        None,
    )
    if not hwnd:
        raise OSError(
            ctypes.get_last_error(),
            "CreateWindowExW failed",
        )

    static_handle = user32.CreateWindowExW(
        0,
        "STATIC",
        "AgentMesh Computer Use Test",
        WS_CHILD | WS_VISIBLE,
        28,
        28,
        320,
        30,
        hwnd,
        None,
        hinstance,
        None,
    )
    if not static_handle:
        raise OSError(
            ctypes.get_last_error(),
            "creating native Static control failed",
        )

    edit_handle = user32.CreateWindowExW(
        0,
        "EDIT",
        "",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | WS_BORDER | ES_AUTOHSCROLL,
        28,
        78,
        410,
        28,
        hwnd,
        wintypes.HANDLE(EDIT_ID),
        hinstance,
        None,
    )
    if not edit_handle:
        raise OSError(
            ctypes.get_last_error(),
            "creating native Edit control failed",
        )

    status_handle = user32.CreateWindowExW(
        0,
        "STATIC",
        "Status: ready",
        WS_CHILD | WS_VISIBLE,
        28,
        124,
        410,
        28,
        hwnd,
        None,
        hinstance,
        None,
    )
    if not status_handle:
        raise OSError(
            ctypes.get_last_error(),
            "creating native status control failed",
        )

    button_handle = user32.CreateWindowExW(
        0,
        "BUTTON",
        "Apply",
        WS_CHILD | WS_VISIBLE | WS_TABSTOP | BS_PUSHBUTTON,
        28,
        170,
        130,
        34,
        hwnd,
        wintypes.HANDLE(APPLY_ID),
        hinstance,
        None,
    )
    if not button_handle:
        raise OSError(
            ctypes.get_last_error(),
            "creating native Button control failed",
        )

    user32.ShowWindow(hwnd, SW_SHOW)
    if not user32.UpdateWindow(hwnd):
        # UpdateWindow may return zero when there is no update region. That is
        # not itself an error, so do not fail the test process here.
        pass

    msg = wintypes.MSG()
    while True:
        result = int(
            user32.GetMessageW(
                ctypes.byref(msg),
                None,
                0,
                0,
            )
        )

        if result == 0:
            break

        if result == -1:
            raise OSError(
                ctypes.get_last_error(),
                "GetMessageW failed",
            )

        user32.TranslateMessage(ctypes.byref(msg))
        user32.DispatchMessageW(ctypes.byref(msg))


if __name__ == "__main__":
    main()
