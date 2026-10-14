"""
Common/context.py

跨请求 / 跨协程传递的上下文变量。
- request_id: 每个 HTTP 请求一个 UUID,由中间件设置,所有 logger 都能拿到
- 当前实现使用 contextvars,天然支持 async(ASGI)

调用方使用方式:
    from Common.context import request_id_var
    rid = request_id_var.get()       # 读取
    token = request_id_var.set(x)    # 设置,返回 token
    request_id_var.reset(token)      # 还原(用 try/finally 包)
"""
from contextvars import ContextVar

request_id_var: ContextVar[str] = ContextVar('request_id', default='-')
