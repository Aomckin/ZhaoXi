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
    def __init__(self, directory: str | Path | None = None) -> None:
        self.directory = Path(directory) if directory is not None else None

    @staticmethod
    def _name(message_id: str, index: int, image: str) -> str:
        identity = hashlib.sha256(message_id.encode("utf-8")).hexdigest()[:24]
        digest = hashlib.sha256(image.encode("ascii")).hexdigest()[:24]
        return f"{identity}-{index}-{digest}.jpg"

    def thumbnail(self, message_id: str, index: int, image: str) -> str | None:
        if not image.startswith("data:image/") or ";base64," not in image:
            return None
        path = self.directory / self._name(message_id, index, image) if self.directory else None
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
                    frame = ImageOps.exif_transpose(source)
                    frame.thumbnail((512, 512))
                    if frame.mode != "RGB":
                        rgb = Image.new("RGB", frame.size, "white")
                        if "A" in frame.getbands():
                            rgb.paste(frame, mask=frame.getchannel("A"))
                        else:
                            rgb.paste(frame.convert("RGB"))
                        frame = rgb
                    output = BytesIO()
                    frame.save(output, format="JPEG", quality=65, optimize=True)
                    payload = output.getvalue()
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
            self._name(message.message_id, index, image)
            for message in messages
            for index, image in enumerate(message.images)
            if message.source != "emoji" and image.startswith("data:image/")
        }
        for path in self.directory.glob("*.jpg"):
            if path.name not in keep:
                path.unlink()
