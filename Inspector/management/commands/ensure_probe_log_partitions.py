"""
Inspector/management/commands/ensure_probe_log_partitions.py

用法:
    python manage.py ensure_probe_log_partitions
    python manage.py ensure_probe_log_partitions --months-ahead=3
    python manage.py ensure_probe_log_partitions --no-default  # 不要 default 兜底

跑这个:
    - Celery beat 每月 1 号 00:30 自动跑一次(见 settings.CELERY_BEAT_SCHEDULE)
    - 任何时候手动跑也安全(全部 IF NOT EXISTS / 名字检查)
"""
from django.core.management.base import BaseCommand, CommandError

from Inspector.partitioning import (
    DEFAULT_PARTITION,
    ensure_partitions,
    get_server_version_num,
    partition_exists,
)


class Command(BaseCommand):
    help = '确保 inspector_probe_log 的按月分区 + (可选) default 分区存在。'

    def add_arguments(self, parser):
        parser.add_argument(
            '--months-ahead', type=int, default=2,
            help='除当月外额外创建几个月。默认 2(共 3 个月)。',
        )
        parser.add_argument(
            '--no-default', action='store_true',
            help='不创建 default 兜底分区(不推荐,会丢未匹配行)。',
        )

    def handle(self, *args, **opts):
        version = get_server_version_num()
        if version < 100000:
            raise CommandError(
                f'PostgreSQL >= 10 required for declarative partitioning; got {version}.'
            )

        created = ensure_partitions(
            months_ahead=opts['months_ahead'],
            create_default=not opts['no_default'],
        )

        # 汇报
        self.stdout.write(self.style.SUCCESS(f'PG version_num: {version}'))
        self.stdout.write(self.style.SUCCESS(f'确保存在的分区 ({len(created)}):'))
        for name in created:
            marker = '(已存在)' if partition_exists(name) else '(新建)'
            kind = 'default' if name == DEFAULT_PARTITION else 'monthly'
            self.stdout.write(f'  {name:50s}  [{kind}]  {marker}')
