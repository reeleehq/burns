"""The ffmpeg backend: does it frame the shot where the pillow backend does?

The question that matters is not "does it produce a file" — a wrong crop
produces a file too. So the load-bearing tests compare the rendered pixels
against `burns._frame.sample_frame`, which is the mapping the golden vectors
already pin, and against the pillow backend itself.

Two numbers to read these by, both measured while building the backend:

- On a **smooth** image the two backends agree at ~52 dB.
- On an image with hard edges they agree at ~34 dB, and that gap is resampler
  choice (Pillow BICUBIC against swscale), not geometry. So the parity tests
  use smooth images deliberately — a grid would measure the resampler and call
  it a framing bug.

Offline: the binary comes from `imageio-ffmpeg`, which `moviepy` already pulls
in, so these need no system ffmpeg and no network.
"""

import subprocess
import sys

import numpy as np
import pytest
from PIL import Image

from burns import BurnsPath, Rect, ken_burns_path, ken_burns_video
from burns._ffmpeg import (
    DFLT_WRITE_KWARGS,
    SAMPLE_LADDER,
    FfmpegBackendError,
    default_ffmpeg_exe,
    keyframes_for,
    sample_count,
)
from burns._frame import sample_frame
from burns.backends import DFLT_BACKEND, frame_count, RENDER_BACKENDS, get_backend

#: Above this, two renders differ only by resampler choice. Measured separation
#: is wide: correct pairings score 43-52 dB and a one-window-off control scores 11.
SAME_FRAMING_DB = 40.0


def smooth_image(width: int = 640, height: int = 480) -> np.ndarray:
    """No hard edges, so a comparison measures framing rather than resampling."""
    img = np.empty((height, width, 3), dtype=np.uint8)
    img[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    img[..., 1] = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    img[..., 2] = 128
    return img


def render(
    img,
    path,
    out,
    *,
    duration=1.0,
    fps=25,
    out_w=640,
    out_h=480,
    backend="ffmpeg",
    **kwargs,
):
    height, width = img.shape[:2]
    return get_backend(backend)(
        img,
        width,
        height,
        path,
        duration=duration,
        fps=fps,
        output=out,
        out_w=out_w,
        out_h=out_h,
        codec="libx264",
        audio_codec="aac",
        **kwargs,
    )


def first_frame(video) -> np.ndarray:
    png = video.with_suffix(".png")
    subprocess.run(
        [
            default_ffmpeg_exe(),
            "-v",
            "error",
            "-y",
            "-i",
            str(video),
            "-frames:v",
            "1",
            str(png),
        ],
        check=True,
        capture_output=True,
    )
    return np.asarray(Image.open(png).convert("RGB")).astype(int)


def psnr(a: np.ndarray, b: np.ndarray) -> float:
    mse = ((a.astype(int) - b.astype(int)) ** 2).mean()
    return float("inf") if mse == 0 else 10 * np.log10(255**2 / mse)


def probe(video) -> tuple[int, int, int]:
    """``(width, height, frames)``, read with ffmpeg rather than ffprobe.

    `imageio-ffmpeg` bundles **ffmpeg only**. An earlier version of this helper
    shelled out to `ffprobe`, which is on a developer's machine via Homebrew and
    is not on the CI runner — so four tests passed locally and died with
    `FileNotFoundError` in CI, before the skip guard could even run. Reading the
    numbers out of ffmpeg's own report keeps these tests dependent on exactly
    the binary the backend itself uses, and on nothing else.
    """
    import re

    from burns._ffmpeg import probe_video

    proc = subprocess.run(
        [default_ffmpeg_exe(), "-hide_banner", "-i", str(video), "-f", "null", "-"],
        capture_output=True,
        text=True,
    )
    size = re.search(r"Stream #0:0.*?[ ,](\d{2,5})x(\d{2,5})", proc.stderr)
    assert size, f"could not read {video.name} from:\n{proc.stderr[-900:]}"
    frames, _ = probe_video(default_ffmpeg_exe(), video)
    return int(size.group(1)), int(size.group(2)), frames


class TestItIsRegistered:
    def test_the_backend_is_reachable_by_name(self):
        assert "ffmpeg" in RENDER_BACKENDS
        assert get_backend("ffmpeg") is RENDER_BACKENDS["ffmpeg"]

    def test_pillow_is_still_the_default(self):
        """The two are not pixel-equivalent, so flipping the default would
        silently change every existing caller's output."""
        assert DFLT_BACKEND == "pillow"

    def test_importing_burns_does_not_pull_looks(self):
        """The backend is deferred, so a caller who never asks for it pays
        nothing — the same courtesy `looks` extends its own CLI."""
        # `sys.executable`, never a bare "python": on the Windows runner the
        # bare name resolved to a different interpreter, which had no moviepy
        # and failed with an error that looked nothing like the real question.
        code = "import sys; import burns; print('looks' in sys.modules)"
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True
        )
        assert out.stdout.strip() == "False", out.stdout + out.stderr


class TestItFramesTheShotWhereBurnsSaysItShould:
    """Against `sample_frame`, the mapping the golden vectors already pin."""

    def test_the_first_frame_matches_burns_own_reference(self, tmp_path):
        img = smooth_image()
        path = BurnsPath.push_in(1.35)
        video = render(img, path, tmp_path / "a.mp4", out_w=1280, out_h=720)
        reference = sample_frame(path, 0.0, img, 640, 480, 1280, 720)
        assert psnr(first_frame(video), reference) > SAME_FRAMING_DB

    def test_it_is_not_merely_close_to_any_frame(self, tmp_path):
        """The control. Without it the test above passes for a backend that
        renders a plausible but wrong window."""
        img = smooth_image()
        path = BurnsPath.push_in(1.35)
        video = render(img, path, tmp_path / "a.mp4", out_w=1280, out_h=720)
        wrong = sample_frame(path, 1.0, img, 640, 480, 1280, 720)
        assert psnr(first_frame(video), wrong) < SAME_FRAMING_DB

    def test_the_two_backends_agree_on_a_smooth_image(self, tmp_path):
        img = smooth_image()
        path = BurnsPath.push_in(1.3)
        a = render(
            img, path, tmp_path / "pillow.mp4", backend="pillow", out_w=640, out_h=480
        )
        b = render(
            img, path, tmp_path / "ffmpeg.mp4", backend="ffmpeg", out_w=640, out_h=480
        )
        assert psnr(first_frame(a), first_frame(b)) > SAME_FRAMING_DB

    def test_the_headline_case_renders(self, tmp_path):
        """A 4:3 source delivered at 16:9 — what `output_aspect` is for, and
        the case `looks` had to grow a reframe to express at all."""
        img = smooth_image(640, 480)
        path = ken_burns_path(0, output_aspect=16 / 9)
        video = render(img, path, tmp_path / "wide.mp4", out_w=1280, out_h=720)
        assert probe(video)[:2] == (1280, 720)
        reference = sample_frame(path, 0.0, img, 640, 480, 1280, 720)
        assert psnr(first_frame(video), reference) > SAME_FRAMING_DB


class TestTheOutputIsWhatWasAskedFor:
    def test_size_frame_count_and_duration(self, tmp_path):
        video = render(
            smooth_image(),
            BurnsPath.push_in(1.2),
            tmp_path / "a.mp4",
            duration=2.0,
            fps=25,
            out_w=1280,
            out_h=720,
        )
        width, height, frames = probe(video)
        assert (width, height) == (1280, 720)
        assert frames == 50, "d=1 is what keeps zoompan 1:1 with the input"

    @pytest.mark.parametrize("size", [(640, 480), (480, 640), (1000, 1000)])
    def test_a_constant_zoom_pan_has_the_pillow_frame_count(self, tmp_path, size):
        """Guard (not a repro) for burns#31: a pure pan once came out 225 frames for 270."""
        keys = (
            (0, Rect(0.078, 0.3103, 0.6897, 0.6897)),
            (1, Rect(0.2323, 0.3103, 0.6897, 0.6897)),
        )
        video = render(
            smooth_image(*size),
            BurnsPath(keyframes=keys),
            tmp_path / "pan.mp4",
            duration=3.0,
            fps=30,
            out_w=640,
            out_h=360,
        )
        assert probe(video)[2] == frame_count(3.0, 30) == 90

    def test_a_wrong_frame_count_is_refused_naming_pillow(self, tmp_path, monkeypatch):
        monkeypatch.setattr("burns._ffmpeg.probe_video", lambda *a: (75, 30.0))
        with pytest.raises(FfmpegBackendError, match='backend="pillow"'):
            render(smooth_image(), BurnsPath.push_in(1.2), tmp_path / "x.mp4")

    def test_a_wrong_frame_rate_is_refused(self, tmp_path, monkeypatch):
        """The 225-for-270 shape: the right count at the wrong clock (burns#31)."""
        monkeypatch.setattr("burns._ffmpeg.probe_video", lambda *a: (90, 25.0))
        with pytest.raises(FfmpegBackendError, match='backend="pillow"'):
            render(
                smooth_image(),
                BurnsPath.push_in(1.2),
                tmp_path / "r.mp4",
                duration=3.0,
                fps=30,
            )

    @pytest.mark.parametrize(
        "duration,fps", [(1.99, 30), (0.01, 30), (2.01, 25), (0.29, 100)]
    )
    def test_both_backends_share_one_frame_count(self, tmp_path, duration, fps):
        """burns#33: moviepy floors, so pillow used to differ from ffmpeg."""
        counts = {}
        for backend in ("pillow", "ffmpeg"):
            video = render(
                smooth_image(),
                BurnsPath.push_in(1.2),
                tmp_path / f"{backend}.mp4",
                duration=duration,
                fps=fps,
                backend=backend,
            )
            counts[backend] = probe(video)[2]
        assert counts["pillow"] == counts["ffmpeg"] == frame_count(duration, fps)

    def test_a_path_that_looks_like_progress_output_is_counted_correctly(
        self, tmp_path
    ):
        video = render(
            smooth_image(), BurnsPath.push_in(1.2), tmp_path / "frame=7.mp4", fps=25
        )
        assert probe(video)[2] == 25

    def test_a_static_path_still_renders(self, tmp_path):
        """No zoom, no pan — it takes the `crop` branch, and `crop` emits the
        window's own odd pixel size unless something scales it."""
        still = BurnsPath.from_start_end(
            Rect(0.1, 0.1, 0.7123, 0.7123), Rect(0.1, 0.1, 0.7123, 0.7123)
        )
        video = render(smooth_image(), still, tmp_path / "a.mp4", out_w=640, out_h=480)
        assert probe(video)[:2] == (640, 480)


class TestSamplingIsMeasuredNotGuessed:
    def test_more_pixels_need_more_samples(self):
        path = BurnsPath.push_in(1.35)
        assert sample_count(path, 640, 480, 1280, 720) < sample_count(
            path, 3840, 2160, 1280, 720
        )

    def test_every_count_comes_from_the_ladder(self):
        path = BurnsPath.push_in(1.35)
        for size in (320, 640, 1920, 3840):
            assert sample_count(path, size, size, 1280, 720) in SAMPLE_LADDER

    def test_an_explicit_count_is_honoured(self):
        frames = keyframes_for(
            BurnsPath.push_in(1.2),
            duration=2.0,
            img_w=640,
            img_h=480,
            out_w=640,
            out_h=480,
            samples=5,
        )
        assert len(frames) == 5

    def test_the_keyframe_clock_is_SECONDS_not_normalised(self):
        """The two clocks meet in this adapter and they are not the same one.
        Confusing them yields a path that runs in the first second of a
        ten-second clip and then holds — which renders perfectly."""
        frames = keyframes_for(
            BurnsPath.push_in(1.2),
            duration=10.0,
            img_w=640,
            img_h=480,
            out_w=640,
            out_h=480,
            samples=3,
        )
        assert [k.t for k in frames] == [0.0, 5.0, 10.0]

    def test_one_sample_is_refused(self):
        with pytest.raises(FfmpegBackendError, match="at least 2"):
            keyframes_for(
                BurnsPath.push_in(1.2),
                duration=1.0,
                img_w=64,
                img_h=48,
                out_w=64,
                out_h=48,
                samples=1,
            )

    def test_every_window_carries_the_output_aspect_exactly(self):
        """`zoompan` can show only one shape, so every keyframe window must
        carry the same aspect. `sample_box_exact` cover-crops in floats, so it
        does — where the integer `sample_box` this once read spread the ratio
        across a pixel of quantisation and needed the aspect reconstructed."""
        frames = keyframes_for(
            ken_burns_path(0, output_aspect=16 / 9),
            duration=2.0,
            img_w=640,
            img_h=480,
            out_w=1280,
            out_h=720,
            samples=17,
        )
        ratios = {round(k.window.w / k.window.h, 9) for k in frames}
        assert len(ratios) == 1, ratios
        assert abs(ratios.pop() - (16 / 9) * (480 / 640)) < 1e-9


class TestItIsNotADropInSwapAndSaysSo:
    def test_an_unrecognised_write_kwarg_raises(self, tmp_path):
        """Silently dropping it would make `backend="ffmpeg"` look like a
        drop-in swap for the pillow backend when it is not."""
        with pytest.raises(FfmpegBackendError, match="does not understand"):
            render(
                smooth_image(64, 48),
                BurnsPath.push_in(1.2),
                tmp_path / "a.mp4",
                out_w=64,
                out_h=48,
                threads=4,
            )

    def test_moviepys_logger_is_accepted_and_ignored(self, tmp_path):
        """The pillow backend defaults it, so a caller forwarding its own
        defaults must not trip the refusal above."""
        video = render(
            smooth_image(64, 48),
            BurnsPath.push_in(1.2),
            tmp_path / "a.mp4",
            out_w=64,
            out_h=48,
            logger=None,
        )
        assert video.exists()

    def test_the_encode_defaults_match_the_pillow_backend(self):
        """Without this, swapping backends changes the file size fourfold —
        measured 270 KB against 1084 KB for one 2 s clip."""
        assert DFLT_WRITE_KWARGS == {"bitrate": "5000k", "preset": "medium"}

    def test_a_path_looks_refuses_names_the_way_through(self, tmp_path):
        """A zoom past 10x is clamped SILENTLY by zoompan, so `looks` refuses
        it. burns must pass that refusal on, naming the backend that can."""
        deep = BurnsPath.from_start_end(
            Rect(0.0, 0.0, 1.0, 1.0), Rect(0.45, 0.45, 0.05, 0.05)
        )
        with pytest.raises(FfmpegBackendError, match='backend="pillow"'):
            render(
                smooth_image(64, 48),
                deep,
                tmp_path / "a.mp4",
                out_w=64,
                out_h=48,
            )


class TestTheBinaryIsAChoice:
    def test_it_defaults_to_the_one_moviepy_already_brings(self):
        exe = default_ffmpeg_exe()
        assert "ffmpeg" in exe.lower()

    def test_a_caller_can_point_it_elsewhere(self, tmp_path):
        """The bundled binary is a GPL build. A caller shipping a commercial
        product may need their own, which is the whole reason this is an
        argument rather than a constant."""
        with pytest.raises(FfmpegBackendError, match="could not run"):
            render(
                smooth_image(64, 48),
                BurnsPath.push_in(1.2),
                tmp_path / "a.mp4",
                out_w=64,
                out_h=48,
                ffmpeg_exe="/nonexistent/ffmpeg",
            )


class TestThroughThePublicFacade:
    """`backend=` on `ken_burns_video`, which is how a caller actually reaches it."""

    def test_both_backends_render_the_headline_case_the_same_shape(self, tmp_path):
        source = tmp_path / "photo.png"
        Image.fromarray(smooth_image(640, 480)).save(source)
        wide = ken_burns_path(0, output_aspect=16 / 9)  # 4:3 source, 16:9 delivery
        shapes = {}
        for backend in ("pillow", "ffmpeg"):
            out = ken_burns_video(
                source,
                wide,
                saveas=tmp_path / f"{backend}.mp4",
                duration=1.5,
                fps=24,
                backend=backend,
                output_size=(1280, 720),
            )
            shapes[backend] = probe(out)
        assert shapes["ffmpeg"] == shapes["pillow"] == (1280, 720, 36)

    def test_an_unknown_backend_still_names_what_is_available(self, tmp_path):
        source = tmp_path / "photo.png"
        Image.fromarray(smooth_image(64, 48)).save(source)
        with pytest.raises(ValueError, match="ffmpeg"):
            ken_burns_video(source, saveas=tmp_path / "a.mp4", backend="nonesuch")
