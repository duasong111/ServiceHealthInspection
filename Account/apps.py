"""
Account/apps.py
"""
from django.apps import AppConfig


class AccountConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Account'
    verbose_name = '账户管理'   # simpleui 侧边栏显示名

    def ready(self):
        # simpleui 2026.1 + Django 6.1 兼容性补丁:让 LazyEncoder 处理 enum
        # 必须在 INSTALLED_APPS 的第一个应用的 ready() 里跑(账号在前面)
        import Common.simpleui_patch  # noqa: F401

        # 注册信号:用户创建时自动签发 Token
        from . import signals  # noqa: F401
