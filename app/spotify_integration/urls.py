
from django.urls import path
from .views import (
    SpotifyAuthURLView,
    SpotifyCallbackView,
    SpotifyProfileView,
    SpotifyDisconnectView,
    SpotifyPlaylistsView,
    SaveToSpotifyView,
    SpotifySearchView,
    SpotifyRecentlyPlayedView,
)

urlpatterns = [
    path('auth/',             SpotifyAuthURLView.as_view(),      name='spotify-auth'),
    path('callback/',         SpotifyCallbackView.as_view(),
         name='spotify-callback'),
    path('profile/',          SpotifyProfileView.as_view(),
         name='spotify-profile'),
    path('disconnect/',       SpotifyDisconnectView.as_view(),
         name='spotify-disconnect'),
    path('playlists/',        SpotifyPlaylistsView.as_view(),
         name='spotify-playlists'),
    path('save/',             SaveToSpotifyView.as_view(),       name='spotify-save'),
    path('search/',           SpotifySearchView.as_view(),
         name='spotify-search'),
    path('recently-played/',  SpotifyRecentlyPlayedView.as_view(),
         name='spotify-recently-played'),
]
