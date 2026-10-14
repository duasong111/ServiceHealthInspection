"""
Account/views.py

三个端点:
  POST /api/auth/login/    username + password -> token
  POST /api/auth/logout/   销毁当前 token
  GET  /api/auth/me/       当前用户信息
"""
from rest_framework import status
from rest_framework.authtoken.models import Token
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.views import APIView

from Common.responses import fail, ok

from .serializers import LoginSerializer


class LoginView(APIView):
    """POST /api/auth/login/

    不需要鉴权,也不需要 CSRF(配 authentication_classes=[] 跳过)。
    """
    authentication_classes: list = []
    permission_classes = [AllowAny]

    def post(self, request, *args, **kwargs):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.validated_data['user']
        token, _ = Token.objects.get_or_create(user=user)
        return ok({
            'token': token.key,
            'user_id': user.id,
            'username': user.username,
        }, message='登录成功')


class LogoutView(APIView):
    """POST /api/auth/logout/  销毁当前 token。"""
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        Token.objects.filter(user=request.user).delete()
        return ok(message='已登出')


class MeView(APIView):
    """GET /api/auth/me/  当前用户信息。"""
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        u = request.user
        return ok({
            'id': u.id,
            'username': u.username,
            'is_superuser': u.is_superuser,
        })
