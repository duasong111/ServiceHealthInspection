"""
run_all.py — 一键起 web + worker + beat(单终端)

默认在同一个终端里起 3 个子进程:
    - web      (uvicorn)
    - worker   (celery worker)
    - beat     (celery beat)

每个子进程的输出会被加 [web] / [worker] / [beat] 前缀,便于区分。
Ctrl+C 一次性杀掉全部子进程,主进程再退出。

可选参数:
    --no-web           不起 web
    --no-worker        不起 worker
    --no-beat          不起 beat
    --no-color         输出不加颜色
    --kill-previous    启动前先杀掉 8000 端口的旧进程(常用于上一轮没干净退出的情况)
"""
import os
import platform
import signal
import subprocess
import sys
import threading
import time


IS_WINDOWS = platform.system() == 'Windows'

# ANSI 颜色前缀(仅 --no-color 不开时启用)
COLORS = {
    'web':    '\033[36m',   # cyan
    'worker': '\033[33m',   # yellow
    'beat':   '\033[35m',   # magenta
    'main':   '\033[32m',   # green
}
RESET = '\033[0m'


def _flag(name: str, default: bool = False) -> bool:
    return name in sys.argv[1:]


def _say(prefix: str, msg: str, use_color: bool) -> None:
    c = COLORS.get(prefix, '') if use_color else ''
    r = RESET if use_color else ''
    print(f'{c}[{prefix}]{r} {msg}', flush=True)


def reader_thread(name: str, stream, use_color: bool) -> None:
    """子进程 -> 主终端,带前缀。"""
    for line in iter(stream.readline, b''):
        try:
            text = line.decode('utf-8', errors='replace').rstrip()
        except Exception:
            text = str(line)
        if text:
            _say(name, text, use_color)
    stream.close()


def spawn(name: str, args: list[str]):
    """起子进程。Windows 用 CREATE_NEW_PROCESS_GROUP 让 Ctrl+C 能传到子进程。"""
    kwargs: dict = {
        'stdout': subprocess.PIPE,
        'stderr': subprocess.STDOUT,
    }
    if IS_WINDOWS:
        kwargs['creationflags'] = subprocess.CREATE_NEW_PROCESS_GROUP
    else:
        kwargs['start_new_session'] = True
    return subprocess.Popen(args, **kwargs)


def kill_port(port: int, use_color: bool) -> int:
    """
    杀掉占用指定端口的进程。Windows 用 PowerShell,Linux/macOS 用 lsof。
    返回杀掉的进程数。
    """
    if IS_WINDOWS:
        # 找出占用端口的 PID 列表
        ps = (
            f"Get-NetTCPConnection -LocalPort {port} -State Listen "
            f"-ErrorAction SilentlyContinue | "
            f"Select-Object -ExpandProperty OwningProcess"
        )
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True,
        )
        pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        killed = 0
        for pid in pids:
            try:
                # /T 杀整棵进程树(uvicorn 子进程就不会漏了)
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    capture_output=True, check=True,
                )
                _say('main', f'killed pid={pid} (held port {port})', use_color)
                killed += 1
            except subprocess.CalledProcessError as e:
                _say('main', f'failed to kill pid={pid}: {e}', use_color)
        return killed
    else:
        # macOS / Linux
        r = subprocess.run(
            ['lsof', '-ti', f'tcp:{port}'],
            capture_output=True, text=True,
        )
        pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
        killed = 0
        for pid in pids:
            try:
                os.kill(pid, signal.SIGKILL)
                _say('main', f'killed pid={pid} (held port {port})', use_color)
                killed += 1
            except OSError as e:
                _say('main', f'failed to kill pid={pid}: {e}', use_color)
        return killed


def _kill_orphan_beats(use_color: bool) -> int:
    """杀掉所有残留的 `celery beat` 进程(只匹配 ` beat ` 带空格的真正 beat 命令,
    不会误伤 `run_celery.py --beat-only` 这种 launcher 进程)。"""
    if not IS_WINDOWS:
        # macOS / Linux 用 pgrep
        r = subprocess.run(
            ['pgrep', '-f', 'celery.* beat '],
            capture_output=True, text=True,
        )
        pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]
    else:
        # Windows:PowerShell 扫命令行,匹配 ' beat '(空格边界)
        ps = (
            "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
            "Where-Object { $_.CommandLine -match ' beat ' } | "
            "Select-Object -ExpandProperty ProcessId"
        )
        r = subprocess.run(
            ['powershell', '-NoProfile', '-Command', ps],
            capture_output=True, text=True,
        )
        pids = [int(x) for x in r.stdout.split() if x.strip().isdigit()]

    killed = 0
    for pid in pids:
        try:
            if IS_WINDOWS:
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(pid)],
                    capture_output=True, check=True,
                )
            else:
                os.kill(pid, signal.SIGKILL)
            _say('main', f'killed orphan beat pid={pid}', use_color)
            killed += 1
        except Exception as e:
            _say('main', f'failed to kill beat pid={pid}: {e}', use_color)
    return killed


def kill_all(processes: list[tuple[str, subprocess.Popen]], use_color: bool) -> None:
    """Windows 用 taskkill /T /F 杀进程树,否则 uvicorn worker 会漏。"""
    for name, p in processes:
        if p.poll() is not None:
            continue
        if IS_WINDOWS:
            try:
                # /T 杀子进程, /F 强杀
                subprocess.run(
                    ['taskkill', '/F', '/T', '/PID', str(p.pid)],
                    capture_output=True, check=False,
                )
            except Exception as e:
                _say('main', f'[{name}] taskkill failed: {e}', use_color)
        else:
            try:
                p.terminate()
            except Exception as e:
                _say('main', f'[{name}] terminate failed: {e}', use_color)

    for name, p in processes:
        try:
            p.wait(timeout=8)
        except subprocess.TimeoutExpired:
            _say('main', f'[{name}] did not exit in 8s, hard kill', use_color)
            try:
                p.kill()
            except Exception:
                pass


def main() -> None:
    no_web = _flag('--no-web')
    no_worker = _flag('--no-worker')
    no_beat = _flag('--no-beat')
    use_color = not _flag('--no-color')
    kill_previous = _flag('--kill-previous')

    # web 启动前:杀掉占用 8000 的旧进程(可避免 "port already in use")
    if kill_previous and not no_web:
        n = kill_port(8000, use_color)
        if n:
            time.sleep(0.5)  # 给 OS 一点时间回收端口

    # 同时也清掉残留的 celery beat 进程(多个 beat 会抢 celerybeat-schedule 锁导致任务不调度)
    if kill_previous and not no_beat:
        _kill_orphan_beats(use_color)

    procs_plan: list[tuple[str, list[str]]] = []
    if not no_web:
        procs_plan.append(('web',    [sys.executable, 'run_server.py']))
    if not no_worker:
        procs_plan.append(('worker', [sys.executable, 'run_celery.py', '--no-beat']))
    if not no_beat:
        procs_plan.append(('beat',   [sys.executable, 'run_celery.py', '--beat-only']))

    if not procs_plan:
        print('Nothing to start (all --no-xxx set).')
        return

    _say('main', '=' * 60, use_color)
    _say('main', f'  Starting {len(procs_plan)} service(s). Ctrl+C to stop all.', use_color)
    _say('main', '=' * 60, use_color)

    processes: list[tuple[str, subprocess.Popen]] = []
    for name, args in procs_plan:
        try:
            p = spawn(name, args)
        except Exception as e:
            _say('main', f'[{name}] failed to start: {e}', use_color)
            continue
        processes.append((name, p))
        _say('main', f'[{name}] pid={p.pid} started', use_color)

    # 起 reader 线程,把子进程 stdout 转到主终端
    for name, p in processes:
        t = threading.Thread(target=reader_thread, args=(name, p.stdout, use_color), daemon=True)
        t.start()

    # 主循环:等子进程 / Ctrl+C
    try:
        while True:
            time.sleep(1)
            for name, p in processes:
                if p.poll() is not None:
                    _say('main', f'[{name}] exited (code={p.returncode}), others keep running', use_color)
    except KeyboardInterrupt:
        _say('main', '\nCtrl+C received, shutting down all...', use_color)
        kill_all(processes, use_color)
        _say('main', 'All services stopped.', use_color)


if __name__ == '__main__':
    main()

