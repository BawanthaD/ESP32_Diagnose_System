"""
Enhanced diagnostic firmware for the MoleNet ESP32-S3 board.

Copy this file to the board as diagnostic.py and copy board_config.py beside it.
Run with:

    import diagnostic
    diagnostic.run()

The GPIO test is a software-level test only. It verifies that MicroPython can
configure/read/toggle selected pins. It cannot prove that the external trace,
solder joint, sensor, or connector is physically good.
"""

import gc
import json
import os
import socket
import sys
import time

try:
    import machine
    from machine import Pin
except ImportError:
    machine = None
    Pin = None

try:
    import ubinascii
except ImportError:
    ubinascii = None

try:
    import vfs
except ImportError:
    vfs = None

import board_config as cfg


PASS = "PASS"
FAIL = "FAIL"
WARN = "WARN"
SKIP = "SKIP"


diag = {
    "board_id": cfg.BOARD_ID,
    "esp32_unique_id": None,
    "overall": FAIL,
    "results": {},
    "summary": {},
}

_wifi_wlan = None


def sleep_ms(ms):
    if hasattr(time, "sleep_ms"):
        time.sleep_ms(ms)
    else:
        time.sleep(ms / 1000.0)


def ticks_ms():
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.time() * 1000)


def ticks_diff(end, start):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(end, start)
    return end - start


def import_module(name):
    return __import__(name)


def import_first(names):
    errors = []
    for name in names:
        try:
            return name, import_module(name), errors
        except Exception as exc:
            errors.append("{}: {}".format(name, exc))
    raise ImportError("; ".join(errors))


def memory_snapshot(collect=True):
    if collect:
        try:
            gc.collect()
        except Exception:
            pass

    free = None
    allocated = None
    total = None
    used_percent = None

    if hasattr(gc, "mem_free"):
        try:
            free = gc.mem_free()
        except Exception:
            free = None

    if hasattr(gc, "mem_alloc"):
        try:
            allocated = gc.mem_alloc()
        except Exception:
            allocated = None

    if free is not None and allocated is not None:
        total = free + allocated
        if total:
            used_percent = round((allocated * 100.0) / total, 1)

    return {
        "free_bytes": free,
        "allocated_bytes": allocated,
        "total_bytes": total,
        "used_percent": used_percent,
    }


def to_jsonable(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (list, tuple)):
        return [to_jsonable(x) for x in value]
    if isinstance(value, dict):
        out = {}
        for key, val in value.items():
            out[str(key)] = to_jsonable(val)
        return out
    try:
        return str(value)
    except Exception:
        return "<unprintable>"


def run_case(name, func):
    before = memory_snapshot(collect=True)
    start = ticks_ms()
    status = FAIL
    detail = {}

    try:
        result = func()
        if isinstance(result, tuple) and len(result) == 2:
            status, detail = result
        elif isinstance(result, bool):
            status = PASS if result else FAIL
            detail = {}
        else:
            status = PASS
            detail = {"message": result}
    except Exception as exc:
        status = FAIL
        detail = {"error": repr(exc)}

    after = memory_snapshot(collect=True)
    elapsed = ticks_diff(ticks_ms(), start)

    if not isinstance(detail, dict):
        detail = {"message": detail}

    detail["memory_before"] = before
    detail["memory_after"] = after
    detail["elapsed_ms"] = elapsed

    diag["results"][name] = {
        "status": status,
        "detail": to_jsonable(detail),
    }

    print("[{}] {} {}".format(status, name, detail_without_memory(detail)))
    return status


def detail_without_memory(detail):
    compact = {}
    for key, value in detail.items():
        if key not in ("memory_before", "memory_after"):
            compact[key] = value
    return compact


def pin_label(item):
    if isinstance(item, dict):
        return item.get("name", "gpio{}".format(item.get("pin"))), item.get("pin"), item
    return "gpio{}".format(item), item, {"pin": item}


def hex_bytes(data):
    if data is None:
        return None
    try:
        return data.hex("-")
    except Exception:
        pass
    try:
        if ubinascii:
            return ubinascii.hexlify(data).decode().upper()
    except Exception:
        pass
    return str(data)


def get_esp32_unique_id():
    if machine is None:
        return None
    try:
        return hex_bytes(machine.unique_id())
    except Exception:
        return None


def parse_number(value):
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    chars = []
    started = False
    for char in text:
        if char in "+-" and not started:
            chars.append(char)
            started = True
        elif char.isdigit() or char == ".":
            chars.append(char)
            started = True
        elif started:
            break
    if not chars or chars == ["+"] or chars == ["-"]:
        raise ValueError("cannot parse number from {}".format(value))
    return float("".join(chars))


def make_i2c():
    if machine is None:
        raise RuntimeError("machine module is not available")

    sda = Pin(cfg.I2C["sda"])
    scl = Pin(cfg.I2C["scl"])
    freq = cfg.I2C.get("freq", 100000)

    if cfg.I2C.get("use_soft_i2c", False) and hasattr(machine, "SoftI2C"):
        return machine.SoftI2C(sda=sda, scl=scl, freq=freq)

    return machine.I2C(cfg.I2C.get("id", 0), sda=sda, scl=scl, freq=freq)


def format_i2c_devices(devices):
    return ["0x{:02x}".format(dev) for dev in devices]


def test_system():
    if machine is None:
        return FAIL, {"error": "machine module unavailable"}

    unique_id = get_esp32_unique_id()
    diag["esp32_unique_id"] = unique_id

    uname = None
    try:
        uname = os.uname()
        uname = {
            "sysname": uname.sysname,
            "nodename": uname.nodename,
            "release": uname.release,
            "version": uname.version,
            "machine": uname.machine,
        }
    except Exception as exc:
        uname = str(exc)

    reset_cause = None
    try:
        reset_cause = machine.reset_cause()
    except Exception:
        pass

    freq = None
    try:
        freq = machine.freq()
    except Exception:
        pass

    return PASS, {
        "unique_id": unique_id,
        "freq_hz": freq,
        "reset_cause": reset_cause,
        "python": str(getattr(sys, "implementation", "unknown")),
        "uname": uname,
        "memory": memory_snapshot(collect=True),
    }


def test_gpio_software():
    if Pin is None:
        return FAIL, {"error": "Pin class unavailable"}

    output_results = []
    init_results = []
    pull_results = []
    failures = []

    for item in cfg.GPIO_OUTPUT_READBACK_PINS:
        name, pin_no, meta = pin_label(item)
        result = {"name": name, "pin": pin_no}
        try:
            pin = Pin(pin_no, Pin.OUT)
            pin.value(0)
            sleep_ms(5)
            low = pin.value()
            pin.value(1)
            sleep_ms(5)
            high = pin.value()
            restore = meta.get("restore", 0)
            pin.value(restore)

            ok = (low == 0 and high == 1)
            result.update({"low_readback": low, "high_readback": high, "restore": restore, "ok": ok})
            if not ok:
                failures.append(result)
        except Exception as exc:
            result.update({"ok": False, "error": str(exc)})
            failures.append(result)
        output_results.append(result)

    seen = set()
    for item in cfg.GPIO_INIT_ONLY_PINS:
        name, pin_no, meta = pin_label(item)
        if pin_no in seen:
            continue
        seen.add(pin_no)
        result = {"name": name, "pin": pin_no}
        try:
            pin = Pin(pin_no)
            result.update({"level": pin.value(), "ok": True})
        except Exception as exc:
            result.update({"ok": False, "error": str(exc)})
            failures.append(result)
        init_results.append(result)

    for item in cfg.GPIO_INPUT_PULL_TEST_PINS:
        name, pin_no, meta = pin_label(item)
        result = {"name": name, "pin": pin_no}
        try:
            down_pin = Pin(pin_no, Pin.IN, Pin.PULL_DOWN)
            sleep_ms(5)
            down = down_pin.value()
            up_pin = Pin(pin_no, Pin.IN, Pin.PULL_UP)
            sleep_ms(5)
            up = up_pin.value()
            ok = (down == 0 and up == 1)
            result.update({"pulldown_read": down, "pullup_read": up, "ok": ok})
            if not ok:
                failures.append(result)
        except Exception as exc:
            result.update({"ok": False, "error": str(exc)})
            failures.append(result)
        pull_results.append(result)

    detail = {
        "note": "software-level GPIO check only; not a physical continuity test",
        "output_readback": output_results,
        "init_only": init_results,
        "input_pull": pull_results,
        "failures": failures,
    }
    return (PASS if not failures else FAIL), detail


def test_leds_visual():
    if Pin is None:
        return FAIL, {"error": "Pin class unavailable"}

    blinked = []
    for pin_no in cfg.LED_PINS:
        led = Pin(pin_no, Pin.OUT)
        led.value(1)
        sleep_ms(150)
        led.value(0)
        sleep_ms(100)
        blinked.append(pin_no)
    return PASS, {"blinked_pins": blinked, "note": "visual check: verify the LEDs blinked"}


def test_i2c_bus():
    i2c = make_i2c()
    devices = i2c.scan()
    return PASS, {
        "scl": cfg.I2C["scl"],
        "sda": cfg.I2C["sda"],
        "freq": cfg.I2C.get("freq"),
        "devices": format_i2c_devices(devices),
    }


def test_bme280():
    if not cfg.BME280.get("enabled", True):
        return SKIP, {"reason": "disabled in board_config.py"}

    i2c = make_i2c()
    devices = i2c.scan()
    expected = cfg.BME280.get("addresses", [0x76, 0x77])
    found = [dev for dev in devices if dev in expected]
    if not found:
        return FAIL, {
            "error": "BME280 address not found on I2C bus",
            "expected": format_i2c_devices(expected),
            "i2c_devices": format_i2c_devices(devices),
        }

    module_name, module, import_errors = import_first(cfg.BME280.get("module_names", ["BME280"]))
    sensor = module.BME280(i2c=i2c)

    raw = {}
    if hasattr(sensor, "values"):
        values = sensor.values
        raw = {"temperature": values[0], "pressure": values[1], "humidity": values[2]}
    else:
        raw = {
            "temperature": getattr(sensor, "temperature"),
            "pressure": getattr(sensor, "pressure"),
            "humidity": getattr(sensor, "humidity"),
        }

    temp_c = parse_number(raw["temperature"])
    pressure = parse_number(raw["pressure"])
    humidity = parse_number(raw["humidity"])

    pressure_hpa = pressure / 100.0 if pressure > 2000 else pressure

    range_warnings = []
    if temp_c < -40 or temp_c > 85:
        range_warnings.append("temperature outside expected BME280 range")
    if pressure_hpa < 300 or pressure_hpa > 1100:
        range_warnings.append("pressure outside expected hPa range")
    if humidity < 0 or humidity > 100:
        range_warnings.append("humidity outside 0-100% range")

    status = WARN if range_warnings else PASS
    return status, {
        "module": module_name,
        "address_found": format_i2c_devices(found),
        "raw": raw,
        "parsed": {
            "temperature_c": temp_c,
            "pressure_hpa": pressure_hpa,
            "humidity_percent": humidity,
        },
        "warnings": range_warnings,
        "import_errors_before_success": import_errors,
    }


def test_ds18b20():
    if not cfg.DS18B20.get("enabled", True):
        return SKIP, {"reason": "disabled in board_config.py"}

    onewire = import_module("onewire")
    ds18x20 = import_module("ds18x20")

    power_pin_no = cfg.DS18B20.get("power_pin")
    power_pin = None
    if power_pin_no is not None:
        power_pin = Pin(power_pin_no, Pin.OUT, value=1)
        sleep_ms(20)

    try:
        data_pin = Pin(cfg.DS18B20["data_pin"])
        sensor = ds18x20.DS18X20(onewire.OneWire(data_pin))
        roms = sensor.scan()
        if not roms:
            return FAIL, {"error": "no DS18B20 ROMs found", "data_pin": cfg.DS18B20["data_pin"]}

        sensor.convert_temp()
        sleep_ms(cfg.DS18B20.get("conversion_ms", 750))
        readings = []
        warnings = []
        for rom in roms:
            temp = sensor.read_temp(rom)
            rom_id = hex_bytes(rom)
            readings.append({"rom": rom_id, "temperature_c": temp})
            if temp is None or temp < -55 or temp > 125:
                warnings.append("{} outside expected DS18B20 range".format(rom_id))

        return (WARN if warnings else PASS), {
            "data_pin": cfg.DS18B20["data_pin"],
            "power_pin": power_pin_no,
            "count": len(roms),
            "readings": readings,
            "warnings": warnings,
        }
    finally:
        if power_pin is not None:
            power_pin.value(0)


def split_signed_tokens(text):
    result = []
    current = ""
    for char in text:
        if char in "+-" and current:
            result.append(current)
            current = char
        else:
            current += char
    if current:
        result.append(current)
    return [item.strip() for item in result if item.strip()]


def decode_sdi12_soil_message(message, address):
    if isinstance(message, bytes):
        text = message.decode().strip()
    else:
        text = str(message).strip()

    tokens = split_signed_tokens(text)

    if len(tokens) == 4:
        try:
            if int(tokens[0]) == int(address):
                tokens = tokens[1:]
        except Exception:
            pass

    if len(tokens) != 3:
        raise ValueError("expected 3 values after parsing, got {} from {!r}".format(len(tokens), text))

    return {
        "raw_text": text,
        "tokens": tokens,
        "soil_id": int(float(tokens[0])),
        "soil_permittivity": float(tokens[1]),
        "soil_temperature_c": float(tokens[2]),
    }


def test_sdi12():
    if not cfg.SDI12.get("enabled", True):
        return SKIP, {"reason": "disabled in board_config.py"}

    SDI12_mod = import_module("SDI12")
    SDI12_cls = getattr(SDI12_mod, "SDI12")

    power = Pin(cfg.SDI12["power"], Pin.OUT, value=1)
    sleep_ms(cfg.SDI12.get("power_up_ms", 165))

    try:
        rx = Pin(cfg.SDI12["rx"])
        tx = Pin(cfg.SDI12["tx"])
        marking = Pin(cfg.SDI12["marking"], Pin.OUT, value=1)
        rx_enable = Pin(cfg.SDI12["rx_enable"], Pin.OUT, value=0)
        tx_enable = Pin(cfg.SDI12["tx_enable"], Pin.OUT, value=0)

        sensor = SDI12_cls(rx, tx, marking, rx_enable, tx_enable)
        raw = sensor.measure(cfg.SDI12.get("address", 1))
        parsed = decode_sdi12_soil_message(raw, cfg.SDI12.get("address", 1))

        return PASS, {
            "address": cfg.SDI12.get("address", 1),
            "pins": {
                "rx": cfg.SDI12["rx"],
                "tx": cfg.SDI12["tx"],
                "marking": cfg.SDI12["marking"],
                "rx_enable": cfg.SDI12["rx_enable"],
                "tx_enable": cfg.SDI12["tx_enable"],
                "power": cfg.SDI12["power"],
            },
            "raw": raw.decode() if isinstance(raw, bytes) else str(raw),
            "parsed": parsed,
        }
    finally:
        power.value(0)


def sd_is_mounted(mount_point):
    try:
        os.listdir(mount_point)
        return True
    except Exception:
        return False


def make_sdcard():
    if machine is None:
        raise RuntimeError("machine module unavailable")

    sd_cfg = cfg.SDCARD
    kwargs = {
        "slot": sd_cfg.get("slot", 2),
        "sck": sd_cfg["sck"],
        "miso": sd_cfg["miso"],
        "mosi": sd_cfg["mosi"],
        "cs": sd_cfg["cs"],
        "freq": sd_cfg.get("freq", 200000),
    }

    try:
        return machine.SDCard(**kwargs)
    except TypeError:
        kwargs.pop("freq", None)
        try:
            return machine.SDCard(**kwargs)
        except TypeError:
            kwargs = {
                "slot": sd_cfg.get("slot", 2),
                "sck": Pin(sd_cfg["sck"]),
                "miso": Pin(sd_cfg["miso"]),
                "mosi": Pin(sd_cfg["mosi"]),
                "cs": Pin(sd_cfg["cs"]),
            }
            return machine.SDCard(**kwargs)


def mount_sd(sd, mount_point):
    if sd_is_mounted(mount_point):
        return "already_mounted"

    try:
        os.mount(sd, mount_point)
        return "os.mount"
    except Exception as os_exc:
        if vfs is None:
            raise os_exc
        vfs.mount(sd, mount_point)
        return "vfs.mount"


def unmount_sd(mount_point):
    try:
        os.umount(mount_point)
        return "os.umount"
    except Exception:
        if vfs is not None:
            try:
                vfs.umount(mount_point)
                return "vfs.umount"
            except Exception:
                pass
    return "not_unmounted"


def test_sd_card():
    if not cfg.SDCARD.get("enabled", True):
        return SKIP, {"reason": "disabled in board_config.py"}

    sd_cfg = cfg.SDCARD
    sd = make_sdcard()
    mount_method = mount_sd(sd, sd_cfg.get("mount_point", "/sd"))

    expected = "ESP32-S3 SD DIAG PASS"
    test_path = sd_cfg.get("test_file", "/sd/diag_test.txt")

    with open(test_path, "w") as file:
        file.write(expected)
        try:
            file.flush()
        except Exception:
            pass

    with open(test_path, "r") as file:
        actual = file.read()

    if actual != expected:
        return FAIL, {
            "mount_method": mount_method,
            "test_file": test_path,
            "error": "read/write mismatch",
            "expected": expected,
            "actual": actual,
        }

    try:
        os.remove(test_path)
    except Exception as exc:
        return WARN, {
            "mount_method": mount_method,
            "test_file": test_path,
            "message": "read/write passed, but test file could not be removed",
            "remove_error": str(exc),
        }

    return PASS, {
        "mount_method": mount_method,
        "slot": sd_cfg.get("slot", 2),
        "freq": sd_cfg.get("freq"),
        "pins": {
            "sck": sd_cfg["sck"],
            "miso": sd_cfg["miso"],
            "mosi": sd_cfg["mosi"],
            "cs": sd_cfg["cs"],
        },
        "test": "mount + write + read + delete OK",
    }


def make_soft_spi_for_lora():
    lora = cfg.LORA
    baudrate = lora.get("baudrate", 400000)

    if hasattr(machine, "SoftSPI"):
        try:
            return machine.SoftSPI(
                baudrate=baudrate,
                sck=Pin(lora["sck"]),
                mosi=Pin(lora["mosi"]),
                miso=Pin(lora["miso"]),
            )
        except TypeError:
            return machine.SoftSPI(
                baudrate=baudrate,
                sck=lora["sck"],
                mosi=lora["mosi"],
                miso=lora["miso"],
            )

    # Fallback for builds without SoftSPI.
    return machine.SPI(
        baudrate=baudrate,
        polarity=0,
        phase=0,
        bits=8,
        firstbit=machine.SPI.MSB,
        sck=Pin(lora["sck"]),
        mosi=Pin(lora["mosi"]),
        miso=Pin(lora["miso"]),
    )


def try_lora_sx1276_driver():
    SX1276_mod = import_module("SX1276")
    Transceiver = getattr(SX1276_mod, "Transceiver")
    spi = make_soft_spi_for_lora()
    cs = Pin(cfg.LORA["cs"], Pin.OUT, value=1)
    reset = Pin(cfg.LORA["reset"], Pin.OUT, value=1)
    dio0 = Pin(cfg.LORA["dio0"], Pin.IN)
    radio = Transceiver(spi, cs, reset, dio0)

    detail = {
        "driver": "SX1276.Transceiver",
        "pins": {
            "sck": cfg.LORA["sck"],
            "miso": cfg.LORA["miso"],
            "mosi": cfg.LORA["mosi"],
            "cs": cfg.LORA["cs"],
            "reset": cfg.LORA["reset"],
            "dio0": cfg.LORA["dio0"],
        },
        "spi": "initialized",
        "radio": "initialized",
    }

    if cfg.LORA.get("probe_lorawan_object", False):
        try:
            EU868 = import_module("EU868")
            LoRaWAN_mod = import_module("LoRaWAN")
            LoRaWAN_cls = getattr(LoRaWAN_mod, "LoRaWAN")
            lw = LoRaWAN_cls(radio, EU868.FREQS)
            detail["lorawan_object"] = "initialized"
            detail["lorawan_joined"] = getattr(lw, "joined", None)
        except Exception as exc:
            detail["lorawan_object"] = "warning: {}".format(exc)
            return WARN, detail

    return PASS, detail


def try_lora_sx127x_driver():
    sx127x_mod = import_module("sx127x")
    SX127x = getattr(sx127x_mod, "SX127x")
    lora_cfg = cfg.LORA

    spi = machine.SPI(
        baudrate=lora_cfg.get("baudrate", 400000),
        polarity=0,
        phase=0,
        bits=8,
        firstbit=machine.SPI.MSB,
        sck=Pin(lora_cfg["sck"], Pin.OUT, Pin.PULL_DOWN),
        mosi=Pin(lora_cfg["mosi"], Pin.OUT, Pin.PULL_UP),
        miso=Pin(lora_cfg["miso"], Pin.IN, Pin.PULL_UP),
    )

    pins = {
        "dio_0": lora_cfg["dio0"],
        "ss": lora_cfg["cs"],
        "reset": lora_cfg["reset"],
        "sck": lora_cfg["sck"],
        "miso": lora_cfg["miso"],
        "mosi": lora_cfg["mosi"],
    }

    lora = SX127x(spi, pins=pins, parameters=cfg.LORA_SX127X_PARAMETERS)
    if hasattr(lora, "println"):
        lora.println(lora_cfg.get("test_message", "DIAG_TEST"))

    return PASS, {
        "driver": "sx127x.SX127x",
        "pins": pins,
        "radio": "initialized",
        "test_tx": "attempted" if hasattr(lora, "println") else "not_available",
    }


def test_lora():
    if not cfg.LORA.get("enabled", True):
        return SKIP, {"reason": "disabled in board_config.py"}

    errors = []
    for driver_name in cfg.LORA.get("driver_preference", ["SX1276", "sx127x"]):
        try:
            if driver_name == "SX1276":
                return try_lora_sx1276_driver()
            if driver_name == "sx127x":
                return try_lora_sx127x_driver()
            errors.append("unknown driver preference: {}".format(driver_name))
        except Exception as exc:
            errors.append("{}: {}".format(driver_name, repr(exc)))

    return FAIL, {"errors": errors}


def test_rtc():
    if machine is None or not hasattr(machine, "RTC"):
        return SKIP, {"reason": "RTC not available"}
    rtc = machine.RTC()
    return PASS, {"datetime": rtc.datetime()}


def wifi_configured():
    ssid = cfg.WIFI.get("ssid", "")
    password = cfg.WIFI.get("password", "")
    return bool(ssid and ssid != "CHANGE_ME" and password and password != "CHANGE_ME")


def test_wifi_connection():
    global _wifi_wlan

    if not cfg.WIFI.get("enabled", False):
        return SKIP, {"reason": "Wi-Fi disabled in board_config.py; main.py does not use Wi-Fi"}

    if not wifi_configured():
        return FAIL, {
            "error": "Wi-Fi enabled but ssid/password are not configured in board_config.py",
            "hint": "set cfg.WIFI['ssid'] and cfg.WIFI['password']",
        }

    network = import_module("network")
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)

    detail = {
        "active": wlan.active(),
        "ssid": cfg.WIFI.get("ssid"),
        "mac": hex_bytes(wlan.config("mac")) if hasattr(wlan, "config") else None,
        "scan_count": None,
    }

    if cfg.WIFI.get("scan", False):
        try:
            networks = wlan.scan()
            detail["scan_count"] = len(networks)
        except Exception as exc:
            detail["scan_error"] = str(exc)

    if not wlan.isconnected():
        wlan.connect(cfg.WIFI.get("ssid"), cfg.WIFI.get("password"))
        timeout_ms = int(cfg.WIFI.get("connect_timeout_s", 15) * 1000)
        start = ticks_ms()
        while not wlan.isconnected() and ticks_diff(ticks_ms(), start) < timeout_ms:
            sleep_ms(250)

    if not wlan.isconnected():
        _wifi_wlan = wlan
        detail["error"] = "connection timeout"
        try:
            detail["status"] = wlan.status()
        except Exception:
            pass
        return FAIL, detail

    _wifi_wlan = wlan
    ifconfig = wlan.ifconfig()
    detail.update({
        "connected": True,
        "ip": ifconfig[0],
        "netmask": ifconfig[1],
        "gateway": ifconfig[2],
        "dns": ifconfig[3],
    })
    try:
        detail["rssi_dbm"] = wlan.status("rssi")
    except Exception:
        pass

    return PASS, detail


def http_post_json(host, port, path, payload, timeout_s=5, extra_headers=None):
    body = json.dumps(payload)
    body_bytes = body.encode()
    addr = socket.getaddrinfo(host, port)[0][-1]
    sock = socket.socket()
    sock.settimeout(timeout_s)
    try:
        sock.connect(addr)

        headers = [
            "POST {} HTTP/1.1".format(path),
            "Host: {}:{}".format(host, port),
            "Content-Type: application/json",
            "Content-Length: {}".format(len(body_bytes)),
            "Connection: close",
        ]

        for key, value in (extra_headers or {}).items():
            headers.append("{}: {}".format(key, value))

        request = "\r\n".join(headers) + "\r\n\r\n"
        sock.send(request.encode())
        sock.send(body_bytes)

        response = sock.recv(512)
        try:
            response_text = response.decode()
        except Exception:
            response_text = str(response)

        first_line = response_text.split("\r\n", 1)[0]
        status_code = None
        parts = first_line.split()
        if len(parts) >= 2:
            try:
                status_code = int(parts[1])
            except Exception:
                pass

        return status_code, first_line, response_text[:512]
    finally:
        try:
            sock.close()
        except Exception:
            pass


def upload_report_to_server():
    if not getattr(cfg, "DIAGNOSTIC_SERVER", {}).get("enabled", False):
        return SKIP, {"reason": "diagnostic server upload disabled in board_config.py"}

    if not cfg.WIFI.get("enabled", False):
        return FAIL, {"error": "server upload enabled but Wi-Fi is disabled"}

    if _wifi_wlan is None or not _wifi_wlan.isconnected():
        return FAIL, {"error": "Wi-Fi is not connected; cannot upload diagnostic report"}

    server = cfg.DIAGNOSTIC_SERVER
    payload = dict(diag)
    payload["upload_note"] = "server_upload result is recorded after this POST attempt"

    status_code, status_line, response_preview = http_post_json(
        server.get("host"),
        server.get("port", 80),
        server.get("post_path", "/api/diagnostic"),
        payload,
        timeout_s=server.get("socket_timeout_s", 5),
        extra_headers=server.get("extra_headers", {}),
    )

    ok = status_code is not None and 200 <= status_code < 300
    detail = {
        "host": server.get("host"),
        "port": server.get("port", 80),
        "post_path": server.get("post_path", "/api/diagnostic"),
        "http_status_code": status_code,
        "http_status_line": status_line,
        "response_preview": response_preview,
    }

    if cfg.WIFI.get("disconnect_after_send", False):
        try:
            _wifi_wlan.disconnect()
            detail["wifi_disconnected_after_send"] = True
        except Exception as exc:
            detail["wifi_disconnect_error"] = str(exc)

    return (PASS if ok else FAIL), detail


def summarize_overall():
    statuses = [item["status"] for item in diag["results"].values()]
    failed = statuses.count(FAIL)
    warnings = statuses.count(WARN)
    skipped = statuses.count(SKIP)
    passed = statuses.count(PASS)

    if failed:
        overall = FAIL
    elif warnings:
        overall = WARN
    else:
        overall = PASS

    diag["overall"] = overall
    diag["summary"] = {
        "passed": passed,
        "warnings": warnings,
        "failed": failed,
        "skipped": skipped,
        "final_memory": memory_snapshot(collect=True),
    }
    return overall


def save_report_to_sd():
    if not cfg.SAVE_JSON_REPORT_TO_SD:
        print("JSON report saving disabled")
        return

    sd_cfg = cfg.SDCARD
    mount_point = sd_cfg.get("mount_point", "/sd")
    try:
        if not sd_is_mounted(mount_point):
            sd = make_sdcard()
            mount_sd(sd, mount_point)

        with open(cfg.JSON_REPORT_PATH, "w") as file:
            json.dump(diag, file)
            try:
                file.flush()
            except Exception:
                pass
        print("Saved diagnostic report to {}".format(cfg.JSON_REPORT_PATH))
    except Exception as exc:
        print("Could not save diagnostic report to SD: {}".format(exc))


def print_summary():
    print("\nDiagnostic summary")
    print("------------------")
    for name, item in diag["results"].items():
        print("{}: {}".format(name, item["status"]))
    print("Overall: {}".format(diag["overall"]))
    print("Memory: {}".format(diag["summary"].get("final_memory")))


def run():
    print("Starting enhanced diagnostic mode for {}".format(cfg.BOARD_ID))

    run_case("system_memory", test_system)
    run_case("rtc", test_rtc)
    run_case("gpio_software", test_gpio_software)
    run_case("leds_visual", test_leds_visual)
    run_case("i2c_bus", test_i2c_bus)
    run_case("bme280_reading", test_bme280)
    run_case("ds18b20_reading", test_ds18b20)
    run_case("sdi12_soil_reading", test_sdi12)
    run_case("sd_card", test_sd_card)
    run_case("lora_radio", test_lora)
    run_case("wifi_connection", test_wifi_connection)

    summarize_overall()
    run_case("server_upload", upload_report_to_server)

    summarize_overall()
    save_report_to_sd()
    print_summary()

    if cfg.RUN_FOREVER_AFTER_DIAG:
        print("Diagnostic complete. Holding board awake.")
        while True:
            sleep_ms(1000)

    return diag


if __name__ == "__main__":
    run()
