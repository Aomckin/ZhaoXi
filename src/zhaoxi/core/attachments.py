"""Bounded inline raster attachments shared by API and conversation messages."""
import base64
import binascii
from typing import Annotated

from pydantic import AfterValidator, Field

MAX_IMAGE_BYTES = 100 * 1024 * 1024


def validate_image(value: str) -> str:
    header, separator, payload = value.partition(',')
    supported = {'data:image/png;base64', 'data:image/jpeg;base64', 'data:image/webp;base64'}
    if not separator or header not in supported:
        raise ValueError('图片仅支持 PNG、JPEG、WebP 的 base64 数据')
    if len(payload) > 4 * ((MAX_IMAGE_BYTES + 2) // 3):
        raise ValueError('每张图片不能超过 100 MB')
    try:
        raw = base64.b64decode(payload, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError('图片 base64 数据无效') from exc
    if not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError('图片不能为空或超过 100 MB')
    valid = (
        header == 'data:image/png;base64' and raw.startswith(b'\x89PNG\r\n\x1a\n')
        or header == 'data:image/jpeg;base64' and raw.startswith(b'\xff\xd8\xff')
        or header == 'data:image/webp;base64' and raw[:4] == b'RIFF' and raw[8:12] == b'WEBP'
    )
    if not valid:
        raise ValueError('图片内容与格式不匹配')
    return value


ImageData = Annotated[str, AfterValidator(validate_image)]
ImageList = Annotated[list[ImageData], Field(max_length=20)]
