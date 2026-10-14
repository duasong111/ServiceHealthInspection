"""
Inspector/admin.py

把 5 个 Model 注册到 Django admin,启用 SimpleUI 后的可视化界面:
- Team / Environment / MonitoredService: 标准 CRUD
- ProbeLog / DailyServiceStat: 只读,只能看不能改
- MonitoredService 还带两个 admin action:立即探测、轮换 Token
"""
from django.contrib import admin
from django.utils import timezone as django_tz

from .models import (
    DailyServiceStat,
    Environment,
    MonitoredService,
    ProbeLog,
    Team,
)
from .services import probe_service, rotate_service_token


# --------------------------------------------------------------------------- #
# Team
# --------------------------------------------------------------------------- #
@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'description', 'memo', 'updated_at')
    list_display_links = ('id', 'name')
    search_fields = ('name', 'description', 'memo')
    list_filter = ()
    list_per_page = 50
    ordering = ('id',)


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
@admin.register(Environment)
class EnvironmentAdmin(admin.ModelAdmin):
    list_display = ('id', 'name', 'description', 'updated_at')
    list_display_links = ('id', 'name')
    search_fields = ('name', 'description')
    list_per_page = 50
    ordering = ('id',)


# --------------------------------------------------------------------------- #
# MonitoredService(核心)
# --------------------------------------------------------------------------- #
def _mask_token(value: str) -> str:
    """admin 列表里把 token 掩码,不直接显示明文。"""
    return '••••••••' if value else '(空)'


@admin.action(description='立即探测选中的服务')
def action_probe_now(modeladmin, request, queryset):
    """同步触发探测,结果写到 ProbeLog。"""
    ok = fail = 0
    for s in queryset:
        try:
            r = probe_service(s, source='manual')
            if r['success']:
                ok += 1
            else:
                fail += 1
        except Exception as exc:  # noqa: BLE001
            fail += 1
            modeladmin.message_user(request, f'探测异常 service_id={s.id}: {exc}', level='error')
    modeladmin.message_user(
        request, f'探测完成:成功 {ok} 个,失败 {fail} 个。详细见 ProbeLog。', level='success',
    )


@admin.action(description='轮换选中的服务 Token')
def action_rotate_token(modeladmin, request, queryset):
    """对选中的服务立即生成新 Token。"""
    n = 0
    for s in queryset:
        rotate_service_token(s)
        n += 1
    modeladmin.message_user(request, f'已轮换 {n} 个服务的 Token。', level='success')


@admin.register(MonitoredService)
class MonitoredServiceAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'name', 'team', 'environment',
        'base_url', 'health_path', 'expected_status',
        'token_display', 'token_rotated_at',
        'is_active', 'updated_at',
    )
    list_display_links = ('id', 'name')
    list_filter = ('environment', 'team', 'is_active')
    search_fields = ('name', 'base_url')
    list_select_related = ('team', 'environment')
    list_per_page = 30
    raw_id_fields = ('team', 'environment')
    readonly_fields = ('token_rotated_at', 'created_at', 'updated_at', 'token_display')
    actions = [action_probe_now, action_rotate_token]
    save_on_top = True
    fieldsets = (
        ('基本信息', {
            'fields': ('name', 'team', 'environment', 'is_active'),
        }),
        ('探针配置', {
            'fields': ('base_url', 'health_path', 'expected_status'),
        }),
        ('Token(敏感)', {
            'fields': ('token_display', 'token', 'token_rotated_at'),
            'description': 'token 字段已加密存储。明文不会回显,只能通过 "轮换" 重新生成。',
        }),
        ('时间', {
            'classes': ('collapse',),
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def token_display(self, obj):
        return _mask_token(obj.token)
    token_display.short_description = 'Token(列表掩码)'


# --------------------------------------------------------------------------- #
# ProbeLog(只读)
# --------------------------------------------------------------------------- #
@admin.register(ProbeLog)
class ProbeLogAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'service', 'checked_at', 'status_code', 'success',
        'elapsed_ms', 'source', 'error_short',
    )
    list_display_links = ('id',)
    list_filter = ('success', 'source', 'status_code', 'service__environment', 'service__team')
    search_fields = ('service__name', 'error')
    date_hierarchy = 'checked_at'
    list_select_related = ('service',)
    list_per_page = 100
    readonly_fields = ('service', 'checked_at', 'status_code', 'success',
                       'elapsed_ms', 'error', 'source')

    def has_add_permission(self, request):
        return False  # 探测日志只由系统写,不允许人工加

    def has_change_permission(self, request, obj=None):
        return False  # 只读

    def error_short(self, obj):
        return (obj.error or '')[:60]
    error_short.short_description = '错误摘要'


# --------------------------------------------------------------------------- #
# DailyServiceStat(只读)
# --------------------------------------------------------------------------- #
@admin.register(DailyServiceStat)
class DailyServiceStatAdmin(admin.ModelAdmin):
    list_display = (
        'id', 'service', 'environment', 'team', 'stat_date',
        'total_count', 'success_count', 'health_rate',
    )
    list_display_links = ('id',)
    list_filter = ('environment', 'team', 'stat_date')
    search_fields = ('service__name',)
    date_hierarchy = 'stat_date'
    list_select_related = ('service', 'environment', 'team')
    list_per_page = 50
    readonly_fields = ('service', 'environment', 'team', 'stat_date',
                       'total_count', 'success_count', 'health_rate')

    def has_add_permission(self, request):
        return False  # 统计只由 Celery 写

    def has_change_permission(self, request, obj=None):
        return False  # 只读
