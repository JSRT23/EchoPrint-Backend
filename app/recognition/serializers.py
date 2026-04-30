from rest_framework import serializers
from app.songs.serializers import SongSerializer
from .models import RecognitionLog


class RecognitionResultSerializer(serializers.Serializer):
    status = serializers.CharField()
    score = serializers.FloatField()
    match_timestamp_seconds = serializers.FloatField(allow_null=True)
    song = SongSerializer(allow_null=True)
    message = serializers.CharField()


class RecognitionLogSerializer(serializers.ModelSerializer):
    song_matched = SongSerializer(read_only=True)

    class Meta:
        model = RecognitionLog
        fields = '__all__'
