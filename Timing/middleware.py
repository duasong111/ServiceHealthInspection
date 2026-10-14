"""
Timing/middleware.py

需求 ⑤:每个 HTTP 请求的耗时统计 + 顺带做 request_id 透传。

行为:
  1. 跳过 settings.TIMING_EXCLUDE_PREFIXES 命中的路径(默认 /static/、/media/、/favicon.ico、/healthz);
  2. 读取或生成 X-Request-ID(透传客户端传入的,否则 UUID4);
  3. 写入 contextvars.request_id_var,让 logger / filter 自动拿到;
  4. 调 self.get_response(),计算 elapsed_ms;
  5. 一定打 logger('django.time'),自动带 request_id;
  6. 一定落库(RequestTimingLog);
  7. 在 response 头里塞 X-Request-ID 与 X-Response-Time-ms,便于前端 / 排查。

设计要点:
  - 落库失败只 warning,不破坏响应(数据库抖一下不能把 API 拖死);
  - 落库方法 _persist 单独抽出来,子类要换写库策略(异步队列、批量、采样)直接覆盖;
  - 写库放在 get_response() 之后,所以测得的时间是"middleware 链 + 视图"的总耗时,
    接近客户端感知到的服务端时间;
  - request_id 透传:客户端传 X-Request-ID 进来,我们原样回传,便于跨服务链路追踪。
"""
import logging
import time
import uuid

from django.conf import settings

from Common.context import request_id_var


logger = logging.getLogger('django.time')

# 默认排除的路径前缀,生产可在 settings.TIMING_EXCLUDE_PREFIXES 覆盖
_DEFAULT_EXCLUDE_PREFIXES = (
    '/static/',
    '/media/',
    '/favicon.ico',
    '/healthz',
)


class RequestTimingMiddleware:
    """每个 HTTP 请求耗时落库 + 打 logger,顺带透传 request_id。"""

    def __init__(self, get_response):
        self.get_response = get_response
        self.exclude_prefixes = tuple(
            getattr(settings, 'TIMING_EXCLUDE_PREFIXES', _DEFAULT_EXCLUDE_PREFIXES)
        )

    def __call__(self, request):
        if self._should_skip(request.path):
            return self.get_response(request)

        # 1) request_id:透传 / 生成
        request_id = request.headers.get('X-Request-ID') or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        request.request_id = request_id  # 让 view 也能取

        start = time.monotonic()
        try:
            response = self.get_response(request)
            elapsed_ms = int((time.monotonic() - start) * 1000)

            path = request.get_full_path()[:512]
            logger.info(
                '%s %s -> %d, %dms',
                request.method, path, response.status_code, elapsed_ms,
            )
            self._persist(request, response, elapsed_ms)
        finally:
            request_id_var.reset(token)

        response['X-Response-Time-ms'] = str(elapsed_ms)
        response['X-Request-ID'] = request_id
        return response

    # ------------------------------------------------------------------ #
    # 内部方法:子类可覆盖
    # ------------------------------------------------------------------ #
    def _should_skip(self, path: str) -> bool:
        return any(path.startswith(p) for p in self.exclude_prefixes)

    def _persist(self, request, response, elapsed_ms: int) -> None:
        """落库。失败仅 warning,不破坏响应。"""
        # 延迟 import,避免 settings 启动期循环
        from .models import RequestTimingLog
        try:
            RequestTimingLog.objects.create(
                path=request.get_full_path()[:512],
                method=request.method[:16],
                status_code=response.status_code,
                elapsed_ms=elapsed_ms,
            )
        except Exception as exc:  # noqa: BLE001 — 任何 DB 错误都不应拖垮请求
            logger.warning('RequestTimingLog 落库失败: %s', exc)
