"""
ServiceHealthInspection/celery.py

Celery 应用入口。标准三件套:
  1) 从 django settings 读所有 CELERY_* 配置
  2) autodiscover_tasks() 自动发现各 app 的 tasks.py
  3) 在 ServiceHealthInspection/__init__.py 里 expose 出去

启动方式(项目根目录):
    celery -A ServiceHealthInspection worker --loglevel=info
    celery -A ServiceHealthInspection beat   --loglevel=info
本地一键启动见 run_celery.py。
"""
import os

from celery import Celery

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ServiceHealthInspection.settings')

app = Celery('ServiceHealthInspection')

# 使用 namespace='CELERY',settings 里所有 CELERY_* 自动注入
app.config_from_object('django.conf:settings', namespace='CELERY')

# 自动从 INSTALLED_APPS 各 app 的 tasks.py 中加载 task
app.autodiscover_tasks()


@app.task(bind=True, name='ServiceHealthInspection.celery.debug_ping')
def debug_ping(self):  # pragma: no cover
    """诊断用:启动 worker 后可以调用一次看链路是否通。"""
    return {'request': str(self.request), 'app': 'ok'}
