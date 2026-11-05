"""
Validação e processamento seguro de imagens enviadas.

- Confere extensão, tamanho e o TIPO REAL do arquivo (decodificação com Pillow).
- Protege contra "decompression bombs" limitando a quantidade de pixels.
- Re-codifica a imagem: remove metadados (EXIF/GPS) e neutraliza arquivos poliglotas.
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from PIL import Image, ImageOps, UnidentifiedImageError

ALLOWED_FORMATS = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}
ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
MAX_PIXELS = 60_000_000  # ~ 7746 x 7746


@dataclass
class ProcessedImage:
    content: ContentFile
    width: int
    height: int
    format: str


def validate_and_process_upload(uploaded, *, max_mb: int, keep_format: bool = True) -> ProcessedImage:
    if uploaded is None:
        raise ValidationError("Envie um arquivo de imagem.")
    ext = Path(uploaded.name or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ValidationError("Formato não permitido. Envie PNG, JPEG ou WebP.")
    if uploaded.size > max_mb * 1024 * 1024:
        raise ValidationError(f"Arquivo muito grande. Limite: {max_mb} MB.")

    uploaded.seek(0)
    head = uploaded.read(64)
    uploaded.seek(0)
    if not (head.startswith(b"\x89PNG\r\n\x1a\n") or head[:3] == b"\xff\xd8\xff"
            or (head[:4] == b"RIFF" and head[8:12] == b"WEBP")):
        raise ValidationError("O conteúdo do arquivo não corresponde a uma imagem PNG, JPEG ou WebP.")

    previous_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = MAX_PIXELS
    try:
        try:
            with Image.open(uploaded) as probe:
                probe.verify()
            uploaded.seek(0)
            image = Image.open(uploaded)
            fmt = image.format
            if fmt not in ALLOWED_FORMATS:
                raise ValidationError("Formato de imagem não suportado.")
            if image.width * image.height > MAX_PIXELS:
                raise ValidationError("Imagem com dimensões excessivas.")
            image.load()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError) as exc:
            raise ValidationError("Arquivo de imagem inválido ou corrompido.") from exc
    finally:
        Image.MAX_IMAGE_PIXELS = previous_limit

    image = ImageOps.exif_transpose(image)
    out = io.BytesIO()
    target = fmt if keep_format else "WEBP"
    if target == "JPEG":
        image = image.convert("RGB")
        image.save(out, "JPEG", quality=95, optimize=True)
    elif target == "PNG":
        if image.mode not in ("RGB", "RGBA", "L", "LA", "P"):
            image = image.convert("RGBA")
        image.save(out, "PNG", optimize=True)
    else:
        if image.mode not in ("RGB", "RGBA"):
            image = image.convert("RGBA")
        image.save(out, "WEBP", quality=92, method=4)
    return ProcessedImage(content=ContentFile(out.getvalue(), name=f"upload{ALLOWED_FORMATS[target]}"),
                          width=image.width, height=image.height, format=target)


def make_web_versions(file_obj, *, max_side: int = 1600, thumb_side: int = 640):
    """Gera versão web (WebP) e miniatura a partir de uma imagem já validada."""
    file_obj.seek(0)
    with Image.open(file_obj) as img:
        img = ImageOps.exif_transpose(img)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() else "RGB")
        main = img.copy()
        main.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        main.save(buf, "WEBP", quality=86, method=5)
        thumb = img.copy()
        thumb.thumbnail((thumb_side, thumb_side), Image.LANCZOS)
        tbuf = io.BytesIO()
        thumb.save(tbuf, "WEBP", quality=80, method=5)
    return (ContentFile(buf.getvalue(), name="image.webp"), main.size,
            ContentFile(tbuf.getvalue(), name="thumb.webp"))
