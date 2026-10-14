"""
Inspector/urls.py

挂在 /api/insperctor/ 前缀下,主路由在 ServiceHealthInspection/urls.py 引入。
"""
from .views import *
from django.urls import path
app_name = 'Inspector'


urlpatterns = [
    # 健康监测
    path('healthz/', HealthzView.as_view(), name='healthz'),
    # --- Team ---
    path('teams/', TeamListCreateView.as_view(), name='team-list-create'),
    path('teams/<int:pk>/', TeamDetailView.as_view(), name='team-detail'),

    # --- Environment ---
    path('environments/', EnvironmentListCreateView.as_view(), name='environment-list-create'),
    path('environments/<int:pk>/', EnvironmentDetailView.as_view(), name='environment-detail'),

    # --- MonitoredService ---
    path('services/', MonitoredServiceListCreateView.as_view(), name='service-list-create'),
    path('services/<int:pk>/', MonitoredServiceDetailView.as_view(), name='service-detail'),
    path('services/<int:pk>/probe/', MonitoredServiceProbeView.as_view(), name='service-probe'),
    path('services/<int:pk>/rotate-token/',
         MonitoredServiceRotateTokenView.as_view(), name='service-rotate-token'),

    # --- 日健康率统计查询 ---
    path('stats/', DailyServiceStatListView.as_view(), name='stats-list'),
]
