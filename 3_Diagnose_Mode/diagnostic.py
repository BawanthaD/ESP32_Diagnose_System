import time
import os
import vfs
import gc
import json
import socket
import machine
import network
import ubinascii

from machine import Pin, I2C, SPI, SDCard
from sx127x import SX127x
import bme280_float as bme280


# -----------------------------
# Board pins
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


diag = {
    "board_id": "",
    "system": "FAIL",
    "led_gpio": "FAIL",
    "bme280": "FAIL",
    "lora": "FAIL",
    "sd_card": "FAIL",
    "wifi": "FAIL",
    "overall": "FAIL",
    "details": {},
}


def set_result(name, passed, detail=""):
    diag[name] = "PASS" if passed else "FAIL"
    diag["details"][name] = detail
    print("[{}] {} {}".format(diag[name], name, detail))


def test_system():
    try:
        gc.collect()
        detail = {
            "freq": machine.freq(),
            "free_mem": gc.mem_free(),
            "reset_cause": machine.reset_cause()
        }
        set_result("system", True, detail)
    except Exception as e:
        set_result("system", False, str(e))


def test_leds():
    try:
        for p in LED_PINS:
            led = Pin(p, Pin.OUT)
            led.value(1)
            time.sleep(0.15)
            led.value(0)
            time.sleep(0.1)
        set_result("led_gpio", True, "pins={}".format(LED_PINS))
    except Exception as e:
        set_result("led_gpio", False, str(e))


def test_bme280():
    try:
        i2c = I2C(0, sda=Pin(I2C_SDA), scl=Pin(I2C_SCL))
        devices = i2c.scan()

        if 0x76 not in devices and 0x77 not in devices:
            set_result("bme280", False, "BME280 not found, I2C={}".format(devices))
            return

        bme = bme280.BME280(i2c=i2c)
        temp, press, hum = bme.values

        set_result("bme280", True, "{} {} {}".format(temp, press, hum))

    except Exception as e:
        set_result("bme280", False, str(e))


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

        set_result("lora", True, "init + test TX OK")

    except Exception as e:
        set_result("lora", False, str(e))


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

        test_path = "/sd/diag_test.txt"
        expected = "ESP32-S3 SD DIAG PASS"

        with open(test_path, "w") as f:
            f.write(expected)
            f.flush()

        with open(test_path, "r") as f:
            actual = f.read()

        if actual != expected:
            set_result("sd_card", False, "read/write mismatch")
            vfs.umount("/sd")
            return

        os.remove(test_path)
        vfs.umount("/sd")

        set_result("sd_card", True, "mount + write + read + delete OK")

    except Exception as e:
        try:
            vfs.umount("/sd")
        except:
            pass
        set_result("sd_card", False, str(e))

def run():
    print("Starting diagnostic mode...")

    test_system()
    test_leds()
    test_bme280()
    test_lora()
    test_sd_card()

    print("Diagnostic complete")

    while True:
        time.sleep(1)