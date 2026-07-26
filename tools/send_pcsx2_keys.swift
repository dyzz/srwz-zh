#!/usr/bin/env swift

import CoreGraphics
import Foundation

func fail(_ message: String) -> Never {
    FileHandle.standardError.write(Data("error: \(message)\n".utf8))
    exit(1)
}

guard CommandLine.arguments.count >= 4 else {
    fail("usage: send_pcsx2_keys.swift PID DELAY_MS KEYCODE [KEYCODE ...]")
}
guard let pid = Int32(CommandLine.arguments[1]), pid > 0 else {
    fail("PID must be a positive integer")
}
guard let delayMilliseconds = UInt32(CommandLine.arguments[2]) else {
    fail("DELAY_MS must be a non-negative integer")
}
let keyCodes = CommandLine.arguments.dropFirst(3).map { raw -> CGKeyCode in
    guard let value = UInt16(raw) else {
        fail("invalid key code: \(raw)")
    }
    return CGKeyCode(value)
}

for keyCode in keyCodes {
    guard
        let down = CGEvent(
            keyboardEventSource: nil,
            virtualKey: keyCode,
            keyDown: true
        ),
        let up = CGEvent(
            keyboardEventSource: nil,
            virtualKey: keyCode,
            keyDown: false
        )
    else {
        fail("could not create key event")
    }
    down.postToPid(pid_t(pid))
    usleep(80_000)
    up.postToPid(pid_t(pid))
    usleep(delayMilliseconds * 1_000)
}
