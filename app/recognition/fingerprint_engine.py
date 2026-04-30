import os
import base64
import hashlib
import hmac
import time
import logging
import requests

logger = logging.getLogger(__name__)

# ── Credenciales fingerprinting normal ───────────────────────────────────────
ACRCLOUD_HOST = os.getenv('ACRCLOUD_HOST', '')
ACRCLOUD_ACCESS_KEY = os.getenv('ACRCLOUD_ACCESS_KEY', '')
ACRCLOUD_ACCESS_SECRET = os.getenv('ACRCLOUD_ACCESS_SECRET', '')

# ── Credenciales humming (tarareo/canto) ─────────────────────────────────────
ACRCLOUD_HUMMING_HOST = os.getenv('ACRCLOUD_HUMMING_HOST', ACRCLOUD_HOST)
ACRCLOUD_HUMMING_ACCESS_KEY = os.getenv(
    'ACRCLOUD_HUMMING_ACCESS_KEY', ACRCLOUD_ACCESS_KEY)
ACRCLOUD_HUMMING_ACCESS_SECRET = os.getenv(
    'ACRCLOUD_HUMMING_ACCESS_SECRET', ACRCLOUD_ACCESS_SECRET)


def _build_signature(access_key: str, access_secret: str, timestamp: str) -> str:
    string_to_sign = '\n'.join([
        'POST', '/v1/identify', access_key,
        'audio', '1', timestamp
    ])
    return base64.b64encode(
        hmac.new(
            access_secret.encode('utf-8'),
            string_to_sign.encode('utf-8'),
            digestmod=hashlib.sha1
        ).digest()
    ).decode('utf-8')


def _call_acrcloud(audio_bytes: bytes, host: str, key: str, secret: str) -> dict:
    """Llama a ACRCloud y retorna el JSON crudo de la respuesta."""
    timestamp = str(time.time())
    sig = _build_signature(key, secret, timestamp)
    url = f'https://{host}/v1/identify'

    files = {'sample': ('recording.wav', audio_bytes, 'audio/wav')}
    data = {
        'access_key':        key,
        'data_type':         'audio',
        'signature_version': '1',
        'signature':         sig,
        'sample_bytes':      len(audio_bytes),
        'timestamp':         timestamp,
    }
    response = requests.post(url, files=files, data=data, timeout=15)
    response.raise_for_status()
    response.encoding = 'utf-8'
    return response.json()


def _parse_result(result: dict, min_score: float = 0.0) -> dict:
    """Convierte la respuesta JSON de ACRCloud al formato interno."""
    status = result.get('status', {})
    code = status.get('code', -1)

    if code == 1001:
        return {'found': False, 'score': 0.0, 'match_timestamp_seconds': None}

    if code != 0:
        raise RuntimeError(
            f"ACRCloud error {code}: {status.get('msg', 'desconocido')}")

    metadata = result.get('metadata', {})
    # ACRCloud fingerprinting → metadata.music
    # ACRCloud humming        → metadata.humming
    music_list = metadata.get('music') or metadata.get('humming', [])
    if not music_list:
        return {'found': False, 'score': 0.0, 'match_timestamp_seconds': None}

    track = music_list[0]

    def clean(s):
        """Fix mojibake UTF-8 leído como Latin-1."""
        if not s:
            return s
        try:
            return s.encode('latin-1').decode('utf-8')
        except Exception:
            return s

    title = clean(track.get('title', ''))
    score = track.get('score', 100) / 100.0
    play_offset = track.get('play_offset_ms', 0)
    match_ts = round(play_offset / 1000, 2) if play_offset else None

    artists = track.get('artists', [])
    artist_name = clean(artists[0].get('name', '')) if artists else ''

    album_info = track.get('album', {})
    album_name = clean(album_info.get('name', ''))

    genres = track.get('genres', [])
    genre = clean(genres[0].get('name', '')) if genres else ''

    duration_ms = track.get('duration_ms')
    duration_seconds = int(duration_ms) // 1000 if duration_ms else None

    # Spotify ID si está disponible
    external = track.get('external_metadata', {})
    spotify_id = external.get('spotify', {}).get('track', {}).get('id')

    # Portada desde Cover Art Archive
    cover_url = None
    release_id = track.get('release_id') or track.get('acrid')
    if release_id:
        cover_url = _get_cover_art(release_id)

    return {
        'found':                   True,
        'score':                   round(float(score), 4),
        'title':                   title,
        'artist':                  artist_name,
        'album':                   album_name,
        'genre':                   genre,
        'cover_url':               cover_url,
        'duration_seconds':        duration_seconds,
        'spotify_id':              spotify_id,
        'preview_url':             None,
        'match_timestamp_seconds': match_ts,
    }


def recognize_audio(audio_bytes: bytes) -> dict:
    """
    Reconocimiento por audio (fingerprinting normal).
    Para canciones sonando en el ambiente.
    """
    if not ACRCLOUD_HOST or not ACRCLOUD_ACCESS_KEY or not ACRCLOUD_ACCESS_SECRET:
        raise RuntimeError('Faltan credenciales de ACRCloud en el .env')
    try:
        result = _call_acrcloud(
            audio_bytes,
            ACRCLOUD_HOST, ACRCLOUD_ACCESS_KEY, ACRCLOUD_ACCESS_SECRET
        )
        return _parse_result(result)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f'Error en ACRCloud: {str(e)}')


def recognize_humming(audio_bytes: bytes) -> dict:
    """
    Reconocimiento por tarareo/canto/silbido (humming).
    Usa las credenciales del proyecto humming de ACRCloud.
    """
    if not ACRCLOUD_HUMMING_HOST or not ACRCLOUD_HUMMING_ACCESS_KEY or not ACRCLOUD_HUMMING_ACCESS_SECRET:
        raise RuntimeError(
            'Faltan credenciales de ACRCloud Humming en el .env')
    try:
        result = _call_acrcloud(
            audio_bytes,
            ACRCLOUD_HUMMING_HOST,
            ACRCLOUD_HUMMING_ACCESS_KEY,
            ACRCLOUD_HUMMING_ACCESS_SECRET,
        )
        # Score mínimo más alto para humming: evita falsos positivos
        return _parse_result(result, min_score=0.82)
    except RuntimeError:
        raise
    except Exception as e:
        raise RuntimeError(f'Error en ACRCloud Humming: {str(e)}')


def _get_cover_art(release_id: str):
    try:
        url = f'https://coverartarchive.org/release/{release_id}/front-250'
        r = requests.get(url, timeout=5, allow_redirects=True)
        if r.status_code == 200:
            return r.url
    except Exception:
        pass
    return None
