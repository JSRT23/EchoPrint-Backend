import base64
import logging
import urllib.parse
import requests
from datetime import timedelta
from django.conf import settings
from django.utils import timezone

logger = logging.getLogger(__name__)


class SpotifyInsufficientScopeError(Exception):
    """Raised when Spotify returns 403 due to missing OAuth scopes."""
    pass


SPOTIFY_AUTH_URL = 'https://accounts.spotify.com/authorize'
SPOTIFY_TOKEN_URL = 'https://accounts.spotify.com/api/token'
SPOTIFY_API_BASE = 'https://api.spotify.com/v1'

SPOTIFY_SCOPES = [
    'user-read-private',
    'user-read-email',
    'user-read-recently-played',
    'user-library-modify',
    'user-library-read',
    'playlist-modify-public',
    'playlist-modify-private',
    'playlist-read-private',
    'playlist-read-collaborative',
    'streaming',
]


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
    return getattr(settings, 'SPOTIFY_REDIRECT_URI',
                   'http://127.0.0.1:8000/api/spotify/callback/')


def get_auth_url(state: str = '') -> str:
    params = {
        'client_id':     _client_id(),
        'response_type': 'code',
        'redirect_uri':  _redirect_uri(),
        'scope':         ' '.join(SPOTIFY_SCOPES),
        'state':         state,
        'show_dialog':   'true',
    }
    query = urllib.parse.urlencode(params)
    return f"{SPOTIFY_AUTH_URL}?{query}"


def _get_client_credentials_token() -> str:
    credentials = base64.b64encode(
        f"{_client_id()}:{_client_secret()}".encode()
    ).decode()
    response = requests.post(
        SPOTIFY_TOKEN_URL,
        data={'grant_type': 'client_credentials'},
        headers={
            'Authorization': f'Basic {credentials}',
            'Content-Type':  'application/x-www-form-urlencoded',
        },
        timeout=10,
    )
    if not response.ok:
        logger.error("Spotify CC token error %s: %s",
                     response.status_code, response.text)
        response.raise_for_status()
    return response.json()['access_token']


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

    needs_refresh = (
        user.spotify_token_expires is None or
        timezone.now() >= user.spotify_token_expires - timedelta(seconds=60)
    )

    if needs_refresh and user.spotify_refresh_token:
        try:
            data = refresh_access_token(user.spotify_refresh_token)
            user.spotify_access_token = data['access_token']
            user.spotify_token_expires = (
                timezone.now() + timedelta(seconds=data.get('expires_in', 3600))
            )
            if 'refresh_token' in data:
                user.spotify_refresh_token = data['refresh_token']
            user.save(update_fields=[
                'spotify_access_token',
                'spotify_refresh_token',
                'spotify_token_expires',
            ])
            logger.info("Token de Spotify refrescado para user_id=%s", user.id)
        except Exception as exc:
            logger.warning(
                "No se pudo refrescar token de Spotify para user_id=%s: %s", user.id, exc)

    return user.spotify_access_token


def spotify_get(user, endpoint: str) -> dict:
    token = get_valid_token(user)
    response = requests.get(
        f"{SPOTIFY_API_BASE}{endpoint}",
        headers={'Authorization': f'Bearer {token}'},
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def spotify_post(user, endpoint: str, payload: dict) -> dict:
    token = get_valid_token(user)
    response = requests.post(
        f"{SPOTIFY_API_BASE}{endpoint}",
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        json=payload,
        timeout=10,
    )
    if not response.ok:
        logger.error("Spotify POST error %s %s: %s",
                     response.status_code, endpoint, response.text[:300])
        if response.status_code == 403:
            raise SpotifyInsufficientScopeError(
                f"Spotify 403 en {endpoint}: permisos insuficientes. "
                "El token no tiene los scopes necesarios. "
                "El usuario debe desconectar y reconectar su cuenta."
            )
        response.raise_for_status()
    return response.json() if response.content else {}


def spotify_put(user, endpoint: str, payload: dict) -> bool:
    """PUT request to Spotify API. Returns True on success."""
    token = get_valid_token(user)
    response = requests.put(
        f"{SPOTIFY_API_BASE}{endpoint}",
        headers={
            'Authorization': f'Bearer {token}',
            'Content-Type':  'application/json',
        },
        json=payload,
        timeout=10,
    )
    if not response.ok:
        logger.error("Spotify PUT error %s %s: %s",
                     response.status_code, endpoint, response.text[:300])
        if response.status_code == 403:
            raise SpotifyInsufficientScopeError(
                f"Spotify 403 en {endpoint}: permisos insuficientes."
            )
        response.raise_for_status()
    return True


def search_track(query: str, limit: int = 20) -> list:
    token = _get_client_credentials_token()
    response = requests.get(
        f"{SPOTIFY_API_BASE}/search",
        headers={'Authorization': f'Bearer {token}'},
        params={'q': query, 'type': 'track'},
        timeout=10,
    )
    if not response.ok:
        logger.error("Spotify search error %s: %s",
                     response.status_code, response.text[:300])
        response.raise_for_status()
    items = response.json().get('tracks', {}).get('items', [])
    return [_format_track(t) for t in items if t]


def search_track_with_genres(query: str, limit: int = 20) -> list:
    token = _get_client_credentials_token()
    response = requests.get(
        f"{SPOTIFY_API_BASE}/search",
        headers={'Authorization': f'Bearer {token}'},
        params={'q': query, 'type': 'track'},
        timeout=10,
    )
    if not response.ok:
        logger.error("Spotify search_genres error %s: %s",
                     response.status_code, response.text[:300])
        response.raise_for_status()

    items = response.json().get('tracks', {}).get('items', [])
    if not items:
        return []

    artist_ids = list({
        t['artists'][0]['id']
        for t in items
        if t and t.get('artists')
    })[:50]

    genre_map: dict = {}
    try:
        artists_resp = requests.get(
            f"{SPOTIFY_API_BASE}/artists",
            headers={'Authorization': f'Bearer {token}'},
            params={'ids': ','.join(artist_ids)},
            timeout=8,
        )
        if artists_resp.ok:
            for a in artists_resp.json().get('artists', []):
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
