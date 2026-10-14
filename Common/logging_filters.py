"""
Common/logging_filters.py

logging.Filter 把 contextvar 注入每条 log record,让 formatter 可以用 %(request_id)s。
settings.LOGGING 里挂上:
    'filters': {'request_id': {'()': 'Common.logging_filters.RequestIDFilter'}}
然后 formatter 用 '[%(request_id)s]' 即可。
"""
import logging

from .context import request_id_var


class RequestIDFilter(logging.Filter):
    """给每条 log record 注入 request_id(从 contextvar 读)。"""

    def filter(self, record: logging.LogRecord) -> bool:  # noqa: A003
        record.request_id = request_id_var.get()
        return True
