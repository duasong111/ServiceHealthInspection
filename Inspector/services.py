"""
Inspector/services.py

把"业务动作"和"HTTP 视图"分开,view 只负责收参/返参,真正的事放这里。
- probe_service: 一次健康探测,被手动接口和 Celery 周期任务共用
- rotate_service_token: 重置一个服务的 Token
"""
import secrets
import time

import requests
from django.utils import timezone

from .models import MonitoredService, ProbeLog


def probe_service(service_or_id, source: str = ProbeLog.SOURCE_MANUAL) -> dict:
    """对单个服务发起健康探测,落库并返回结构化结果。

    Args:
        service_or_id:  MonitoredService 实例,或它的 pk(int) — 后者给 Celery 用
                        (Celery 任务传参建议用 id,不要序列化 ORM 实例)
        source:   触发来源,'manual' 或 'cron'

    Returns:
        dict,包含 service_id / url / status_code / success / elapsed_ms / error / checked_at
    """
    if isinstance(service_or_id, MonitoredService):
        service = service_or_id
    else:
        service = MonitoredService.objects.get(pk=service_or_id)

    url = service.base_url.rstrip('/') + service.health_path
    headers = {}
    if service.token:
        headers['Authorization'] = f'Bearer {service.token}'

    status_code = None
    success = False
    error = ''
    start = time.monotonic()
    try:
        resp = requests.get(url, headers=headers, timeout=5)
        status_code = resp.status_code
        success = (status_code == service.expected_status)
    except requests.RequestException as exc:
        error = str(exc)
    elapsed_ms = int((time.monotonic() - start) * 1000)

    log = ProbeLog.objects.create(
        service=service,
        checked_at=timezone.now(),
        status_code=status_code,
        success=success,
        elapsed_ms=elapsed_ms,
        error=error,
        source=source,
    )
    return {
        'service_id': service.id,
        'service_name': service.name,
        'url': url,
        'status_code': status_code,
        'expected_status': service.expected_status,
        'success': success,
        'elapsed_ms': elapsed_ms,
        'error': error,
        'checked_at': log.checked_at.isoformat(),
    }


def rotate_service_token(service: MonitoredService) -> str:
    """生成新 Token 并加密写回数据库,返回明文(调用方按需返回给前端)。"""
    new_token = secrets.token_urlsafe(32)
    service.token = new_token
    service.token_rotated_at = timezone.now()
    service.save(update_fields=['token', 'token_rotated_at'])
    return new_token
