"""
Inspector/serializers.py

DRF ModelSerializer 集中放这里。原则:
- token 字段 write_only,常规读接口不返回明文(轮换接口单独返回);
- 通过 source / SerializerMethodField 暴露 team_name / environment_name 等冗余字段,
  减少前端二次拼装的请求。
"""
from rest_framework import serializers

from .models import (
    DailyServiceStat,
    Environment,
    MonitoredService,
    ProbeLog,
    Team,
)


# --------------------------------------------------------------------------- #
# Team
# --------------------------------------------------------------------------- #
class TeamSerializer(serializers.ModelSerializer):
    class Meta:
        model = Team
        fields = ('id', 'name', 'description', 'memo', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


# --------------------------------------------------------------------------- #
# Environment
# --------------------------------------------------------------------------- #
class EnvironmentSerializer(serializers.ModelSerializer):
    class Meta:
        model = Environment
        fields = ('id', 'name', 'description', 'created_at', 'updated_at')
        read_only_fields = ('id', 'created_at', 'updated_at')


# --------------------------------------------------------------------------- #
# MonitoredService
# --------------------------------------------------------------------------- #
class MonitoredServiceSerializer(serializers.ModelSerializer):
    team_name = serializers.CharField(source='team.name', read_only=True)
    environment_name = serializers.CharField(source='environment.name', read_only=True)

    class Meta:
        model = MonitoredService
        fields = (
            'id', 'name', 'team', 'team_name',
            'environment', 'environment_name',
            'base_url', 'health_path', 'expected_status',
            'token', 'token_rotated_at',
            'is_active',
            'created_at', 'updated_at',
        )
        read_only_fields = ('id', 'created_at', 'updated_at',
                            'team_name', 'environment_name', 'token_rotated_at')
        extra_kwargs = {
            'token': {'write_only': True, 'required': False, 'allow_blank': True},
        }


# --------------------------------------------------------------------------- #
# ProbeLog
# --------------------------------------------------------------------------- #
class ProbeLogSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)

    class Meta:
        model = ProbeLog
        fields = (
            'id', 'service', 'service_name',
            'checked_at', 'status_code', 'success',
            'elapsed_ms', 'error', 'source',
        )
        read_only_fields = fields


# --------------------------------------------------------------------------- #
# DailyServiceStat
# --------------------------------------------------------------------------- #
class DailyServiceStatSerializer(serializers.ModelSerializer):
    service_name = serializers.CharField(source='service.name', read_only=True)
    environment_name = serializers.CharField(source='environment.name', read_only=True)
    team_name = serializers.CharField(source='team.name', read_only=True)

    class Meta:
        model = DailyServiceStat
        fields = (
            'id', 'service', 'service_name',
            'environment', 'environment_name',
            'team', 'team_name',
            'stat_date', 'total_count', 'success_count', 'health_rate',
        )
        read_only_fields = fields
