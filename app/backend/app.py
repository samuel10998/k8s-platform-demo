"""Jednoduchý backend pre zadanie Aspecta.

Endpointy:
  GET /api/hello  - odpoveď pre frontend (cez Ingress)
  GET /healthz    - liveness: proces žije
  GET /readyz     - readiness: appka má konfiguráciu a môže prijímať požiadavky

Konfigurácia (premenné prostredia):
  APP_GREETING  - text pozdravu (ConfigMap)
  APP_ENV       - názov prostredia, napr. dev / prod (ConfigMap)
  API_KEY       - tajný kľúč (Secret); bez neho appka nie je "ready"
"""

import os
import socket

from flask import Flask, jsonify

app = Flask(__name__)


@app.get("/api/hello")
def hello():
    return jsonify(
        message=os.environ.get("APP_GREETING", "Ahoj z backendu"),
        environment=os.environ.get("APP_ENV", "neznáme"),
        pod=socket.gethostname(),
        secret_configured=bool(os.environ.get("API_KEY")),
    )


@app.get("/healthz")
def healthz():
    return jsonify(status="ok")


@app.get("/readyz")
def readyz():
    if not os.environ.get("API_KEY"):
        return jsonify(status="not ready", reason="chýba API_KEY"), 503
    return jsonify(status="ready")
