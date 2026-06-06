from flask import Flask, render_template, request, jsonify
from datetime import datetime

app = Flask(__name__)

boards = {}

@app.route("/")
def dashboard():
    return render_template("dashboard.html")

@app.route("/api/boards")
def get_boards():
    return jsonify(list(boards.values()))

@app.route("/api/diagnostic", methods=["POST"])
def diagnostic():
    data = request.get_json()

    data["last_seen"] = datetime.now().strftime(
        "%Y-%m-%d %H:%M:%S"
    )

    boards[data["board_id"]] = data

    return jsonify({"status": "ok"})


if __name__ == "__main__":
    app.run(
        host="0.0.0.0",
        port=5000,
        debug=True
    )