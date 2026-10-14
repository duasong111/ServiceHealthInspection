"""
Account/signals.py

post_save(User) → 自动签发 Token,免去手动跑 drf_create_token 的麻烦。
"""
from django.contrib.auth import get_user_model
from django.db.models.signals import post_save
from django.dispatch import receiver
from rest_framework.authtoken.models import Token


@receiver(post_save, sender=get_user_model())
def create_auth_token(sender, instance, created, **kwargs):
    if created:
        Token.objects.create(user=instance)
