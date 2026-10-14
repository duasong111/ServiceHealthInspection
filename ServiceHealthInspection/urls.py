"""
URL configuration for ServiceHealthInspection project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
# from django.contrib import admin
from django.conf import settings
from django.contrib import admin
from django.urls import path, include
from django.contrib.staticfiles.urls import staticfiles_urlpatterns

urlpatterns = [
    # SimpleUI 可视化后台(账号走 Django 原生 auth,不是 DRF Token)
    path("admin/", admin.site.urls),
    # 设备巡检接口
    path("api/insperctor/", include('Inspector.urls', namespace='Inspector')),
    # 定时任务接口
    path("api/time/", include('Timing.urls', namespace='Timing')),
    # 鉴权接口(增强 ④)
    path("api/auth/", include('Account.urls', namespace='Account')),
]

# ===== dev 模式挂载静态文件服务 =====
# Django 自带 runserver 会自动加 staticfiles_urlpatterns(),
# 但我们走 uvicorn/ASGI,需要手动挂上,否则 simpleui 的 css/js/img 全 404
# 生产请用 nginx / collectstatic,不要走这里
if settings.DEBUG:
    urlpatterns += staticfiles_urlpatterns()

