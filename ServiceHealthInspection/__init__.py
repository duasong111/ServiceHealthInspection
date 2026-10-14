"""
ServiceHealthInspection 项目根包。

启动时让 Celery app 自动被 import,确保:
  - Django 启动过程中 @shared_task 装饰器能正常注册到 app
  - worker / beat 进程能直接拿到 app 实例
"""
from .celery import app as celery_app

__all__ = ('celery_app',)
