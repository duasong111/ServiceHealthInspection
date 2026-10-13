import os
import uvicorn
# 根据任务量来去启动线程数目
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "ServiceHealthInspection.settings")
if __name__ == "__main__":

    uvicorn.run(
        "ServiceHealthInspection.asgi:application",
        host="0.0.0.0",
        port=8000,
        workers=1,
        loop="asyncio",
    )