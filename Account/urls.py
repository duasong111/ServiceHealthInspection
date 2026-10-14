"""
Account/urls.py

挂在 /api/auth/ 前缀下。
"""
from django.urls import path

from .views import LoginView, LogoutView, MeView

app_name = 'Account'

urlpatterns = [
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('me/', MeView.as_view(), name='me'),
]
