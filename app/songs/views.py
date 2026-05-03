from rest_framework import generics, permissions, filters
from rest_framework.response import Response
from rest_framework.views import APIView
from django.db.models import Q, Count
from django.shortcuts import get_object_or_404
from .models import Song, Artist, Album, UserHistory
from .serializers import (
    SongSerializer, SongSearchSerializer,
    ArtistSerializer, AlbumSerializer, UserHistorySerializer
)
from app.spotify_integration.spotify_client import enrich_song_from_spotify


class SongListView(generics.ListAPIView):
    queryset = Song.objects.select_related('artist', 'album').all()
    serializer_class = SongSerializer
    permission_classes = [permissions.AllowAny]


class SongDetailView(generics.RetrieveAPIView):
    queryset = Song.objects.select_related('artist', 'album').all()
    serializer_class = SongSerializer
    permission_classes = [permissions.AllowAny]


class SongSearchView(APIView):
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        query = request.query_params.get('q', '').strip()
        if not query:
            return Response({'error': 'Parámetro q es requerido.'}, status=400)

        songs = Song.objects.filter(
            Q(title__icontains=query) |
            Q(artist__name__icontains=query) |
            Q(lyrics__icontains=query)
        ).select_related('artist', 'album')[:20]

        serializer = SongSearchSerializer(songs, many=True)
        return Response({
            'query': query,
            'count': len(serializer.data),
            'results': serializer.data
        })


class UserHistoryView(generics.ListAPIView):
    serializer_class = UserHistorySerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return UserHistory.objects.filter(
            user=self.request.user
        ).select_related('song', 'song__artist', 'song__album')


class UserHistoryAddView(APIView):
    """
    Agrega una canción al historial manualmente.
    Usado cuando el usuario reproduce desde búsqueda de texto (Spotify).
    """
    permission_classes = [permissions.IsAuthenticated]

    def post(self, request):
        # Datos que vienen del frontend (canción de Spotify)
        spotify_id = request.data.get('spotify_id', '')
        title = request.data.get('title', '').strip()
        artist_name = request.data.get('artist', '').strip()
        album_name = request.data.get('album', '').strip()
        cover_url = request.data.get('cover_url', '')
        preview_url = request.data.get('preview_url', '')
        genre = request.data.get('genre', '')

        if not title or not artist_name:
            return Response({'error': 'title y artist son requeridos.'}, status=400)

        # Buscar o crear artista
        artist, _ = Artist.objects.get_or_create(
            name__iexact=artist_name,
            defaults={'name': artist_name, 'spotify_id': ''}
        )

        # Buscar o crear álbum
        album = None
        if album_name:
            album, _ = Album.objects.get_or_create(
                title__iexact=album_name,
                artist=artist,
                defaults={'title': album_name, 'cover_url': cover_url or None}
            )

        # Buscar o crear canción
        song, created = Song.objects.get_or_create(
            spotify_id=spotify_id,
            defaults={
                'title':               title,
                'artist':              artist,
                'album':               album,
                'genre':               genre,
                'cover_url':           cover_url or None,
                'spotify_preview_url': preview_url or '',
            }
        )
        # Si ya existía, actualizar cover/preview si faltaban
        if not created:
            updated = False
            if not song.cover_url and cover_url:
                song.cover_url = cover_url
                updated = True
            if not song.spotify_preview_url and preview_url:
                song.spotify_preview_url = preview_url
                updated = True
            if updated:
                song.save()

        # Registrar en historial
        history_entry = UserHistory.objects.create(
            user=request.user,
            song=song,
            method='text',
            match_timestamp_seconds=None,
        )

        return Response({
            'message': 'Canción agregada al historial.',
            'history_id': history_entry.id,
            'song': SongSerializer(song).data,
        }, status=201)


class UserHistoryDeleteView(APIView):
    """
    Elimina una entrada del historial del usuario autenticado.
    """
    permission_classes = [permissions.IsAuthenticated]

    def delete(self, request, pk):
        entry = get_object_or_404(UserHistory, pk=pk, user=request.user)
        entry.delete()
        return Response({'message': 'Entrada eliminada del historial.'}, status=200)


class UserStatsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    def get(self, request):
        history = UserHistory.objects.filter(user=request.user)

        top_genres = (
            history.values('song__genre')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        top_artists = (
            history.values('song__artist__name')
            .annotate(count=Count('id'))
            .order_by('-count')[:5]
        )
        by_method = (
            history.values('method')
            .annotate(count=Count('id'))
        )

        return Response({
            'total_identified': history.count(),
            'top_genres':       list(top_genres),
            'top_artists':      list(top_artists),
            'by_method':        list(by_method),
        })


class ItunesProxyView(APIView):
    """Proxy server-side para la API de iTunes, evitando el redirect musics:// en browsers."""
    permission_classes = [permissions.AllowAny]

    def get(self, request):
        term = request.query_params.get('term', '').strip()
        if not term:
            return Response({'error': 'term requerido'}, status=400)
        try:
            import urllib.request
            import urllib.parse
            import json as _json
            q = urllib.parse.urlencode({
                'term':   term,
                'media':  'music',
                'entity': 'song',
                'limit':  '10',
            })
            url = f'https://itunes.apple.com/search?{q}'
            req = urllib.request.Request(url, headers={
                'User-Agent': 'Mozilla/5.0 (compatible; Echoprint/1.0)',
                'Accept':     'application/json',
            })
            with urllib.request.urlopen(req, timeout=8) as resp:
                data = _json.loads(resp.read().decode('utf-8'))
            return Response(data)
        except Exception as e:
            return Response({'error': str(e), 'results': []}, status=502)
