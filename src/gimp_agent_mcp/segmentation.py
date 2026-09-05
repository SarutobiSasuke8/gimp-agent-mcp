"""Optional AI subject segmentation, server-side, via rembg.

Install with ``uv sync --extra segmentation``. The first call downloads the chosen ONNX model
(~170 MB for u2net) into rembg's cache; that download is the only network access in this project.
"""

from __future__ import annotations

import io
from typing import Any

MODELS = {
    "u2net": "general purpose, best default",
    "isnet-general-use": "general purpose, sharper edges, slower",
    "u2net_human_seg": "people",
    "isnet-anime": "illustrations and anime",
    "silueta": "small and fast, lower quality",
}


def available() -> bool:
    try:
        import rembg  # noqa: F401
        from PIL import Image  # noqa: F401
    except ImportError:
        return False
    return True


def subject_mask(png_bytes: bytes, model: str = "u2net", alpha_matting: bool = False) -> dict[str, Any]:
    """Return an 8-bit greyscale mask (255 = subject) the same size as the input PNG."""
    if not available():
        raise RuntimeError("segmentation needs the optional extra: uv sync --extra segmentation (installs rembg, onnxruntime, pillow)")
    if model not in MODELS:
        raise ValueError(f"unknown model {model!r}; choose from {sorted(MODELS)}")
    from PIL import Image
    from rembg import new_session, remove

    session = new_session(model)
    src = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    mask_img = remove(src, session=session, only_mask=True, alpha_matting=alpha_matting)
    if mask_img.size != src.size:
        mask_img = mask_img.resize(src.size)
    mask = mask_img.convert("L")
    bbox = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
    return {"width": mask.width, "height": mask.height, "gray": mask.tobytes(), "bbox": bbox, "model": model}
