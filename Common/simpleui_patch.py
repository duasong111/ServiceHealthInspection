"""
Common/simpleui_patch.py

django-simpleui 2026.1 与 Django 6.1 的兼容性补丁。

问题:
    simpleui.templatetags.simpletags.custom_button 通过 json.dumps 序列化
    admin action 的 __dict__,但 Django 6.x 的 admin Action 在 __dict__ 里
    多了 `locations: list[<ActionLocation>]` 这种 enum 列表,simpleui 内置的
    LazyEncoder 不识别 enum → 整个 changelist 页 500:
        TypeError: Object of type ActionLocation is not JSON serializable

修法:
    替换 simpleui.templatetags.LazyEncoder.default,让 enum 直接返回 .value。
    不动 simpleui 安装包(避免 pip install -U 时被覆盖)。

用法:
    import Common.simpleui_patch  # noqa   在 settings.py 顶部加载
"""
import enum

from simpleui.templatetags import simpletags as _simpletags


_original_default = _simpletags.LazyEncoder.default


def _patched_default(self, obj):
    # enum 优先,转成其 value(通常是 str)
    if isinstance(obj, enum.Enum):
        return obj.value
    return _original_default(self, obj)


# 替换类方法
_simpletags.LazyEncoder.default = _patched_default
