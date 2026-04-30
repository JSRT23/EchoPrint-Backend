import base64
import json
import logging
import ssl
import urllib.request
import urllib.parse
import urllib.error
import requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)

SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_BASE = 'https://api.spotify.com/v1'

SPOTIFY_SCOPES = [
    'user-read-private',
    'user-read-email',
    'user-read-recently-played',
    'playlist-modify-public',
    'playlist-modify-private',
    'playlist-read-private',
    'streaming',
]

# SSL context explícito para Python 3.14
_SSL_CTX = ssl.create_default_context()


def _client_id() -> str:
    value = getattr(settings, 'SPOTIFY_CLIENT_ID', None)
    if not value:
        raise ValueError('SPOTIFY_CLIENT_ID no encontrado en settings.')
    return value


def _client_secret() -> str:
    value = getattr(settings, 'SPOTIFY_CLIENT_SECRET', None)
    if not value:
        raise ValueError('SPOTIFY_CLIENT_SECRET no encontrado en settings.')
    return value


def _redirect_uri() -> str:
    return getattr(settings, 'SPOTIFY_REDIRECT_URI', 'http://127.0.0.1:8000/api/spotify/callback/')


def get_auth_url(state: str = '') -> str:
    params = {
        'client_id':     _client_id(),
        'response_type': 'code',
        'redirect_uri':  _redirect_uri(),
        'scope':         ' '.join(SPOTIFY_SCOPES),
        'state':         state,
        'show_dialog':   'true',
    }
    query = '&'.join([f"{k}={v}" for k, v in params.items()])
    return f"{SPOTIFY_AUTH_URL}?{query}"


def _get_client_credentials_token() -> str:
    credentials = base64.b64encode(
        f"{_client_id()}:{_client_secret()}".encode()
    ).decode()
    body = urllib.parse.urlencode(
        {'grant_type': 'client_credentials'}).encode('utf-8')
    req = urllib.request.Request(
        SPOTIFY_TOKEN_URL,
        data=body,
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type':  'application/x-www-form-urlencoded',
        },
        method='POST',
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))['access_token']
    except urllib.error.HTTPError as e:
        body_err = e.read().decode('utf-8')
        logger.error("Spotify token error %s — %s", e.code, body_err)
        raise RuntimeError(
            f"Error obteniendo token: {e.code} {body_err}") from e


def _http_get(url: str, token: str) -> dict:
    """GET autenticado usando urllib con SSL explícito."""
    # Log de diagnóstico — ver en terminal de Django
    logger.warning("SPOTIFY_GET url=%s token_prefix=%s", url, token[:15])
    req = urllib.request.Request(
        url,
        method='GET',
        headers={
            'Authorization': f'Bearer {token}',
            'Accept':        'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as resp:
            return json.loads(resp.read().decode('utf-8'))
    except urllib.error.HTTPError as e:
        body = e.read().decode('utf-8')
        logger.error("Spotify GET error %s %s — %s", e.code, url, body)
        raise RuntimeError(f"{e.code} {e.reason}: {body}") from e


def exchange_code_for_tokens(code: str) -> dict:
    response = requests.post(SPOTIFY_TOKEN_URL, data={
        'grant_type':    'authorization_code',
        'code':          code,
        'redirect_uri':  _redirect_uri(),
        'client_id':     _client_id(),
        'client_secret': _client_secret(),
    }, timeout=10)
    response.raise_for_status()
    return response.json()


def refresh_access_token(refresh_token: str) -> dict:
    response = requests.post(SPOTIFY_TOKEN_URL, data={
        'grant_type':    'refresh_token',
        'refresh_token': refresh_token,
        'client_id':     _client_id(),
        'client_secret': _client_secret(),
    }, timeout=10)
    response.raise_for_status()
    return response.json()


def get_valid_token(user) -> str:
    if not user.spotify_access_token:
        raise ValueError('Usuario no conectado a Spotify.')
    if user.spotify_token_expires and \
       timezone.now() >= user.spotify_token_expires - timedelta(seconds=60):
        data = refresh_access_token(user.spotify_refresh_token)
        user.spotify_access_token = data['access_token']
        user.spotify_token_expires = timezone.now(
        ) + timedelta(seconds=data['expires_in'])
        if 'refresh_token' in data:
            user.spotify_refresh_token = data['refresh_token']
        user.save(update_fields=[
            'spotify_access_token',
            'spotify_refresh_token',
            'spotify_token_expires',
        ])
    return user.spotify_access_token


def spotify_get(user, endpoint: str) -> dict:
    return _http_get(f"{SPOTIFY_API_BASE}{endpoint}", get_valid_token(user))


def spotify_post(user, endpoint: str, payload: dict) -> dict:
    token = get_valid_token(user)
    body = json.dumps(payload).encode('utf-8')
    req = urllib.request.Request(
        f"{SPOTIFY_API_BASE}{endpoint}",
        data=body,
        method='POST',
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
            'Accept':        'application/json',
        },
    )
    try:
        with urllib.request.urlopen(req, context=_SSL_CTX, timeout=10) as resp:
            content = resp.read()
            return json.loads(content.decode('utf-8')) if content else {}
    except urllib.error.HTTPError as e:
        body_err = e.read().decode('utf-8')
        raise RuntimeError(f"{e.code}: {body_err}") from e


def search_track(query: str, limit: int = 20) -> list:
    token = _get_client_credentials_token()
    # Sin limit explícito — Spotify usa 20 por defecto
    params = urllib.parse.urlencode({'q': query, 'type': 'track'})
    url = f"{SPOTIFY_API_BASE}/search?{params}"
    data = _http_get(url, token)
    items = data.get('tracks', {}).get('items', [])
    return [_format_track(t) for t in items if t]


def search_track_with_genres(query: str, limit: int = 20) -> list:
    token = _get_client_credentials_token()
    # Sin limit explícito — Spotify usa 20 por defecto para evitar "Invalid limit"
    params = urllib.parse.urlencode({'q': query, 'type': 'track'})
    url = f"{SPOTIFY_API_BASE}/search?{params}"
    data = _http_get(url, token)
    items = data.get('tracks', {}).get('items', [])
    if not items:
        return []

    artist_ids = list({
        t['artists'][0]['id']
        for t in items
        if t and t.get('artists')
    })[:50]

    genre_map: dict = {}
    try:
        ids_params = urllib.parse.urlencode({'ids': ','.join(artist_ids)})
        artists_data = _http_get(
            f"{SPOTIFY_API_BASE}/artists?{ids_params}", token)
        for a in artists_data.get('artists', []):
            if a:
                genres = a.get('genres', [])
                genre_map[a['id']] = genres[0] if genres else ''
    except Exception:
        pass

    tracks = []
    for t in items:
        if not t:
            continue
        formatted = _format_track(t)
        artist_id = t['artists'][0]['id'] if t.get('artists') else ''
        formatted['genre'] = genre_map.get(artist_id, '')
        tracks.append(formatted)
    return tracks


def _format_track(track: dict) -> dict:
    images = track.get('album', {}).get('images', [])
    return {
        'spotify_id':   track['id'],
        'title':        track['name'],
        'artist':       track['artists'][0]['name'] if track.get('artists') else '',
        'album':        track.get('album', {}).get('name', ''),
        'genre':        '',
        'cover_url':    images[0]['url'] if images else None,
        'preview_url':  track.get('preview_url') or None,
        'duration_ms':  track.get('duration_ms'),
        'external_url': track.get('external_urls', {}).get('spotify') or None,
    }


def enrich_song_from_spotify(title: str, artist: str) -> dict:
    query = f"track:{title} artist:{artist}"
    try:
        results = search_track(query, limit=1)
        if results:
            return results[0]
    except Exception:
        pass
    return {}
