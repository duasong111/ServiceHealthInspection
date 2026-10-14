"""
Timing/admin.py

请求耗时日志,只读。
"""
from django.contrib import admin

from .models import RequestTimingLog


@admin.register(RequestTimingLog)
class RequestTimingLogAdmin(admin.ModelAdmin):
    list_display = ('id', 'method', 'path_short', 'status_code', 'elapsed_ms', 'created_at')
    list_display_links = ('id',)
    list_filter = ('method', 'status_code')
    search_fields = ('path',)
    date_hierarchy = 'created_at'
    list_per_page = 100
    readonly_fields = ('method', 'path', 'status_code', 'elapsed_ms', 'created_at')

    def has_add_permission(self, request):
        return False  # 只由中间件写

    def has_change_permission(self, request, obj=None):
        return False  # 只读

    def path_short(self, obj):
        return (obj.path or '')[:80]
    path_short.short_description = '路径'
