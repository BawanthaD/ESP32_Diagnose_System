let testCatalog = [];
let allConfigs = {};
let latestBoards = [];

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

function getResult(board, name) {
    const results = board.results || {};
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
    return Array.from(new Set([...catalogNames, ...resultNames]));
}

function testLabel(testName) {
    const item = testCatalog.find(test => test.name === testName);
    return item ? item.label : testName;
}

function testRowsHtml(board) {
    return allTestNames(board).map(testName => {
        const result = getResult(board, testName);
        return `
            <tr>
                <td>${escapeHtml(testLabel(testName))}<br><span class="small">${escapeHtml(testName)}</span></td>
                <td>${statusHtml(result.status)}</td>
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

function checkboxListHtml(prefix, checkedTests) {
    const checkedSet = new Set(checkedTests || []);
    return testCatalog.map(test => {
        const id = `${prefix}-${test.name}`.replaceAll(/[^a-zA-Z0-9_-]/g, "_");
        return `
            <label class="check-item" for="${escapeHtml(id)}">
                <input id="${escapeHtml(id)}" type="checkbox" value="${escapeHtml(test.name)}" ${checkedSet.has(test.name) ? "checked" : ""}>
                <span>${escapeHtml(test.label)}</span>
            </label>
        `;
    }).join("");
}

function effectiveBoardConfig(board) {
    return board.dashboard_config || { skip_tests: [] };
}

function boardCardHtml(board) {
    const deviceKey = board.device_key || board.esp32_unique_id || board.board_id || "UNKNOWN_BOARD";
    const cfg = effectiveBoardConfig(board);
    const summary = board.summary || {};
    const boardId = board.board_id || "—";
    const uniqueId = board.esp32_unique_id || getNested(getResult(board, "system_memory").detail, ["unique_id"], "—");

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
                    </div>
                </div>
                <div class="muted">
                    ${escapeHtml(summary.passed ?? 0)} pass ·
                    ${escapeHtml(summary.warnings ?? 0)} warn ·
                    ${escapeHtml(summary.failed ?? 0)} fail ·
                    ${escapeHtml(summary.skipped_pass ?? 0)} skipped-pass
                </div>
            </div>

            <div class="board-grid">
                <section class="panel">
                    <h3>Key readings</h3>
                    ${readingsHtml(board)}
                </section>

                <section class="panel">
                    <h3>Skip tests for this board</h3>
                    <div class="checkbox-grid board-skip-list">
                        ${checkboxListHtml(`board-${deviceKey}`, cfg.board_skip_tests || [])}
                    </div>
                    <div class="override-actions">
                        <button class="save-board-btn" type="button">Save board skips</button>
                        <button class="secondary clear-board-btn" type="button">Clear board skips</button>
                    </div>
                </section>
            </div>

            <section class="panel" style="margin-top: 18px;">
                <h3>Test results</h3>
                <table>
                    <thead>
                        <tr><th>Test</th><th>Status</th><th>Detail</th></tr>
                    </thead>
                    <tbody>${testRowsHtml(board)}</tbody>
                </table>
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
    document.getElementById("global-skip-list").innerHTML = checkboxListHtml("global", globalConfig.skip_tests || []);
}

function renderBoards(boards) {
    const container = document.getElementById("boards-container");
    if (!boards.length) {
        container.innerHTML = `<div class="empty">Waiting for boards...</div>`;
        return;
    }

    container.innerHTML = boards.map(boardCardHtml).join("");
    attachBoardButtonHandlers();
}

function collectChecked(container) {
    return Array.from(container.querySelectorAll("input[type='checkbox']:checked")).map(input => input.value);
}

async function saveConfig(deviceKey, skipTests) {
    const response = await fetch(`/api/test-config/${encodeURIComponent(deviceKey)}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ skip_tests: skipTests })
    });

    if (!response.ok) {
        throw new Error(`Config save failed: ${response.status}`);
    }

    return await response.json();
}

function attachBoardButtonHandlers() {
    document.querySelectorAll(".board-card").forEach(card => {
        const deviceKey = card.dataset.deviceKey;
        const list = card.querySelector(".board-skip-list");

        card.querySelector(".save-board-btn").addEventListener("click", async () => {
            await saveConfig(deviceKey, collectChecked(list));
            await loadDashboard();
        });

        card.querySelector(".clear-board-btn").addEventListener("click", async () => {
            list.querySelectorAll("input[type='checkbox']").forEach(input => input.checked = false);
            await saveConfig(deviceKey, []);
            await loadDashboard();
        });
    });
}

async function saveGlobalConfig() {
    const list = document.getElementById("global-skip-list");
    await saveConfig("global", collectChecked(list));
    await loadDashboard();
}

async function loadDashboard() {
    try {
        const [catalogResponse, configResponse, boardResponse] = await Promise.all([
            fetch("/api/test-catalog"),
            fetch("/api/test-configs"),
            fetch("/api/boards")
        ]);

        testCatalog = await catalogResponse.json();
        allConfigs = await configResponse.json();
        latestBoards = await boardResponse.json();

        renderStats(latestBoards);
        renderGlobalConfig();
        renderBoards(latestBoards);
    } catch (err) {
        console.error(err);
    }
}

document.getElementById("refresh-btn").addEventListener("click", loadDashboard);
document.getElementById("save-global-btn").addEventListener("click", saveGlobalConfig);

setInterval(loadDashboard, 3000);
loadDashboard();
