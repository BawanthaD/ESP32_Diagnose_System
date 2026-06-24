"""
Board configuration for the MoleNet ESP32-S3 board.

Keep all pin assignments and diagnostic options here so the normal firmware
and diagnostic firmware can share the same hardware map.
"""

BOARD_ID = "molenet-esp32s3"
RUN_FOREVER_AFTER_DIAG = True

# -----------------------------
# LEDs / simple GPIO
# -----------------------------
STATUS_LED_PIN = 2
LED_PINS = [2, 38]

# Pins that are safe to toggle during the software GPIO readback test.
GPIO_OUTPUT_READBACK_PINS = [
    {"name": "status_led", "pin": 2, "restore": 0},
    {"name": "aux_led", "pin": 38, "restore": 0},
    {"name": "sdi12_power", "pin": 1, "restore": 0},
    {"name": "sdi12_tx_enable", "pin": 35, "restore": 0},
    {"name": "sdi12_rx_enable", "pin": 36, "restore": 0},
    {"name": "sdi12_marking", "pin": 37, "restore": 1},
    {"name": "ds18b20_power", "pin": 41, "restore": 0},
]

# Pins that are checked by creating a Pin object and reading their level only.
# This verifies the pin number is valid in MicroPython without actively toggling it.
GPIO_INIT_ONLY_PINS = [
    {"name": "i2c_scl", "pin": 8},
    {"name": "i2c_sda", "pin": 9},
    {"name": "sd_sck", "pin": 12},
    {"name": "sd_miso", "pin": 13},
    {"name": "sd_mosi", "pin": 11},
    {"name": "sd_cs", "pin": 10},
    {"name": "lora_sck", "pin": 14},
    {"name": "lora_miso", "pin": 21},
    {"name": "lora_mosi", "pin": 47},
    {"name": "lora_cs", "pin": 48},
    {"name": "lora_reset", "pin": 15},
    {"name": "lora_dio0", "pin": 46},
    {"name": "ds18b20_data", "pin": 42},
    {"name": "sdi12_rx", "pin": 18},
    {"name": "sdi12_tx", "pin": 17},
]

# Optional pull-up/pull-down check. Leave empty if pins are connected to
# external circuits that may force their logic level.
GPIO_INPUT_PULL_TEST_PINS = []

# -----------------------------
# I2C / BME280
# -----------------------------
I2C = {
    "id": 0,
    "sda": 9,
    "scl": 8,
    "freq": 10_000,
    "use_soft_i2c": True,
}

BME280 = {
    "enabled": True,
    "addresses": [0x76, 0x77],
    "module_names": ["BME280", "bme280_float"],
}

# -----------------------------
# DS18B20 one-wire temperature sensor
# -----------------------------
DS18B20 = {
    "enabled": True,
    "data_pin": 42,
    "power_pin": 41,
    "conversion_ms": 750,
}

# -----------------------------
# SDI-12 / TEROS soil sensor
# -----------------------------
SDI12 = {
    "enabled": True,
    "address": 1,
    "rx": 18,
    "tx": 17,
    "marking": 37,
    "rx_enable": 36,
    "tx_enable": 35,
    "power": 1,
    "power_up_ms": 165,
}

# -----------------------------
# SD card
# -----------------------------
SDCARD = {
    "enabled": True,
    "slot": 2,
    "sck": 12,
    "miso": 13,
    "mosi": 11,
    "cs": 10,
    "freq": 200_000,
    "mount_point": "/sd",
    "test_file": "/sd/diag_test.txt",
}

SAVE_JSON_REPORT_TO_SD = True
JSON_REPORT_PATH = "/sd/diagnostic_report.json"

# -----------------------------
# LoRa / SX1276
# -----------------------------
LORA = {
    "enabled": True,
    "driver_preference": ["SX1276", "sx127x"],
    "baudrate": 400_000,
    "sck": 14,
    "miso": 21,
    "mosi": 47,
    "cs": 48,
    "reset": 15,
    "dio0": 46,
    "probe_lorawan_object": True,
    "test_message": "DIAG_TEST",
}

# Parameters used only when the fallback sx127x driver is present.
LORA_SX127X_PARAMETERS = {
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

# Main firmware dependencies worth checking in diagnostic mode.
REQUIRED_MAIN_MODULES = [
    "BME280",
    "onewire",
    "ds18x20",
    "SDI12",
    "SX1276",
    "LoRaWAN",
    "EU868",
    "config_OTAA",
]

# -----------------------------
# Wi-Fi + diagnostic report upload
# -----------------------------
WIFI = {
    "enabled": True,
    "ssid": "BAWANTHA-LEGION 4449",
    "password": "079*X2j1",
    "connect_timeout_s": 15,
    "scan": False,
    "disconnect_after_send": False,
}

# Optional HTTP POST upload of the full diagnostic JSON.
# This is based on the older Wi-Fi diagnostic sender test code.
DIAGNOSTIC_SERVER = {
    "enabled": True,
    "host": "134.102.101.40",
    "port": 5000,
    "post_path": "/api/diagnostic",
    "socket_timeout_s": 5,
    "extra_headers": {},
}
