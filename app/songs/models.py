from django.db import models
from app.users.models import CustomUser


class Artist(models.Model):
    name = models.CharField(max_length=255)
    bio = models.TextField(blank=True, null=True)
    image_url = models.URLField(blank=True, null=True)
    spotify_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return self.name


class Album(models.Model):
    title = models.CharField(max_length=255)
    artist = models.ForeignKey(
        Artist, on_delete=models.CASCADE, related_name='albums')
    release_year = models.IntegerField(blank=True, null=True)
    cover_url = models.URLField(blank=True, null=True)
    spotify_id = models.CharField(max_length=100, blank=True, null=True)

    def __str__(self):
        return f"{self.title} — {self.artist.name}"


class Song(models.Model):
    title = models.CharField(max_length=255)
    artist = models.ForeignKey(
        Artist, on_delete=models.CASCADE, related_name='songs')
    album = models.ForeignKey(
        Album, on_delete=models.SET_NULL, null=True, blank=True, related_name='songs')
    genre = models.CharField(max_length=100, blank=True, null=True)
    duration_seconds = models.IntegerField(blank=True, null=True)
    lyrics = models.TextField(blank=True, null=True)
    cover_url = models.URLField(blank=True, null=True)
    spotify_id = models.CharField(max_length=100, blank=True, null=True)
    spotify_preview_url = models.URLField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} — {self.artist.name}"


class Fingerprint(models.Model):
    song = models.OneToOneField(
        Song, on_delete=models.CASCADE, related_name='fingerprint')
    hash_data = models.TextField()  # JSON con los hashes del fingerprint
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Fingerprint de {self.song.title}"


class UserHistory(models.Model):
    METHOD_CHOICES = [
        ('audio',   'Audio'),
        ('text',    'Texto'),
        ('humming', 'Tarareo'),
    ]
    user = models.ForeignKey(
        CustomUser, on_delete=models.CASCADE, related_name='history')
    song = models.ForeignKey(
        Song, on_delete=models.CASCADE, related_name='history')
    method = models.CharField(
        max_length=10, choices=METHOD_CHOICES, default='audio')
    match_timestamp_seconds = models.FloatField(blank=True, null=True)
    identified_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-identified_at']

    def __str__(self):
        return f"{self.user.email} identificó {self.song.title}"
