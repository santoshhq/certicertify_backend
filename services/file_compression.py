import logging
from io import BytesIO

import pymupdf
from PIL import Image, ImageOps

logger = logging.getLogger(__name__)


# Files larger than this are compressed ...
COMPRESS_THRESHOLD_BYTES = 200 * 1024
# ... down to (at most) this size.
COMPRESS_TARGET_BYTES = 150 * 1024


# ============================================================
# 1. JPG / JPEG
# ============================================================

def _compress_jpeg(data: bytes, target: int) -> bytes:
    """
    Re-encode a JPEG with decreasing quality, then decreasing
    resolution, until it fits in `target` bytes.
    Returns the smallest result produced.
    """

    image = Image.open(BytesIO(data))
    image = ImageOps.exif_transpose(image)

    if image.mode != "RGB":
        image = image.convert("RGB")

    original_width, original_height = image.size
    best = data

    for scale in (1.0, 0.85, 0.7, 0.55, 0.4, 0.3, 0.2):

        if scale == 1.0:
            resized = image
        else:
            size = (
                max(1, int(original_width * scale)),
                max(1, int(original_height * scale)),
            )
            resized = image.resize(size, Image.LANCZOS)

        for quality in (85, 75, 65, 55, 45, 35):

            buffer = BytesIO()
            resized.save(buffer, format="JPEG", quality=quality, optimize=True, progressive=True)
            result = buffer.getvalue()

            if len(result) < len(best):
                best = result

            if len(result) <= target:
                return result

    return best


# ============================================================
# 2. PDF
# ============================================================

def _pdf_recompress(data: bytes, dpi: int | None, quality: int | None) -> bytes:
    """
    Keep the PDF as-is (text stays selectable) but downsample /
    re-encode embedded images and drop unused objects.
    """

    with pymupdf.open(stream=data, filetype="pdf") as doc:

        if dpi and quality:
            doc.rewrite_images(
                dpi_threshold=dpi + 10,
                dpi_target=dpi,
                quality=quality,
            )

        return doc.tobytes(
            garbage=4,
            deflate=True,
            deflate_images=True,
            deflate_fonts=True,
            clean=True,
        )


def _pdf_rasterize(data: bytes, dpi: int, quality: int) -> bytes:
    """
    Last resort: render every page to a JPEG and rebuild the PDF
    from those images. Always small, but text is no longer selectable.
    """

    with pymupdf.open(stream=data, filetype="pdf") as source, pymupdf.open() as output:

        for page in source:
            pixmap = page.get_pixmap(dpi=dpi)
            jpeg = pixmap.tobytes("jpeg", jpg_quality=quality)

            new_page = output.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(new_page.rect, stream=jpeg)

        return output.tobytes(garbage=4, deflate=True)


def _compress_pdf(data: bytes, target: int) -> bytes:

    best = data

    attempts = [
        (_pdf_recompress, None, None),
        (_pdf_recompress, 150, 75),
        (_pdf_recompress, 120, 65),
        (_pdf_recompress, 96, 55),
        (_pdf_recompress, 72, 45),
        (_pdf_rasterize, 150, 70),
        (_pdf_rasterize, 120, 60),
        (_pdf_rasterize, 100, 50),
        (_pdf_rasterize, 72, 40),
    ]

    for method, dpi, quality in attempts:

        try:
            result = method(data, dpi, quality)
        except Exception as error:
            logger.warning("PDF compression step %s(%s, %s) failed: %s", method.__name__, dpi, quality, error)
            continue

        if len(result) < len(best):
            best = result

        if len(result) <= target:
            return result

    return best


# ============================================================
# 3. PUBLIC ENTRY POINT
# ============================================================

def compress_if_needed(data: bytes, extension: str) -> bytes:
    """
    If `data` is larger than 200 KB, compress it to ~150 KB.

    Supported: pdf, jpg, jpeg. Anything else, or any failure,
    returns the original bytes unchanged.
    """

    if len(data) <= COMPRESS_THRESHOLD_BYTES:
        return data

    extension = extension.lower()

    try:
        if extension in ("jpg", "jpeg"):
            result = _compress_jpeg(data, COMPRESS_TARGET_BYTES)
        elif extension == "pdf":
            result = _compress_pdf(data, COMPRESS_TARGET_BYTES)
        else:
            return data
    except Exception as error:
        logger.warning("Compression failed for .%s file, uploading original: %s", extension, error)
        return data

    logger.info("Compressed .%s file from %d KB to %d KB", extension, len(data) // 1024, len(result) // 1024)

    return result
