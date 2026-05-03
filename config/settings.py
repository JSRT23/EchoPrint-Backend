"""
Django settings for config project.
"""

from pathlib import Path
from datetime import timedelta
import os
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

# ─── ENV ─────────────────────────────────────
load_dotenv(BASE_DIR / '.env')

# ─── Seguridad ───────────────────────────────
SECRET_KEY = os.getenv('SECRET_KEY', 'unsafe-secret-key')

DEBUG = os.getenv('DEBUG', 'False') == 'True'

ALLOWED_HOSTS = os.getenv(
    'ALLOWED_HOSTS',
    '127.0.0.1,localhost,.onrender.com'
).split(',')

FRONTEND_URL = os.getenv(
    'FRONTEND_URL',
    'http://localhost:5173'
)

# ─── Spotify ─────────────────────────────────
SPOTIFY_CLIENT_ID = os.getenv('SPOTIFY_CLIENT_ID')
SPOTIFY_CLIENT_SECRET = os.getenv('SPOTIFY_CLIENT_SECRET')
SPOTIFY_REDIRECT_URI = os.getenv('SPOTIFY_REDIRECT_URI')

# ─── AcoustID ────────────────────────────────
ACOUSTID_API_KEY = os.getenv('ACOUSTID_API_KEY')

# ─── Apps ────────────────────────────────────
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'corsheaders',

    'app.users',
    'app.songs',
    'app.recognition',
    'app.spotify_integration',
]

# ─── Middleware ──────────────────────────────
MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
    # FIX: CorsMiddleware debe ir ANTES de cualquier otro middleware
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',

    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'
WSGI_APPLICATION = 'config.wsgi.application'

# ─── Templates ───────────────────────────────
TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

# ─── Base de datos (Render PostgreSQL ready) ─
if os.getenv('DATABASE_URL'):
    import dj_database_url

    DATABASES = {
        'default': dj_database_url.config(
            conn_max_age=600,
            ssl_require=True
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# ─── DRF + JWT ───────────────────────────────
REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': (
        'rest_framework_simplejwt.authentication.JWTAuthentication',
    ),
}

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(hours=1),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
}

# ─── CORS / CSRF ─────────────────────────────
# FIX: Soporte para múltiples dominios de frontend separados por coma
_raw_origins = os.getenv('CORS_ALLOWED_ORIGINS', FRONTEND_URL)
_origins_list = [o.strip() for o in _raw_origins.split(',') if o.strip()]

# En desarrollo siempre permitir ambos orígenes locales
if DEBUG or not os.getenv('CORS_ALLOWED_ORIGINS'):
    for _local in ['http://localhost:5173', 'http://127.0.0.1:5173',
                   'http://localhost:3000', 'http://127.0.0.1:3000']:
        if _local not in _origins_list:
            _origins_list.append(_local)

CORS_ALLOWED_ORIGINS = _origins_list

# FIX: Agrega soporte para patrones de Vercel (previews de PR)
_raw_regex = os.getenv('CORS_ALLOWED_ORIGIN_REGEXES', '')
CORS_ALLOWED_ORIGIN_REGEXES = [r.strip()
                               for r in _raw_regex.split(',') if r.strip()]

CORS_ALLOW_CREDENTIALS = True

CORS_ALLOW_HEADERS = [
    'accept',
    'accept-encoding',
    'authorization',
    'content-type',
    'dnt',
    'origin',
    'user-agent',
    'x-csrftoken',
    'x-requested-with',
]

CORS_ALLOW_METHODS = [
    'DELETE',
    'GET',
    'OPTIONS',
    'PATCH',
    'POST',
    'PUT',
]

CSRF_TRUSTED_ORIGINS = [o.strip()
                        for o in _raw_origins.split(',') if o.strip()]

# ─── Auth ────────────────────────────────────
AUTH_USER_MODEL = 'users.CustomUser'

# ─── i18n ───────────────────────────────────
LANGUAGE_CODE = 'es-co'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

# ─── Static ──────────────────────────────────
STATIC_URL = '/static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

# ─── Media ───────────────────────────────────
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# ── Logging para debug ────────────────────────────────────────────────────────
LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {
        'console': {
            'class': 'logging.StreamHandler',
        },
    },
    'root': {
        'handlers': ['console'],
        'level': 'ERROR',
    },
    'loggers': {
        'app': {
            'handlers': ['console'],
            'level': 'DEBUG',
            'propagate': False,
        },
    },
}
