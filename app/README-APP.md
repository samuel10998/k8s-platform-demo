# Hotová appka / generovaná pomocou AI

## backend/

- Python, Flask, spúšťa sa cez **gunicorn** na porte **8000**
- závislosti: `requirements.txt`
- spúšťací príkaz: `gunicorn --bind 0.0.0.0:8000 app:app`

| Endpoint | Na čo je | Odpoveď |
|---|---|---|
| `GET /api/hello` | volá ho frontend (pôjde cez Ingress) | JSON: správa, prostredie, meno Podu, či je nastavený Secret |
| `GET /healthz` | liveness probe | vždy `200` |
| `GET /readyz` | readiness probe | `200` keď je nastavený `API_KEY`, inak `503` |

Premenné prostredia:

| Premenná | Odkiaľ v Kubernetes | Povinná |
|---|---|---|
| `APP_GREETING` | ConfigMap | nie (má predvolenú hodnotu) |
| `APP_ENV` | ConfigMap | nie |
| `API_KEY` | Secret | áno, bez nej Pod nebude Ready |

`/healthz` a `/readyz` nie sú pod `/api`, takže cez Ingress nebudú zvonka dostupné. Používa ich len kubelet.

## frontend/

- jedna statická stránka `index.html`
- servíruje ju nginx; volá backend relatívnou cestou `/api/hello`, takže funguje až keď sú frontend aj backend za tým istým Ingressom
- samostatne spustená (bez backendu) stránku ukáže, ale tlačidlo vypíše „Backend nedostupný“, čo je v poriadku
