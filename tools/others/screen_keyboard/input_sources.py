"""Select enabled macOS keyboard input sources without synthetic key events."""

from contextlib import contextmanager
from collections.abc import Iterable, Iterator, Mapping
import ctypes as c
import importlib
import plistlib
import time
from typing import Any, cast

import CoreFoundation  # pyright: ignore[reportMissingImports]
import objc  # pyright: ignore[reportMissingImports]

from utils.macos_input import frontmost_target

_TIS = c.CDLL('/System/Library/Frameworks/Carbon.framework/Carbon')
_CF = c.CDLL('/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation')
for library, name, result, arguments in (
    (_TIS, 'TISCopyCurrentKeyboardInputSource', c.c_void_p, []),
    (_TIS, 'TISCreateInputSourceList', c.c_void_p, [c.c_void_p, c.c_bool]),
    (_TIS, 'TISGetInputSourceProperty', c.c_void_p, [c.c_void_p, c.c_void_p]),
    (_TIS, 'TISSelectInputSource', c.c_int32, [c.c_void_p]),
    (_CF, 'CFArrayGetCount', c.c_long, [c.c_void_p]),
    (_CF, 'CFArrayGetValueAtIndex', c.c_void_p, [c.c_void_p, c.c_long]),
    (_CF, 'CFBooleanGetValue', c.c_bool, [c.c_void_p]),
    (_CF, 'CFStringGetLength', c.c_long, [c.c_void_p]),
    (_CF, 'CFStringGetCString', c.c_bool, [c.c_void_p, c.c_void_p, c.c_long, c.c_uint32]),
    (_CF, 'CFEqual', c.c_bool, [c.c_void_p, c.c_void_p]),
    (_CF, 'CFRelease', None, [c.c_void_p]),
):
    function = getattr(library, name)
    function.restype, function.argtypes = result, arguments

# The Input menu asks the target's Text Services Manager to perform the switch.
# These two entry points are private and may be absent on other macOS versions.
# Protocol reference: https://github.com/laishulu/macism/blob/master/TSMUtils.swift
_tsm: dict[str, Any] = {}
objc.loadBundleFunctions(None, _tsm, [
    ('CFMessagePortCreatePerProcessRemote', b'^{__CFMessagePort=}^{__CFAllocator=}^{__CFString=}i', '',
     {'retval': {'already_cfretained': True}}),
    ('_CreateFlattenedInputSource', b'B^vo^@', '', {'arguments': {1: {'already_cfretained': True}}}),
], skip_undefined=True)
_TSM_SELECT_INPUT_SOURCE = 7


def _constant(name: str) -> int | None:
    return c.c_void_p.in_dll(_TIS, name).value


def _property(source: int, name: str) -> int | None:
    return _TIS.TISGetInputSourceProperty(source, _constant(name))


def _source_id(source: int) -> str:
    value = _property(source, 'kTISPropertyInputSourceID')
    if not value:
        raise RuntimeError('Input source has no identifier.')
    buffer = c.create_string_buffer(_CF.CFStringGetLength(value) * 4 + 1)
    if not _CF.CFStringGetCString(value, buffer, len(buffer), 0x08000100):  # UTF-8
        raise RuntimeError('Cannot read input source identifier.')
    return buffer.value.decode('utf-8')


def current_input_source() -> str:
    source = _TIS.TISCopyCurrentKeyboardInputSource()
    if not source:
        raise RuntimeError('Current input source is unavailable.')
    try:
        return _source_id(source)
    finally:
        _CF.CFRelease(source)


@contextmanager
def _enabled_sources() -> Iterator[dict[str, int]]:
    array = _TIS.TISCreateInputSourceList(None, False)
    if not array:
        raise RuntimeError('Keyboard input sources are unavailable.')
    try:
        sources = {}
        for index in range(_CF.CFArrayGetCount(array)):
            source = _CF.CFArrayGetValueAtIndex(array, index)
            category = _property(source, 'kTISPropertyInputSourceCategory')
            selectable = _property(source, 'kTISPropertyInputSourceIsSelectCapable')
            if (category and _CF.CFEqual(category, _constant('kTISCategoryKeyboardInputSource'))
                    and selectable and _CF.CFBooleanGetValue(selectable)):
                sources[_source_id(source)] = source
        yield sources
    finally:
        _CF.CFRelease(array)


def _select_in_target(source: int, pid: int) -> bool:
    """Ask the frontmost text client to activate the source, keeping keyboard focus there."""
    remote = _tsm.get('CFMessagePortCreatePerProcessRemote')
    flatten = _tsm.get('_CreateFlattenedInputSource')
    if remote is None or flatten is None:
        return False
    port = remote(None, 'com.apple.tsm.portname', pid)
    if port is None:
        return False
    ok, flat = flatten(source, None)
    if not ok or flat is None:
        return False
    cf = cast(Any, CoreFoundation)
    request, error = cf.CFPropertyListCreateData(None, {'tsmInputSourceSelectedInpSrcKey': flat},
                                                  cf.kCFPropertyListXMLFormat_v1_0, 0, None)
    if request is None:
        raise RuntimeError(f'Could not encode input source: {error}')
    status, reply = cf.CFMessagePortSendRequest(port, _TSM_SELECT_INPUT_SOURCE, request, .3, .3,
                                                cf.kCFRunLoopDefaultMode, None)
    if status != cf.kCFMessagePortSuccess:
        raise RuntimeError(f'The text client did not acknowledge the input source switch ({status}).')
    if reply:
        error_code = plistlib.loads(bytes(reply)).get('tsmInputModeReplyToServerErrorKey', 0)
        if error_code:
            raise RuntimeError(f'The text client rejected the input source switch ({error_code}).')
    return True


def _select(source_id: str, source: int) -> int:
    pid = frontmost_target()
    if not pid:
        raise RuntimeError('No foreground application to switch input sources.')
    if _select_in_target(source, pid):
        return pid
    status = _TIS.TISSelectInputSource(source)
    if status:
        raise RuntimeError(f'Input source switch failed ({status}).')
    for _ in range(20):
        if current_input_source() == source_id:
            return pid
        time.sleep(.01)
    raise RuntimeError('Input source did not change.')


def choose_input_source(current: str, enabled: Iterable[str], previous: str | None,
                        history: Iterable[Mapping[str, str]]) -> str:
    candidates = [previous]
    for entry in history:
        candidates.append(entry.get('Input Mode') or entry.get('Bundle ID'))
        if entry.get('InputSourceKind') == 'Keyboard Layout':
            candidates.append('com.apple.keylayout.' + entry.get('KeyboardLayout Name', ''))
    candidates.extend(enabled)
    for candidate in candidates:
        if candidate and candidate != current and candidate in enabled:
            return candidate
    raise RuntimeError('No other enabled keyboard input source.')


def switch_input_source(previous: str | None = None) -> tuple[str, int]:
    """Switch sources and return the old source ID and the target application's PID."""
    F: Any = importlib.import_module('Foundation')
    preferences = F.NSUserDefaults.standardUserDefaults().persistentDomainForName_('com.apple.HIToolbox') or {}
    current = current_input_source()
    with _enabled_sources() as sources:
        target = choose_input_source(current, sources, previous, preferences.get('AppleInputSourceHistory', []))
        pid = _select(target, sources[target])
    return current, pid
