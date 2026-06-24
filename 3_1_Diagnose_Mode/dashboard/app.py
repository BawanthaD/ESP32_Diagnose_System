from flask import Flask, render_template, request, jsonify
from datetime import datetime, timezone
import json
import os

app = Flask(__name__)

DATA_DIR = os.environ.get("DIAG_DATA_DIR", "data")
BOARDS_FILE = os.path.join(DATA_DIR, "boards.json")
CONFIGS_FILE = os.path.join(DATA_DIR, "test_configs.json")

PASS_LIKE = {"PASS", "SKIP", "SKIP_PASS"}
FAIL_LIKE = {"FAIL", "ERROR"}
WARN_LIKE = {"WARN", "WARNING"}

TEST_CATALOG = [
    {"name": "system_memory", "label": "System / Memory", "critical": True},
    {"name": "rtc", "label": "RTC", "critical": False},
    {"name": "gpio_software", "label": "GPIO Software", "critical": True},
    {"name": "leds_visual", "label": "LED Visual", "critical": False},
    {"name": "i2c_bus", "label": "I2C Bus", "critical": True},
    {"name": "bme280_reading", "label": "BME280 Reading", "critical": True},
    {"name": "ds18b20_reading", "label": "DS18B20 Reading", "critical": False},
    {"name": "sdi12_soil_reading", "label": "SDI-12 Soil Reading", "critical": False},
    {"name": "sd_card", "label": "SD Card", "critical": False},
    {"name": "lora_radio", "label": "LoRa Radio", "critical": True},
    {"name": "wifi_connection", "label": "WiFi Connection", "critical": False},
    {"name": "server_upload", "label": "Server Upload", "critical": False},
]

SKIPPABLE_TEST_NAMES = {item["name"] for item in TEST_CATALOG}
IGNORED_TEST_RESULTS = {"required_main_modules"}
METADATA_RESULTS = {"server_upload"}


def valid_skip_tests(names):
    return sorted({str(name) for name in (names or []) if str(name) in SKIPPABLE_TEST_NAMES})


def move_non_test_results(report):
    results = report.setdefault("results", {})
    non_test_results = report.setdefault("non_test_results", {})

    for name in sorted(METADATA_RESULTS):
        if name in results:
            non_test_results[name] = results.pop(name)

    ignored_results = report.setdefault("ignored_results", {})
    for name in sorted(IGNORED_TEST_RESULTS):
        if name in results:
            ignored_results[name] = results.pop(name)

    if not non_test_results:
        report.pop("non_test_results", None)
    if not ignored_results:
        report.pop("ignored_results", None)

    return report

LEGACY_TEST_MAP = {
    "system": "system_memory",
    "led_gpio": "gpio_software",
    "bme280": "bme280_reading",
    "lora": "lora_radio",
    "wifi": "wifi_connection",
}

boards = {}
test_configs = {}


def ensure_data_dir():
    os.makedirs(DATA_DIR, exist_ok=True)


def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as file:
            return json.load(file)
    except Exception:
        return default


def save_json(path, data):
    ensure_data_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
    os.replace(tmp, path)


def load_state():
    global boards, test_configs
    boards = load_json(BOARDS_FILE, {})
    test_configs = load_json(CONFIGS_FILE, {})
    if "global" not in test_configs:
        test_configs["global"] = {"skip_tests": [], "updated_at": None, "note": ""}
    for config in test_configs.values():
        config["skip_tests"] = valid_skip_tests(config.get("skip_tests", []))

def save_boards():
    save_json(BOARDS_FILE, boards)


def save_configs():
    save_json(CONFIGS_FILE, test_configs)


def now_iso():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def clean_status(status):
    if status is None:
        return "UNKNOWN"
    status = str(status).upper()
    if status == "WARNING":
        return "WARN"
    return status


def board_key(report):
    return (
        str(report.get("esp32_unique_id") or "").strip()
        or str(report.get("device_id") or "").strip()
        or str(report.get("board_id") or "").strip()
        or "UNKNOWN_BOARD"
    )


def normalise_results(report):
    """Accept both the new results{} diagnostic format and the older flat format."""
    if isinstance(report.get("results"), dict):
        for test_name, item in list(report["results"].items()):
            if isinstance(item, dict):
                item["status"] = clean_status(item.get("status"))
                item.setdefault("detail", {})
            else:
                report["results"][test_name] = {"status": clean_status(item), "detail": {}}
        return report

    results = {}
    for old_name, new_name in LEGACY_TEST_MAP.items():
        if old_name in report:
            results[new_name] = {
                "status": clean_status(report.get(old_name)),
                "detail": report.get("details", {}).get(old_name, {}),
            }

    if "sd_card" in report:
        results["sd_card"] = {
            "status": clean_status(report.get("sd_card")),
            "detail": report.get("details", {}).get("sd_card", {}),
        }

    report["results"] = results
    return report


def get_config(device_key):
    global_config = test_configs.get("global", {})
    board_config = test_configs.get(device_key, {})

    global_skip_tests = valid_skip_tests(global_config.get("skip_tests", []))
    board_skip_tests = valid_skip_tests(board_config.get("skip_tests", []))
    skip_tests = set(global_skip_tests)
    skip_tests.update(board_skip_tests)

    return {
        "device_key": device_key,
        "global_skip_tests": global_skip_tests,
        "board_skip_tests": board_skip_tests,
        "skip_tests": sorted(skip_tests),
        "updated_at": board_config.get("updated_at") or global_config.get("updated_at"),
        "note": board_config.get("note", ""),
    }


def apply_dashboard_skips(report):
    key = report["device_key"]
    effective_config = get_config(key)
    skip_tests = set(effective_config.get("skip_tests", []))
    results = report.setdefault("results", {})

    for test_name in sorted(skip_tests):
        previous = results.get(test_name, {})
        previous_status = clean_status(previous.get("status")) if isinstance(previous, dict) else clean_status(previous)
        previous_detail = previous.get("detail", {}) if isinstance(previous, dict) else {}
        results[test_name] = {
            "status": "SKIP_PASS",
            "detail": {
                "skipped_by_dashboard": True,
                "reason": "Test skipped from dashboard and counted as pass",
                "previous_status": previous_status,
                "previous_detail": previous_detail,
            },
        }

    report["dashboard_config"] = effective_config
    return report


def summarise(report):
    statuses = []
    for item in report.get("results", {}).values():
        if isinstance(item, dict):
            statuses.append(clean_status(item.get("status")))
        else:
            statuses.append(clean_status(item))

    passed = sum(1 for status in statuses if status == "PASS")
    skipped_pass = sum(1 for status in statuses if status == "SKIP_PASS")
    skipped = sum(1 for status in statuses if status == "SKIP")
    warnings = sum(1 for status in statuses if status in WARN_LIKE)
    failed = sum(1 for status in statuses if status in FAIL_LIKE)
    unknown = sum(1 for status in statuses if status not in PASS_LIKE and status not in WARN_LIKE and status not in FAIL_LIKE)

    if failed or unknown:
        overall = "FAIL"
    elif warnings:
        overall = "WARN"
    else:
        overall = "PASS"

    report["overall"] = overall
    report["summary"] = {
        **report.get("summary", {}),
        "passed": passed,
        "skipped_pass": skipped_pass,
        "skipped": skipped,
        "warnings": warnings,
        "failed": failed,
        "unknown": unknown,
        "test_count": len(statuses),
    }
    return report


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/boards")
def get_boards():
    ordered = sorted(
        boards.values(),
        key=lambda item: item.get("last_seen_sort", ""),
        reverse=True,
    )
    return jsonify(ordered)


@app.route("/api/test-catalog")
def get_test_catalog():
    return jsonify(TEST_CATALOG)


@app.route("/api/test-configs")
def get_test_configs():
    return jsonify(test_configs)


@app.route("/api/test-config/<path:device_key>", methods=["GET"])
def get_test_config(device_key):
    return jsonify(get_config(device_key))


@app.route("/api/test-config/<path:device_key>", methods=["POST"])
def update_test_config(device_key):
    payload = request.get_json(silent=True) or {}

    current = test_configs.get(device_key, {"skip_tests": [], "updated_at": None, "note": ""})

    if "skip_tests" in payload:
        skip_tests = payload.get("skip_tests") or []
        current["skip_tests"] = valid_skip_tests(skip_tests)

    # Convenience mode for toggling one test.
    if "test" in payload and "skip" in payload:
        skip_tests = set(current.get("skip_tests", []))
        test_name = str(payload["test"])
        if test_name in SKIPPABLE_TEST_NAMES:
            if payload.get("skip"):
                skip_tests.add(test_name)
            else:
                skip_tests.discard(test_name)
        current["skip_tests"] = valid_skip_tests(skip_tests)

    if "note" in payload:
        current["note"] = str(payload.get("note") or "")

    current["updated_at"] = now_iso()
    test_configs[device_key] = current
    save_configs()

    return jsonify(get_config(device_key))


@app.route("/api/diagnostic", methods=["POST"])
def diagnostic():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "JSON object expected"}), 400

    data = normalise_results(data)
    data = move_non_test_results(data)
    data["device_key"] = board_key(data)
    data["last_seen"] = now_iso()
    data["last_seen_sort"] = datetime.now(timezone.utc).isoformat()

    data = apply_dashboard_skips(data)
    data = summarise(data)

    boards[data["device_key"]] = data
    save_boards()

    return jsonify({"status": "ok", "device_key": data["device_key"], "overall": data["overall"]})


load_state()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
