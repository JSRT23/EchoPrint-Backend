from django.db import models
from app.songs.models import Song


class RecognitionLog(models.Model):
    STATUS_CHOICES = [
        ('success', 'Éxito'),
        ('no_match', 'Sin coincidencia'),
        ('error', 'Error'),
    ]

    song_matched = models.ForeignKey(
        Song, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='recognition_logs'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES)
    score = models.FloatField(default=0.0)
    match_timestamp_seconds = models.FloatField(null=True, blank=True)
    audio_duration = models.FloatField(null=True, blank=True)
    error_message = models.TextField(blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.status} — {self.song_matched} ({self.score})"
