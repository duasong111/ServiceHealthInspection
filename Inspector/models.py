"""
Inspector 应用的 ORM 模型。

包含:
- Team              负责团队
- Environment       部署环境(dev / test / prod)
- MonitoredService  被巡检的 HTTP 服务
- ProbeLog          每次健康探测的结果日志(需求 ② + ④ 共同依赖)
- DailyServiceStat  每日健康率统计(需求 ④,按 env × team 冗余保存)
"""
from django.core.validators import RegexValidator
from django.db import models

from Common.fields import EncryptedCharField


# --------------------------------------------------------------------------- #
# 抽象基类
# --------------------------------------------------------------------------- #
class TimeStampedModel(models.Model):
    """带 created_at / updated_at 的抽象基类,统一时间字段风格。"""

    created_at = models.DateTimeField(auto_now_add=True, verbose_name='创建时间')
    updated_at = models.DateTimeField(auto_now=True, verbose_name='更新时间')

    class Meta:
        abstract = True


# --------------------------------------------------------------------------- #
# 基础数据:Team / Environment
# --------------------------------------------------------------------------- #
class Team(TimeStampedModel):
    """负责维护若干服务的团队。"""

    name = models.CharField(
        max_length=64,
        unique=True,
        verbose_name='团队名称',
        help_text='团队名称,全局不允许重复',
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='团队描述',
    )
    memo = models.TextField(
        blank=True,
        default='',
        verbose_name='备注',
    )

    class Meta:
        db_table = 'inspector_team'
        ordering = ('id',)
        verbose_name = '负责团队'
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.name


class Environment(TimeStampedModel):
    """服务部署的环境。题目要求仅 dev / test / prod 三档。"""

    name = models.CharField(
        max_length=32,
        unique=True,
        verbose_name='环境标识',
        help_text='环境标识,如 dev / test / prod',
    )
    description = models.CharField(
        max_length=255,
        blank=True,
        default='',
        verbose_name='环境说明',
    )

    class Meta:
        db_table = 'inspector_environment'
        ordering = ('id',)
        verbose_name = '环境'
        verbose_name_plural = verbose_name

    def __str__(self) -> str:
        return self.name


# --------------------------------------------------------------------------- #
# 核心:MonitoredService
# --------------------------------------------------------------------------- #
class MonitoredService(TimeStampedModel):
    """一个具体可被巡检的 HTTP 服务,是整个系统的主表。"""

    team = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        related_name='services',
        verbose_name='负责团队',
    )
    environment = models.ForeignKey(
        Environment,
        on_delete=models.PROTECT,
        related_name='services',
        verbose_name='部署环境',
    )
    name = models.CharField(
        max_length=128,
        verbose_name='服务名称',
    )
    base_url = models.URLField(
        max_length=512,
        verbose_name='服务基础地址',
        help_text='例如 http://10.0.1.11:8000',
    )
    health_path = models.CharField(
        max_length=255,
        validators=[RegexValidator(r'^/.*', message='健康检查路径必须以 / 开头')],
        verbose_name='健康检查路径',
        help_text='例如 /healthz/',
    )
    expected_status = models.PositiveSmallIntegerField(
        default=200,
        verbose_name='期望状态码',
        help_text='健康检查接口期望返回的 HTTP 状态码,默认 200',
    )
    # Fernet 对称加密字段:依赖 settings.FIELD_ENCRYPTION_KEY
    # 写入时自动加密落库,读取时自动解密。
    token = EncryptedCharField(
        max_length=4096,
        blank=True,
        default='',
        verbose_name='巡检 Token(密文)',
    )
    token_rotated_at = models.DateTimeField(
        null=True,
        blank=True,
        verbose_name='Token 上次轮换时间',
    )
    is_active = models.BooleanField(
        default=True,
        verbose_name='是否启用巡检',
    )

    class Meta:
        db_table = 'inspector_monitored_service'
        ordering = ('id',)
        verbose_name = '被巡检服务'
        verbose_name_plural = verbose_name
        # 同一服务在 dev/test/prod 都会出现,跨环境允许重名
        unique_together = (('name', 'environment'),)
        indexes = [
            models.Index(fields=['is_active']),
        ]

    def __str__(self) -> str:
        return f'{self.environment.name}/{self.name}'


# --------------------------------------------------------------------------- #
# 日志:ProbeLog
# --------------------------------------------------------------------------- #
class ProbeLog(models.Model):
    """每次健康探测的结果日志。

    - 需求 ② 的接口调用后会写入;
    - 需求 ④ 的每日统计从此聚合。
    """

    SOURCE_MANUAL = 'manual'
    SOURCE_CRON = 'cron'
    SOURCE_CHOICES = (
        (SOURCE_MANUAL, '手动触发'),
        (SOURCE_CRON, '周期任务'),
    )

    service = models.ForeignKey(
        MonitoredService,
        on_delete=models.CASCADE,
        related_name='probe_logs',
        verbose_name='被巡检服务',
    )
    checked_at = models.DateTimeField(
        verbose_name='探测时间',
    )
    status_code = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        verbose_name='实际状态码',
    )
    success = models.BooleanField(
        default=False,
        verbose_name='是否健康',
    )
    elapsed_ms = models.PositiveIntegerField(
        null=True,
        blank=True,
        verbose_name='HTTP 耗时(ms)',
    )
    error = models.TextField(
        blank=True,
        default='',
        verbose_name='异常信息',
    )
    source = models.CharField(
        max_length=16,
        choices=SOURCE_CHOICES,
        default=SOURCE_MANUAL,
        verbose_name='触发来源',
    )

    class Meta:
        db_table = 'inspector_probe_log'
        ordering = ('-checked_at',)
        verbose_name = '探测日志'
        verbose_name_plural = verbose_name
        indexes = [
            models.Index(fields=['service', '-checked_at']),
        ]

    def __str__(self) -> str:
        return f'service={self.service_id} @ {self.checked_at:%Y-%m-%d %H:%M:%S} success={self.success}'


# --------------------------------------------------------------------------- #
# 统计:DailyServiceStat
# --------------------------------------------------------------------------- #
class DailyServiceStat(models.Model):
    """每日健康率统计(需求 ④)。

    environment / team 为冗余字段,保证 service 改归属后历史快照仍然真实。
    """

    service = models.ForeignKey(
        MonitoredService,
        on_delete=models.CASCADE,
        related_name='daily_stats',
        verbose_name='被巡检服务',
    )
    environment = models.ForeignKey(
        Environment,
        on_delete=models.PROTECT,
        related_name='daily_stats',
        verbose_name='当日所属环境',
    )
    team = models.ForeignKey(
        Team,
        on_delete=models.PROTECT,
        related_name='daily_stats',
        verbose_name='当日所属团队',
    )
    stat_date = models.DateField(
        db_index=True,
        verbose_name='统计日期(上海时区)',
    )
    total_count = models.PositiveIntegerField(
        default=0,
        verbose_name='总探测次数',
    )
    success_count = models.PositiveIntegerField(
        default=0,
        verbose_name='成功次数',
    )
    health_rate = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        default=0,
        verbose_name='健康率(0~1)',
    )

    class Meta:
        db_table = 'inspector_daily_service_stat'
        ordering = ('-stat_date',)
        verbose_name = '日健康率统计'
        verbose_name_plural = verbose_name
        unique_together = (('service', 'stat_date'),)
        indexes = [
            models.Index(fields=['environment', 'team', '-stat_date']),
        ]

    def __str__(self) -> str:
        return f'service={self.service_id} {self.stat_date} health_rate={self.health_rate}'
