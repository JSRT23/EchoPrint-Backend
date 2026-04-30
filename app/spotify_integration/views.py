import logging
from datetime import timedelta
from django.utils import timezone
from django.conf import settings
from django.core import signing
from django.shortcuts import redirect
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import permissions

from .spotify_client import (
    get_auth_url, exchange_code_for_tokens,
    spotify_get, spotify_post,
    search_track_with_genres, _format_track,
)
from .models import SpotifyPlaylist
from .serializers import SpotifyPlaylistSerializer, SpotifyTrackSerializer
from app.users.models import CustomUser

logger = logging.getLogger(__name__)

FRONTEND_URL = getattr(settings, 'FRONTEND_URL', 'http://localhost:5173')
_OAUTH_SALT = 'spotify-oauth-state-v1'


class SpotifyAuthURLView(APIView):
    """
    Genera la URL de autorización de Spotify.
    Firma el user_id en el parámetro `state` con Django signing (TTL 10 min)
    para identificar al usuario en el callback sin necesitar JWT.
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        state = signing.dumps(
            {'user_id': request.user.id},
            salt=_OAUTH_SALT,
        )
        url = get_auth_url(state=state)
        logger.warning("SpotifyAuth: user_id=%s auth_url=%s",
                       request.user.id, url[:80])
        return Response({'auth_url': url})


class SpotifyCallbackView(APIView):
    """
    Callback de Spotify — PÚBLICO (AllowAny).
    Spotify redirige aquí sin JWT; identificamos al usuario
    mediante el `state` firmado criptográficamente.
    """
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        code = request.query_params.get('code')
        error = request.query_params.get('error')
        state = request.query_params.get('state', '')

        if error or not code:
            logger.warning("SpotifyCallback rechazado: error=%s", error)
            return redirect(f"{FRONTEND_URL}/?spotify_error=access_denied")

        # Decodificar state para obtener al usuario
        try:
            data = signing.loads(state, salt=_OAUTH_SALT, max_age=600)
            user = CustomUser.objects.get(id=data['user_id'])
        except signing.SignatureExpired:
            logger.warning("SpotifyCallback state expirado")
            return redirect(f"{FRONTEND_URL}/?spotify_error=state_expired")
        except (signing.BadSignature, KeyError, CustomUser.DoesNotExist) as exc:
            logger.warning("SpotifyCallback state inválido: %s", exc)
            return redirect(f"{FRONTEND_URL}/?spotify_error=invalid_state")

        # Intercambiar code por tokens
        try:
            tokens = exchange_code_for_tokens(code)
            user.spotify_access_token = tokens['access_token']
            user.spotify_refresh_token = tokens.get('refresh_token', '')
            user.spotify_token_expires = (
                timezone.now() + timedelta(seconds=tokens['expires_in'])
            )
            user.save(update_fields=[
                'spotify_access_token',
                'spotify_refresh_token',
                'spotify_token_expires',
            ])
            logger.info("Spotify conectado para user_id=%s", user.id)
            return redirect(f"{FRONTEND_URL}/?spotify_connected=true")
        except Exception:
            logger.exception("Error intercambiando tokens de Spotify")
            return redirect(f"{FRONTEND_URL}/?spotify_error=token_exchange_failed")


class SpotifyProfileView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.spotify_access_token:
            return Response({'error': 'No conectado a Spotify.'}, status=404)
        try:
            profile = spotify_get(request.user, '/me')
            return Response(profile)
        except Exception as e:
            logger.exception("Error en SpotifyProfile")
            return Response({'error': str(e)}, status=500)


class SpotifyDisconnectView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        user = request.user
        user.spotify_access_token = None
        user.spotify_refresh_token = None
        user.spotify_token_expires = None
        user.save(update_fields=[
            'spotify_access_token',
            'spotify_refresh_token',
            'spotify_token_expires',
        ])
        return Response({'message': 'Spotify desconectado.'})


class SpotifyPlaylistsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.spotify_access_token:
            return Response({'error': 'No conectado a Spotify.'}, status=403)
        try:
            data = spotify_get(request.user, '/me/playlists?limit=20')
            playlists = [{
                'id':           p['id'],
                'name':         p['name'],
                'tracks_total': p['tracks']['total'],
                'image':        p['images'][0]['url'] if p.get('images') else None,
                'external_url': p['external_urls'].get('spotify'),
            } for p in data.get('items', [])]
            return Response({'playlists': playlists})
        except Exception as e:
            return Response({'error': str(e)}, status=500)


class SaveToSpotifyView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        spotify_track_id = request.data.get('spotify_track_id')
        playlist_id = request.data.get('playlist_id')

        if not spotify_track_id:
            return Response({'error': 'spotify_track_id es requerido.'}, status=400)
        if not request.user.spotify_access_token:
            return Response({
                'error': 'No conectado a Spotify.',
                'code':  'not_connected'
            }, status=403)

        try:
            if not playlist_id:
                playlist_id = self._get_or_create_echoprint_playlist(
                    request.user)
            track_uri = f"spotify:track:{spotify_track_id}"
            spotify_post(
                request.user,
                f'/playlists/{playlist_id}/tracks',
                {'uris': [track_uri]}
            )
            return Response({
                'message':     'Canción guardada en Spotify.',
                'playlist_id': playlist_id
            })
        except Exception as e:
            logger.exception("Error guardando en Spotify")
            return Response({'error': str(e)}, status=500)

    def _get_or_create_echoprint_playlist(self, user) -> str:
        existing = SpotifyPlaylist.objects.filter(
            user=user, is_echoprint_playlist=True
        ).first()
        if existing:
            return existing.spotify_playlist_id

        profile = spotify_get(user, '/me')
        spotify_user_id = profile['id']
        data = spotify_post(
            user,
            f'/users/{spotify_user_id}/playlists',
            {
                'name':        'Echoprint - Mis Canciones',
                'description': 'Canciones identificadas con Echoprint Music',
                'public':      False,
            },
        )
        SpotifyPlaylist.objects.create(
            user=user,
            spotify_playlist_id=data['id'],
            name=data['name'],
            is_echoprint_playlist=True,
        )
        return data['id']


class SpotifySearchView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if not query:
            return Response({'error': 'Parámetro q es requerido.'}, status=400)
        try:
            limit = max(1, min(int(request.query_params.get('limit', 20)), 50))
            results = search_track_with_genres(query, limit=limit)
            serializer = SpotifyTrackSerializer(results, many=True)
            return Response({'results': serializer.data})
        except ValueError as e:
            logger.error("SpotifySearch config error: %s", e)
            return Response({'error': str(e)}, status=503)
        except Exception as e:
            logger.exception("SpotifySearch error")
            return Response({'error': f'Error al buscar en Spotify: {str(e)}'}, status=500)


class SpotifyRecentlyPlayedView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.spotify_access_token:
            return Response({'error': 'No conectado a Spotify.'}, status=403)
        try:
            limit = int(request.query_params.get('limit', 20))
            data = spotify_get(
                request.user,
                f'/me/player/recently-played?limit={min(limit, 50)}'
            )
            tracks = []
            for item in data.get('items', []):
                track = item.get('track')
                if track:
                    formatted = _format_track(track)
                    formatted['played_at'] = item.get('played_at')
                    tracks.append(formatted)
            serializer = SpotifyTrackSerializer(tracks, many=True)
            return Response({'results': serializer.data})
        except Exception as e:
            logger.exception("SpotifyRecentlyPlayed error")
            return Response({'error': str(e)}, status=500)
