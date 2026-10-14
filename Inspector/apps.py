from django.apps import AppConfig


class InspectorConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'Inspector'
    verbose_name = '巡检服务'   # simpleui 侧边栏显示名

    def ready(self):
        # 注册信号:post_save / post_delete 触发缓存失效
        from . import signals  # noqa: F401
