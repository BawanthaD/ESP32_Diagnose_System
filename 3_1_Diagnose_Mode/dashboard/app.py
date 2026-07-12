from flask import Flask, render_template, request, jsonify
from datetime import datetime, timezone
from copy import deepcopy
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
    # {"name": "leds_visual", "label": "LED Visual", "critical": False},
    {"name": "i2c_bus", "label": "I2C Bus", "critical": True},
    {"name": "bme280_reading", "label": "BME280 Reading", "critical": True},
    {"name": "ds18b20_reading", "label": "DS18B20 Reading", "critical": False},
    {"name": "sdi12_soil_reading", "label": "SDI-12 Soil Reading", "critical": False},
    {"name": "sd_card", "label": "SD Card", "critical": False},
    {"name": "lora_radio", "label": "LoRa Radio", "critical": True},
    {"name": "wifi_connection", "label": "WiFi Connection", "critical": False},
]

SKIPPABLE_TEST_NAMES = {item["name"] for item in TEST_CATALOG}
IGNORED_TEST_RESULTS = {"required_main_modules"}
METADATA_RESULTS = {"server_upload"}

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
            data = json.load(file)
            return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def save_json(path, data):
    ensure_data_dir()
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, sort_keys=True)
    os.replace(tmp, path)


def now_iso():
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")


def now_sort_iso():
    return datetime.now(timezone.utc).isoformat()


def clean_status(status):
    if status is None:
        return "UNKNOWN"
    status = str(status).strip().upper()
    if status == "WARNING":
        return "WARN"
    return status or "UNKNOWN"


def valid_skip_tests(names):
    return sorted({str(name) for name in (names or []) if str(name) in SKIPPABLE_TEST_NAMES})


def board_key(report):
    """Stable key used to store one latest result per physical board."""
    return (
        str(report.get("esp32_unique_id") or "").strip()
        or str(report.get("device_id") or "").strip()
        or str(report.get("board_id") or "").strip()
        or "UNKNOWN_BOARD"
    )


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


def extract_raw_results(report):
    """
    Keep the board's original test result separate from dashboard skip overrides.

    Older saved files may only have overridden SKIP_PASS values. When possible, restore
    the original status/detail from the stored previous_status/previous_detail fields.
    """
    if isinstance(report.get("raw_results"), dict):
        return deepcopy(report["raw_results"])

    raw_results = deepcopy(report.get("results", {}))
    for test_name, result in list(raw_results.items()):
        if not isinstance(result, dict):
            raw_results[test_name] = {"status": clean_status(result), "detail": {}}
            continue

        status = clean_status(result.get("status"))
        detail = result.get("detail", {}) if isinstance(result.get("detail"), dict) else {}
        if status == "SKIP_PASS" and detail.get("skipped_by_dashboard"):
            raw_results[test_name] = {
                "status": clean_status(detail.get("previous_status")),
                "detail": detail.get("previous_detail", {}) if isinstance(detail.get("previous_detail"), dict) else {},
            }
        else:
            raw_results[test_name] = {
                "status": status,
                "detail": detail,
            }

    return raw_results


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
    raw_results = extract_raw_results(report)
    effective_results = deepcopy(raw_results)

    for test_name in sorted(skip_tests):
        previous = raw_results.get(test_name, {})
        previous_status = clean_status(previous.get("status")) if isinstance(previous, dict) else clean_status(previous)
        previous_detail = previous.get("detail", {}) if isinstance(previous, dict) else {}
        effective_results[test_name] = {
            "status": "SKIP_PASS",
            "detail": {
                "skipped_by_dashboard": True,
                "reason": "Test skipped from dashboard and counted as pass",
                "previous_status": previous_status,
                "previous_detail": previous_detail,
            },
        }

    report["raw_results"] = raw_results
    report["results"] = effective_results
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


def recompute_board(report):
    report = apply_dashboard_skips(report)
    report = summarise(report)
    return report


def recompute_saved_boards(device_key=None):
    changed = False
    keys = list(boards.keys()) if device_key in (None, "global") else [device_key]
    for key in keys:
        if key in boards and isinstance(boards[key], dict):
            boards[key] = recompute_board(boards[key])
            changed = True
    if changed:
        save_boards()


def load_state():
    global boards, test_configs
    boards = load_json(BOARDS_FILE, {})
    test_configs = load_json(CONFIGS_FILE, {})

    if "global" not in test_configs:
        test_configs["global"] = {"skip_tests": [], "updated_at": None, "note": ""}

    for config in test_configs.values():
        if isinstance(config, dict):
            config["skip_tests"] = valid_skip_tests(config.get("skip_tests", []))

    # Migrate older stored board data into the new raw_results + display results structure.
    for key, report in list(boards.items()):
        if isinstance(report, dict):
            report.setdefault("device_key", key)
            boards[key] = recompute_board(report)


def save_boards():
    save_json(BOARDS_FILE, boards)


def save_configs():
    save_json(CONFIGS_FILE, test_configs)


@app.route("/")
def dashboard():
    return render_template("dashboard.html")


@app.route("/api/boards", methods=["GET"])
def get_boards():
    ordered = sorted(
        boards.values(),
        key=lambda item: item.get("last_seen_sort", ""),
        reverse=True,
    )
    return jsonify(ordered)


@app.route("/api/boards", methods=["DELETE"])
def reset_all_boards():
    boards.clear()
    save_boards()
    return jsonify({"status": "ok", "message": "All stored board results were reset", "cleared": "all"})


@app.route("/api/boards/reset", methods=["POST"])
def reset_all_boards_post():
    return reset_all_boards()


@app.route("/api/board/<path:device_key>", methods=["DELETE"])
def reset_board(device_key):
    existed = device_key in boards
    boards.pop(device_key, None)
    save_boards()
    return jsonify({
        "status": "ok",
        "message": "Stored board result was reset" if existed else "No stored result found for this board",
        "device_key": device_key,
        "cleared": existed,
    })


@app.route("/api/board/<path:device_key>/reset", methods=["POST"])
def reset_board_post(device_key):
    return reset_board(device_key)


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
    if not isinstance(payload, dict):
        return jsonify({"status": "error", "message": "JSON object expected"}), 400

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
    recompute_saved_boards(device_key)

    return jsonify(get_config(device_key))


@app.route("/api/diagnostic", methods=["POST"])
def diagnostic():
    data = request.get_json(silent=True) or {}
    if not isinstance(data, dict):
        return jsonify({"status": "error", "message": "JSON object expected"}), 400

    data = normalise_results(data)
    data = move_non_test_results(data)
    data["device_key"] = board_key(data)

    previous = boards.get(data["device_key"], {})
    was_overwritten = bool(previous)
    seen_at = now_iso()
    data["first_seen"] = previous.get("first_seen") or seen_at
    data["last_seen"] = seen_at
    data["last_seen_sort"] = now_sort_iso()
    data["run_count"] = int(previous.get("run_count", 0) or 0) + 1

    # Store original submitted results separately so dashboard skips can be toggled
    # later without destroying the real test outcome.
    data["raw_results"] = extract_raw_results(data)
    data = recompute_board(data)

    # This intentionally overwrites the previous result for the same physical board.
    # The dashboard is a latest-result view, not a historical log.
    boards[data["device_key"]] = data
    save_boards()

    return jsonify({
        "status": "ok",
        "device_key": data["device_key"],
        "overall": data["overall"],
        "overwritten_previous_result": was_overwritten,
        "run_count": data["run_count"],
    })


load_state()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
