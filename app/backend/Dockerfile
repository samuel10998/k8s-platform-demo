FROM python:3.12.16-slim

WORKDIR /app

# Najprv skopírujeme závislosti
COPY requirements.txt .

# Inštalácia Python závislostí
RUN pip install --no-cache-dir -r requirements.txt

# Vytvorenie používateľa
RUN useradd --uid 10001 --create-home appuser

# Skopírovanie aplikácie
COPY app.py .

# Spustenie pod non-root používateľom
USER 10001

# Port aplikácie
EXPOSE 8000

# Spustenie aplikácie cez Gunicorn (exec forma)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "app:app"]