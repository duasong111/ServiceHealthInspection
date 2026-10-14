"""
Inspector/partitioning.py

ProbeLog 表的 PostgreSQL 声明式分区相关 SQL 工具。
被 migration (0003) 和 management command 共享。

为什么不用 Django 的 Meta.partitioning:
    Django 6.1.2 的 django.db.models 里没暴露 PostgresPartitioningStrategy /
    PostgresPartition,得走 raw SQL,这里集中放。
"""
from datetime import date, timedelta

from django.db import connection


PARTITION_PREFIX = "inspector_probe_log_p"
DEFAULT_PARTITION = "inspector_probe_log_default"
PARENT_TABLE = "inspector_probe_log"


# --------------------------------------------------------------------------- #
# 时间工具
# --------------------------------------------------------------------------- #
def month_bounds(d: date) -> tuple[date, date]:
    """返回 (本月第一天, 下月第一天)。"""
    start = d.replace(day=1)
    nxt = (start + timedelta(days=32)).replace(day=1)
    return start, nxt


def add_months(d: date, n: int) -> date:
    """在 d 的基础上加 n 个月。n 可负。"""
    year = d.year + (d.month - 1 + n) // 12
    month = (d.month - 1 + n) % 12 + 1
    return date(year, month, 1)


def partition_name(d: date) -> str:
    """'2026-10-15' → 'inspector_probe_log_p_202610'。"""
    return f"{PARTITION_PREFIX}_{d:%Y%m}"


# --------------------------------------------------------------------------- #
# SQL 执行 / 状态查询
# --------------------------------------------------------------------------- #
def _exec(sql: str, params: tuple = ()) -> None:
    with connection.cursor() as c:
        c.execute(sql, params)


def partition_exists(name: str) -> bool:
    with connection.cursor() as c:
        c.execute("SELECT 1 FROM pg_class WHERE relname=%s", (name,))
        return c.fetchone() is not None


def get_server_version_num() -> int:
    """PostgreSQL 服务器版本,例如 150013 = 15.13。"""
    with connection.cursor() as c:
        c.execute("SELECT current_setting('server_version_num')")
        return int(c.fetchone()[0])


# --------------------------------------------------------------------------- #
# 建 / 删 分区
# --------------------------------------------------------------------------- #
def create_month_partition(d: date) -> str:
    """建当月的 RANGE 分区;若已存在直接返回名字(幂等)。"""
    name = partition_name(d)
    if partition_exists(name):
        return name
    start, end = month_bounds(d)
    _exec(
        f"CREATE TABLE IF NOT EXISTS {name} "
        f"PARTITION OF {PARENT_TABLE} "
        f"FOR VALUES FROM (%s) TO (%s)",
        (start, end),
    )
    return name


def create_default_partition() -> str:
    """建默认分区,作为兜底(任何不在显式分区范围内的行都进这里)。"""
    if partition_exists(DEFAULT_PARTITION):
        return DEFAULT_PARTITION
    _exec(
        f"CREATE TABLE IF NOT EXISTS {DEFAULT_PARTITION} "
        f"PARTITION OF {PARENT_TABLE} DEFAULT"
    )
    return DEFAULT_PARTITION


def ensure_partitions(months_ahead: int = 2, create_default: bool = True) -> list[str]:
    """
    确保当月 + 之后 N 个月 + (可选)默认分区都存在。
    跑多次没事,所有 CREATE 都 IF NOT EXISTS / 名字检查。
    """
    today = date.today().replace(day=1)
    created = [create_month_partition(add_months(today, i)) for i in range(months_ahead + 1)]
    if create_default:
        created.append(create_default_partition())
    return created
