"""
Common/cache.py

统一缓存封装。所有 GET 接口默认会被基类自动缓存,失效由 Inspector.signals
里 post_save / post_delete 自动清。

对外两个东西:
  1) CacheMixin       APIView mixin,装上 dispatch 自动读写缓存
  2) cached_view      函数式 / 单方法的装饰器版本

默认 60s TTL,子类覆盖:
    class MyView(CacheMixin, APIView):
        cache_timeout = 120          # 自定义 TTL
    class MyView(CacheMixin, APIView):
        cache_timeout = 0            # 禁用缓存

设计要点:
  - 只缓存 GET / HEAD;POST / PUT / PATCH / DELETE 全部直走;
  - cache key 由 method + full_path(含 query)+ 算 md5;
    不带 user_id,因为本项目所有 GET 数据对所有登录用户是共享的;
  - 缓存命中时额外加 X-Cache: HIT,未命中时 X-Cache: MISS,便于排查;
  - 缓存的 value 是 {'data': ..., 'status_code': ...} 二元组,
    反序列化时需要把 accepted_renderer / media_type / renderer_context
    都设上,否则 DRF Response.render() 会 assert 失败。
"""
import hashlib
import logging

from django.core.cache import cache
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response


logger = logging.getLogger(__name__)

# 缓存 key 前缀,失效时用 prefix 通配
VIEW_KEY_PREFIX = 'view:'

# 默认 TTL(秒)
DEFAULT_TIMEOUT = 60

# 缓存命中时给 Response 用的 renderer / context
_DEFAULT_RENDERER = JSONRenderer()
_DEFAULT_MEDIA_TYPE = 'application/json'


# --------------------------------------------------------------------------- #
# 工具方法
# --------------------------------------------------------------------------- #
def make_cache_key(request, *args, **kwargs) -> str:
    """根据 method + full_path 算 cache key。"""
    raw = f'{request.method}:{request.get_full_path()}'
    digest = hashlib.md5(raw.encode('utf-8')).hexdigest()
    return f'{VIEW_KEY_PREFIX}{digest}'


def invalidate_view_cache() -> int:
    """清掉所有 view:* 缓存,返回删除数量(粗略)。

    简化版:任意业务表变更 → 全清。比精确失效好维护,小项目足够。
    django-redis / django 内置 RedisCache 都支持 delete_pattern;
    locmem 不支持,fallback 到 clear()(把所有 key 全清)。
    """
    try:
        return cache.delete_pattern(f'{VIEW_KEY_PREFIX}*') or 0
    except AttributeError:
        cache.clear()
        return -1


def _restore_response(cached_data: dict, request=None) -> Response:
    """从 cache 反序列化的 dict 重建 DRF Response。

    必须把 accepted_renderer / accepted_media_type / renderer_context 都设上,
    否则 Response.render() 会 assert 失败。
    """
    resp = Response(cached_data['data'], status=cached_data['status_code'])
    # 尽量用 request 协商出来的 renderer,否则退到 JSONRenderer
    if request is not None and getattr(request, 'accepted_renderer', None) is not None:
        resp.accepted_renderer = request.accepted_renderer
        resp.accepted_media_type = getattr(request, 'accepted_media_type', _DEFAULT_MEDIA_TYPE)
    else:
        resp.accepted_renderer = _DEFAULT_RENDERER
        resp.accepted_media_type = _DEFAULT_MEDIA_TYPE
    resp.renderer_context = {'request': request} if request is not None else {}
    return resp


# --------------------------------------------------------------------------- #
# Mixin:装在 APIView 上自动缓存 GET
# --------------------------------------------------------------------------- #
class CacheMixin:
    """APIView mixin:对 GET / HEAD 自动读写缓存,带 X-Cache 头。

    装到 BaseListCreateAPIView / BaseDetailAPIView 上之后,所有继承的子类
    自动获得缓存行为,无需额外配置。
    """

    cache_timeout: int = DEFAULT_TIMEOUT

    def dispatch(self, request, *args, **kwargs):
        # 不缓存非 GET / HEAD,或显式禁用
        if not self.cache_timeout or request.method not in ('GET', 'HEAD'):
            return super().dispatch(request, *args, **kwargs)

        cache_key = make_cache_key(request, *args, **kwargs)
        cached_data = cache.get(cache_key)
        if cached_data is not None:
            resp = _restore_response(cached_data, request)
            resp['X-Cache'] = 'HIT'
            logger.debug('cache HIT %s', cache_key)
            return resp

        response = super().dispatch(request, *args, **kwargs)

        # 只缓存成功的响应(2xx)
        if 200 <= response.status_code < 300:
            cache.set(
                cache_key,
                {'data': response.data, 'status_code': response.status_code},
                self.cache_timeout,
            )
            response['X-Cache'] = 'MISS'
            logger.debug('cache MISS %s (cached %ss)', cache_key, self.cache_timeout)
        return response


# --------------------------------------------------------------------------- #
# 装饰器:对非继承基类的视图 / 独立方法用
# --------------------------------------------------------------------------- #
def cached_view(timeout: int = DEFAULT_TIMEOUT):
    """方法级缓存装饰器。

    用法:
        class MyView(APIView):
            @cached_view(timeout=120)
            def get(self, request):
                ...
    """
    def decorator(func):
        def wrapper(self, request, *args, **kwargs):
            if not timeout or request.method not in ('GET', 'HEAD'):
                return func(self, request, *args, **kwargs)

            cache_key = make_cache_key(request, *args, **kwargs)
            cached_data = cache.get(cache_key)
            if cached_data is not None:
                resp = _restore_response(cached_data, request)
                resp['X-Cache'] = 'HIT'
                return resp

            response = func(self, request, *args, **kwargs)
            if 200 <= response.status_code < 300:
                cache.set(
                    cache_key,
                    {'data': response.data, 'status_code': response.status_code},
                    timeout,
                )
                response['X-Cache'] = 'MISS'
            return response
        return wrapper
    return decorator
