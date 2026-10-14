"""测试用 settings:继承项目 settings,只把 DB 换成 SQLite in-memory,跑端到端验证。"""
import os

# 强制设置一个有效 Fernet key,避开 dev 兜底
os.environ.setdefault('INSPECTOR_FIELD_ENCRYPTION_KEY', 'vzCXHpYGV4qtWyEcekdVdZX6u2Vff-r5EfrRyS7kkr0=')

from ServiceHealthInspection.settings import *  # noqa: F401,F403

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': ':memory:',
    },
}
# 让 Celery 在 in-memory 模式下能直接同步执行,不用真起 worker
CELERY_TASK_ALWAYS_EAGER = True
CELERY_BROKER_URL = 'memory://'
CELERY_RESULT_BACKEND = 'cache+memory://'
# 测试环境没有 Redis,缓存用进程内 locmem
CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.locmem.LocMemCache',
        'LOCATION': 'shi-test-cache',
    },
}
