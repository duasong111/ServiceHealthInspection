"""
Inspector/migrations/0003_probe_log_partitioning.py

把 inspector_probe_log 转成按月分区的 PostgreSQL 声明式分区表。

为什么走 raw SQL 而不是 Django 的 Meta.partitioning:
    Django 6.1.2 的 django.db.models 没暴露 PostgresPartitioningStrategy /
    PostgresPartition(import 一下 ImportError 就知道了),所以这里全部
    用 migrations.RunPython 直接发 SQL。

迁移步骤(forward):
  0) 校验 PG >= 10
  1) 把现表 rename 成 _legacy
  2) drop legacy 上的 FK(分区表的 FK 约束要重建在 parent 上)
  3) drop legacy 上的冗余单列索引(原 checked_at 上的 db_index=True)
  4) CREATE TABLE inspector_probe_log (...) PARTITION BY RANGE (checked_at)
  5) PK 必须包含分区键:(id, checked_at)
  6) 加 FK(PG ≥ 12,10/11 跳过 — 它们已 EOL)
  7) 建 default 分区 + 当月/+1/+2 月分区
  8) INSERT ... SELECT 把 3 条数据从 legacy 迁过来
  9) 重建复合索引 (service_id, checked_at DESC)
  10) 重置 sequence
  11) DROP legacy

reverse:
  1) drop 分区表 CASCADE
  2) rename _legacy 回原名(如果还在的话 — forward 成功的话 _legacy 已删)
  3) 状态:Django state 也要恢复 checked_at 的 db_index=True

依赖:必须在 0001_initial 之后(才能动 probe_log 表)。
"""
from django.db import migrations, models
from django.db.migrations.operations.special import RunPython


# --------------------------------------------------------------------------- #
# 工具 SQL(用函数包起来方便 forward/reverse 共享)
# --------------------------------------------------------------------------- #
def _get_version_num(cursor):
    cursor.execute("SELECT current_setting('server_version_num')")
    return int(cursor.fetchone()[0])


def _find_fk_constraint(cursor, table, column):
    """找出指向某张表/列的 FK 约束名(用来 drop)。"""
    cursor.execute(
        """
        SELECT conname
          FROM pg_constraint c
          JOIN pg_attribute a ON a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)
         WHERE c.contype = 'f'
           AND c.conrelid = %s::regclass
           AND a.attname = %s
        """,
        (table, column),
    )
    row = cursor.fetchone()
    return row[0] if row else None


def _find_index(cursor, table, columns):
    """按列名找索引(可能多个,返回第一个)。"""
    cursor.execute(
        """
        SELECT i.relname
          FROM pg_index x
          JOIN pg_class i ON i.oid = x.indexrelid
          JOIN pg_class t ON t.oid = x.indrelid
          JOIN pg_attribute a
            ON a.attrelid = t.oid AND a.attnum = ANY(x.indkey)
         WHERE t.relname = %s
           AND a.attname = %s
           AND x.indisunique = false
         LIMIT 1
        """,
        (table, columns[0]),
    )
    row = cursor.fetchone()
    return row[0] if row else None


# --------------------------------------------------------------------------- #
# forward
# --------------------------------------------------------------------------- #
def forward(apps, schema_editor):
    from Inspector.partitioning import (
        DEFAULT_PARTITION,
        ensure_partitions,
    )

    cursor = schema_editor.connection.cursor()

    # 0) PG 版本检查
    version = _get_version_num(cursor)
    if version < 100000:
        raise RuntimeError(
            f'PostgreSQL >= 10 required for declarative partitioning; got {version}.'
        )

    # 1) rename existing
    cursor.execute(
        "ALTER TABLE inspector_probe_log RENAME TO inspector_probe_log_legacy"
    )

    # 2) drop legacy 上的 FK(service_id 那个)
    fk_name = _find_fk_constraint(cursor, 'inspector_probe_log_legacy', 'service_id')
    if fk_name:
        cursor.execute(
            f'ALTER TABLE inspector_probe_log_legacy DROP CONSTRAINT {fk_name}'
        )

    # 3) drop legacy 上的冗余单列 checked_at 索引(原 db_index=True 建的)
    idx_name = _find_index(cursor, 'inspector_probe_log_legacy', ['checked_at'])
    if idx_name:
        cursor.execute(f'DROP INDEX IF EXISTS {idx_name}')

    # 4) CREATE 新的分区 parent table
    #    字段名 / 类型 / 默认值 必须跟 0001_initial.py 里 Django 建的完全一致
    #    (除了 PK 改成 (id, checked_at) — 分区表的 PK 必须包含分区键)
    cursor.execute("""
        CREATE TABLE inspector_probe_log (
            id          BIGINT  NOT NULL DEFAULT nextval('inspector_probe_log_id_seq'),
            service_id  BIGINT  NOT NULL,
            checked_at  TIMESTAMPTZ NOT NULL,
            status_code SMALLINT,
            success     BOOLEAN NOT NULL DEFAULT FALSE,
            elapsed_ms  INTEGER,
            error       TEXT NOT NULL DEFAULT '',
            source      VARCHAR(16) NOT NULL DEFAULT 'manual',
            PRIMARY KEY (id, checked_at)
        ) PARTITION BY RANGE (checked_at)
    """)

    # 5) 重新加 FK(PG ≥ 12 支持 partitioned table 的 FK,10/11 跳过)
    if version >= 120000:
        cursor.execute("""
            ALTER TABLE inspector_probe_log
              ADD CONSTRAINT inspector_probe_log_service_id_fk
              FOREIGN KEY (service_id) REFERENCES inspector_monitored_service(id)
              ON DELETE CASCADE
        """)
    else:
        import logging
        logging.getLogger('Inspector.migration').warning(
            'PG < 12: SKIP FK on partitioned table. '
            '应用层 on_delete=CASCADE 仍会生效(走 ORM 删 service 时)。'
        )

    # 6) 分区(走 Inspector.partitioning)
    ensure_partitions(months_ahead=2, create_default=True)

    # 7) 把 3 条 legacy 数据迁过来(INSERT ... SELECT 走分区路由,按 checked_at 自动归位)
    cursor.execute("""
        INSERT INTO inspector_probe_log
            (id, service_id, checked_at, status_code, success, elapsed_ms, error, source)
        SELECT id, service_id, checked_at, status_code, success, elapsed_ms, error, source
          FROM inspector_probe_log_legacy
    """)

    # 8) 重建复合索引 (service_id, checked_at DESC) — 在 parent 上建,自动下放到每个 partition
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS inspector_probe_log_service_checked_at_idx
          ON inspector_probe_log (service_id, checked_at DESC)
    """)

    # 9) 重置 sequence(避免下次 INSERT 撞 id)
    cursor.execute("""
        SELECT setval(
            'inspector_probe_log_id_seq',
            GREATEST(COALESCE((SELECT MAX(id) FROM inspector_probe_log), 0), 1)
        )
    """)

    # 10) DROP legacy CASCADE:一并把 IDENTITY sequence 干掉(它绑在 legacy 上)
    cursor.execute('DROP TABLE inspector_probe_log_legacy CASCADE')

    # 11) 重建 sequence(同名字,但 OID 变了!)
    cursor.execute('CREATE SEQUENCE inspector_probe_log_id_seq START 1')

    # 12) ⚠️ 关键:新表上 id 列的 DEFAULT nextval('inspector_probe_log_id_seq') 在
    #     CREATE TABLE 时是按旧 sequence 的 OID 绑定的,sequence 被 drop+重建后
    #     OID 变了,但 DEFAULT 里还是旧 OID,导致 INSERT 时 id=NULL 违反 NOT NULL。
    #     必须重新 SET DEFAULT 一次,让它重新解析到新 sequence 的 OID。
    cursor.execute(
        "ALTER TABLE inspector_probe_log "
        "ALTER COLUMN id SET DEFAULT nextval('inspector_probe_log_id_seq')"
    )

    # 13) 把 sequence 重新绑给新表(下次再 migrate / drop 时好处理)
    cursor.execute(
        'ALTER SEQUENCE inspector_probe_log_id_seq OWNED BY inspector_probe_log.id'
    )

    # 14) 重新 reset sequence(因为 CREATE 把它重置成 1 了,得回到当前 max)
    cursor.execute("""
        SELECT setval(
            'inspector_probe_log_id_seq',
            GREATEST(COALESCE((SELECT MAX(id) FROM inspector_probe_log), 0), 1)
        )
    """)


# --------------------------------------------------------------------------- #
# reverse
# --------------------------------------------------------------------------- #
def reverse(apps, schema_editor):
    cursor = schema_editor.connection.cursor()

    # 分区表整套删掉(子表通过 CASCADE 自动一起删)
    cursor.execute('DROP TABLE IF EXISTS inspector_probe_log CASCADE')

    # 试图把 _legacy rename 回来(forward 成功了的话 _legacy 不在,会报错,无所谓)
    cursor.execute("""
        DO $$
        BEGIN
          IF EXISTS (
            SELECT 1 FROM pg_class WHERE relname = 'inspector_probe_log_legacy'
          ) THEN
            ALTER TABLE inspector_probe_log_legacy RENAME TO inspector_probe_log;
          END IF;
        END $$;
    """)


# --------------------------------------------------------------------------- #
# migration class
# --------------------------------------------------------------------------- #
class Migration(migrations.Migration):
    dependencies = [
        ('Inspector', '0002_alter_monitoredservice_token'),
    ]

    operations = [
        # 1) 状态层:更新 Django 对 ProbeLog.checked_at 字段的理解
        #    (从 0001 里的 db_index=True 变成没索引 — 分区键已隐含索引)
        migrations.AlterField(
            model_name='probelog',
            name='checked_at',
            field=models.DateTimeField(verbose_name='探测时间'),
        ),
        # 2) 数据库层:raw SQL 转分区表
        migrations.RunPython(forward, reverse),
    ]
