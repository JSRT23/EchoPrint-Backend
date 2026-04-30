from rest_framework import serializers
from .models import Artist, Album, Song, Fingerprint, UserHistory


class ArtistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Artist
        fields = '__all__'


class AlbumSerializer(serializers.ModelSerializer):
    artist = ArtistSerializer(read_only=True)
    artist_id = serializers.PrimaryKeyRelatedField(
        queryset=Artist.objects.all(), source='artist', write_only=True
    )

    class Meta:
        model = Album
        fields = ['id', 'title', 'artist', 'artist_id',
                  'release_year', 'cover_url', 'spotify_id']


class SongSerializer(serializers.ModelSerializer):
    artist = ArtistSerializer(read_only=True)
    album = AlbumSerializer(read_only=True)

    class Meta:
        model = Song
        fields = [
            'id', 'title', 'artist', 'album', 'genre',
            'duration_seconds', 'lyrics', 'cover_url',
            'spotify_id', 'spotify_preview_url', 'created_at'
        ]


class SongSearchSerializer(serializers.ModelSerializer):
    artist_name = serializers.CharField(source='artist.name', read_only=True)
    album_title = serializers.CharField(source='album.title', read_only=True)

    class Meta:
        model = Song
        fields = ['id', 'title', 'artist_name', 'album_title',
                  'cover_url', 'spotify_preview_url', 'genre']


class UserHistorySerializer(serializers.ModelSerializer):
    song = SongSearchSerializer(read_only=True)

    class Meta:
        model = UserHistory
        fields = ['id', 'song', 'method',
                  'match_timestamp_seconds', 'identified_at']
