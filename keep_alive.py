import os
from flask import Flask
from threading import Thread
 
app = Flask("")
 
@app.route("/")
def home():
    return "alive"
 
def run():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)
 
def keep_alive():
    Thread(target=run).start()
