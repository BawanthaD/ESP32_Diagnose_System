import time
from machine import Pin
import sys

DIAG_BUTTON_PIN = 0   # change this if you have a real user button
DIAG_ACTIVE_LEVEL = 0 # 0 = active low, 1 = active high


def button_diag_requested():
    try:
        btn = Pin(DIAG_BUTTON_PIN, Pin.IN, Pin.PULL_UP)

        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 2000:
            if btn.value() != DIAG_ACTIVE_LEVEL:
                return False
            time.sleep(0.05)

        return True

    except:
        return False


def serial_diag_requested():
    print("Type 'diag' within 3 seconds to enter diagnostic mode...")

    start = time.ticks_ms()
    cmd = ""

    while time.ticks_diff(time.ticks_ms(), start) < 3000:
        if sys.stdin in select.poll():
            pass

    return False