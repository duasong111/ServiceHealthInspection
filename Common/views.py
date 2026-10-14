"""
Common/views.py

通用 API 基类(不包含响应封装,响应封装见 Common/responses.py):
- StandardPagination          统一分页
- BaseListCreateAPIView       list + create 基类(自带 GET 缓存)
- BaseDetailAPIView           retrieve / update / delete 基类(自带 GET 缓存)

约定响应格式:
成功: {"code": 0, "message": "success", "data": <payload>}
失败: {"code": 非0, "message": "<错误描述>", "data": <可选>}
列表分页:
    {"code": 0, "message": "success", "data": {
        "items": [...], "total": N, "page": P, "page_size": S,
    }}

缓存策略:基类默认 60s TTL,失效由 Inspector.signals 监听 post_save / post_delete 自动清;
子类按需覆盖:
    cache_timeout = 0    禁用缓存(适合 probe、rotate-token、auth 等)
    cache_timeout = 300  自定义 TTL
"""
from django.db.models import Q
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.views import APIView

from Common.cache import CacheMixin
from Common.responses import (  # noqa: F401  — 供基类内部使用,调用方请从 Common.responses 直接 import
    conflict,
    created,
    no_content,
    not_found,
    ok,
)


# --------------------------------------------------------------------------- #
# 统一分页
# --------------------------------------------------------------------------- #
class StandardPagination(PageNumberPagination):
    """page / page_size 形式,前端易用。"""

    page_size = 20
    page_size_query_param = 'page_size'
    max_page_size = 200
    page_query_param = 'page'

    def get_paginated_response(self, data):
        return Response({
            'code': 0,
            'message': 'success',
            'data': {
                'items': data,
                'total': self.page.paginator.count,
                'page': self.page.number,
                'page_size': self.get_page_size(self.request),
            },
        })


class UniqueCheckMixin:
    """给 list/create / detail 基类用的 unique 冲突检测。

    单独抽出来是因为两个基类都需要它;
    之所以不走 DRF 的 UniqueValidator:它的 ValidationError 会被 handler 翻译成 422,
    而本项目约定"唯一约束冲突"走 409。
    """

    def _check_unique_conflict(self, serializer, exclude_pk=None):
        model = self.queryset.model
        for field in model._meta.get_fields():
            if not getattr(field, 'unique', False) or getattr(field, 'primary_key', False):
                continue
            if field.name not in serializer.validated_data:
                continue
            value = serializer.validated_data[field.name]
            if value in (None, ''):
                continue
            qs = model.objects.filter(**{field.name: value})
            if exclude_pk is not None:
                qs = qs.exclude(pk=exclude_pk)
            if qs.exists():
                field_zh = getattr(field, 'verbose_name', None) or field.name
                return conflict(
                    message=f'{field_zh} 已存在',
                    data={'field': field.name, 'value': value},
                )
        return None


# --------------------------------------------------------------------------- #
# 基类:List + Create
# --------------------------------------------------------------------------- #
class BaseListCreateAPIView(UniqueCheckMixin, CacheMixin, APIView):
    """GET 列表(支持 keyword 搜索 / 精确字段过滤) + POST 创建。

    子类必须设置:
        queryset         例如: Team.objects.all()
        serializer_class 例如: TeamSerializer

    可选设置:
        search_fields    元组,包含的字段会按 ?keyword=xxx 模糊搜索
        filter_fields    元组,包含的字段会按 ?field=value 精确过滤
        ordering         字符串或元组,默认排序
        cache_timeout    默认 60;设 0 禁用缓存
    """

    queryset = None
    serializer_class = None
    pagination_class = StandardPagination
    search_fields: tuple = ()
    filter_fields: tuple = ()
    ordering = '-id'
    cache_timeout: int = 60

    # ---- 工具方法 ---- #
    def get_queryset(self):
        if self.queryset is None:
            raise NotImplementedError('子类必须指定 queryset')

        qs = self.queryset

        # 1) 关键字搜索
        kw = self.request.query_params.get('keyword', '').strip()
        if kw and self.search_fields:
            q = Q()
            for f in self.search_fields:
                q |= Q(**{f'{f}__icontains': kw})
            qs = qs.filter(q)

        # 2) 精确字段过滤
        for f in self.filter_fields:
            v = self.request.query_params.get(f)
            if v not in (None, ''):
                qs = qs.filter(**{f: v})

        # 3) 排序
        if self.ordering:
            qs = qs.order_by(*(self.ordering if isinstance(self.ordering, (list, tuple)) else (self.ordering,)))

        return qs

    def get_serializer(self, *args, **kwargs):
        if self.serializer_class is None:
            raise NotImplementedError('子类必须指定 serializer_class')
        return self.serializer_class(*args, **kwargs)

    # ---- 视图方法 ---- #
    def get(self, request, *args, **kwargs):
        qs = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(qs, request, view=self)
        serializer = self.get_serializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # 显式查 unique 字段,duplicate → 409(避开 DRF UniqueValidator 的 422)
        dup = self._check_unique_conflict(serializer)
        if dup is not None:
            return dup
        from django.db import IntegrityError
        try:
            serializer.save()
        except IntegrityError as exc:
            return conflict(message='资源冲突', data={'detail': str(exc)})
        return created(serializer.data, message='创建成功')


# --------------------------------------------------------------------------- #
# 基类:Retrieve / Update / Delete
# --------------------------------------------------------------------------- #
class BaseDetailAPIView(UniqueCheckMixin, CacheMixin, APIView):
    """GET 单条 / PUT 全量更新 / PATCH 部分更新 / DELETE 删除。

    子类必须设置:
        queryset
        serializer_class

    可选:
        lookup_field   默认 'pk'
        cache_timeout  默认 60;设 0 禁用缓存
    """

    queryset = None
    serializer_class = None
    lookup_field = 'pk'
    cache_timeout: int = 60

    # ---- 工具方法 ---- #
    def get_queryset(self):
        if self.queryset is None:
            raise NotImplementedError('子类必须指定 queryset')
        return self.queryset

    def get_serializer(self, *args, **kwargs):
        if self.serializer_class is None:
            raise NotImplementedError('子类必须指定 serializer_class')
        return self.serializer_class(*args, **kwargs)

    def get_object(self):
        qs = self.get_queryset()
        lookup = self.kwargs.get(self.lookup_field)
        try:
            return qs.get(pk=lookup)
        except qs.model.DoesNotExist:
            return None

    # ---- 视图方法 ---- #
    def get(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj is None:
            return not_found(message='资源不存在')
        return ok(self.get_serializer(obj).data)

    def put(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj is None:
            return not_found(message='资源不存在')
        serializer = self.get_serializer(obj, data=request.data)
        serializer.is_valid(raise_exception=True)
        dup = self._check_unique_conflict(serializer, exclude_pk=obj.pk)
        if dup is not None:
            return dup
        from django.db import IntegrityError
        try:
            serializer.save()
        except IntegrityError as exc:
            return conflict(message='资源冲突', data={'detail': str(exc)})
        return ok(serializer.data, message='更新成功')

    def patch(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj is None:
            return not_found(message='资源不存在')
        serializer = self.get_serializer(obj, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        dup = self._check_unique_conflict(serializer, exclude_pk=obj.pk)
        if dup is not None:
            return dup
        from django.db import IntegrityError
        try:
            serializer.save()
        except IntegrityError as exc:
            return conflict(message='资源冲突', data={'detail': str(exc)})
        return ok(serializer.data, message='更新成功')

    def delete(self, request, *args, **kwargs):
        obj = self.get_object()
        if obj is None:
            return not_found(message='资源不存在')
        obj.delete()
        return no_content()
