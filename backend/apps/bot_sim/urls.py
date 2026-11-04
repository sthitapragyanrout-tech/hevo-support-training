from django.urls import path

from . import views

app_name = "sim_api"

urlpatterns = [
    path("activities/<int:pk>/sessions/", views.StartView.as_view(), name="start"),
    path("activities/<int:pk>/preview/", views.PreviewView.as_view(), name="preview"),
    path("scenario-count/", views.ScenarioCountView.as_view(), name="scenario-count"),
    path("sessions/<int:pk>/", views.SessionView.as_view(), name="session"),
    path("sessions/<int:pk>/messages/", views.MessageView.as_view(), name="message"),
    path("sessions/<int:pk>/retry/", views.RetryView.as_view(), name="retry"),
    path("sessions/<int:pk>/skip/", views.SkipView.as_view(), name="skip"),
    path("sessions/<int:pk>/finish/", views.FinishView.as_view(), name="finish"),
    path("sessions/<int:pk>/result/", views.ResultView.as_view(), name="result"),
]
