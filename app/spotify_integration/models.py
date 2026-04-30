from django.db import models
from app.users.models import CustomUser


class SpotifyPlaylist(models.Model):
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='spotify_playlists')
    spotify_playlist_id = models.CharField(max_length=100)
    name = models.CharField(max_length=255)
    is_echoprint_playlist = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} — {self.user.email}"
