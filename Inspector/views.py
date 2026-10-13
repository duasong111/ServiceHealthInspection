
import json
import time
from django.http import JsonResponse
from django.shortcuts import render
from django.views import View
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.renderers import BaseRenderer


class HealthzView(View):

    def get(self, request, *args, **kwargs):
        return JsonResponse({"status": "ok", "ts": int(time.time())})

    def head(self, request, *args, **kwargs):
        from django.http import HttpResponse
        return HttpResponse(status=200)