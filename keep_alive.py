import os
from flask import Flask
from threading import Thread

app = Flask("")


@app.route("/")
def home():
    return "alive"


def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port, use_reloader=False, threaded=True)


def keep_alive():
    t = Thread(target=run, daemon=True)
    t.start()
