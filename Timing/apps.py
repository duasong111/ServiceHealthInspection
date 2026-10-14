from django.apps import AppConfig


class TimingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Timing'
    verbose_name = '请求耗时'   # simpleui 侧边栏显示名
