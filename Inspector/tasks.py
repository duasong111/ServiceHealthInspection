"""
Inspector/tasks.py

Celery 周期任务,集中放这里:
- rotate_all_tokens                  需求 ③:每 8 小时重置所有 active 服务的 Token
- aggregate_daily_health_rate        需求 ④:每天 00:00 聚合昨日健康率
- probe_all_active_services          增强 ③:每 5 分钟 fan-out 派单
- probe_one_service_task             ↑ 每单 worker 真正去 HTTP GET 的执行体
- cleanup_old_probe_logs             每天 01:00 删 20 天前的明细
- run_ensure_probe_log_partitions    每月 1 号 00:30 滚动建分区

设计要点:
  - 全部用 @shared_task,settings CELERY_BEAT_SCHEDULE 里按名字调用;
  - 业务逻辑复用 services.py(与手动接口共用同一份代码);
  - 时区:计算"昨天"边界用 Asia/Shanghai,但 ORM 查询用 UTC(Django USE_TZ=True);
  - probe 用 fan-out:dispatcher 只 enqueue,真正的 HTTP 调用在 per-service task 里并行跑;
  - aggregate 不再包 transaction.atomic(),update_or_create 自身原子、单服务失败不影响其它;
  - cleanup 用 _raw_delete + disable_invalidation,避开 cache 失效风暴。
"""
import logging
from datetime import timedelta, timezone as dt_timezone
from zoneinfo import ZoneInfo

import requests
from celery import shared_task
from django.db.models import Count, Q
from django.utils import timezone

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------- #
# 需求 ③:每 8 小时重置所有 active 服务的 Token
# --------------------------------------------------------------------------- #
@shared_task(
    name='Inspector.tasks.rotate_all_tokens',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def rotate_all_tokens(self):
    """把 is_active=True 的服务逐个调 services.rotate_service_token()。"""
    from .models import MonitoredService
    from .services import rotate_service_token

    rotated = 0
    errors: list[dict] = []
    for service in MonitoredService.objects.filter(is_active=True).iterator():
        try:
            rotate_service_token(service)
            rotated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception('rotate_service_token 失败: service_id=%s', service.id)
            errors.append({'service_id': service.id, 'error': str(exc)})

    logger.info('rotate_all_tokens: 成功 %d,失败 %d', rotated, len(errors))
    return {'rotated': rotated, 'errors': errors}


# --------------------------------------------------------------------------- #
# 需求 ④:每天 00:00 聚合昨日健康率
# --------------------------------------------------------------------------- #
@shared_task(
    name='Inspector.tasks.aggregate_daily_health_rate',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
)
def aggregate_daily_health_rate(self):
    """聚合 [昨日 00:00, 今日 00:00) 上海时区窗口的探针日志,按服务写入日统计。

    关键变化:不再包 transaction.atomic()。
    原来一个事务跨所有服务,5000 服务级别会持有行锁几分钟,出任意一单
    失败全部回滚。现在 update_or_create 自身原子,单服务失败互不影响。
    """
    from .models import DailyServiceStat, MonitoredService, ProbeLog

    # 1) "昨天" 边界,先按上海时区切
    sh_tz = ZoneInfo('Asia/Shanghai')
    now_sh = timezone.now().astimezone(sh_tz)
    today_start_sh = now_sh.replace(hour=0, minute=0, second=0, microsecond=0)
    yesterday_start_sh = today_start_sh - timedelta(days=1)

    # 2) 转 UTC 用于 ORM 查询(USE_TZ=True,DB 存的是 UTC)
    yesterday_start_utc = yesterday_start_sh.astimezone(dt_timezone.utc)
    today_start_utc = today_start_sh.astimezone(dt_timezone.utc)
    stat_date = yesterday_start_sh.date()  # 上海时区的"昨天"日期

    services = (
        MonitoredService.objects
        .select_related('team', 'environment')
        .iterator(chunk_size=500)  # 不一次性 material 5000 个 service
    )
    updated = 0
    errors: list[dict] = []

    for service in services:
        try:
            agg = ProbeLog.objects.filter(
                service=service,
                checked_at__gte=yesterday_start_utc,
                checked_at__lt=today_start_utc,
            ).aggregate(
                total=Count('id'),
                success=Count('id', filter=Q(success=True)),
            )
            total = agg['total'] or 0
            success = agg['success'] or 0
            rate = (success / total) if total else 0

            # 环境/团队冗余存:service 改归属后历史快照仍然真实
            DailyServiceStat.objects.update_or_create(
                service=service,
                stat_date=stat_date,
                defaults={
                    'environment': service.environment,
                    'team': service.team,
                    'total_count': total,
                    'success_count': success,
                    'health_rate': rate,
                },
            )
            updated += 1
        except Exception as exc:  # noqa: BLE001
            logger.exception('aggregate 单服务失败: service_id=%s', service.id)
            errors.append({'service_id': service.id, 'error': str(exc)})

    logger.info(
        'aggregate_daily_health_rate: stat_date=%s 写入 %d 条,失败 %d',
        stat_date, updated, len(errors),
    )
    return {'stat_date': str(stat_date), 'updated': updated, 'errors': errors}


# --------------------------------------------------------------------------- #
# 增强 ③:每 5 分钟 fan-out 派单(只入队,不做实际 HTTP)
# --------------------------------------------------------------------------- #
@shared_task(
    name='Inspector.tasks.probe_all_active_services',
    bind=True,
    max_retries=1,
    default_retry_delay=30,
)
def probe_all_active_services(self):
    """把 is_active=True 的服务逐个入队 probe_one_service_task,本任务自身秒回。

    这样:
      - dispatcher 不会撞 4 min 的 soft time limit
      - 多个 worker 真正并行消费 N 个探测任务
      - 一个服务 5s 超时只堵一个 worker slot,不影响其它的
    """
    from .models import MonitoredService
    from .models import ProbeLog  # for SOURCE_CRON

    ids = list(
        MonitoredService.objects.filter(is_active=True).values_list('id', flat=True)
    )
    if not ids:
        logger.info('probe_all_active_services: 没有 active 服务,跳过')
        return {'enqueued': 0}

    for sid in ids:
        probe_one_service_task.delay(sid, ProbeLog.SOURCE_CRON)

    logger.info('probe_all_active_services: enqueued=%d', len(ids))
    return {'enqueued': len(ids)}


# --------------------------------------------------------------------------- #
# 真正的"一次探测"任务 — 在 worker 上跑
# --------------------------------------------------------------------------- #
@shared_task(
    name='Inspector.tasks.probe_one_service_task',
    bind=True,
    max_retries=2,
    default_retry_delay=10,
    soft_time_limit=15,
    time_limit=20,
)
def probe_one_service_task(self, service_id: int, source: str = 'cron'):
    """对单个 service_id 做一次健康探测。Celery 入参用 id(避免 ORM 实例序列化)。

    返回 dict 跟 services.probe_service 一致,只是来源字段由 source 决定。
    """
    from .services import probe_service
    try:
        return probe_service(service_id, source=source)
    except Exception as exc:  # noqa: BLE001
        logger.exception('probe_one_service_task 抛异常: service_id=%s err=%s', service_id, exc)
        return {
            'service_id': service_id,
            'success': False,
            'error': str(exc),
        }


# --------------------------------------------------------------------------- #
# 数据清理:每天 01:00 删 20 天前的 ProbeLog
# --------------------------------------------------------------------------- #
@shared_task(
    name='Inspector.tasks.cleanup_old_probe_logs',
    bind=True,
    max_retries=1,
    default_retry_delay=300,
    soft_time_limit=1800,    # 30 min
    time_limit=2400,         # 40 min
)
def cleanup_old_probe_logs(self, days: int = 20):
    """删 days 天前的 ProbeLog。

    关键设计:
      - 用 _raw_delete() 走底层 SQL,绕开 ORM 的逐行 delete + 信号回调
      - 包 disable_invalidation() 防止 60M 行删除触发 60M 次 cache 失效
      - 每批 10000 行,单事务短,不会长时间持锁
    """
    from .models import ProbeLog
    from .signals import disable_invalidation

    cutoff = timezone.now() - timedelta(days=days)
    deleted_total = 0
    with disable_invalidation():
        while True:
            ids = list(
                ProbeLog.objects
                .filter(checked_at__lt=cutoff)
                .values_list('id', flat=True)[:10000]
            )
            if not ids:
                break
            # _raw_delete 返回 (count, {field: count}) — 我们只关心 count
            count, _ = ProbeLog.objects.filter(id__in=ids)._raw_delete()
            deleted_total += count

    logger.info('cleanup_old_probe_logs: deleted=%d cutoff=%s', deleted_total, cutoff.isoformat())
    return {'deleted': deleted_total, 'cutoff': cutoff.isoformat()}


# --------------------------------------------------------------------------- #
# 每月 1 号 00:30 滚动建分区
# --------------------------------------------------------------------------- #
@shared_task(
    name='Inspector.tasks.run_ensure_probe_log_partitions',
    bind=True,
    max_retries=2,
    default_retry_delay=60,
    soft_time_limit=60,
    time_limit=120,
)
def run_ensure_probe_log_partitions(self):
    """每月定时跑,确保当月 + 之后 2 个月 + default 分区都存在。"""
    from .partitioning import ensure_partitions
    ensured = ensure_partitions(months_ahead=2, create_default=True)
    logger.info('run_ensure_probe_log_partitions: ensured=%s', ensured)
    return {'ensured': ensured}
