"""
Account/admin.py

把 DRF Token 也注册到 admin,方便给某个用户签发 / 重置 / 吊销 token。
User 用 Django 自带的 UserAdmin,只是把 Token 嵌进详情页。
"""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth import get_user_model
from rest_framework.authtoken.models import Token

User = get_user_model()


# 把 Token 嵌到 User 详情页(可看、可手动重置)
class TokenInline(admin.StackedInline):
    model = Token
    can_delete = False
    extra = 0
    readonly_fields = ('key',)
    fields = ('key',)


# Django 在 django.contrib.auth.admin 里已经默认注册过 User,
# 这里要先把默认那个 unregister,再用我们扩展过的版本(带 Token 内联)覆盖。
admin.site.unregister(User)


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    inlines = [TokenInline]


# 单独把 Token 也注册出来(便于批量管理)
@admin.register(Token)
class TokenAdmin(admin.ModelAdmin):
    list_display = ('key', 'user', 'created')
    list_filter = ('user__is_staff', 'user__is_superuser')
    search_fields = ('user__username', 'key')
    readonly_fields = ('key', 'user', 'created')
    list_per_page = 50

