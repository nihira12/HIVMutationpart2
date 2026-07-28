# HIV Resistance Intelligence

A Flask-based web app for exploring HIV drug resistance mutations, co-occurrence patterns, and interaction data.

## Run locally

```bash
python -m pip install -r requirements.txt
python app.py
```

## Render deployment

Set the start command to:

```bash
gunicorn app:app
```
