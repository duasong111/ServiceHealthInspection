"""
Inspector/signals.py

任一业务表变更 → 清掉所有 view 缓存。

简化策略:不清单条 key,直接 prefix 全清。
理由:
  1. cache key 散在 view 命名空间下,跨表关联(MonitoredService 改了,
     它的 stats 也失效),精准失效要列全链路,易漏;
  2. 本系统变更量级低,全清的代价 < 精准失效的维护成本;
  3. 想升级时把 Common.cache.invalidate_view_cache 换成细粒度版本即可。

disable_invalidation():
    批量清理/数据迁移时用,临时断开所有 _invalidate 信号,避免上百万次
    cache.delete_pattern 把 Redis 搞挂。退出 with 块时 finally 兜底重连。
    嵌套也安全(每次都 disconnect,reverse connect)。
"""
from contextlib import contextmanager

from django.core.cache import cache
from django.db.models.signals import post_delete, post_save

from .models import DailyServiceStat, Environment, MonitoredService, ProbeLog, Team


def _invalidate(**kwargs):
    """清 view 缓存,失败仅 warning,不要把业务写操作搞挂。"""
    from Common.cache import invalidate_view_cache
    try:
        n = invalidate_view_cache()
    except Exception as exc:  # noqa: BLE001
        cache.logger.warning('invalidate_view_cache failed: %s', exc) if hasattr(cache, 'logger') else None
        return
    # 用标准 logger 记一笔,方便排障
    import logging
    logging.getLogger('Inspector.cache').info('invalidate_view_cache after %s: %s', kwargs.get('sender'), n)


# 任意业务表写 / 删都失效 — 把所有 (signal, model, receiver) 三元组存一份,
# 后面 disable_invalidation() 用它做 disconnect / reconnect。
_BUSINESS_MODELS = (Team, Environment, MonitoredService, ProbeLog, DailyServiceStat)
_SIGNAL_HOOKS = (
    [(post_save, m, _invalidate) for m in _BUSINESS_MODELS]
    + [(post_delete, m, _invalidate) for m in _BUSINESS_MODELS]
)
for sig, model, recv in _SIGNAL_HOOKS:
    sig.connect(recv, sender=model)


@contextmanager
def disable_invalidation():
    """批量操作时短暂断开所有 _invalidate 信号(防 cache.delete_pattern 风暴)。

    退出 with 块时按反序 reconnect,即使中途异常也保证重连。可嵌套。

    用法:
        from Inspector.signals import disable_invalidation
        with disable_invalidation():
            ProbeLog.objects.filter(...).delete()  # 不会触发 cache 失效
    """
    # 1) 全部 disconnect
    for sig, model, recv in _SIGNAL_HOOKS:
        sig.disconnect(recv, sender=model)
    try:
        yield
    finally:
        # 2) 反序 reconnect(嵌套场景下保证 disconnect 几次就 reconnect 几次)
        for sig, model, recv in reversed(_SIGNAL_HOOKS):
            sig.connect(recv, sender=model)

