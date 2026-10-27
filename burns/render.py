"""Ken Burns **renderers** — turn still images into pan/zoom video.

Two entry points, both consuming a :class:`~burns.path.BurnsPath` (the
render-agnostic motion spec) plus a render-time ``duration``:

- :func:`ken_burns_video` — one image, one :class:`BurnsPath`, one mp4. Dispatches
  to a pluggable backend (see :mod:`burns.backends`); the default ``"pillow"``
  backend is a lazy moviepy clip, so the whole video is never held in memory.
- :func:`ken_burns_film` — a sequence of ``(image, path, duration)`` panels
  rendered as a **single** continuous film (no per-panel intermediate files, no
  concat seams, no per-panel tail freezes), with an optional pre-built audio
  track muxed in.

Use :func:`burns.ken_burns_path` (or :meth:`BurnsPath.push_in`) to build paths
instead of hand-authoring keyframes.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import moviepy as mp
import numpy as np
from PIL import Image as PIL_Image

from burns._frame import output_size_for, sample_frame
from burns._util import _auto_video_path, _ensure_output_path, _non_colliding_key
from burns.backends import DFLT_BACKEND, frame_exact_clip, get_backend, write_clip
from burns.path import BurnsPath, PanelInput
from burns.rect import Rect

_VIDEO_EXTS = (".mp4", ".mov", ".avi", ".mkv")

# The standard 2-second push-in: full image -> 1.3x center zoom, ease-in-out.
DEFAULT_BURNS_PATH = BurnsPath.from_start_end(
    Rect(0.0, 0.0, 1.0, 1.0), Rect.from_center_zoom(0.5, 0.5, 1.3)
)
DEFAULT_DURATION_S = 2.0


def _load_image(image, *, where: str) -> tuple[np.ndarray, int, int, Path | None]:
    """Decode ``image`` (path / PIL.Image / ndarray) to ``(np, w, h, src_path)``."""
    src_path = None
    if isinstance(image, (str, Path)):
        src_path = Path(image)
        img = PIL_Image.open(str(image)).convert("RGB")
    elif isinstance(image, np.ndarray):
        img = PIL_Image.fromarray(image)
    elif hasattr(image, "convert"):
        img = image.convert("RGB")
    else:
        raise ValueError(f"{where}: unsupported image type: {type(image)}")
    w, h = img.size
    return np.array(img), w, h, src_path


def ken_burns_video(
    image,
    path: BurnsPath = DEFAULT_BURNS_PATH,
    *,
    duration: float = DEFAULT_DURATION_S,
    fps: int = 30,
    saveas: str | None = None,
    output_size: tuple[int, int] | None = None,
    backend: str = DFLT_BACKEND,
    codec: str = "libx264",
    audio_codec: str = "aac",
    **write_kwargs,
) -> Path:
    """Render one image into a pan/zoom video from a :class:`BurnsPath`.

    Args:
        image: path / ``PIL.Image`` / ``np.ndarray``.
        path: the motion spec. Default is a 2-second standard push-in.
        duration: clip length in seconds (the path's clock is normalized, so
            duration is supplied here, not baked into the path).
        fps: frames per second.
        saveas: output path. Default: the source image's name with
            ``_kenburns`` appended (auto-uniquified so an existing file is not
            overwritten). Required-ish when ``image`` has no source path —
            falls back to a temp file.
        output_size: explicit ``(width, height)`` (even-snapped). If omitted and
            ``path.output_aspect`` is set, the size is derived from it; otherwise
            the source image's size is used.
        backend: registered render backend name (default ``"pillow"``).
        codec, audio_codec, **write_kwargs: forwarded to ``write_videofile``.

    Returns:
        The output :class:`~pathlib.Path`.

    Examples:
        >>> ken_burns_video("photo.jpg")  # 2s push-in  # doctest: +SKIP
        >>> from burns import ken_burns_path
        >>> ken_burns_video(  # doctest: +SKIP
        ...     "photo.jpg", ken_burns_path(1), duration=5.0, saveas="out.mp4"
        ... )
    """
    if duration <= 0:
        raise ValueError(f"ken_burns_video: duration must be > 0, got {duration}")
    img_np, img_w, img_h, src_path = _load_image(image, where="ken_burns_video")
    out_w, out_h = output_size_for(
        img_w, img_h, output_aspect=path.output_aspect, output_size=output_size
    )
    output_path = _resolve_output(saveas, src_path)
    return get_backend(backend)(
        img_np,
        img_w,
        img_h,
        path,
        duration=duration,
        fps=fps,
        output=output_path,
        out_w=out_w,
        out_h=out_h,
        codec=codec,
        audio_codec=audio_codec,
        **write_kwargs,
    )


def _resolve_output(saveas: str | None, src_path: Path | None) -> Path:
    """Pick the output path: explicit ``saveas``, else auto-name from source."""
    if saveas is not None:
        output_path = _ensure_output_path(saveas)
        if not output_path.suffix or output_path.suffix.lower() not in _VIDEO_EXTS:
            output_path = output_path.with_suffix(".mp4")
        return output_path
    if src_path is None:
        return Path(tempfile.gettempdir()) / f"kenburns_{os.getpid()}.mp4"
    output_path = _auto_video_path(str(src_path), "_kenburns", ext=".mp4")
    directory = output_path.parent
    try:
        existing = set(os.listdir(directory)) if directory else set(os.listdir("."))
    except OSError:
        existing = set()
    if output_path.name in existing:
        output_path = directory / _non_colliding_key(output_path.name, existing)
    return output_path


def ken_burns_film(
    panels,
    *,
    saveas: str,
    fps: int = 30,
    audio_path=None,
    codec: str = "libx264",
    audio_codec: str = "aac",
    **write_kwargs,
) -> Path:
    """Render an N-panel Ken Burns film in a single pass.

    Each panel is an ``(image, path, duration_s)`` triple
    (:data:`burns.PanelInput`): ``image`` is a path / ``PIL.Image`` /
    ``np.ndarray``, ``path`` a :class:`BurnsPath`, ``duration_s`` how long the
    panel occupies the film. Panels play back-to-back; the camera cuts at panel
    boundaries but motion never pauses on a static frame within a panel.

    A single ``VideoClip`` (rather than per-panel render + concatenate) avoids
    the concat re-encode seam and per-panel tail freeze, and keeps frame
    generation lazy via one global ``make_frame(t)`` closure.

    Args:
        panels: iterable of ``(image, path, duration_s)`` triples.
        saveas: output mp4 path (required — a film has no single source image).
        fps: frame rate.
        audio_path: optional pre-built track (already matching the film
            duration); muxed in when supplied. Per-panel audio assembly is the
            caller's job — the renderer stays pure visual.
        codec, audio_codec, **write_kwargs: forwarded to ``write_videofile``.

    Returns:
        The written mp4 :class:`~pathlib.Path`.
    """
    panel_renders = []
    film_duration = 0.0
    for idx, panel in enumerate(panels):
        if not isinstance(panel, (list, tuple)) or len(panel) != 3:
            raise ValueError(
                f"panel {idx}: expected (image, path, duration_s) triple, got {panel!r}"
            )
        image, path, duration = panel
        if not isinstance(path, BurnsPath):
            raise ValueError(f"panel {idx}: path must be a BurnsPath, got {type(path)}")
        duration = float(duration)
        if duration <= 0:
            raise ValueError(f"panel {idx}: duration_s must be > 0, got {duration}")
        img_np, img_w, img_h, _ = _load_image(image, where=f"panel {idx}")
        panel_renders.append(
            {
                "img_np": img_np,
                "img_w": img_w,
                "img_h": img_h,
                "path": path,
                "duration": duration,
                "film_offset": film_duration,
                "output_aspect": path.output_aspect,
                "size": (img_w, img_h),
            }
        )
        film_duration += duration

    if film_duration <= 0:
        raise ValueError("ken_burns_film: panels must be non-empty")

    # Output frame size = first panel's resolved size (honoring its output_aspect).
    first = panel_renders[0]
    out_w, out_h = output_size_for(
        first["img_w"], first["img_h"], output_aspect=first["output_aspect"]
    )

    def make_frame(t):
        if t >= film_duration:
            pr = panel_renders[-1]
            local_norm = 1.0
        else:
            pr = next(p for p in panel_renders if t < p["film_offset"] + p["duration"])
            local_norm = (t - pr["film_offset"]) / pr["duration"]
        return sample_frame(
            pr["path"],
            local_norm,
            pr["img_np"],
            pr["img_w"],
            pr["img_h"],
            out_w,
            out_h,
        )

    output_path = _ensure_output_path(saveas)
    if not output_path.suffix or output_path.suffix.lower() not in _VIDEO_EXTS:
        output_path = output_path.with_suffix(".mp4")

    clip = frame_exact_clip(make_frame, film_duration, fps)
    if audio_path is not None:
        clip = clip.with_audio(mp.AudioFileClip(str(audio_path)))

    return write_clip(clip, output_path, codec=codec, audio_codec=audio_codec, **write_kwargs)
