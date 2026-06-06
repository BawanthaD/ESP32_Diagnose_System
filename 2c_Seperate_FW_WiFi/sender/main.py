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

WIFI_SSID = "BAWANTHA-LEGION 4449"
WIFI_PASSWORD = "079*X2j1"

LAPTOP_IP = "134.102.101.40"
SERVER_PORT = 5000
POST_PATH = "/api/diagnostic"


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


def get_board_id():
    try:
        chip_id = ubinascii.hexlify(machine.unique_id()).decode().upper()
        return chip_id
    except:
        return "ESP32_UNKNOWN"


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


def connect_wifi():
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)

        if not wlan.isconnected():
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)

            for _ in range(25):
                if wlan.isconnected():
                    break
                time.sleep(0.5)

        if wlan.isconnected():
            ip = wlan.ifconfig()[0]
            set_result("wifi", True, "IP={}".format(ip))
            return wlan

        set_result("wifi", False, "connection timeout")
        return None

    except Exception as e:
        set_result("wifi", False, str(e))
        return None


def update_overall():
    required = ["system", "led_gpio", "bme280", "lora", "sd_card", "wifi"]

    for item in required:
        if diag[item] != "PASS":
            diag["overall"] = "FAIL"
            return

    diag["overall"] = "PASS"


def send_to_server():
    try:
        payload = json.dumps(diag)

        addr = socket.getaddrinfo(LAPTOP_IP, SERVER_PORT)[0][-1]
        s = socket.socket()
        s.settimeout(5)
        s.connect(addr)

        request = (
            "POST {} HTTP/1.1\r\n"
            "Host: {}:{}\r\n"
            "Content-Type: application/json\r\n"
            "Content-Length: {}\r\n"
            "Connection: close\r\n"
            "\r\n"
            "{}"
        ).format(
            POST_PATH,
            LAPTOP_IP,
            SERVER_PORT,
            len(payload),
            payload
        )

        s.send(request.encode())
        response = s.recv(512)
        s.close()

        print("Server response:", response)
        return True

    except Exception as e:
        print("Send to server FAIL:", e)
        return False


def run_diagnostics():
    print("")
    print("========== ESP32-S3 WIFI DIAGNOSTIC SENDER ==========")

    diag["board_id"] = get_board_id()

    print("Board ID:", diag["board_id"])

    test_system()
    test_leds()
    test_bme280()
    test_lora()
    test_sd_card()

    connect_wifi()
    update_overall()

    print("Diagnostic JSON:")
    print(json.dumps(diag))

    if diag["wifi"] == "PASS":
        send_to_server()

    print("Done.")


run_diagnostics()

while True:
    time.sleep(5)