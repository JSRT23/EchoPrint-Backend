from rest_framework import serializers
from .models import SpotifyPlaylist


class SpotifyPlaylistSerializer(serializers.ModelSerializer):
    class Meta:
        model = SpotifyPlaylist
        fields = '__all__'
        read_only_fields = ['user', 'created_at']


class SpotifyTrackSerializer(serializers.Serializer):
    """
    Serializer para tracks de Spotify.
    Usamos CharField en lugar de URLField para los campos de URL opcionales
    porque DRF's URLField lanza ValidationError cuando el valor es None,
    incluso con allow_null=True en algunas versiones.
    Spotify eliminó preview_url de la mayoría de mercados desde 2023.
    """
    spotify_id = serializers.CharField()
    title = serializers.CharField()
    artist = serializers.CharField()
    album = serializers.CharField(default='')
    genre = serializers.CharField(default='', allow_blank=True)
    cover_url = serializers.CharField(
        allow_null=True, required=False, default=None)
    preview_url = serializers.CharField(
        allow_null=True, required=False, default=None)
    duration_ms = serializers.IntegerField(
        allow_null=True, required=False, default=None)
    external_url = serializers.CharField(
        allow_null=True, required=False, default=None)
