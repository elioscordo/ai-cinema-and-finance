from rest_framework import serializers
from audiomixer.models import Tutorial, Audio, \
    AudioAnalysis, Speaker, Language, Playlist


class SpeakerSerializer(serializers.ModelSerializer):
    class Meta:
        model = Speaker
        fields = ['name', 'code']


class AudioAnalysysSerializer(serializers.ModelSerializer):
    class Meta:
        model = AudioAnalysis
        fields = ['data']


class AudioSerializer(serializers.ModelSerializer):
    analysis = AudioAnalysysSerializer(read_only=True)
    speaker = SpeakerSerializer(read_only=True)

    class Meta:
        model = Audio
        fields = ['url', 'analysis', 'speaker']


class TutorialSerializer(serializers.ModelSerializer):
    audios = AudioSerializer(read_only=True, many=True)

    class Meta:
        model = Tutorial
        fields = ['id', 'name', 'audios', 'language']


class PlaylistSerializer(serializers.ModelSerializer):
    class Meta:
        model = Playlist
        fields = ['id', 'name']


class LanguageSerializer(serializers.ModelSerializer):
    class Meta:
        model = Language
        fields = '__all__'
