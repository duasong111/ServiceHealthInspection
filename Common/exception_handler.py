"""
Common/exception_handler.py

把 DRF 的内置异常(NotAuthenticated / PermissionDenied / ValidationError /
NotFound / MethodNotAllowed / Throttled 等)统一包成我们的
{code, message, data} 格式,HTTP 状态码保持原义。

特殊处理:
  - ValidationError 里如果是 "已存在 / already exists" 类的,转 409(冲突)
  - 其它 ValidationError → 422(字段校验失败)

未捕获的异常(没被 DRF 处理的)返回 None,交给 Django 默认的 500 处理。
"""
import logging
import traceback

from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.views import exception_handler as drf_exception_handler

from Common.responses import (
    bad_request,
    conflict,
    forbidden,
    method_not_allowed,
    not_found,
    server_error,
    unauthorized,
    unprocessable_entity,
)


logger = logging.getLogger(__name__)


_UNIQUE_KEYWORDS = ('already exists', '已存在', 'must be unique', 'unique')


def _is_unique_error(detail) -> bool:
    """判断 ValidationError 的 detail 是否属于"唯一冲突"。"""
    candidates = []
    if isinstance(detail, dict):
        for v in detail.values():
            candidates.extend(v if isinstance(v, list) else [v])
    elif isinstance(detail, list):
        candidates = detail
    elif isinstance(detail, str):
        candidates = [detail]
    for item in candidates:
        s = str(item).lower()
        if any(kw in s for kw in _UNIQUE_KEYWORDS):
            return True
    return False


def _extract_message(exc) -> str:
    """从 DRF 异常中提取人话。"""
    detail = getattr(exc, 'detail', None)
    if detail is None:
        return str(exc)
    if isinstance(detail, str):
        return detail
    if isinstance(detail, list):
        return detail[0] if detail else '错误'
    if isinstance(detail, dict):
        first_key = next(iter(detail))
        first_val = detail[first_key]
        if isinstance(first_val, list) and first_val:
            return f'{first_key}: {first_val[0]}'
        return f'{first_key}: {first_val}'
    return str(detail)


def custom_exception_handler(exc, context):
    """DRF 异常 → 我们的统一响应格式。"""
    response = drf_exception_handler(exc, context)
    if response is None:
        # 真正未捕获的异常,记日志后用 500 包一下
        logger.error('Unhandled exception in %s: %s',
                     context.get('view'), traceback.format_exc())
        return server_error(message='服务器内部错误')

    status_code = response.status_code
    message = _extract_message(exc)
    data = response.data if isinstance(response.data, dict) else None

    # 1) 鉴权类
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        return unauthorized(message=message, data=data)
    if isinstance(exc, PermissionDenied):
        return forbidden(message=message, data=data)
    if isinstance(exc, NotFound):
        return not_found(message=message, data=data)

    # 2) 字段校验 → 区分 409 / 422
    if isinstance(exc, ValidationError):
        if _is_unique_error(response.data):
            # 唯一约束冲突 → 409
            return conflict(message=message, data=data)
        # 其它字段校验失败 → 422
        errors = response.data if isinstance(response.data, (dict, list)) else None
        return unprocessable_entity(message=message, errors=errors)

    if isinstance(exc, Throttled):
        return bad_request(message=message or '请求过于频繁', data=data)

    # 3) 其它 DRF 异常,按状态码路由
    if isinstance(exc, APIException):
        if status_code == 405:
            return method_not_allowed(message=message, data=data)
        if status_code == 400:
            return bad_request(message=message, data=data)
        if status_code == 401:
            return unauthorized(message=message, data=data)
        if status_code == 403:
            return forbidden(message=message, data=data)
        if status_code == 404:
            return not_found(message=message, data=data)
        if status_code == 409:
            return conflict(message=message, data=data)
        if status_code >= 500:
            return server_error(message=message, data=data)
        return fail_fallback(message=message, status_code=status_code, data=data)

    # 4) 兜底
    return fail_fallback(message=message, status_code=status_code, data=data)


def fail_fallback(message: str, status_code: int, data):
    """兜底:按状态码选包装。"""
    from Common.responses import fail
    return fail(message=message, http_status=status_code, data=data)
