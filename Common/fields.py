"""
Common/fields.py

自实现的 EncryptedCharField —— 替代 django-cryptography 的 encrypt() 字段,
用 Fernet 做对称加密,行为等价:

    from Common.fields import EncryptedCharField
    token = EncryptedCharField(max_length=4096, blank=True, default='')

底层存储:
    - 数据库里存的是 base64 密文(str)
    - 业务层读写时都是明文 str

密钥:
    settings.FIELD_ENCRYPTION_KEY  (Fernet.generate_key() 生成的 44 字节 base64)
    缺失时延迟到字段首次使用时再报错,避免 settings 还没注入时直接爆炸。
"""
from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.db import models


def _get_cipher() -> Fernet:
    key = getattr(settings, 'FIELD_ENCRYPTION_KEY', None)
    if not key:
        raise ImproperlyConfigured(
            'FIELD_ENCRYPTION_KEY 未配置。请运行 '
            '`python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` '
            '生成密钥,通过环境变量 INSPECTOR_FIELD_ENCRYPTION_KEY 注入。'
        )
    if isinstance(key, str):
        key = key.encode('utf-8')
    return Fernet(key)


class EncryptedCharField(models.CharField):
    """用 Fernet 加密的 CharField。

    - max_length 建议给大一些(默认 4096),因为密文会比明文长
    - 明文最大长度不受 max_length 限制(max_length 仅约束密文长度)
    """

    description = 'Fernet 加密的 CharField'

    def __init__(self, *args, **kwargs):
        # 默认给大点的 max_length,确保密文能塞下
        kwargs.setdefault('max_length', 4096)
        super().__init__(*args, **kwargs)

    # ---- 读路径:从数据库拿到的密文 → 明文 ---- #
    def from_db_value(self, value, expression, connection):
        if value is None or value == '':
            return value
        try:
            return _get_cipher().decrypt(value.encode('utf-8')).decode('utf-8')
        except (InvalidToken, ValueError):
            # 解析失败时不要让整条记录炸掉,返回原始值便于排查
            return value

    def to_python(self, value):
        if isinstance(value, str) or value is None:
            return value
        return str(value)

    # ---- 写路径:明文 → 密文 ---- #
    def get_prep_value(self, value):
        if value in (None, ''):
            return value
        # 已经是密文(以 gAAAAA 开头)就跳过,避免双重加密
        if isinstance(value, str) and value.startswith('gAAAAA'):
            return value
        return _get_cipher().encrypt(str(value).encode('utf-8')).decode('utf-8')
