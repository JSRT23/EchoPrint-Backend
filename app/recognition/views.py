from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions, throttling
from django.utils import timezone
from app.songs.models import Song, Artist, Album, UserHistory
from app.songs.serializers import SongSerializer
from app.spotify_integration.spotify_client import enrich_song_from_spotify
from .models import RecognitionLog
from .fingerprint_engine import recognize_audio, recognize_humming


class RecognizeThrottle(throttling.AnonRateThrottle):
    """
    Limita el endpoint de reconocimiento para usuarios anónimos.
    Evita abuso del servicio ACRCloud (de pago).
    Tasa: 10 reconocimientos por hora por IP.
    Configurable en settings con ANON_RECOGNIZE_RATE.
    """
    scope = 'recognize'


def _upsert_history(user, song, method, match_timestamp_seconds=None):
    """
    Flujo de historial limpio y profesional:
    - Si la canción ya existe en el historial del usuario,
      ELIMINA la entrada anterior y crea una nueva con timestamp actual.
      → Siempre aparece en el tope, sin duplicados.
    - Si no existe, simplemente la crea.
    Devuelve (entry, was_new).
    """
    existing = UserHistory.objects.filter(
        user=user,
        song=song,
    ).order_by('-identified_at').first()

    if existing:
        existing.delete()

    entry = UserHistory.objects.create(
        user=user,
        song=song,
        method=method,
        match_timestamp_seconds=match_timestamp_seconds,
    )
    return entry, True


def _get_or_create_song_from_result(result: dict) -> Song:
    """
    Busca la canción en la BD por título+artista.
    Si no existe la crea enriqueciendo con Spotify.
    Lógica compartida entre audio y humming.
    """
    title = result.get('title', '')
    artist_name = result.get('artist', '')

    # Buscar si ya existe (por spotify_id primero, luego título+artista)
    spotify_id = result.get('spotify_id', '')
    if spotify_id:
        existing = Song.objects.filter(
            spotify_id=spotify_id
        ).select_related('artist', 'album').first()
        if existing:
            return existing

    existing = Song.objects.filter(
        title__iexact=title,
        artist__name__iexact=artist_name
    ).select_related('artist', 'album').first()

    if existing:
        return existing

    # Enriquecer con Spotify
    spotify_data = enrich_song_from_spotify(title, artist_name)

    # Crear o buscar artista
    artist, _ = Artist.objects.get_or_create(
        name__iexact=artist_name,
        defaults={
            'name':       artist_name,
            'spotify_id': spotify_data.get('spotify_id', ''),
        }
    )

    # Crear o buscar álbum
    album = None
    album_title = result.get('album') or spotify_data.get('album', '')
    if album_title:
        album, _ = Album.objects.get_or_create(
            title__iexact=album_title,
            artist=artist,
            defaults={
                'title':     album_title,
                'cover_url': spotify_data.get('cover_url'),
            }
        )

    # Crear canción
    song = Song.objects.create(
        title=title,
        artist=artist,
        album=album,
        genre=result.get('genre', ''),
        duration_seconds=result.get('duration_seconds'),
        cover_url=(
            result.get('cover_url') or
            spotify_data.get('cover_url')
        ),
        spotify_id=spotify_data.get('spotify_id', ''),
        spotify_preview_url=spotify_data.get('preview_url', ''),
    )

    return song


class RecognizeAudioView(APIView):
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RecognizeThrottle]

    def post(self, request):
        audio_file = request.FILES.get('audio')

        if not audio_file:
            return Response(
                {'error': 'No se recibió archivo de audio.'}, status=400
            )

        if audio_file.size > 10 * 1024 * 1024:
            return Response(
                {'error': 'El archivo supera 10MB.'}, status=400
            )

        try:
            audio_bytes = audio_file.read()
            import logging
            logger = logging.getLogger(__name__)
            logger.error("RECOGNIZE: tamaño=%d bytes, content_type=%s", len(
                audio_bytes), audio_file.content_type)
            result = recognize_audio(audio_bytes)
        except RuntimeError as e:
            import logging
            logging.getLogger(__name__).error(
                "RECOGNIZE RuntimeError: %s", str(e), exc_info=True)
            return Response({'error': str(e)}, status=422)

        if not result['found']:
            RecognitionLog.objects.create(
                status='no_match',
                score=result['score'],
            )
            return Response({
                'status': 'no_match',
                'message': 'No se encontró ninguna canción coincidente.',
                'score': result['score'],
                'match_timestamp_seconds': None,
                'song': None,
            })

        song = _get_or_create_song_from_result(result)
        match_ts = result.get('match_timestamp_seconds')

        # ── Historial SIN duplicados ───────────────────────────────────
        if request.user.is_authenticated:
            _upsert_history(
                user=request.user,
                song=song,
                method='audio',
                match_timestamp_seconds=match_ts,
            )

        RecognitionLog.objects.create(
            song_matched=song,
            status='success',
            score=result['score'],
            match_timestamp_seconds=match_ts,
        )

        return Response({
            'status': 'success',
            'message': '¡Canción identificada!',
            'score': result['score'],
            'match_timestamp_seconds': match_ts,
            'song': SongSerializer(song).data,
        })


class RecognizeHummingView(APIView):
    """
    Reconocimiento por tarareo / canto / silbido.
    Usa el proyecto Humming de ACRCloud.
    """
    permission_classes = [permissions.AllowAny]
    throttle_classes = [RecognizeThrottle]

    def post(self, request):
        audio_file = request.FILES.get('audio')

        if not audio_file:
            return Response({'error': 'No se recibió archivo de audio.'}, status=400)

        if audio_file.size > 10 * 1024 * 1024:
            return Response({'error': 'El archivo supera 10MB.'}, status=400)

        try:
            audio_bytes = audio_file.read()
            result = recognize_humming(audio_bytes)
        except RuntimeError as e:
            return Response({'error': str(e)}, status=422)

        if not result['found']:
            RecognitionLog.objects.create(
                status='no_match', score=result['score'])
            return Response({
                'status':  'no_match',
                'message': 'No se encontró ninguna canción. Intenta tararear más claro.',
                'score':   result['score'],
                'song':    None,
            })

        song = _get_or_create_song_from_result(result)
        match_ts = result.get('match_timestamp_seconds')

        # ── Historial SIN duplicados ───────────────────────────────────
        if request.user.is_authenticated:
            _upsert_history(
                user=request.user,
                song=song,
                method='humming',
                match_timestamp_seconds=match_ts,
            )

        RecognitionLog.objects.create(
            song_matched=song, status='success',
            score=result['score'], match_timestamp_seconds=match_ts,
        )

        return Response({
            'status':  'success',
            'message': '¡Canción identificada por tarareo!',
            'score':   result['score'],
            'match_timestamp_seconds': match_ts,
            'song':    SongSerializer(song).data,
        })
