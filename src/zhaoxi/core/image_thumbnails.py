"""Small, disposable model-context copies of session images."""

from __future__ import annotations

import base64
import hashlib
import re
from io import BytesIO
from pathlib import Path


def references_image(text: str) -> bool:
    return bool(re.search(r"图|照片|画面|视觉|看清|看见|影像|截图", text))


class ImageThumbnailCache:
    MODEL_MAX_EDGE = 1600
    MODEL_MAX_BYTES = 512 * 1024

    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else None

    @staticmethod
    def _name(message_id: str, index: int, image: str, *, model: bool = False) -> str:
        identity = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
        digest = hashlib.sha256(image.encode("ascii")).hexdigest()[:24]
        return f"{identity}-{index}-{digest}{'-model' if model else ''}.jpg"

    def thumbnail(self, message_id: str, index: int, image: str) -> str | None:
        return self._preview(message_id, index, image, model=False)

    def model_preview(self, message_id: str, index: int, image: str) -> str | None:
        """Bound current model inputs while retaining full originals for tools."""
        return self._preview(message_id, index, image, model=True)

    def _preview(self, message_id: str, index: int, image: str, *, model: bool) -> str | None:
        if not image.startswith("data:image/") or ";base64," not in image:
            return None
        path = self.directory / self._name(message_id, index, image, model=model) if self.directory else None
        try:
            payload = path.read_bytes() if path is not None and path.is_file() else None
        except OSError:
            payload = None
        if payload is None:
            try:
                from PIL import Image, ImageOps, UnidentifiedImageError
                from PIL.Image import DecompressionBombError

                raw = base64.b64decode(image.partition(",")[2], validate=True)
                with Image.open(BytesIO(raw)) as source:
                    if model and max(source.size) <= self.MODEL_MAX_EDGE and len(raw) <= self.MODEL_MAX_BYTES:
                        return image
                    frame = ImageOps.exif_transpose(source)
                    edge = self.MODEL_MAX_EDGE if model else 512
                    frame.thumbnail((edge, edge))
                    if frame.mode != "RGB":
                        rgb = Image.new("RGB", frame.size, "white")
                        if "A" in frame.getbands():
                            rgb.paste(frame, mask=frame.getchannel("A"))
                        else:
                            rgb.paste(frame.convert("RGB"))
                        frame = rgb
                    while True:
                        output = BytesIO()
                        frame.save(output, format="JPEG", quality=85 if model else 65, optimize=True)
                        payload = output.getvalue()
                        if not model or len(payload) <= self.MODEL_MAX_BYTES:
                            break
                        edge = max(1, int(max(frame.size) * 0.8))
                        frame.thumbnail((edge, edge))
            except (ImportError, OSError, ValueError, DecompressionBombError, UnidentifiedImageError):
                return None
            if path is not None:
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    temporary = path.with_suffix(".tmp")
                    temporary.write_bytes(payload)
                    temporary.replace(path)
                except OSError:
                    pass  # A cache failure must not turn a chat request into an error.
        return "data:image/jpeg;base64," + base64.b64encode(payload).decode("ascii")

    def retain(self, messages: list) -> None:
        """Remove only cache files not referenced by persisted messages."""
        if self.directory is None or not self.directory.is_dir():
            return
        keep = {
            self._name(message.message_id, index, image, model=model)
            for message in messages
            for index, image in enumerate(message.images)
            for model in (False, True)
            if message.source != "emoji" and image.startswith("data:image/")
        }
        for path in self.directory.glob("*.jpg"):
            if path.name not in keep:
                path.unlink()
