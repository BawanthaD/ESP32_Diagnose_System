let testCatalog = [];
let allConfigs = {};
let latestBoards = [];
let isLoading = false;
let dirtyForms = new Set();
let currentSearch = "";
let currentStatusFilter = "all";

const AUTO_REFRESH_MS = 3000;

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#039;");
}

function statusClass(status) {
    const s = String(status || "UNKNOWN").toUpperCase();
    if (s === "PASS") return "pass";
    if (s === "FAIL" || s === "ERROR") return "fail";
    if (s === "WARN" || s === "WARNING") return "warn";
    if (s === "SKIP_PASS") return "skip-pass";
    if (s === "SKIP") return "skip";
    return "unknown";
}

function statusLabel(status) {
    const s = String(status || "UNKNOWN").toUpperCase();
    if (s === "SKIP_PASS") return "SKIPPED → PASS";
    return s;
}

function statusHtml(status) {
    const cls = statusClass(status);
    return `<span class="status ${cls}">${escapeHtml(statusLabel(status))}</span>`;
}

function getResult(board, name, source = "results") {
    const results = board[source] || {};
    const result = results[name];
    if (!result) return { status: "UNKNOWN", detail: {} };
    if (typeof result === "object") return { status: result.status || "UNKNOWN", detail: result.detail || {} };
    return { status: result, detail: {} };
}

function getNested(obj, path, fallback = null) {
    let current = obj;
    for (const part of path) {
        if (!current || typeof current !== "object" || !(part in current)) return fallback;
        current = current[part];
    }
    return current;
}

function prettyBytes(bytes) {
    if (bytes === null || bytes === undefined || Number.isNaN(Number(bytes))) return "—";
    const n = Number(bytes);
    if (n < 1024) return `${n} B`;
    if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
    return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

function readingCard(label, value) {
    return `
        <div class="reading">
            <div class="label">${escapeHtml(label)}</div>
            <div class="value">${escapeHtml(value ?? "—")}</div>
        </div>
    `;
}

function readingsHtml(board) {
    const system = getResult(board, "system_memory").detail;
    const bme = getResult(board, "bme280_reading").detail;
    const ds = getResult(board, "ds18b20_reading").detail;
    const sdi = getResult(board, "sdi12_soil_reading").detail;
    const wifi = getResult(board, "wifi_connection").detail;

    const mem = getNested(board, ["summary", "final_memory"], getNested(system, ["memory"], {}));
    const bmeParsed = getNested(bme, ["parsed"], {});
    const dsReadings = Array.isArray(ds.readings) ? ds.readings : [];
    const sdiParsed = getNested(sdi, ["parsed"], {});

    return `
        <div class="reading-grid">
            ${readingCard("Free memory", prettyBytes(mem.free_bytes))}
            ${readingCard("Memory used", mem.used_percent !== undefined && mem.used_percent !== null ? `${mem.used_percent}%` : "—")}
            ${readingCard("BME temp", bmeParsed.temperature_c !== undefined ? `${bmeParsed.temperature_c} °C` : "—")}
            ${readingCard("BME humidity", bmeParsed.humidity_percent !== undefined ? `${bmeParsed.humidity_percent}%` : "—")}
            ${readingCard("BME pressure", bmeParsed.pressure_hpa !== undefined ? `${bmeParsed.pressure_hpa} hPa` : "—")}
            ${readingCard("DS18B20", dsReadings.length ? dsReadings.map(r => `${r.temperature_c} °C`).join(", ") : "—")}
            ${readingCard("Soil permittivity", sdiParsed.soil_permittivity ?? "—")}
            ${readingCard("Soil temp", sdiParsed.soil_temperature_c !== undefined ? `${sdiParsed.soil_temperature_c} °C` : "—")}
            ${readingCard("WiFi IP", wifi.ip || wifi.ip_address || "—")}
        </div>
    `;
}

function allTestNames(board) {
    const catalogNames = testCatalog.map(t => t.name);
    const resultNames = Object.keys(board.results || {});
    const rawNames = Object.keys(board.raw_results || {});
    return Array.from(new Set([...catalogNames, ...resultNames, ...rawNames]));
}

function testCatalogItem(testName) {
    return testCatalog.find(test => test.name === testName);
}

function testLabel(testName) {
    const item = testCatalogItem(testName);
    return item ? item.label : testName;
}

function originalResultNote(board, testName) {
    const result = getResult(board, testName);
    const raw = getResult(board, testName, "raw_results");
    if (String(result.status).toUpperCase() !== "SKIP_PASS") return "";
    return `<div class="small">Original: ${statusHtml(raw.status)}</div>`;
}

function testRowsHtml(board) {
    return allTestNames(board).map(testName => {
        const result = getResult(board, testName);
        const item = testCatalogItem(testName);
        const criticalBadge = item?.critical ? `<span class="mini-badge">critical</span>` : "";
        return `
            <tr>
                <td>
                    <div class="test-name">${escapeHtml(testLabel(testName))} ${criticalBadge}</div>
                    <span class="small">${escapeHtml(testName)}</span>
                </td>
                <td>
                    ${statusHtml(result.status)}
                    ${originalResultNote(board, testName)}
                </td>
                <td>
                    <details>
                        <summary>details</summary>
                        <pre>${escapeHtml(JSON.stringify(result.detail || {}, null, 2))}</pre>
                    </details>
                </td>
            </tr>
        `;
    }).join("");
}

function checkboxListHtml(checkedTests) {
    const checkedSet = new Set(checkedTests || []);
    return testCatalog.map(test => {
        return `
            <label class="check-item">
                <input type="checkbox" value="${escapeHtml(test.name)}" ${checkedSet.has(test.name) ? "checked" : ""}>
                <span>
                    ${escapeHtml(test.label)}
                    ${test.critical ? `<small>critical</small>` : ""}
                </span>
            </label>
        `;
    }).join("");
}

function effectiveBoardConfig(board) {
    return board.dashboard_config || { board_skip_tests: [], global_skip_tests: [], skip_tests: [] };
}

function boardSearchText(board) {
    return [
        board.device_key,
        board.board_id,
        board.esp32_unique_id,
        board.device_id,
        getNested(getResult(board, "system_memory").detail, ["unique_id"], ""),
    ].filter(Boolean).join(" ").toLowerCase();
}

function filteredBoards() {
    return latestBoards.filter(board => {
        const matchesSearch = !currentSearch || boardSearchText(board).includes(currentSearch.toLowerCase());
        const matchesStatus = currentStatusFilter === "all" || String(board.overall || "UNKNOWN").toUpperCase() === currentStatusFilter;
        return matchesSearch && matchesStatus;
    });
}

function boardCardHtml(board) {
    const deviceKey = board.device_key || board.esp32_unique_id || board.board_id || "UNKNOWN_BOARD";
    const cfg = effectiveBoardConfig(board);
    const summary = board.summary || {};
    const boardId = board.board_id || deviceKey || "UNKNOWN_BOARD";
    const uniqueId = board.esp32_unique_id || getNested(getResult(board, "system_memory").detail, ["unique_id"], "—");
    const globalSkipped = cfg.global_skip_tests?.length ? cfg.global_skip_tests.map(testLabel).join(", ") : "None";
    const runCount = Number(board.run_count || 1);

    return `
        <article class="card board-card" data-device-key="${escapeHtml(deviceKey)}">
            <div class="board-header">
                <div>
                    <div class="board-title">
                        <h2>${escapeHtml(boardId)}</h2>
                        ${statusHtml(board.overall)}
                    </div>
                    <div class="board-meta">
                        <span><strong>Device key:</strong> ${escapeHtml(deviceKey)}</span>
                        <span><strong>ESP32 ID:</strong> ${escapeHtml(uniqueId)}</span>
                        <span><strong>Last seen:</strong> ${escapeHtml(board.last_seen || "—")}</span>
                        <span><strong>Runs seen:</strong> ${escapeHtml(runCount)}</span>
                    </div>
                </div>
                <div class="summary-pill">
                    ${escapeHtml(summary.passed ?? 0)} pass ·
                    ${escapeHtml(summary.warnings ?? 0)} warn ·
                    ${escapeHtml(summary.failed ?? 0)} fail ·
                    ${escapeHtml(summary.skipped_pass ?? 0)} skipped
                </div>
            </div>

            <div class="board-grid">
                <section class="panel">
                    <h3>Key readings</h3>
                    ${readingsHtml(board)}
                </section>

                <section class="panel">
                    <div class="panel-heading-row">
                        <h3>Skip tests for this board</h3>
                        <span class="small">Global skips: ${escapeHtml(globalSkipped)}</span>
                    </div>
                    <div class="checkbox-grid board-skip-list">
                        ${checkboxListHtml(cfg.board_skip_tests || [])}
                    </div>
                    <div class="override-actions">
                        <button class="save-board-btn" type="button">Save board skips</button>
                        <button class="secondary clear-board-btn" type="button">Clear board skips</button>
                        <button class="danger reset-board-btn" type="button">Reset result</button>
                    </div>
                    <p class="small action-help">Reset result removes only this board's stored latest pass/fail data. It does not remove skip settings.</p>
                </section>
            </div>

            <section class="panel results-panel">
                <h3>Test results</h3>
                <div class="table-wrap">
                    <table>
                        <thead>
                            <tr><th>Test</th><th>Status</th><th>Detail</th></tr>
                        </thead>
                        <tbody>${testRowsHtml(board)}</tbody>
                    </table>
                </div>
            </section>
        </article>
    `;
}

function renderStats(boards) {
    document.getElementById("total").innerText = boards.length;
    document.getElementById("passed").innerText = boards.filter(b => b.overall === "PASS").length;
    document.getElementById("warnings").innerText = boards.filter(b => b.overall === "WARN").length;
    document.getElementById("failed").innerText = boards.filter(b => b.overall === "FAIL").length;
    document.getElementById("skipped-pass").innerText = boards.reduce((total, b) => total + Number(getNested(b, ["summary", "skipped_pass"], 0)), 0);
}

function renderGlobalConfig() {
    const globalConfig = allConfigs.global || { skip_tests: [] };
    document.getElementById("global-skip-list").innerHTML = checkboxListHtml(globalConfig.skip_tests || []);
}

function renderBoards(boards) {
    const container = document.getElementById("boards-container");
    if (!latestBoards.length) {
        container.innerHTML = `<div class="empty">Waiting for boards…</div>`;
        return;
    }

    if (!boards.length) {
        container.innerHTML = `<div class="empty">No boards match the current filter.</div>`;
        return;
    }

    container.innerHTML = boards.map(boardCardHtml).join("");
}

function renderDashboard() {
    renderStats(latestBoards);
    renderGlobalConfig();
    renderBoards(filteredBoards());
    dirtyForms.clear();
    updateAutoRefreshNote();
}

function collectChecked(container) {
    return Array.from(container.querySelectorAll("input[type='checkbox']:checked")).map(input => input.value);
}

function setConnectionState(kind, text) {
    const el = document.getElementById("connection-state");
    el.innerHTML = `<span class="dot ${escapeHtml(kind)}"></span>${escapeHtml(text)}`;
}

function setLastRefresh() {
    document.getElementById("last-refresh").innerText = `Last refresh: ${new Date().toLocaleTimeString()}`;
}

function updateAutoRefreshNote() {
    const note = document.getElementById("auto-refresh-note");
    note.innerText = dirtyForms.size ? "Auto-refresh paused while editing" : "Auto-refresh every 3 s";
}

function showToast(message, kind = "ok") {
    const toast = document.getElementById("toast");
    toast.innerText = message;
    toast.className = `toast show ${kind}`;
    window.clearTimeout(showToast.timeoutId);
    showToast.timeoutId = window.setTimeout(() => {
        toast.className = "toast";
    }, 2800);
}

async function fetchJson(url, options = {}) {
    const response = await fetch(url, options);
    let payload = null;
    try {
        payload = await response.json();
    } catch {
        payload = null;
    }

    if (!response.ok) {
        const message = payload?.message || `${options.method || "GET"} ${url} failed with ${response.status}`;
        throw new Error(message);
    }

    return payload;
}

async function saveConfig(deviceKey, skipTests) {
    return await fetchJson(`/api/test-config/${encodeURIComponent(deviceKey)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skip_tests: skipTests })
    });
}

async function resetBoard(deviceKey) {
    return await fetchJson(`/api/board/${encodeURIComponent(deviceKey)}`, { method: "DELETE" });
}

async function resetAllBoards() {
    return await fetchJson("/api/boards", { method: "DELETE" });
}

function setBusy(button, busyText) {
    button.dataset.originalText = button.innerText;
    button.innerText = busyText;
    button.disabled = true;
}

function clearBusy(button) {
    button.innerText = button.dataset.originalText || button.innerText;
    button.disabled = false;
}

async function loadDashboard(options = {}) {
    const force = options.force === true;
    if (isLoading) return;
    if (!force && dirtyForms.size) {
        updateAutoRefreshNote();
        return;
    }

    isLoading = true;
    setConnectionState("unknown", "Refreshing…");

    try {
        const [catalog, configs, boards] = await Promise.all([
            fetchJson("/api/test-catalog"),
            fetchJson("/api/test-configs"),
            fetchJson("/api/boards")
        ]);

        testCatalog = catalog;
        allConfigs = configs;
        latestBoards = boards;

        renderDashboard();
        setConnectionState("pass", "Connected");
        setLastRefresh();
    } catch (err) {
        console.error(err);
        setConnectionState("fail", "Connection error");
        showToast(err.message || "Dashboard refresh failed", "error");
    } finally {
        isLoading = false;
    }
}

function markDirty(sectionKey) {
    dirtyForms.add(sectionKey || "config");
    updateAutoRefreshNote();
}

function clearDirty(sectionKey) {
    if (sectionKey) {
        dirtyForms.delete(sectionKey);
    } else {
        dirtyForms.clear();
    }
    updateAutoRefreshNote();
}

document.addEventListener("change", event => {
    if (event.target.matches("#global-skip-list input[type='checkbox'], .board-skip-list input[type='checkbox']")) {
        const card = event.target.closest(".board-card");
        markDirty(card ? `board:${card.dataset.deviceKey}` : "global");
    }
});

document.getElementById("refresh-btn").addEventListener("click", () => {
    if (dirtyForms.size && !window.confirm("You have unsaved skip changes. Refresh and discard them?")) return;
    clearDirty();
    loadDashboard({ force: true });
});

document.getElementById("save-global-btn").addEventListener("click", async event => {
    const button = event.currentTarget;
    const list = document.getElementById("global-skip-list");
    setBusy(button, "Saving…");
    try {
        await saveConfig("global", collectChecked(list));
        clearDirty("global");
        showToast("Global skip settings saved");
        if (!dirtyForms.size) await loadDashboard({ force: true });
    } catch (err) {
        console.error(err);
        showToast(err.message || "Could not save global skips", "error");
    } finally {
        clearBusy(button);
    }
});

document.getElementById("reset-all-btn").addEventListener("click", async event => {
    if (!window.confirm("Reset stored pass/fail data for ALL boards? Skip settings will be kept.")) return;
    const button = event.currentTarget;
    setBusy(button, "Resetting…");
    try {
        await resetAllBoards();
        clearDirty();
        showToast("All stored board results were reset");
        await loadDashboard({ force: true });
    } catch (err) {
        console.error(err);
        showToast(err.message || "Could not reset board results", "error");
    } finally {
        clearBusy(button);
    }
});

document.getElementById("board-search").addEventListener("input", event => {
    currentSearch = event.target.value.trim();
    renderBoards(filteredBoards());
});

document.getElementById("status-filter").addEventListener("change", event => {
    currentStatusFilter = event.target.value;
    renderBoards(filteredBoards());
});

document.getElementById("boards-container").addEventListener("click", async event => {
    const card = event.target.closest(".board-card");
    if (!card) return;

    const deviceKey = card.dataset.deviceKey;
    const list = card.querySelector(".board-skip-list");

    if (event.target.matches(".save-board-btn")) {
        const button = event.target;
        setBusy(button, "Saving…");
        try {
            await saveConfig(deviceKey, collectChecked(list));
            clearDirty(`board:${deviceKey}`);
            showToast("Board skip settings saved");
            if (!dirtyForms.size) await loadDashboard({ force: true });
        } catch (err) {
            console.error(err);
            showToast(err.message || "Could not save board skips", "error");
        } finally {
            clearBusy(button);
        }
    }

    if (event.target.matches(".clear-board-btn")) {
        const button = event.target;
        list.querySelectorAll("input[type='checkbox']").forEach(input => { input.checked = false; });
        setBusy(button, "Clearing…");
        try {
            await saveConfig(deviceKey, []);
            clearDirty(`board:${deviceKey}`);
            showToast("Board skip settings cleared");
            if (!dirtyForms.size) await loadDashboard({ force: true });
        } catch (err) {
            console.error(err);
            showToast(err.message || "Could not clear board skips", "error");
        } finally {
            clearBusy(button);
        }
    }

    if (event.target.matches(".reset-board-btn")) {
        if (!window.confirm(`Reset stored result for board ${deviceKey}? Skip settings will be kept.`)) return;
        const button = event.target;
        setBusy(button, "Resetting…");
        try {
            await resetBoard(deviceKey);
            clearDirty(`board:${deviceKey}`);
            showToast("Board result reset");
            if (!dirtyForms.size) await loadDashboard({ force: true });
        } catch (err) {
            console.error(err);
            showToast(err.message || "Could not reset board result", "error");
        } finally {
            clearBusy(button);
        }
    }
});

setInterval(() => loadDashboard(), AUTO_REFRESH_MS);
loadDashboard({ force: true });
