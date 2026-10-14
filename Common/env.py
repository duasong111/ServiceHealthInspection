"""
Common/env.py

极简 .env 加载器:在 settings.py 最开始调用 load_dotenv(),
从项目根 .env 文件里把 KEY=VALUE 形式加载到 os.environ(已有的不覆盖)。
零依赖,标准库 10 行实现。
"""
import os
from pathlib import Path


def load_dotenv(env_path: str | os.PathLike | None = None) -> None:
    """从 .env 加载到 os.environ(已存在的变量不覆盖)。"""
    if env_path is None:
        env_path = Path(__file__).resolve().parent.parent / '.env'
    env_path = Path(env_path)
    if not env_path.exists():
        return

    for raw_line in env_path.read_text(encoding='utf-8').splitlines():
        line = raw_line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, _, value = line.partition('=')
        key = key.strip()
        value = value.strip().strip('"').strip("'")  # 去引号
        if key and key not in os.environ:
            os.environ[key] = value
