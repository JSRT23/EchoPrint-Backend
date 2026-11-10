# 🎧 EchoPrint — Backend

API REST de **EchoPrint**: autenticación, reconocimiento de canciones, historial e integración con Spotify.

![Django](https://img.shields.io/badge/Django-6.0-092E20?logo=django&logoColor=white)
![DRF](https://img.shields.io/badge/DRF-JWT-A30000)
![Docker](https://img.shields.io/badge/Docker-ready-2496ED?logo=docker&logoColor=white)

## Servicios externos

| Servicio | Para qué |
|---|---|
| ACRCloud | Reconocimiento de audio |
| AcoustID | Huella acústica / metadatos |
| Spotify | Vincular cuenta y abrir temas |

## Apps y endpoints

| App | Prefijo |
|---|---|
| `users` | `/api/users/` |
| `songs` | `/api/songs/` |
| `recognition` | `/api/recognize/` |
| `spotify_integration` | `/api/spotify/` |

## Variables de entorno

Copia `.env.example` a `.env` y completa:

`SECRET_KEY`, `DEBUG`, `ALLOWED_HOSTS`, `FRONTEND_URL`, `ACRCLOUD_*`, `SPOTIFY_*`, `ACOUSTID_API_KEY`. Opcionales: `DATABASE_URL`, `CORS_ALLOWED_ORIGINS`.

Sin `DATABASE_URL` se usa SQLite.

## Cómo correrlo

### Con Docker

```bash
git clone https://github.com/JSRT23/EchoPrint-Backend.git
cd EchoPrint-Backend
cp .env.example .env
docker compose up --build        # http://localhost:8000
```

El compose monta el código (`.:/app`) y usa `runserver`; la imagen del `Dockerfile` arranca con `gunicorn config.wsgi`.

### Sin Docker

Requiere Python 3.12.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python manage.py migrate
python manage.py runserver
```

Frontend: [EchoPrint-Music](https://github.com/JSRT23/EchoPrint-Music).
