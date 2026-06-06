function statusHtml(value) {

    let cls = "fail";

    if (value === "PASS")
        cls = "pass";

    return `
        <div class="status">
            <div class="status-dot ${cls}"></div>
            ${value}
        </div>
    `;
}

async function loadBoards() {

    try {

        const response = await fetch("/api/boards");
        const boards = await response.json();

        document.getElementById("total").innerText =
            boards.length;

        document.getElementById("passed").innerText =
            boards.filter(
                b => b.overall === "PASS"
            ).length;

        document.getElementById("failed").innerText =
            boards.filter(
                b => b.overall !== "PASS"
            ).length;

        const tbody =
            document.getElementById("tbody");

        if (boards.length === 0) {

            tbody.innerHTML = `
                <tr>
                    <td colspan="8" class="empty">
                        Waiting for boards...
                    </td>
                </tr>
            `;

            return;
        }

        tbody.innerHTML = boards.map(board => `

        <tr>

            <td>
                <div class="board-id">
                    ${board.board_id}
                </div>
            </td>

            <td>${statusHtml(board.bme280)}</td>

            <td>${statusHtml(board.lora)}</td>

            <td>${statusHtml(board.sd_card)}</td>

            <td>${statusHtml(board.wifi)}</td>

            <td>${statusHtml(board.overall)}</td>

            <td>
                <span class="last-seen">
                    ${board.last_seen}
                </span>
            </td>

        </tr>

        `).join("");

    }
    catch(err) {

        console.log(err);

    }
}

setInterval(loadBoards, 2000);

loadBoards();