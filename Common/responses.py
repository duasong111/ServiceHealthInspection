"""
Common/responses.py

统一响应封装 + HTTP 状态码使用规范。

约定响应格式:
成功: {"code": 0, "message": "success", "data": <payload>}
失败: {"code": 非0, "message": "<错误描述>", "data": <可选>}

================================================================================
HTTP 状态码使用规范(全项目统一)
================================================================================
  200 OK            GET 成功;PUT/PATCH 成功;登录成功
  201 Created       POST 创建新资源(返回新对象)
  202 Accepted      异步操作触发(rotate-token、批量)
  204 No Content    DELETE 成功(无 body)
  400 Bad Request   JSON 解析失败、缺参数
  401 Unauthorized  没 token / token 错 / 已失效
  403 Forbidden     已登录但没权限
  404 Not Found     GET/PUT/PATCH/DELETE 的 pk 找不到
  405 Method Not Allowed  路由不支持该 verb
  409 Conflict      唯一约束冲突(name 重复)
  422 Unprocessable Entity  字段校验失败(语义错,留口)
  429 Too Many Requests      限流(未来加)
  500 Internal Server Error 未捕获异常
  503 Service Unavailable    维护中、依赖不可达

注意:响应里的 'code' 字段是业务码,与 HTTP 状态码不同。
  - code=0  → 业务成功(HTTP 2xx)
  - code≠0 → 业务失败(HTTP 4xx/5xx)
================================================================================
"""
from rest_framework import status
from rest_framework.response import Response


# =========================================================================== #
# 2xx 成功
# =========================================================================== #
def ok(data=None, message: str = 'success', http_status: int = status.HTTP_200_OK) -> Response:
    """200 OK — GET 成功 / 通用成功。"""
    return Response({'code': 0, 'message': message, 'data': data}, status=http_status)


def created(data=None, message: str = '创建成功') -> Response:
    """201 Created — POST 创建新资源。"""
    return Response({'code': 0, 'message': message, 'data': data}, status=status.HTTP_201_CREATED)


def accepted(data=None, message: str = '已接受') -> Response:
    """202 Accepted — 异步操作触发(rotate-token、批量 probe)。"""
    return Response({'code': 0, 'message': message, 'data': data}, status=status.HTTP_202_ACCEPTED)


def no_content() -> Response:
    """204 No Content — DELETE 成功(无 body)。"""
    return Response(status=status.HTTP_204_NO_CONTENT)


# =========================================================================== #
# 4xx 客户端错误
# =========================================================================== #
def fail(message: str = 'error', code: int = 1,
         http_status: int = status.HTTP_400_BAD_REQUEST, data=None) -> Response:
    """通用失败响应(默认 400)。"""
    return Response({'code': code, 'message': message, 'data': data}, status=http_status)


def bad_request(message: str = '请求参数错误', code: int = 4000, data=None) -> Response:
    """400 Bad Request — 语法错(JSON 解析失败、缺参数)。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_400_BAD_REQUEST)


def unauthorized(message: str = '请先登录', code: int = 4001, data=None) -> Response:
    """401 Unauthorized — 没 token / token 错 / 已失效。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_401_UNAUTHORIZED)


def forbidden(message: str = '无权访问', code: int = 4003, data=None) -> Response:
    """403 Forbidden — 已登录但没权限。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_403_FORBIDDEN)


def not_found(message: str = '资源不存在', code: int = 4004, data=None) -> Response:
    """404 Not Found — GET/PUT/PATCH/DELETE 的 pk 找不到。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_404_NOT_FOUND)


def method_not_allowed(message: str = '方法不允许', code: int = 4005, data=None) -> Response:
    """405 Method Not Allowed — 路由不支持该 verb。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_405_METHOD_NOT_ALLOWED)


def conflict(message: str = '资源冲突', code: int = 4009, data=None) -> Response:
    """409 Conflict — 唯一约束冲突、状态冲突。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_409_CONFLICT)


def unprocessable_entity(message: str = '字段校验失败', code: int = 4022,
                         data=None, errors: dict | list | None = None) -> Response:
    """422 Unprocessable Entity — 语义错(字段格式对但值非法)。"""
    payload = dict(data or {})
    if errors is not None:
        payload['errors'] = errors
    return Response({'code': code, 'message': message, 'data': payload},
                    status=status.HTTP_422_UNPROCESSABLE_ENTITY)


# =========================================================================== #
# 5xx 服务器错误
# =========================================================================== #
def server_error(message: str = '服务器内部错误', code: int = 5000, data=None) -> Response:
    """500 Internal Server Error。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


def service_unavailable(message: str = '服务暂不可用', code: int = 5030, data=None) -> Response:
    """503 Service Unavailable — 维护中、依赖不可达。"""
    return Response({'code': code, 'message': message, 'data': data}, status=status.HTTP_503_SERVICE_UNAVAILABLE)
