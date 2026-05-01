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
    spotify_get, spotify_post, spotify_put,
    search_track_with_genres, _format_track,
    SpotifyInsufficientScopeError,
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
            return Response({'error': 'No conectado a Spotify.', 'code': 'not_connected'}, status=403)
        try:
            profile = spotify_get(request.user, '/me')
            spotify_user_id = profile.get('id', '')

            data = spotify_get(request.user, '/me/playlists?limit=50')
            playlists = []
            for p in data.get('items', []):
                if not p or not p.get('id'):
                    continue
                owner_id = p.get('owner', {}).get('id', '')
                collaborative = p.get('collaborative', False)
                if owner_id != spotify_user_id and not collaborative:
                    continue
                playlists.append({
                    'id':           p['id'],
                    'name':         p['name'],
                    'tracks_total': p.get('tracks', {}).get('total', 0),
                    'image':        p['images'][0]['url'] if p.get('images') else None,
                    'external_url': p.get('external_urls', {}).get('spotify'),
                })
            return Response({'playlists': playlists})
        except Exception as e:
            err_str = str(e)
            logger.exception(
                "SpotifyPlaylistsView error para user_id=%s", request.user.id)
            # Token expirado o inválido → limpiar y pedir reconexión
            if '401' in err_str or 'Unauthorized' in err_str.lower():
                request.user.spotify_access_token = None
                request.user.spotify_refresh_token = None
                request.user.spotify_token_expires = None
                request.user.save(update_fields=[
                    'spotify_access_token',
                    'spotify_refresh_token',
                    'spotify_token_expires',
                ])
                return Response({'error': 'Token expirado. Reconecta tu cuenta de Spotify.', 'code': 'not_connected'}, status=403)
            return Response({'error': err_str}, status=500)


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

        track_uri = f"spotify:track:{spotify_track_id}"

        # Intentar guardar en playlist
        try:
            if not playlist_id:
                playlist_id = self._get_or_create_echoprint_playlist(
                    request.user)

            spotify_post(
                request.user,
                f'/playlists/{playlist_id}/tracks',
                {'uris': [track_uri]}
            )
            return Response({
                'message':     'Canción guardada en Spotify.',
                'playlist_id': playlist_id,
                'saved_as':    'playlist',
            })

        except SpotifyInsufficientScopeError:
            # La app está en modo Development — Spotify bloquea escritura en playlists.
            # Fallback: guardar en "Liked Songs" (PUT /me/tracks) que sí funciona en dev.
            logger.warning(
                "Playlist bloqueada (403 dev mode) para user_id=%s — fallback a Liked Songs",
                request.user.id
            )
            try:
                spotify_put(
                    request.user,
                    '/me/tracks',
                    {'ids': [spotify_track_id]}
                )
                return Response({
                    'message':  'Canción guardada en tus "Me gusta" de Spotify '
                                '(la app está en modo desarrollo; para guardar en playlists '
                                'activa el Extended Quota Mode en el Spotify Dashboard).',
                    'saved_as': 'liked_songs',
                })
            except SpotifyInsufficientScopeError:
                return Response({
                    'error': 'Tu sesión de Spotify no tiene permisos. '
                             'Desconecta y vuelve a conectar tu cuenta.',
                    'code': 'insufficient_scope'
                }, status=403)
            except Exception as e2:
                logger.exception("Error en fallback Liked Songs")
                return Response({'error': str(e2)}, status=500)

        except Exception as e:
            err_str = str(e)
            logger.exception("Error guardando en Spotify")
            if '401' in err_str:
                return Response({
                    'error': 'Token de Spotify expirado. Reconecta tu cuenta.',
                    'code': 'not_connected'
                }, status=403)
            return Response({'error': err_str}, status=500)

    def _get_or_create_echoprint_playlist(self, user) -> str:
        existing = SpotifyPlaylist.objects.filter(
            user=user, is_echoprint_playlist=True
        ).first()
        if existing:
            # Verify the playlist still exists on Spotify side
            try:
                spotify_get(
                    user, f'/playlists/{existing.spotify_playlist_id}?fields=id')
                return existing.spotify_playlist_id
            except Exception:
                # Playlist was deleted on Spotify, recreate it
                existing.delete()

        # Use /me/playlists instead of /users/{id}/playlists to avoid 403
        # on Spotify developer accounts that haven't requested extended quota
        data = spotify_post(
            user,
            '/me/playlists',
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


class LikeTrackView(APIView):
    """Añade una canción a los 'Me gusta' del usuario en Spotify."""
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        spotify_track_id = request.data.get('spotify_track_id')
        if not spotify_track_id:
            return Response({'error': 'spotify_track_id es requerido.'}, status=400)
        if not request.user.spotify_access_token:
            return Response({'error': 'No conectado a Spotify.', 'code': 'not_connected'}, status=403)
        try:
            spotify_put(request.user, '/me/tracks',
                        {'ids': [spotify_track_id]})
            return Response({'message': 'Canción añadida a Me gusta.'})
        except SpotifyInsufficientScopeError:
            return Response({'error': 'Permisos insuficientes. Reconecta tu cuenta.', 'code': 'insufficient_scope'}, status=403)
        except Exception as e:
            err_str = str(e)
            logger.exception("Error en LikeTrackView")
            if '401' in err_str:
                return Response({'error': 'Token expirado. Reconecta tu cuenta.', 'code': 'not_connected'}, status=403)
            return Response({'error': err_str}, status=500)


class SpotifyDebugView(APIView):
    """
    Endpoint de diagnóstico — solo para desarrollo.
    GET /api/spotify/debug/         → info del token
    GET /api/spotify/debug/?test_playlist=<playlist_id> → prueba POST real a esa playlist
    """
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        if not request.user.spotify_access_token:
            return Response({'error': 'No conectado a Spotify.'}, status=404)
        try:
            from .spotify_client import get_valid_token
            import requests as req
            token = get_valid_token(request.user)

            # Info básica del usuario
            me_resp = req.get(
                'https://api.spotify.com/v1/me',
                headers={'Authorization': f'Bearer {token}'},
                timeout=10,
            )
            me = me_resp.json()
            all_headers = dict(me_resp.headers)

            tests = {}

            # Test 1: leer playlists propias
            pl_resp = req.get(
                'https://api.spotify.com/v1/me/playlists?limit=3',
                headers={'Authorization': f'Bearer {token}'},
                timeout=10,
            )
            tests['read_playlists_status'] = pl_resp.status_code
            playlists_sample = []
            if pl_resp.ok:
                for p in pl_resp.json().get('items', [])[:3]:
                    if p:
                        playlists_sample.append({
                            'id': p['id'],
                            'name': p['name'],
                            'owner': p.get('owner', {}).get('id'),
                        })
            tests['playlists_sample'] = playlists_sample

            # Test 2: crear playlist de prueba en /me/playlists
            create_resp = req.post(
                'https://api.spotify.com/v1/me/playlists',
                headers={
                    'Authorization': f'Bearer {token}',
                    'Content-Type': 'application/json',
                },
                json={'name': '__echoprint_test__', 'public': False},
                timeout=10,
            )
            tests['create_playlist_status'] = create_resp.status_code
            tests['create_playlist_body'] = create_resp.json()

            # Test 3: si se creó, intentar añadir un track (Bad Bunny - Dakiti)
            if create_resp.ok:
                new_pl_id = create_resp.json().get('id')
                add_resp = req.post(
                    f'https://api.spotify.com/v1/playlists/{new_pl_id}/tracks',
                    headers={
                        'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/json',
                    },
                    json={'uris': ['spotify:track:1yoMvmasuxZfqHEGZtrMb0']},
                    timeout=10,
                )
                tests['add_track_to_new_playlist_status'] = add_resp.status_code
                tests['add_track_to_new_playlist_body'] = add_resp.json()

                # Limpiar: borrar la playlist de prueba (unfollow = delete)
                req.delete(
                    f'https://api.spotify.com/v1/playlists/{new_pl_id}/followers',
                    headers={'Authorization': f'Bearer {token}'},
                    timeout=10,
                )

            # Test 4: si viene playlist_id en query, probar añadir track ahí
            test_pl = request.query_params.get('test_playlist')
            if test_pl:
                add2_resp = req.post(
                    f'https://api.spotify.com/v1/playlists/{test_pl}/tracks',
                    headers={
                        'Authorization': f'Bearer {token}',
                        'Content-Type': 'application/json',
                    },
                    json={'uris': ['spotify:track:1yoMvmasuxZfqHEGZtrMb0']},
                    timeout=10,
                )
                tests['add_track_to_existing_status'] = add2_resp.status_code
                tests['add_track_to_existing_body'] = add2_resp.json()

            return Response({
                'spotify_user_id': me.get('id'),
                'product': me.get('product'),
                'token_preview': token[:20] + '...',
                'token_expires': str(request.user.spotify_token_expires),
                'spotify_response_headers': {
                    k: v for k, v in all_headers.items()
                    if k.lower().startswith('x-') or k.lower() == 'content-type'
                },
                'tests': tests,
            })
        except Exception as e:
            logger.exception("SpotifyDebugView error")
            return Response({'error': str(e)}, status=500)


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
