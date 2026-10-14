"""
run_celery.py — 本地开发启动 Celery worker / beat 的便捷脚本。

⚠️  Windows 上的两个坑:
  1. Celery 不支持 worker+beat 单进程模式(--beat 依赖 fork(),Windows 没有),
     脚本会自动检测平台,Windows 下默认只起 worker,提示你另开终端跑 beat。
     Linux / macOS 仍然可以单进程 worker+beat。
  2. Celery 5.6 + billiard 在 Windows prefork pool 下,`fast_trace_task` 解析
     request 上下文时会抛 ValueError("not enough values to unpack"),bind=True
     的任务直接挂。我们用 threads pool 绕过 billiard,Windows 上加 --pool=threads。

用法:
    python run_celery.py                    # worker(Linux/mac 自动加 --beat;Windows 只起 worker + threads pool)
    python run_celery.py --no-beat          # 显式只起 worker
    python run_celery.py --with-beat        # 强制单进程 worker+beat(Windows 会报错)
    python run_celery.py --beat-only        # 只起 beat
    python run_celery.py --concurrency=4    # worker 并发数
    python run_celery.py --loglevel=debug   # 日志级别
    python run_celery.py --pool=solo        # 强制 solo pool(单线程,Windows 最稳但慢)

生产推荐拆两个进程(用 docker-compose 编排),直接走 celery 命令:
    celery -A ServiceHealthInspection worker --pool=threads --loglevel=info
    celery -A ServiceHealthInspection beat   --loglevel=info
"""
import os
import platform
import subprocess
import sys


IS_WINDOWS = platform.system() == 'Windows'


def _flag(name: str, default: str) -> str:
    """从 sys.argv 抓 --name=value,没传则返回 default。"""
    prefix = f'--{name}='
    for arg in sys.argv[1:]:
        if arg.startswith(prefix):
            return arg.split('=', 1)[1]
    return default


def build_cmd() -> list[str]:
    argv = sys.argv[1:]
    if '-h' in argv or '--help' in argv:
        print(__doc__)
        sys.exit(0)
    no_beat = '--no-beat' in argv
    beat_only = '--beat-only' in argv
    force_beat = '--with-beat' in argv
    loglevel = _flag('loglevel', 'info')
    concurrency = _flag('concurrency', '2')
    pool = _flag('pool', 'threads' if IS_WINDOWS else 'prefork')

    cmd = [sys.executable, '-m', 'celery', '-A', 'ServiceHealthInspection']

    # --- 模式 1:只要 beat ---
    if beat_only:
        return cmd + ['beat', f'--loglevel={loglevel}']

    # --- 模式 2:worker(可选加 --beat)---
    cmd += [
        'worker',
        f'--loglevel={loglevel}',
        f'--concurrency={concurrency}',
        f'--pool={pool}',
    ]

    if no_beat:
        return cmd

    if force_beat:
        # 用户显式强制单进程,Windows 跑下去会报 fork() 错
        if IS_WINDOWS:
            print('[WARN] --with-beat on Windows will fail (no fork()).')
        return cmd + ['--beat']

    # 默认行为
    if IS_WINDOWS:
        print('=' * 70)
        print(f'  Windows: pool={pool}  concurrency={concurrency}')
        print('  worker only. Run beat in another terminal:')
        print('      python run_celery.py --beat-only')
        print('  Until beat is up, scheduled tasks (8h token / daily 00:00 / 5min probe)')
        print('  will NOT fire.')
        print('=' * 70)
        return cmd

    # Linux / mac:单进程 worker+beat
    return cmd + ['--beat']


def main() -> None:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'ServiceHealthInspection.settings')
    cmd = build_cmd()
    print('>>>', ' '.join(cmd))
    try:
        subprocess.run(cmd, check=True)
    except KeyboardInterrupt:
        print('\nBye.')


if __name__ == '__main__':
    main()

