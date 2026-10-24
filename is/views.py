from rest_framework import viewsets, filters, generics

from django_filters.rest_framework import DjangoFilterBackend

from audiomixer.models import Tutorial, Language
from audiomixer.serializers import TutorialSerializer


class TutorialViewSet(viewsets.ModelViewSet):
    queryset = Tutorial.objects.all()
    serializer_class = TutorialSerializer
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend
    ]
    search_fields = ['title']
    filterset_fields = ['language']


class PagedTutorialViewSet(viewsets.ModelViewSet):
    queryset = Tutorial.objects.all()
    serializer_class = TutorialSerializer
    filter_backends = [
        filters.SearchFilter,
        DjangoFilterBackend
    ]
    search_fields = ['title']
    filterset_fields = ['language']


class LanguageViewSet(viewsets.ModelViewSet):
    queryset = Language.objects.all()
    serializer_class = TutorialSerializer


class PlaylistTutorialList(generics.ListAPIView):
    serializer_class = TutorialSerializer

    def get_queryset(self):
        playlist = self.kwargs['playlist']
        query = Tutorial.objects.filter(
            playlisttutorial__playlist=playlist
        )
        return query


class PlaylistView(generics.ListAPIView):
    serializer_class = TutorialSerializer

    def get_queryset(self):
        playlist = self.kwargs['playlist']
        query = Tutorial.objects.filter(
            playlisttutorial__playlist=playlist
        )
        return query
