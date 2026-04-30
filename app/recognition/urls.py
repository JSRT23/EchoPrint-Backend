from django.urls import path
from .views import RecognizeAudioView, RecognizeHummingView

urlpatterns = [
    path('',         RecognizeAudioView.as_view(),   name='recognize'),
    path('humming/', RecognizeHummingView.as_view(),  name='recognize-humming'),
]
