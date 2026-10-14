"""
Timing 应用的 ORM 模型。

当前只承载 RequestTimingLog(需求 ⑤ 中间件落库的请求耗时日志)。
"""
from django.db import models


class RequestTimingLog(models.Model):
    """每条 HTTP 请求的耗时记录,由 RequestTimingMiddleware 写入。"""

    path = models.CharField(
        max_length=512,
        verbose_name='请求路径',
    )
    method = models.CharField(
        max_length=16,
        verbose_name='HTTP 方法',
    )
    status_code = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name='响应状态码',
    )
    elapsed_ms = models.PositiveIntegerField(
        verbose_name='请求耗时(ms)',
    )
    created_at = models.DateTimeField(
        auto_now_add=True,
        db_index=True,
        verbose_name='记录时间',
    )

    class Meta:
        db_table = 'timing_request_log'
        ordering = ('-created_at',)
        verbose_name = '请求耗时日志'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['-created_at']),
            models.Index(fields=['elapsed_ms']),
        ]

    def __str__(self) -> str:
        return f'{self.method} {self.path} {self.elapsed_ms}ms'
