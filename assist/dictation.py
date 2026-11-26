"""Dictation with FluidVoice from a button in SleePO's AI boxes (Sam, 22 Oct 2026).

FluidVoice (com.FluidApp.app) has no URL scheme, AppleScript dictionary or Shortcuts actions: it starts and stops on its
keyboard shortcut (Sam's: the Fn key alone). A web page cannot press a key outside the browser, so the page focuses the text
box and asks this server, on the same Mac, to press the shortcut once, as if Sam had: FluidVoice records and pastes what he
says into the focused box (its "reliable paste" insertion), and a second press stops it.

The key press is a CoreGraphics event posted through ctypes (no extra packages; the venv has no pyobjc). macOS only lets a
process post key events when it is allowed under System Settings › Privacy & Security › Accessibility: trusted() says
whether this server is, and ask_trust() shows the system prompt that adds it to that list. The shortcut is read from
FluidVoice's own settings each time, so a changed shortcut keeps working (a modifier key alone, or a key with modifiers).
"""
import ctypes
import json
import os
import plistlib
import subprocess
import sys
import time

BUNDLE = "com.FluidApp.app"
APP = "/Applications/FluidVoice.app"
DEFAULT = {"kind": "keyboard", "keyCode": 63, "modifierKeyCodes": [63], "modifierFlagsRawValue": 0}   # Fn alone

# modifier keys (virtual key code -> CGEventFlags bit): pressed alone, they arrive as a flags-changed event, not a key down
MODIFIERS = {63: 0x800000,                                    # Fn
             55: 0x100000, 54: 0x100000,                      # Command
             56: 0x020000, 60: 0x020000,                      # Shift
             58: 0x080000, 61: 0x080000,                      # Option
             59: 0x040000, 62: 0x040000,                      # Control
             57: 0x010000}                                    # Caps Lock
NAMES = {63: "Fn", 55: "Command", 54: "right Command", 56: "Shift", 60: "right Shift", 58: "Option", 61: "right Option",
         59: "Control", 62: "right Control", 57: "Caps Lock"}
FLAGS_CHANGED, HID_TAP = 12, 0

_as = _cf = None


def _libs():
    global _as, _cf
    if _as is None:
        _as = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/ApplicationServices.framework/ApplicationServices")
        _cf = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        _as.CGEventCreateKeyboardEvent.restype = ctypes.c_void_p
        _as.CGEventCreateKeyboardEvent.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_bool]
        _as.CGEventSetFlags.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
        _as.CGEventSetType.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        _as.CGEventPost.argtypes = [ctypes.c_uint32, ctypes.c_void_p]
        _as.AXIsProcessTrusted.restype = ctypes.c_bool
        _as.AXIsProcessTrustedWithOptions.restype = ctypes.c_bool
        _as.AXIsProcessTrustedWithOptions.argtypes = [ctypes.c_void_p]
        _cf.CFRelease.argtypes = [ctypes.c_void_p]
        _cf.CFDictionaryCreate.restype = ctypes.c_void_p
        _cf.CFDictionaryCreate.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p]
    return _as, _cf


def parse_shortcut(prefs):
    """FluidVoice's dictation shortcut from its settings (a dict of `defaults export`), else Fn."""
    for key in ("PrimaryDictationShortcuts", "HotkeyShortcutKey"):
        v = prefs.get(key)
        try:
            v = json.loads(v) if isinstance(v, (bytes, str)) else v
        except ValueError:
            continue
        if isinstance(v, list):
            v = v[0] if v else None
        if isinstance(v, dict) and v.get("kind", "keyboard") == "keyboard" and isinstance(v.get("keyCode"), int):
            return v
    return DEFAULT


def shortcut():
    try:
        out = subprocess.run(["defaults", "export", BUNDLE, "-"], capture_output=True, timeout=5).stdout
        return parse_shortcut(plistlib.loads(out) if out else {})
    except Exception:
        return DEFAULT


def describe(sc):
    code = sc.get("keyCode")
    if code in MODIFIERS and not sc.get("modifierFlagsRawValue"):
        return NAMES.get(code, f"key {code}")
    mods = sc.get("modifierFlagsRawValue") or 0
    parts = [n for bit, n in ((0x040000, "Control"), (0x080000, "Option"), (0x020000, "Shift"), (0x100000, "Command"), (0x800000, "Fn")) if mods & bit]
    return " + ".join(parts + [f"key {code}"])


def trusted():
    try:
        return bool(_libs()[0].AXIsProcessTrusted())
    except Exception:
        return False


def ask_trust():
    """Show macOS's prompt that adds this server to Accessibility (once; after that, System Settings decides)."""
    try:
        a, cf = _libs()
        key = ctypes.c_void_p.in_dll(a, "kAXTrustedCheckOptionPrompt")
        yes = ctypes.c_void_p.in_dll(cf, "kCFBooleanTrue")
        keys, vals = (ctypes.c_void_p * 1)(key.value), (ctypes.c_void_p * 1)(yes.value)
        d = cf.CFDictionaryCreate(None, keys, vals, 1, ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryKeyCallBacks")),
                                  ctypes.addressof(ctypes.c_void_p.in_dll(cf, "kCFTypeDictionaryValueCallBacks")))
        ok = bool(a.AXIsProcessTrustedWithOptions(d))
        cf.CFRelease(d)
        return ok
    except Exception:
        return False


def running():
    return subprocess.run(["pgrep", "-x", "FluidVoice"], capture_output=True).returncode == 0


def _post(code, down, flags, modifier):
    a, cf = _libs()
    e = a.CGEventCreateKeyboardEvent(None, code, down)
    if not e:
        raise RuntimeError("could not make the key event")
    if modifier:
        a.CGEventSetType(e, FLAGS_CHANGED)
    a.CGEventSetFlags(e, flags)
    a.CGEventPost(HID_TAP, e)
    cf.CFRelease(e)


def press():
    """Press FluidVoice's shortcut once. Returns a status dict for the page."""
    sc = shortcut()
    info = {"shortcut": describe(sc), "app": os.path.exists(APP)}
    if not info["app"]:
        return {**info, "ok": False, "need": "install", "message": "FluidVoice is not in Applications."}
    if not trusted():
        ask_trust()
        return {**info, "ok": False, "need": "accessibility", "python": os.path.realpath(sys.executable),
                "message": "macOS has to allow SleePO to press keys: System Settings › Privacy & Security › Accessibility, "
                           "turn on Python (the SleePO server), then click the microphone again."}
    if not running():
        subprocess.run(["open", "-g", "-a", APP])
        for _ in range(20):
            time.sleep(0.25)
            if running():
                break
        time.sleep(1.0)   # let it register its shortcut
    code, mods = sc["keyCode"], sc.get("modifierFlagsRawValue") or 0
    if code in MODIFIERS and not mods:   # a modifier key alone (Fn): down then up, as flag changes
        _post(code, True, MODIFIERS[code], True)
        time.sleep(0.06)
        _post(code, False, 0, True)
    else:                                 # a key with modifiers
        _post(code, True, mods, False)
        time.sleep(0.04)
        _post(code, False, mods, False)
    return {**info, "ok": True}
