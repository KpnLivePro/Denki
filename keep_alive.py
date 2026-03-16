from __future__ import annotations

from threading import Thread

from flask import Flask

app = Flask(__name__)


@app.route("/")
def home() -> str:
    return "Denki is alive ⚡"


def run() -> None:
    app.run(host="0.0.0.0", port=8081)


def keep_alive() -> None:
    t = Thread(target=run)
    t.daemon = True
    t.start()