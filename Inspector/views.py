"""
Inspector/views.py

按"一个端点一个 APIView 类"的约定,每个类只暴露与该端点相关的 HTTP 方法。
通用 list/create 与 detail 行为抽到 Common.views.BaseListCreateAPIView /
BaseDetailAPIView,这里只负责写子类的 queryset / serializer_class / filter 等。
"""
from django.utils import timezone as django_tz
from rest_framework import status
from rest_framework.permissions import AllowAny
from rest_framework.views import APIView

from Common.cache import CacheMixin
from Common.responses import fail, not_found, ok
from Common.views import (
    BaseDetailAPIView,
    BaseListCreateAPIView,
)

from .models import DailyServiceStat, Environment, MonitoredService, Team
from .serializers import (
    DailyServiceStatSerializer,
    EnvironmentSerializer,
    MonitoredServiceSerializer,
    TeamSerializer,
)
from .services import probe_service, rotate_service_token


# =========================================================================== #
# 健康检查(免鉴权,供 K8s / LB 探活)—— 禁用缓存,实时反映服务状态
# =========================================================================== #
class HealthzView(APIView):
    """GET /api/insperctor/healthz/  探活用,跳过鉴权 + 缓存。"""

    authentication_classes: list = []
    permission_classes = [AllowAny]

    def get(self, request, *args, **kwargs):
        return ok({
            'status': 'ok',
            'ts': django_tz.now().isoformat(),
        })


# =========================================================================== #
# Team
# =========================================================================== #
class TeamListCreateView(BaseListCreateAPIView):
    """GET /api/insperctor/teams/        列表(支持 ?keyword= 搜索)
    POST /api/insperctor/teams/       新建团队
    """

    queryset = Team.objects.all()
    serializer_class = TeamSerializer
    search_fields = ('name',)


class TeamDetailView(BaseDetailAPIView):
    """GET    /api/insperctor/teams/<pk>/    详情
    PUT    /api/insperctor/teams/<pk>/    全量更新
    PATCH  /api/insperctor/teams/<pk>/    部分更新
    DELETE /api/insperctor/teams/<pk>/    删除(若该团队下还有服务,FK PROTECT 会阻止)
    """

    queryset = Team.objects.all()
    serializer_class = TeamSerializer


# =========================================================================== #
# Environment
# =========================================================================== #
class EnvironmentListCreateView(BaseListCreateAPIView):
    """GET  /api/insperctor/environments/
    POST /api/insperctor/environments/
    """

    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer
    search_fields = ('name',)


class EnvironmentDetailView(BaseDetailAPIView):
    """GET/PUT/PATCH/DELETE /api/insperctor/environments/<pk>/"""
    queryset = Environment.objects.all()
    serializer_class = EnvironmentSerializer


# =========================================================================== #
# MonitoredService
# =========================================================================== #
class MonitoredServiceListCreateView(BaseListCreateAPIView):
    """GET  /api/insperctor/services/?team_id=&environment_id=&is_active=&keyword=
    POST /api/insperctor/services/
    """

    queryset = MonitoredService.objects.select_related('team', 'environment').all()
    serializer_class = MonitoredServiceSerializer
    search_fields = ('name', 'base_url')
    filter_fields = ('team_id', 'environment_id', 'is_active')
    ordering = 'id'


class MonitoredServiceDetailView(BaseDetailAPIView):
    """GET/PUT/PATCH/DELETE /api/insperctor/services/<pk>/"""

    queryset = MonitoredService.objects.select_related('team', 'environment').all()
    serializer_class = MonitoredServiceSerializer


class MonitoredServiceProbeView(APIView):
    """POST /api/insperctor/services/<pk>/probe/

    主动触发一次健康检查:对 base_url + health_path 发 GET,比对 expected_status,
    写 ProbeLog 并把本次结果回传给前端。
    """

    def post(self, request, pk, *args, **kwargs):
        try:
            service = MonitoredService.objects.get(pk=pk)
        except MonitoredService.DoesNotExist:
            return not_found(message='服务不存在')

        result = probe_service(service, source='manual')
        return ok(result, message='探测完成')


class MonitoredServiceRotateTokenView(APIView):
    """POST /api/insperctor/services/<pk>/rotate-token/

    立即为指定服务生成新 Token 并加密写回,仅此处返回明文。
    """

    def post(self, request, pk, *args, **kwargs):
        try:
            service = MonitoredService.objects.get(pk=pk)
        except MonitoredService.DoesNotExist:
            return not_found(message='服务不存在')

        new_token = rotate_service_token(service)
        return ok({
            'service_id': service.id,
            'service_name': service.name,
            'token': new_token,
            'token_rotated_at': service.token_rotated_at.isoformat(),
        }, message='Token 已轮换')


# =========================================================================== #
# DailyServiceStat — 自带缓存(60s,基类的 CacheMixin 已经处理;只换下超时)
# =========================================================================== #
class DailyServiceStatListView(CacheMixin, APIView):
    """GET /api/insperctor/stats/?date=YYYY-MM-DD&environment=dev&team=<team_name>

    仅做查询,统计由 Celery 任务在 00:00 写入。
    """

    cache_timeout: int = 60  # 统计每天才更新,缓存 60s 完全够

    def get(self, request, *args, **kwargs):
        qs = DailyServiceStat.objects.select_related(
            'service', 'environment', 'team',
        ).all()

        date_str = request.query_params.get('date')
        if date_str:
            qs = qs.filter(stat_date=date_str)
        env = request.query_params.get('environment')
        if env:
            qs = qs.filter(environment__name=env)
        team = request.query_params.get('team')
        if team:
            qs = qs.filter(team__name=team)

        qs = qs.order_by('-stat_date', 'service_id')[:500]
        return ok(DailyServiceStatSerializer(qs, many=True).data)
