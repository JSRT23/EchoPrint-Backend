from django.urls import path
from .views import (
    SongListView, SongDetailView, SongSearchView,
    UserHistoryView, UserHistoryAddView, UserHistoryDeleteView,
    UserStatsView, ItunesProxyView
)

urlpatterns = [
    path('',          SongListView.as_view(),         name='song-list'),
    path('<int:pk>/', SongDetailView.as_view(),        name='song-detail'),
    path('search/',   SongSearchView.as_view(),        name='song-search'),
    path('history/',           UserHistoryView.as_view(),       name='user-history'),
    path('history/add/',       UserHistoryAddView.as_view(),
         name='user-history-add'),
    path('history/<int:pk>/delete/', UserHistoryDeleteView.as_view(),
         name='user-history-delete'),
    path('stats/',    UserStatsView.as_view(),         name='user-stats'),
    path('itunes/',   ItunesProxyView.as_view(),       name='itunes-proxy'),
]
