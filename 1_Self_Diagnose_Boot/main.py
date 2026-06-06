import time
import network
import ustruct as struct
from machine import Pin, SPI, I2C
from sx127x import SX127x
import bme280_float as bme280

DIAG_BME_OK  = 1 << 0
DIAG_LORA_OK = 1 << 1
DIAG_WIFI_OK = 1 << 2
DIAG_SD_OK   = 1 << 3
DIAG_LED_OK  = 1 << 4
DIAG_CRIT    = 1 << 7

diag_status = 0

# LEDs - change pins according to your board
LED_PINS = [2, 38]   # example only

# I2C pins
I2C_SDA = 9
I2C_SCL = 8

# LoRa pins
lora_pins = {
    'dio_0': 46,
    'ss': 48,
    'reset': 45,
    'sck': 14,
    'miso': 21,
    'mosi': 47,
}

lora_default = {
    'frequency': 868000000,
    'frequency_offset': 0,
    'tx_power_level': 14,
    'signal_bandwidth': 125e3,
    'spreading_factor': 9,
    'coding_rate': 5,
    'preamble_length': 8,
    'implicitHeader': False,
    'sync_word': 0x12,
    'enable_CRC': True,
    'invert_IQ': False,
    'debug': False,
}

bme = None
lora = None


def test_leds():
    try:
        for pin_no in LED_PINS:
            led = Pin(pin_no, Pin.OUT)
            led.value(1)
            time.sleep(0.2)
            led.value(0)
        return True
    except Exception as e:
        print("LED test failed:", e)
        return False


def test_bme280():
    global bme

    try:
        i2c = I2C(0, sda=Pin(I2C_SDA), scl=Pin(I2C_SCL))
        devices = i2c.scan()
        print("I2C devices:", [hex(d) for d in devices])

        if 0x76 not in devices and 0x77 not in devices:
            print("BME280 not found")
            return False

        bme = bme280.BME280(i2c=i2c)

        temp = bme.values[0]
        press = bme.values[1]
        hum = bme.values[2]

        print("BME280:", temp, press, hum)
        return True

    except Exception as e:
        print("BME280 test failed:", e)
        return False


def test_lora():
    global lora

    try:
        lora_spi = SPI(
            baudrate=10000000,
            polarity=0,
            phase=0,
            bits=8,
            firstbit=SPI.MSB,
            sck=Pin(lora_pins['sck'], Pin.OUT, Pin.PULL_DOWN),
            mosi=Pin(lora_pins['mosi'], Pin.OUT, Pin.PULL_UP),
            miso=Pin(lora_pins['miso'], Pin.IN, Pin.PULL_UP),
        )

        lora = SX127x(lora_spi, pins=lora_pins, parameters=lora_default)

        print("LoRa init OK")
        return True

    except Exception as e:
        print("LoRa test failed:", e)
        return False


def test_wifi_basic():
    try:
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)

        mac = wlan.config("mac")
        print("WiFi MAC:", ":".join("{:02X}".format(b) for b in mac))

        return True

    except Exception as e:
        print("WiFi test failed:", e)
        return False


def test_sd_card():
    # Keep this disabled first until SD pins/interface are confirmed.
    print("SD test skipped")
    return False


def run_boot_diagnostics():
    global diag_status

    print("========== BOOT DIAGNOSTIC START ==========")

    if test_leds():
        diag_status |= DIAG_LED_OK

    if test_bme280():
        diag_status |= DIAG_BME_OK

    if test_lora():
        diag_status |= DIAG_LORA_OK

    if test_wifi_basic():
        diag_status |= DIAG_WIFI_OK

    if test_sd_card():
        diag_status |= DIAG_SD_OK

    if not (diag_status & DIAG_BME_OK) or not (diag_status & DIAG_LORA_OK):
        diag_status |= DIAG_CRIT

    print("Diagnostic status byte:", bin(diag_status))
    print("Diagnostic status hex :", hex(diag_status))
    print("========== BOOT DIAGNOSTIC END ==========")

    return diag_status


STRUCT_FORMAT = "!BBHfL"
# group_id: 1 byte
# diag_status: 1 byte
# counter: 2 bytes
# temperature: float
# pressure: unsigned long

counter = 0
group_id = 1

run_boot_diagnostics()

while True:
    try:
        if bme is not None:
            temperature = float(bme.values[0].replace("C", ""))
            pressure = int(float(bme.values[1].replace("hPa", "")))
        else:
            temperature = -999.0
            pressure = 0

        payload = struct.pack(
            STRUCT_FORMAT,
            group_id,
            diag_status,
            counter,
            temperature,
            pressure
        )

        print("TX:", group_id, diag_status, counter, temperature, pressure)
        print("Payload size:", len(payload), "bytes")

        if lora is not None:
            lora.println(payload)
        else:
            print("LoRa not available. Packet not sent.")

        counter += 1
        time.sleep(5)

    except Exception as e:
        print("Main loop error:", e)
        time.sleep(5)