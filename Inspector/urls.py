
# from django.contrib import admin
from django.urls import path

from django.urls import path, include
from .views import *
app_name = 'Inspector'

urlpatterns = [
    path('healthz/', HealthzView.as_view(), name='healthz'),
]
