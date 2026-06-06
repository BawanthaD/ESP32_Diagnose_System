import time
from machine import Pin, SPI, I2C
from sx127x import SX127x
import bme280_float as bme280
import ustruct as struct

i2c = I2C(0, sda=Pin(9), scl=Pin(8))
bme = bme280.BME280(i2c=i2c)

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

lora_pins = {
    'dio_0': 46,
    'ss': 48,
    'reset': 45,
    'sck': 14,
    'miso': 21,
    'mosi': 47,
}

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

STRUCT_FORMAT = "!BHfL"

counter = 0
group_id = 1

while True:

    temperature = float(
        bme.values[0].replace("C", "")
    )

    pressure = int(
        float(
            bme.values[1].replace("hPa", "")
        )
    )

    payload = struct.pack(
        STRUCT_FORMAT,
        group_id,
        counter,
        temperature,
        pressure
    )

    print("TX:", group_id, counter, temperature, pressure)
    print("Payload size:", len(payload), "bytes")

    lora.println(payload)

    counter += 1

    time.sleep(5)