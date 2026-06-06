import time
import os
import vfs
import gc
import machine
import network
from machine import Pin, I2C, SPI, SDCard
from sx127x import SX127x
import bme280_float as bme280


# -----------------------------
# Pins
# -----------------------------
LED_PINS = [2, 38]

I2C_SDA = 9
I2C_SCL = 8

SD_SCK  = 12
SD_MISO = 13
SD_MOSI = 11
SD_CS   = 10

lora_pins = {
    "dio_0": 46,
    "ss": 48,
    "reset": 45,
    "sck": 14,
    "miso": 21,
    "mosi": 47,
}

lora_default = {
    "frequency": 868000000,
    "frequency_offset": 0,
    "tx_power_level": 14,
    "signal_bandwidth": 125e3,
    "spreading_factor": 9,
    "coding_rate": 5,
    "preamble_length": 8,
    "implicitHeader": False,
    "sync_word": 0x12,
    "enable_CRC": True,
    "invert_IQ": False,
    "debug": False,
}


results = {}


def result(name, ok, detail=""):
    results[name] = ok
    status = "PASS" if ok else "FAIL"
    print("[{}] {} {}".format(status, name, detail))


def test_system():
    try:
        gc.collect()
        detail = "freq={} free_mem={} reset_cause={}".format(
            machine.freq(),
            gc.mem_free(),
            machine.reset_cause()
        )
        result("SYSTEM", True, detail)
    except Exception as e:
        result("SYSTEM", False, str(e))


def test_leds():
    try:
        for p in LED_PINS:
            led = Pin(p, Pin.OUT)
            led.value(1)
            time.sleep(0.2)
            led.value(0)
            time.sleep(0.1)
        result("LED_GPIO", True, "pins={}".format(LED_PINS))
    except Exception as e:
        result("LED_GPIO", False, str(e))


def test_i2c_bme280():
    try:
        i2c = I2C(0, sda=Pin(I2C_SDA), scl=Pin(I2C_SCL))
        devices = i2c.scan()
        print("I2C devices:", [hex(x) for x in devices])

        if 0x76 not in devices and 0x77 not in devices:
            result("BME280", False, "not found on I2C")
            return

        bme = bme280.BME280(i2c=i2c)
        temp, press, hum = bme.values

        result("BME280", True, "{} {} {}".format(temp, press, hum))

    except Exception as e:
        result("BME280", False, str(e))


def test_lora():
    try:
        spi = SPI(
            baudrate=10000000,
            polarity=0,
            phase=0,
            bits=8,
            firstbit=SPI.MSB,
            sck=Pin(lora_pins["sck"], Pin.OUT, Pin.PULL_DOWN),
            mosi=Pin(lora_pins["mosi"], Pin.OUT, Pin.PULL_UP),
            miso=Pin(lora_pins["miso"], Pin.IN, Pin.PULL_UP),
        )

        lora = SX127x(spi, pins=lora_pins, parameters=lora_default)
        lora.println("DIAG_TEST")

        result("LORA", True, "init + TX command OK")

    except Exception as e:
        result("LORA", False, str(e))


def test_sd_card():
    try:
        sd = SDCard(
            slot=2,
            sck=Pin(SD_SCK),
            miso=Pin(SD_MISO),
            mosi=Pin(SD_MOSI),
            cs=Pin(SD_CS)
        )

        vfs.mount(sd, "/sd")
        files = os.listdir("/sd")
        print("SD files:", files)

        path = "/sd/diag_test.txt"
        expected = "ESP32-S3 SD DIAG PASS"

        with open(path, "w") as f:
            f.write(expected)
            f.flush()

        with open(path, "r") as f:
            actual = f.read()

        if actual != expected:
            result("SD_CARD", False, "read/write mismatch")
            vfs.umount("/sd")
            return

        os.remove(path)
        vfs.umount("/sd")

        result("SD_CARD", True, "mount + write + read + delete OK")

    except Exception as e:
        try:
            vfs.umount("/sd")
        except:
            pass
        result("SD_CARD", False, str(e))


def test_wifi_basic():
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        mac = wlan.config("mac")
        mac_str = ":".join("{:02X}".format(b) for b in mac)

        result("WIFI_BASIC", True, "MAC={}".format(mac_str))

        wlan.active(False)

    except Exception as e:
        result("WIFI_BASIC", False, str(e))


def print_summary():
    print("")
    print("========== DIAGNOSTIC SUMMARY ==========")

    passed = 0
    failed = 0

    for name in results:
        if results[name]:
            passed += 1
            print("{}: PASS".format(name))
        else:
            failed += 1
            print("{}: FAIL".format(name))

    print("----------------------------------------")
    print("PASSED:", passed)
    print("FAILED:", failed)

    if failed == 0:
        print("OVERALL RESULT: PASS")
    else:
        print("OVERALL RESULT: FAIL")

    print("========================================")


print("")
print("========== ESP32-S3 SERIAL DIAGNOSTIC ==========")

test_system()
test_leds()
test_i2c_bme280()
test_lora()
test_sd_card()
test_wifi_basic()
print_summary()

while True:
    time.sleep(1)