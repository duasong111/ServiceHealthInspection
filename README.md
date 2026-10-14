# ServiceHealthInspection

内网 HTTP 服务健康巡检系统。基于 Django + DRF + Celery,提供服务的注册、健康探测、Token 轮换、每日健康率统计、请求耗时埋点等能力。

---

##  项目部分截图展示

按使用流程顺序展示 7 张关键页面:

### 1️⃣ 登录界面

![登录界面](Image/login.png)

### 2️⃣ 被巡检服务管理

![被巡检服务](Image/fuwu.png)

### 3️⃣ 配置(团队 / 环境 / 触发器)

![配置](Image/peizhi.png)

### 4️⃣ 巡检记录 1

![巡检记录 1](Image/xunjian1.png)

### 5️⃣ 巡检记录 2

![巡检记录 2](Image/xunjian2.png)

### 6️⃣ 健康率统计

![健康率统计](Image/jiankang5.png)

### 7️⃣ 请求耗时统计

![请求耗时](Image/haoshi.png)

### 8️⃣ Docker 部署

![Docker 部署](Image/bushu.png)

---

## 目录

- [✨ 亮点速览](#-亮点速览)
- [核心功能](#核心功能)
- [技术栈](#技术栈)
- [目录结构](#目录结构)
- [本地开发(4 步走)](#本地开发-4-步走)
- [🧪 端到端实战速查(从拉代码到登录后台)](#-端到端实战速查从拉代码到登录后台)
- [Docker 部署](#docker-部署)
- [可视化后台 (SimpleUI)](#可视化后台-simpleui)
- [中规模架构亮点](#中规模架构亮点)
- [API 一览](#api-一览)
- [周期任务](#周期任务)
- [关键配置项](#关键配置项)
- [故障排查](#故障排查)

---

## ✨ 亮点速览

> 1000+ 服务级别(中等规模)也能跑得动。下面的设计都是为这个目标做的取舍。

| # | 亮点 | 一句话 |
|---|---|---|
| 🚀 | **Fan-out 探测** | 5 分钟周期只入队不阻塞,每个服务一个独立任务并行消费,5s 慢服务只堵一个 worker slot |
| 🗂️ | **按月分区表** | `ProbeLog` 走 PG 10+ 声明式分区,父表 + 当月/+1/+2 + default,六千万行也不卡 |
| 🧹 | **20 天数据生命周期** | 每天 01:00 走 `_raw_delete` + `disable_invalidation` 清理,绕开 cache 失效风暴 |
| 📆 | **分区自动滚动** | 每月 1 号 00:30 自动建未来 2 个月的分区,永远比当前时间领先 |
| 🔁 | **Beat 自愈** | `--kill-previous` 一并干掉孤儿 beat 进程,杜绝多 beat 抢锁导致任务不触发 |
| 🪟 | **Windows 兼容** | Celery 5.6 + billiard 在 Windows prefork 有 bug,自动切 `threads` pool |
| 🛡️ | **Token 加密** | Fernet 加密的 `EncryptedCharField`,数据库脱库也不泄漏 |

---

## 核心功能

| # | 需求 | 落点 |
|---|---|---|
| ① | 服务 / 环境 / 团队 多表管理,带 CRUD | `Inspector` 三个 Model + DRF ViewSet 风格 APIView |
| ② | 按需触发对某个服务的健康检查(HTTP GET + 状态码比对) | `POST /api/insperctor/services/<pk>/probe/` |
| ③ | 每个服务维护巡检 Token,8 小时随机重置,加密存储 | Celery 周期任务 + `Common/fields.py:EncryptedCharField`(Fernet) |
| ④ | 每天 00:00 按环境 × 团队维度统计近 24h 健康率,入库 | Celery 每日任务 + `DailyServiceStat` 表 |
| ⑤ | 实现中间件,统计每个请求耗时 | `Timing/middleware.py:RequestTimingMiddleware` |
| ⑥ | **5 分钟全量自动巡检,fan-out 派单** | `probe_all_active_services` 派单 + `probe_one_service_task` 执行 |
| ⑦ | **ProbeLog 按月分区,自动清理 + 自动滚动** | `Inspector/partitioning.py` + 0003 迁移 + 两个周期任务 |
| ⑧ | **Redis 视图缓存 + 信号自动失效** | `Common/cache.py` + `Inspector/signals.py`(含 `disable_invalidation`) |

---

## 技术栈

- **Python** 3.12
- **Web** Django 6.1.2 + DRF 3.18
- **DB** PostgreSQL 15(`psycopg[binary]` 驱动)
- **缓存 / Broker** Redis 7
- **周期任务** Celery 5.6(beat 走 `Asia/Shanghai` 时区)
- **加密** `cryptography.fernet`(自实现 `EncryptedCharField` 字段)
- **HTTP 探测** `requests`
- **容器** Docker + docker-compose(多服务编排)

---

## 目录结构

```
ServiceHealthInspection/
├── Common/                    # 通用基础设施(无 model)
│   ├── fields.py              # EncryptedCharField(Fernet 加密字段)
│   ├── cache.py               # Redis 视图缓存 + cache.delete_pattern
│   ├── views.py               # BaseListCreateAPIView / BaseDetailAPIView / ok/fail
│   ├── logging_filters.py     # RequestIDFilter(把 request_id 注入 log)
│   └── simpleui_patch.py      # 修 simpleui + Django 6.x 的 ActionLocation 序列化 bug
├── Account/                   # 鉴权(DRF Token + simpleui 集成)
│   ├── models.py
│   ├── serializers.py
│   ├── views.py               # LoginView / LogoutView / MeView
│   ├── urls.py
│   ├── admin.py               # 自定义 UserAdmin + TokenInline
│   └── apps.py                # ready() 加载 simpleui_patch
├── Inspector/                 # 巡检业务
│   ├── models.py              # Team / Environment / MonitoredService / ProbeLog / DailyServiceStat
│   ├── serializers.py         # 5 个 ModelSerializer
│   ├── services.py            # probe_service / rotate_service_token(view 和 task 共用)
│   ├── signals.py             # post_save/post_delete 自动清缓存 + disable_invalidation()
│   ├── partitioning.py        # PG 月分区 SQL 工具(create_month_partition / ensure_partitions)
│   ├── tasks.py               # 5 个 Celery 周期任务(详见下方)
│   ├── views.py               # 9 个 APIView(每端点一个类)
│   ├── urls.py
│   ├── admin.py               # 5 个 ModelAdmin + 2 个批量 action
│   ├── apps.py
│   ├── management/            # 自定义 manage.py 命令
│   │   └── commands/
│   │       └── ensure_probe_log_partitions.py
│   └── migrations/
│       ├── 0001_initial.py
│       ├── 0002_alter_monitoredservice_token.py
│       └── 0003_probe_log_partitioning.py   # raw SQL:转分区表
├── Timing/                    # 请求耗时埋点
│   ├── models.py              # RequestTimingLog
│   ├── middleware.py          # RequestTimingMiddleware
│   └── admin.py
├── ServiceHealthInspection/   # 项目根
│   ├── __init__.py            # expose celery_app
│   ├── celery.py              # Celery app
│   ├── settings.py            # 全配置(5 条 beat schedule 在这里)
│   ├── urls.py                # /api/insperctor/ + /api/time/ + /api/auth/ + /admin/
│   ├── asgi.py / wsgi.py
├── test_settings.py           # 仅本地端到端测试用,生产别用
├── manage.py
├── run_server.py              # uvicorn 启动
├── run_celery.py              # celery worker/beat 启动(Windows 默认 threads pool)
├── run_all.py                 # 一键起 web + worker + beat,带 --kill-previous
├── requirements.txt
├── Dockerfile
├── docker-compose.yml         # postgres + redis + web + celery_worker + celery_beat
└── README.md
```

---

## 本地开发(4 步走)

### 1) 准备环境

需要本机有:
- Python 3.12+(含 `venv` / `pip`)
- 可达的 PostgreSQL 15(若用 Docker,可跳过)
- 可达的 Redis 7(若用 Docker,可跳过)

### 2) 安装依赖

```bash
# 1. 虚拟环境
python -m venv .venv
.venv/Scripts/python -m pip install --upgrade pip

# 2. 安装项目依赖
.venv/Scripts/pip install -r requirements.txt
```

### 3) 配置数据库与密钥

最小配置(本地默认即可,所有项都有 dev 兜底):

```bash
# 必须:Fernet 加密密钥(用脚本现生成一个)
.venv/Scripts/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 把输出贴到下面这条命令的 = 后面
export INSPECTOR_FIELD_ENCRYPTION_KEY=上面输出的key

# 可选:数据库 / Redis(用项目默认值,跳过本段)
# export DB_HOST=127.0.0.1
# export DB_PORT=5432
# export DB_NAME=postgres
# export DB_USER=postgres
# export DB_PASSWORD=postgres
# export REDIS_HOST=127.0.0.1
# export REDIS_PORT=6379
# export REDIS_PASSWORD=
# export REDIS_DB=5
```

数据库 / Redis 实际值写在 `ServiceHealthInspection/settings.py` 中,生产请改成环境变量读取。

### 4) 迁移 + 启动

> 下面的命令按 **macOS / Linux** 写,Windows 把 `python` 替换成 `.venv/Scripts/python.exe`、`source` 替换成 `.venv/Scripts/activate.bat` 即可。其他平台差异详细见 [🧪 端到端实战速查](#-端到端实战速查从拉代码到登录后台) 那节。

```bash
# 建表(已 commit 的 migrations 会自动被 Django 识别,No changes detected 是正常的)
python manage.py makemigrations Inspector Timing Account
python manage.py migrate                       # 推荐不带 app 参数,让 Django 按依赖顺序跑

# 创建初始 superuser(可选,登录用)
python manage.py createsuperuser
python manage.py drf_create_token <你的用户名>     # 给这个用户签发 API token

# 起 web + Celery(三个角色)
#   A) 一键起 web + worker + beat(同一个终端 + 颜色前缀,Ctrl+C 一并停):
python run_all.py --kill-previous             # 推荐,会顺手杀掉上一个 :8000 占位进程和孤儿 beat

#   B) 分窗口起(需要分别开三个终端):
python run_server.py                          # uvicorn,监听 0.0.0.0:8000
python run_celery.py --no-beat                # 终端 2:celery worker
python run_celery.py --beat-only              # 终端 3:celery beat
```

### 5) 验证

```bash
# 1) 健康检查(不需要鉴权)
curl http://127.0.0.1:8000/api/insperctor/healthz/

# 2) 登录拿 token
curl -X POST http://127.0.0.1:8000/api/auth/login/ \
     -H "Content-Type: application/json" \
     -d '{"username":"<你刚才的用户名>","password":"<密码>"}'
#   => {"code":0, "message":"success", "data": {"token":"<your-token>"}}

# 3) 带 token 调 API
TOKEN=上面拿到的token
curl http://127.0.0.1:8000/api/insperctor/teams/ \
     -H "Authorization: Token $TOKEN"
```

---

## 🧪 端到端实战速查(从拉代码到登录后台)

> 下面是一次真实的"冷启动 → 登录 admin → 看到数据"的全流程实录,把上面 4 步走串起来,同时把中间踩到的几个坑标注出来,方便后人参考。命令均在 macOS 上跑过,Linux/Windows 路径稍有差异(把 `python` 换成 `.venv/Scripts/python.exe`)。

### 0) 拉代码并复用旧虚拟环境

```bash
cd /Users/duasong/DevelopProject/BackProject/ServiceHealthInspection
git pull origin main
# 查看本次增量:53 files changed, +4277 -79(从 23d20a4 到 40fcd76)
```

如果本机已经有别的项目的 `.venv` 也装过 Django/DRF,可以直接复用 —— 本项目 requirements 里的版本与 Django 6.1.2、DRF 3.18 兼容。

```bash
source /path/to/your/.venv/bin/activate   # macOS/Linux
# 或
.venv\Scripts\activate.bat                # Windows
```

### 1) 装依赖(注意一定要加 `-r`)

```bash
# ❌ 这种写法 pip 会去找名叫 "requirements.txt" 的发行包,必然报：
#    ERROR: Could not find a version that satisfies the requirement requirements.txt
pip install requirements.txt

# ✅ 必须加 -r 才会按文件里的列表装
pip install -r requirements.txt
```

依赖命中后,`pip` 会输出 `Requirement already satisfied ...` 对已经存在的版本,`Collecting ...` 对新增的(典型新增是 `django-simpleui`、`celery`、`requests`、`amqp`、`kombu` 等)。

### 2) 生成 Fernet 加密 key(强烈建议显式注入)

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 例:UmicxUN3GJXo2LTmudnRI5bsZJoeNnyI69HB_KmmzaE=
# (每次运行都会生成不同的 key,所有 key 都有效,选一个粘过去)
export INSPECTOR_FIELD_ENCRYPTION_KEY="把上面输出的字符串粘过来"
```

> 没设置环境变量也能起来,DEBUG 模式下会打一条 warning:
> `INSPECTOR_FIELD_ENCRYPTION_KEY 未设置,使用 dev 兜底 key。生产请通过环境变量注入。`
> 等到 `DEBUG=False` 时,这条不设直接 `ImproperlyConfigured`,见 [故障排查](#故障排查)。

### 3) 初始化数据库

```bash
# 先看下当前状态:Inspector 0001-0003、Timing 0001,Account 没有迁移
python manage.py showmigrations Inspector Timing Account
# Inspector
#  [ ] 0001_initial
#  [ ] 0002_alter_monitoredservice_token
#  [ ] 0003_probe_log_partitioning
# Timing
#  [ ] 0001_initial
# Account
#  (no migrations)
```

注意 `Account (no migrations)` —— **这是正常的**,不是漏写了。`Account/models.py` 里只有一行注释「复用 Django 内置 auth.User,本应用不自建 User model」,所以确实不需要建表。

```bash
# 1. 生成(会发现全部 No changes detected,因为迁移都进了仓库)
python manage.py makemigrations Inspector Timing Account
#  → No changes detected in apps 'Account', 'Timing', 'Inspector'

# 2. ⚠️ 不要这样写 ↓↓↓(见故障排查 [migrate 的位置参数陷阱])
# python manage.py migrate Inspector Timing
# CommandError: Cannot find a migration matching 'Timing' from app 'Inspector'.
# 原因:Django 的 migrate 是 `migrate <app_label> <migration_name>` 语法,
#      第二个位置参数会被当成 "Inspector 这个 app 下的某个迁移名",自然找不到叫 Timing 的。

# 3. ✅ 一次跑完所有应用(推荐)
python manage.py migrate
#  Applying Inspector.0001_initial... OK
#  Applying Inspector.0002_alter_monitoredservice_token... OK
#  Applying Inspector.0003_probe_log_partitioning... OK
#  Applying Timing.0001_initial... OK
#  ...
```

如果你执意要按 app 分批,得 **每个 app 单独写一次**:

```bash
python manage.py migrate Inspector
python manage.py migrate Timing
```

### 4) 创建超级管理员

```bash
python manage.py createsuperuser
# 用户名 (leave blank to use 'duasong'): duasong
# 电子邮件地址: 2272168170@qq.com
# Password: ********
# Password (again): ********
# Superuser created successfully.
```

也可以走 DRF 单独签发 API token(给前端/脚本用):

```bash
python manage.py drf_create_token <你的用户名>
# Generated token  xxxxxxxxxxxxxxxxxxxxxxxx for user <你的用户名>
```

### 5) 一键起 web + worker + beat

```bash
python run_all.py
# [main] ============================================================
# [main]   Starting 3 service(s). Ctrl+C to stop all.
# [main] ============================================================
# [main] [web] pid=19465 started
# [main] [worker] pid=19466 started
# [main] [beat] pid=19467 started
# [web]    INFO:     Uvicorn running on http://0.0.0.0:8000 (Press CTRL+C to quit)
# [worker] .> transport:   redis://:**@192.168.18.245:6379/6
# [worker] .> results:     redis://:**@192.168.18.245:6379/7
# [worker] .> concurrency: 2 (prefork)
# [worker] [tasks]
# [worker]   . Inspector.tasks.aggregate_daily_health_rate
# [worker]   . Inspector.tasks.cleanup_old_probe_logs
# [worker]   . Inspector.tasks.probe_all_active_services
# [worker]   . Inspector.tasks.probe_one_service_task
# [worker]   . Inspector.tasks.rotate_all_tokens
# [worker]   . Inspector.tasks.run_ensure_probe_log_partitions
# [worker]   . ServiceHealthInspection.celery.debug_ping
```

- `web / worker / beat` 三个子进程都用颜色前缀区分,Ctrl+C 一并停掉。
- `-`-broker` 自动指向 `redis://:<REDIS_PASSWORD>@<REDIS_HOST>:<REDIS_PORT>/6`,
  `result backend` 指向 `/7`,业务缓存走 `/5`(在 `settings.py` 顶部 REDIS_URL 定义)。

如果上轮没干净退出,加了 `--kill-previous` 自动清端口和孤儿 beat:

```bash
python run_all.py --kill-previous
```

### 6) 浏览器登录 admin 看效果

打开 <http://127.0.0.1:8000/admin/>,看到 SimpleUI 登录页:

```
用户名: admin
密码: ********
```

登录成功后侧边栏会自动出现 5 张本项目表:

| 菜单 | 内容 |
|---|---|
| **团队管理 / Team** | 增删改查 `Team` |
| **环境管理 / Environment** | 增删改查 `Environment`(dev / test / prod) |
| **服务管理 / Monitored service** | 列表 + 两个批量 action(立即探测 / 轮换 Token) |
| **探测日志 / Probe log** | 只读,按时间/服务/成功状态筛选 |
| **每日健康率 / Daily service stat** | 只读,按日期/团队/环境筛选 |

外加 Django 自带的 Users / Groups / Tokens,可以在 User 详情页直接看到该用户内联的 DRF Token。

### 7) 一键验完完整链路

```bash
# 7.1 不需要鉴权的健康探针
curl http://127.0.0.1:8000/api/insperctor/healthz/
# → {"code":0,"message":"success","data":"ok"}

# 7.2 拿 token
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username":"duasong","password":"你的密码"}' | python -c "import sys,json; print(json.load(sys.stdin)['data']['token'])")
echo $TOKEN

# 7.3 带 token 调业务接口
curl http://127.0.0.1:8000/api/insperctor/teams/ -H "Authorization: Token $TOKEN"

# 7.4 手动派一次 fan-out 探测(可选,等不及 5 分钟 beat 也可以手动触发)
python manage.py shell -c "from Inspector.tasks import probe_all_active_services; probe_all_active_services.delay()"
```

---

## Docker 部署

> Docker 编排用 **`profiles` + `override` 文件** 切成两个模式,各取所需:
> - `postgres` / `redis` 服务标了 `profiles: ["infra"]`,默认 `up` 不会起。
> - `docker-compose.local.yml` 是 override 文件,只在「宿主机已有 PG/Redis」时叠加上。

### 场景 1 — 啥都没有,从零起(全套)

```bash
# 1) 准备密钥(从 .env 注入,生产别 commit)
grep -q '^INSPECTOR_FIELD_ENCRYPTION_KEY=' .env || \
  echo "INSPECTOR_FIELD_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> .env

# 2) 起栈:--profile infra 把 postgres + redis 也带起来
docker compose --profile infra --env-file .env up -d --build

# 3) 迁移 + 创建管理员(只跑一次)
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser

# 4) 看日志
docker compose logs -f web celery_worker celery_beat
```

服务起来后:

| 入口 | URL |
|---|---|
| Web | `http://<host>:8000`(宿主机 / 容器所在机器) |
| Postgres | `localhost:5432`(密码 `gsm200818534`) |
| Redis | `localhost:6379`(密码 `gsm200818534`) |

### 场景 2 — 宿主机已经有 PG / Redis(本项目当前生产用法)

内网已经有 PG(192.168.x.x) / Redis 在跑,只想跑应用容器。override 文件把
`DB_HOST` / `REDIS_HOST` 重定向到 `host.docker.internal`(macOS / Windows Docker Desktop) 或
`172.17.0.1`(Linux 默认 bridge 网关)。

```bash
# 1) 同样的 .env 准备
grep -q '^INSPECTOR_FIELD_ENCRYPTION_KEY=' .env || \
  echo "INSPECTOR_FIELD_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')" >> .env

# 2) 起栈 —— 只跑 web + worker + beat,postgres/redis 复用宿主机
docker compose -f docker-compose.yml -f docker-compose.local.yml \
               --env-file .env up -d --build

# 3) 迁移 + 创建管理员(连的是宿主机 PG)
docker compose exec web python manage.py migrate
docker compose exec web python manage.py createsuperuser

# 4) 看日志
docker compose logs -f web celery_worker celery_beat
```

要换宿主机 / 端口 / 密码,在 shell 里覆盖即可,不用改文件:

```bash
LOCAL_DB_HOST=192.168.18.245  \
LOCAL_DB_NAME=go            \
LOCAL_REDIS_HOST=192.168.18.245 \
docker compose -f docker-compose.yml -f docker-compose.local.yml \
               --env-file .env up -d --build
```

### 场景 3 — 纯本机(连内网已有的 PG/Redis,不碰 docker)

最简单,完全不依赖 docker。本项目目前的默认开发姿势。

```bash
source /path/to/.venv/bin/activate
python run_all.py --kill-previous
#   ⇒ web + worker + beat 三个进程,Ctrl+C 一并停
```

`settings.py` 里 `DB_HOST` / `REDIS_HOST` 默认就是 `192.168.18.245`(你局域网的
PG / Redis),无需任何配置直接通。

---

### 三种场景对比

| 维度 | 场景 1(全套) | 场景 2(已有基础设施) | 场景 3(纯本机) |
|---|---|---|---|
| 启 docker | ✅ | ✅ | ❌ |
| 自起 PG/Redis 容器 | ✅ (`--profile infra`) | ❌(跳过) | ❌ |
| 应用 DB_HOST | `postgres` (DNS) | `host.docker.internal` | `192.168.18.245` (局域网默认) |
| 一个命令搞定 | `docker compose --profile infra up -d --build` | `docker compose -f ... -f docker-compose.local.yml up -d --build` | `python run_all.py` |
| 数据持久化 | docker volume `postgres_data` | 宿主机 PG 自己的存储 | 宿主机 PG |
| 适用人群 | 第一次接触本项目,什么都没有 | 内网已有 PG/Redis(你本次实战走这条) | 日常开发调样式 |

---

## 可视化后台 (SimpleUI)

系统集成了 [django-simpleui](https://github.com/lyhiving/simpleui),把 Django 原生 admin 替换成更现代的 UI 主题。共注册 7 张表,鼠标点一点就能管所有数据。

### 启动后访问

| 入口 | URL | 说明 |
|---|---|---|
| **管理后台** | <http://localhost:8000/admin/> | SimpleUI 主题,**账号走 Django 原生 auth(不是 DRF Token)** |
| API 健康检查 | <http://localhost:8000/api/insperctor/healthz/> | 接口存活探针 |
| API 鉴权 | <http://localhost:8000/api/auth/login/> | 拿 DRF Token 给前端/脚本调 API 用 |

### 创建管理员账号(首次)

```bash
python manage.py createsuperuser
# Username: admin
# Email: admin@example.com
# Password: ********
```

### 登录后能看到的功能

- **团队管理** —— 增删改查 `Team`
- **环境管理** —— 增删改查 `Environment`(dev / test / prod)
- **服务管理** —— 增删改 `MonitoredService`,列表里带两个**批量 action**:
  - 🔍 **立即探测选中的服务** —— 同步触发一次 HTTP 探测,结果立刻写进 `ProbeLog`
  - 🔁 **轮换选中的服务 Token** —— 立即给选中服务生成新 Token
  - Token 字段在列表里以 `••••••••` 形式掩码,详情页**不允许直接编辑**(只能重新生成)
- **探测日志** —— `ProbeLog`,只读(按时间/服务/成功状态筛选)
- **每日健康率** —— `DailyServiceStat`,只读(按日期/团队/环境筛选)
- **请求耗时日志** —— `RequestTimingLog`,只读
- **用户管理** —— Django 原生,在 User 详情页**内联显示**该用户的 DRF Token
- **Token 管理** —— 单独列表页,搜索 username 一键吊销/查找

### 主题与汉化

- 主题:`simpleui.css`(在 `settings.py` 的 `SIMPLEUI_DEFAULT_THEME` 可改 `elegant` / `layui` 等,**值必须带 `.css` 后缀**,否则 simpleui 的 actions 模板会拼出 404)
- 菜单/索引标题:在 `settings.py` 的 `SIMPLEUI_LOGIN_TITLE` / `SIMPLEUI_INDEX_TITLE` 改
- Model 列表的"verbose name"用中文,菜单就是中文
- `LANGUAGE_CODE = 'zh-hans'`、`TIME_ZONE = 'Asia/Shanghai'`、`USE_TZ = True`

> ⚠️ admin 操作(增删改 model)走的是 Django 自己的 ORM,**不会**走 DRF 接口,所以 Redis 缓存不会被感知。
> 我们用 `Inspector/signals.py` 监听 model 的 `post_save / post_delete`,**任何**写入(包括 admin 改的)都会清掉缓存,放心。

---

## 中规模架构亮点

> 下面的设计都是冲着 **"1000 个服务、5 分钟一次、全量巡检"** 去的。任何一条单独看都不复杂,合在一起就是一套能上规模的东西。

### 1. 探测 Fan-out(dispatcher + per-service)

**问题**:5000 个服务 × 5s 超时,串行跑 = 7 小时,远超 4 分钟 Celery 软超时。
**方案**:5 分钟周期里,`probe_all_active_services` 只做一件事 —— 把所有 active service 的 id `delay()` 进队列,任务自身 50ms 内返回。真正的 HTTP 调用在 `probe_one_service_task` 里跑。

```
beat(每 5min)
   │
   ▼  probe_all_active_services(dispatcher, 50ms 返回)
   │   enqueue N 个 task
   │
   ├──▶ worker slot 1 ──▶ probe_one_service_task(sid=1) ──▶ HTTP GET
   ├──▶ worker slot 2 ──▶ probe_one_service_task(sid=2) ──▶ HTTP GET
   ├──▶ worker slot 3 ──▶ probe_one_service_task(sid=3) ──▶ HTTP GET
   └──▶ ...
```

- 单服务 5s 超时只堵一个 worker slot,不影响其它
- 加 worker 数量就直接线性扩
- 每个 task 都有 `soft_time_limit=15s / time_limit=20s`,不会雪崩

代码: [Inspector/tasks.py:135-194](Inspector/tasks.py#L135-L194)

### 2. ProbeLog 按月分区表

**问题**:1000 服务 × 12 次/小时 × 24h × 30 天 = **8640 万行**,单表 SELECT `WHERE service_id=? AND checked_at>?` 走全表扫,Pg 7s+。
**方案**:PostgreSQL 10+ 声明式分区,按 `checked_at` 按月切。`service_id=?` 走分区裁剪(partition pruning)后只扫当月那一张子表,查询 < 50ms。

```
inspector_probe_log(父表,PARTITION BY RANGE(checked_at))
├── inspector_probe_log_p_202610    ← 当月
├── inspector_probe_log_p_202611    ← +1 月
├── inspector_probe_log_p_202612    ← +2 月
└── inspector_probe_log_default     ← 历史/未来兜底
```

- **PK 必须是 `(id, checked_at)`** —— 分区表的唯一约束必须包含分区键
- 复合索引 `(service_id, checked_at DESC)` 在父表上建,自动下放到每张子表
- FK 用 PG 12+ 的 partitioned FK(本机是 15.13,符合)

代码:
- 迁移: [Inspector/migrations/0003_probe_log_partitioning.py](Inspector/migrations/0003_probe_log_partitioning.py)(raw SQL,走 `migrations.RunPython`)
- 工具: [Inspector/partitioning.py](Inspector/partitioning.py)
- 手动命令: `python manage.py ensure_probe_log_partitions --months-ahead=2`

### 3. 数据生命周期:20 天清理 + 月度分区滚动

#### 3a. 每天 01:00 清理 20 天前的明细

```python
cleanup_old_probe_logs(days=20)   # Celery beat
    ↓
disable_invalidation()            # 关掉 post_save/post_delete 信号
    ↓
while 取 10000 个 id:
    _raw_delete()                 # 走底层 SQL,绕 ORM 逐行 delete
    ↓
恢复信号
```

为什么不直接 `ProbeLog.objects.filter(...).delete()`?
- ORM delete 一行一回信号,20 天 500 万行 = 500 万次 cache 失效,直接把 Redis 打死
- 改用 `_raw_delete()` 走底层,只发一条 `DELETE FROM ... WHERE id IN (...)`,信号用 `disable_invalidation()` 临时关掉

#### 3b. 每月 1 号 00:30 滚动建分区

```python
run_ensure_probe_log_partitions()  # Celery beat
    ↓
ensure_partitions(months_ahead=2, create_default=True)
    ↓
建 当月 / +1月 / +2月 / default 分区
```

- 任务秒级完成(只是 `CREATE TABLE IF NOT EXISTS`)
- 永远领先当前时间 2 个月,跨年/闰月不会漏

### 4. 缓存失效:精细化 + 批量旁路

| 场景 | 走法 | 为什么 |
|---|---|---|
| 单条 CRUD(admin / API) | `post_save/post_delete` 信号 → `cache.delete_pattern('view:*')` | 改一条就清一类,简单可靠 |
| 批量删除(cleanup) | `with disable_invalidation():` 临时关信号 | 500 万行删除不能让 Redis 死 |
| 周期聚合(aggregate) | 不用事务包,失败单条互不影响 | 5000 服务里挂 1 个不影响其它 |
| Admin 改数据 | ORM 写,信号照样触发 | 不用单独处理 |

### 5. Beat 进程自愈

**老问题**:本机之前有 3 个孤儿 `celery beat` 进程(PID 26260 / 30052 / 8476)同时抢 `celerybeat-schedule` 文件锁,3 个里只有 1 个赢,任务时灵时不灵。
**解法**:`run_all.py --kill-previous` 在起新进程前,先用 PowerShell CIM 扫 `python.exe` 找命令行包含 `celery.*beat` 的进程,`taskkill /F /T` 干掉,再起新的。

```bash
python run_all.py --kill-previous
#   1) 杀掉占用 :8000 的进程
#   2) 杀掉所有 celery beat 进程(包括孤儿)
#   3) 起 web + worker + beat
```

### 6. Windows 兼容:`--pool=threads`

**问题**:Celery 5.6 + billiard 在 Windows prefork pool 下,`fast_trace_task` 解析 request 上下文抛 `ValueError("not enough values to unpack")`,`bind=True` 的任务直接挂。
**解法**:`run_celery.py` 检测到 Windows,自动加 `--pool=threads`。threads pool 绕开 billiard 的 fork 路径,功能完全一样,只是没多进程共享内存优化(对纯 IO 型 HTTP 探测没影响)。

```bash
# Windows(默认 threads)
python run_celery.py

# Linux / macOS(默认 prefork,单进程 worker+beat)
python run_celery.py

# 强制单进程 worker+beat(Windows 会报错)
python run_celery.py --with-beat
```

### 7. SimpleUI 集成(可视化)

[Django 原生 admin 替换成 SimpleUI 主题](https://github.com/lyhiving/simpleui),7 张表全注册,鼠标就能管。

- 主题:`SIMPLEUI_DEFAULT_THEME = 'simpleui.css'`(simpleui 的 actions 模板会拼 `.../theme/<SIMPLEUI_DEFAULT_THEME>`,没 `.css` 后缀就 404)
- 汉化:`LANGUAGE_CODE = 'zh-hans'`,`USE_TZ = True`,`TIME_ZONE = 'Asia/Shanghai'`
- Model `verbose_name` 全部中文,菜单跟着中文
- simpleui 2026.x + Django 6.1 有个 `ActionLocation` enum 不能 JSON 序列化的 bug,`Common/simpleui_patch.py` 在 `Account.apps.AccountConfig.ready()` 里 monkey-patch 掉了
- Token 在列表里掩码,详情页只读,要换就调 `/api/insperctor/services/<pk>/rotate-token/`

---

## API 一览

所有响应统一格式:
```json
{ "code": 0, "message": "success", "data": <payload> }
```
列表分页:
```json
{
  "code": 0, "message": "success",
  "data": { "items": [...], "total": N, "page": P, "page_size": S }
}
```

> 所有 API 默认要 `Authorization: Token <token>`,只有 `/api/auth/login/` 与 `/api/insperctor/healthz/` 不需要。

### 鉴权

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/auth/login/` | username + password → token |
| POST | `/api/auth/logout/` | 销毁当前 token |
| GET | `/api/auth/me/` | 当前用户信息 |

### 团队

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/api/insperctor/teams/` | 列表 / 新建 |
| GET / PUT / PATCH / DELETE | `/api/insperctor/teams/<pk>/` | 详情 / 更新 / 删除 |

### 环境

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/api/insperctor/environments/` | 列表 / 新建 |
| GET / PUT / PATCH / DELETE | `/api/insperctor/environments/<pk>/` | 详情 / 更新 / 删除 |

### 服务

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / POST | `/api/insperctor/services/?team_id=&environment_id=&is_active=&keyword=` | 列表(支持过滤) / 新建 |
| GET / PUT / PATCH / DELETE | `/api/insperctor/services/<pk>/` | 详情 / 更新 / 删除 |
| POST | `/api/insperctor/services/<pk>/probe/` | 主动探测(返回本次结果) |
| POST | `/api/insperctor/services/<pk>/rotate-token/` | 立即轮换 Token(返回新 token 明文) |

### 统计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/insperctor/stats/?date=YYYY-MM-DD&environment=dev&team=<name>` | 查询日健康率 |

### 健康检查(不需要鉴权)

| 方法 | 路径 | 说明 |
|---|---|---|
| GET / HEAD | `/api/insperctor/healthz/` | 探活 |

---

## 周期任务

`ServiceHealthInspection/settings.py` 里的 `CELERY_BEAT_SCHEDULE`,5 条任务:

| Beat 名字 | 触发 | 任务 | 作用 |
|---|---|---|---|
| `inspector.probe-all-active-every-5min` | `*/5 * * * *` | `probe_all_active_services` | **fan-out 派单** —— 入队 N 个 `probe_one_service_task` |
| `inspector.rotate-tokens-every-8h` | `0 */8 * * *` | `rotate_all_tokens` | 重置所有 `is_active=True` 服务的 Token |
| `inspector.aggregate-daily-health-rate` | `0 0 * * *` | `aggregate_daily_health_rate` | 聚合昨日 24h 健康率写入 `DailyServiceStat` |
| `inspector.cleanup-old-probe-logs-daily` | `0 1 * * *` | `cleanup_old_probe_logs(days=20)` | **每天 01:00 删 20 天前的 ProbeLog** |
| `inspector.ensure-probe-log-partitions-monthly` | `30 0 1 * *` | `run_ensure_probe_log_partitions` | **每月 1 号 00:30 滚动建未来 2 个月分区** |

> ⚠️ Beat 必须**且只能**跑一个进程。多 beat 抢同一份 `celerybeat-schedule` 文件锁,只有 1 个能拿到,任务就不触发。`run_all.py --kill-previous` 会先杀光孤儿 beat 再起新的。

手动触发(开发期):
```bash
.venv/Scripts/python manage.py shell -c "
from Inspector.tasks import (
    probe_all_active_services, rotate_all_tokens,
    aggregate_daily_health_rate, cleanup_old_probe_logs,
    run_ensure_probe_log_partitions,
)
probe_all_active_services.delay()
rotate_all_tokens.delay()
aggregate_daily_health_rate.delay()
cleanup_old_probe_logs.delay(days=20)
run_ensure_probe_log_partitions.delay()
"
```

手动建分区(等不及月度任务):
```bash
.venv/Scripts/python manage.py ensure_probe_log_partitions --months-ahead=2
```

---

## 关键配置项

环境变量 / `settings.py` 双轨:环境变量优先,缺省时用 `settings.py` 里的 dev 值。

| 变量 | 含义 | 备注 |
|---|---|---|
| `INSPECTOR_FIELD_ENCRYPTION_KEY` | Fernet 加密密钥 | **生产必须设置**,否则 EncryptedCharField 拒绝工作 |
| `DB_HOST` / `DB_PORT` / `DB_NAME` / `DB_USER` / `DB_PASSWORD` | PostgreSQL 连接 | 默认 `10.1.1.136:5432`,**PG 必须 ≥ 10**(分区表) |
| `REDIS_HOST` / `REDIS_PORT` / `REDIS_PASSWORD` / `REDIS_DB` | Redis 连接 | 业务缓存 db=5,Celery broker db=6,result backend db=7 |
| `DJANGO_SETTINGS_MODULE` | Django settings 模块 | 默认 `ServiceHealthInspection.settings` |
| `DEBUG` | Django debug 模式 | 默认 `True` |
| `TIMING_EXCLUDE_PREFIXES` | 不打 timing 日志的路径前缀 | 默认 `/static/`, `/media/`, `/favicon.ico`, `/healthz` |
| `CELERY_TASK_TIME_LIMIT` | 任务硬超时(秒) | 默认 `30 * 60`(原来 4 分钟,跑批量 aggregate 都不够) |
| `CELERY_TASK_SOFT_TIME_LIMIT` | 任务软超时(秒) | 默认 `28 * 60` |
| `CELERY_BROKER_TRANSPORT_OPTIONS` | Celery broker 行为 | `{'visibility_timeout': 1800}` 30 分钟 |

`DEBUG=False` 时如果 `INSPECTOR_FIELD_ENCRYPTION_KEY` 没设,启动会直接 `ImproperlyConfigured` 拒绝起来,避免生产裸奔。

---

## 故障排查

**`ERROR: Could not find a version that satisfies the requirement requirements.txt`**

写成了 `pip install requirements.txt`,pip 把 `requirements.txt` 当成「叫这个名字的发行包」去找,当然找不到。
**正解**:`pip install -r requirements.txt`(加 `-r`)。

**`migrate Inspector Timing` 报 `Cannot find a migration matching 'Timing' from app 'Inspector'`**

Django 的 `migrate` 语法是 `migrate <app_label> [<migration_name>]`,第二个位置参数被当成了「在第一个 app 里找某条迁移」。所以 `migrate Inspector Timing` 的意思是「去 Inspector 里找叫 Timing 的迁移」—— 当然没有。

**正解**:要么直接 `python manage.py migrate`(推荐),要么每个 app 拆开写:

```bash
python manage.py migrate Inspector
python manage.py migrate Timing
```

**绝对不要**写成 `migrate Inspector Timing Account`,App 越多越容易翻车。

**`django.core.exceptions.ImproperlyConfigured: Application labels aren't unique, duplicates: <App名>`**

冷启动时偶发,典型原因有二:

1. 本地 `__pycache__/` 残留的字节码文件和当前代码不一致 —— `find . -name __pycache__ -exec rm -rf {} +` 清掉再来。
2. 真正写重复了:两个不同 app 在 `INSTALLED_APPS` 里 `default_auto_field` 计算出的 label 冲突,或者 `AppConfig.name` 路径解析后撞了另一个 app。

排查方法:`python manage.py check` 会列出冲突的具体 app 名,照着去改 `INSTALLED_APPS` 或 `AppConfig.label`。
最稳的兜底是 `find . -name __pycache__ -exec rm -rf {} +` 后重新跑 `python manage.py migrate`(不带 app 参数,让 Django 自己按依赖顺序来)。

**`UserWarning: INSPECTOR_FIELD_ENCRYPTION_KEY 未设置,使用 dev 兜底 key。生产请通过环境变量注入。`**

DEBUG 模式下的预期行为 —— 表示没设 Fernet 加密 key,系统用了一个写死在 `settings.py` 里的 dev 兜底 key(`_DEV_FALLBACK_KEY`)。

- DEBUG 模式:无视警告也能用,**别用于生产**(所有加密的 Token 都能被这个 key 解出来)。
- 生产 / `DEBUG=False`:未设置直接 `ImproperlyConfigured` 拒绝启动,见上面「关键配置项」一节。

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
export INSPECTOR_FIELD_ENCRYPTION_KEY="上面输出的字符串"
```

**`Warning: StreamingHttpResponse must consume synchronous iterators in order to serve them asynchronously. Use an asynchronous iterator instead.`**

simpleui 静态文件在 ASGI 模式下的已知噪音,不影响功能。三种处理方式:

1. 忽略 —— 静态资源照样返回 200。
2. 起开发服务时用 WSGI 而不是 ASGI:`python manage.py runserver`(自动走 WSGI,不会触发这条 warning)。
3. 生产用 `gunicorn` / `uwsgi`(本项目默认 WSGI),不上 ASGI,自然没这条。

**`ImproperlyConfigured: Error loading psycopg2 or psycopg module`**
`psycopg[binary]` 没装。`pip install "psycopg[binary]>=3.1"`。

**`Fernet key must be 32 url-safe base64-encoded bytes`**
`INSPECTOR_FIELD_ENCRYPTION_KEY` 不是合法 Fernet key。用
`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` 重新生成。

**Celery worker 起来后 beat schedule 不触发**
1. 确认启动命令带 `--beat`(本项目 `run_celery.py` 默认带)。
2. 确认 `CELERY_TIMEZONE = 'Asia/Shanghai'`,否则 00:00 不会按上海时间触发。
3. **确认本机只有 1 个 beat 进程**。多 beat 抢同一份 `celerybeat-schedule` 文件锁,只有 1 个能拿到,任务就死活不触发。
   ```bash
   # Windows:看有几个 beat
   powershell -Command "(Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | Where-Object { \$_.CommandLine -match 'celery.*beat' }).Count"
   # 不是 1 就用 run_all.py --kill-previous 重启
   python run_all.py --kill-previous
   ```
4. 删掉被锁住的 schedule 文件(必要时):
   ```bash
   rm -f celerybeat-schedule celerybeat-schedule-shm celerybeat-schedule-wal
   ```

**Windows Celery 抛 `ValueError: not enough values to unpack (expected 4, got 3)` in fast_trace_task**
Celery 5.6 + billiard 在 Windows prefork pool 下的 bug,`bind=True` 任务直接挂。本项目 `run_celery.py` 检测到 Windows 自动加 `--pool=threads` 绕开。如果手敲了 `celery worker` 命令,自己加 `--pool=threads`。

**请求耗时中间件没落库**
- 看 `settings.py` 的 `MIDDLEWARE`,确认 `Timing.middleware.RequestTimingMiddleware` 在 SecurityMiddleware 之后。
- 看 `TIMING_EXCLUDE_PREFIXES`,确认请求路径不在排除列表里。
- 看 `inspector_request_timing` 表,`/static/`、`/favicon.ico`、`/healthz` 这类不会落。

**Token 轮换之后探测 401**
轮换后服务要把新 token 通过 `Authorization: Bearer <token>` 带回;旧的 token 立刻失效。这是设计如此。

**simpleui admin 报 `Object of type ActionLocation is not JSON serializable`**
simpleui 2026.x + Django 6.1 的 bug,枚举值不能被 `LazyEncoder` 序列化。本项目 `Common/simpleui_patch.py` 在 `Account.apps.AccountConfig.ready()` 里 monkey-patch 掉了。**不要把 patch 写进 settings.py 顶部**,会撞 `AppRegistryNotReady`。
如果莫名又出现,确认 `INSTALLED_APPS` 里 `Account` 在 `simpleui` 前面,`AccountConfig.ready()` 会先于 simpleui 模板加载。

**迁移 0003 失败:`relation "inspector_probe_log" is not a table`**
分区表不是普通表,某些 admin 工具看到 `relkind='p'` 会一脸懵。验证分区是否到位:
```python
from django.db import connection
c = connection.cursor()
c.execute("SELECT relname, relkind FROM pg_class WHERE relname LIKE 'inspector_probe_log%' ORDER BY relname")
print(c.fetchall())
# 期望:[(parent,'p'), (p_202610,'r'), (p_202611,'r'), (p_202612,'r'), (default,'r')]
```

**Redis 缓存里老数据(改了 model 但列表还是旧的)**
- 单条 CRUD:信号会自动 `cache.delete_pattern('view:*')`,60s 内能拿到新数据
- 批量 cleanup:用 `with disable_invalidation():` 是预期行为,执行完统一刷新
- 想强制刷:`python manage.py shell -c "from django.core.cache import cache; cache.clear()"`
