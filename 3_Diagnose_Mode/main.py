import time
from machine import Pin

DIAG_BUTTON_PIN = 0   
DIAG_ACTIVE_LEVEL = 0


def diagnostic_button_held():
    try:
        btn = Pin(DIAG_BUTTON_PIN, Pin.IN, Pin.PULL_UP)

        print("Checking diagnostic button...")

        start = time.ticks_ms()

        while time.ticks_diff(time.ticks_ms(), start) < 2000:
            if btn.value() != DIAG_ACTIVE_LEVEL:
                print("Normal mode selected")
                return False

            time.sleep(0.05)

        print("Diagnostic mode selected")
        return True

    except Exception as e:
        print("Button check failed:", e)
        return False


if diagnostic_button_held():
    import diagnostic
    diagnostic.run()
else:
    import transmit
    transmit.run()