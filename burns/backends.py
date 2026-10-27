"""Pluggable single-clip render backends — the open-closed seam.

A backend turns one ``(image, BurnsPath, duration)`` into one video file. They
all share the :class:`RenderBackend` call signature and live in a name-keyed
:data:`RENDER_BACKENDS` registry, so adding a backend (an FFmpeg ``zoompan``
fast-path, a future GPU path) never edits the facade — you
:func:`register_backend` it and select it with ``backend="…"``.

The default backend, ``"pillow"``, drives a lazy ``moviepy.VideoClip`` whose
per-frame closure calls :func:`burns._frame.sample_frame`, so the whole clip is
never materialized in memory and the spec-to-pixel mapping stays in one place.
The multi-panel film renderer in :mod:`burns.render` deliberately does *not* go
through this registry — it is a single-pass encode across panels, which a
per-clip backend cannot express.
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Callable, Protocol

import moviepy as mp
import numpy as np

from burns._frame import sample_frame
from burns.path import BurnsPath


def frame_count(duration: float, fps: int) -> int:
    """The frames a ``duration``-second clip at ``fps`` has, for every backend.

    The single definition. It rounds, as the fleet's other assemblers do, and
    never returns less than one. moviepy alone would floor (1.99 s at 30 fps is
    59 frames), which is why :func:`pillow_backend` sizes its clip from this.

    Examples:
        >>> frame_count(9.0, 30), frame_count(1.99, 30), frame_count(0.001, 30)
        (270, 60, 1)
    """
    return max(1, round(duration * fps))


#: Fraction of a frame added to a clip's duration. moviepy takes
#: ``int(duration * fps)`` frames, so any value strictly between 0 and 1 makes
#: ``n / fps`` land on ``n`` despite float noise; a quarter keeps the clip
#: well inside the next frame.
_FRAME_MARGIN = 0.25


def frame_exact_clip(make_frame: Callable, duration: float, fps: int) -> mp.VideoClip:
    """A moviepy clip with exactly ``frame_count(duration, fps)`` frames.

    Used by every moviepy-based render path, so they share one frame count.
    """
    n_frames = frame_count(duration, fps)
    return mp.VideoClip(make_frame, duration=(n_frames + _FRAME_MARGIN) / fps).with_fps(
        fps
    )


class RenderBackend(Protocol):
    """Encode one image + :class:`BurnsPath` into a video file at ``output``.

    Args mirror :func:`burns.ken_burns_video` after argument resolution: the
    image is already a decoded ``(H, W, C)`` uint8 array with its pixel size,
    and the output frame size ``(out_w, out_h)`` is already even-snapped.
    Returns the written path.
    """

    def __call__(
        self,
        img_np: np.ndarray,
        img_w: int,
        img_h: int,
        path: BurnsPath,
        *,
        duration: float,
        fps: int,
        output: Path,
        out_w: int,
        out_h: int,
        codec: str,
        audio_codec: str,
        **write_kwargs,
    ) -> Path: ...


def pillow_backend(
    img_np: np.ndarray,
    img_w: int,
    img_h: int,
    path: BurnsPath,
    *,
    duration: float,
    fps: int,
    output: Path,
    out_w: int,
    out_h: int,
    codec: str,
    audio_codec: str,
    **write_kwargs,
) -> Path:
    """Default backend: lazy moviepy ``VideoClip`` + per-frame Pillow resampling.

    Quality default; jitter-free (the window is computed in floating point and
    rasterized once per frame, so there is no FFmpeg ``zoompan`` integer-rounding
    stair-step).
    """

    def make_frame(t):
        # moviepy drives t in seconds; the path's clock is normalized.
        return sample_frame(path, t / duration, img_np, img_w, img_h, out_w, out_h)

    clip = frame_exact_clip(make_frame, duration, fps)
    return write_clip(clip, output, codec=codec, audio_codec=audio_codec, **write_kwargs)


def write_clip(clip: mp.VideoClip, output: Path, *, codec: str, audio_codec: str, **write_kwargs) -> Path:
    """``clip.write_videofile(output)`` with burns' encode defaults, then close it.

    MoviePy muxes audio through a temp file it writes to the **current directory**
    unless told otherwise (``<stem>TEMP_MPY_wvf_snd.<ext>``), so a render left
    one wherever its caller happened to run (reeleehq/reelee#747). It goes in a
    private directory beside ``output`` instead, removed whatever happens.
    """
    write_kwargs.setdefault("bitrate", "5000k")
    write_kwargs.setdefault("preset", "medium")
    write_kwargs.setdefault("logger", None)
    output = Path(output)
    with tempfile.TemporaryDirectory(prefix=".burns-", dir=output.parent) as tmp:
        write_kwargs.setdefault("temp_audiofile_path", tmp)
        clip.write_videofile(str(output), codec=codec, audio_codec=audio_codec, **write_kwargs)
    clip.close()
    return output


def _ffmpeg_backend(*args, **kwargs) -> Path:
    """The ffmpeg backend, imported on first use.

    Deferred so that `import burns` does not pull `looks` in for callers who
    never ask for this backend — the same courtesy `looks` extends its own CLI.
    """
    from burns._ffmpeg import ffmpeg_backend

    return ffmpeg_backend(*args, **kwargs)


RENDER_BACKENDS: dict[str, Callable[..., Path]] = {
    "pillow": pillow_backend,
    "ffmpeg": _ffmpeg_backend,
}

#: Still `pillow`, deliberately. The two backends are NOT pixel-equivalent
#: (measured ~47 dB, dominated by resampler choice rather than by anything
#: either does wrong), so flipping the default would silently change the output
#: of every existing caller. The speed advantage that motivates the ffmpeg path
#: is also still unmeasured — see thorwhalen/burns#12.
DFLT_BACKEND = "pillow"


def register_backend(name: str, backend: Callable[..., Path]) -> None:
    """Register a render backend under ``name`` (open-closed extension point)."""
    RENDER_BACKENDS[name] = backend


def get_backend(name: str = DFLT_BACKEND) -> Callable[..., Path]:
    """Look up a registered backend by name.

    Examples:
        >>> get_backend() is get_backend("pillow")
        True
    """
    try:
        return RENDER_BACKENDS[name]
    except KeyError:
        raise ValueError(
            f"burns: unknown render backend {name!r}. "
            f"Available: {sorted(RENDER_BACKENDS)}"
        ) from None
