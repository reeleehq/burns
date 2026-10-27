"""Tests for the frame mapping and the renderers.

The renders use moviepy's bundled ffmpeg, so they run offline. Synthetic images
use even dimensions (libx264 requires even width/height).
"""

import numpy as np
import pytest
from pathlib import Path

from burns import BurnsPath, Rect, ken_burns_film, ken_burns_path, ken_burns_video
from burns._frame import even, output_size_for, sample_frame


def _gradient_image(width: int = 64, height: int = 48) -> np.ndarray:
    img = np.empty((height, width, 3), dtype=np.uint8)
    img[..., 0] = np.linspace(0, 255, width, dtype=np.uint8)[None, :]
    img[..., 1] = np.linspace(0, 255, height, dtype=np.uint8)[:, None]
    img[..., 2] = 128
    return img


class TestFrameMapping:
    def test_even_snaps_down(self):
        assert (even(101), even(100), even(1)) == (100, 100, 2)

    def test_output_size_defaults_to_image(self):
        assert output_size_for(800, 600, output_aspect=None) == (800, 600)

    def test_output_size_from_aspect_keeps_height(self):
        assert output_size_for(800, 600, output_aspect=1.0) == (600, 600)

    def test_explicit_output_size_wins_and_snaps_even(self):
        assert output_size_for(800, 600, output_aspect=2.0, output_size=(101, 99)) == (
            100,
            98,
        )

    def test_sample_frame_returns_output_dims(self):
        img = _gradient_image()
        path = BurnsPath.push_in(1.5)
        frame = sample_frame(path, 0.5, img, 64, 48, 64, 48)
        assert frame.shape[:2] == (48, 64)

    def test_sample_frame_cover_crops_to_output_aspect(self):
        # A 4:3 source rendered to a 1:1 output frame must come out square,
        # not stretched — the cover-crop trims the wide sides.
        img = _gradient_image(64, 48)
        path = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 1, 1))
        frame = sample_frame(path, 0.0, img, 64, 48, 48, 48)
        assert frame.shape[:2] == (48, 48)


class TestKenBurnsVideo:
    def test_renders_default_push_in(self, tmp_path):
        out = tmp_path / "out.mp4"
        result = ken_burns_video(
            _gradient_image(), duration=0.4, fps=10, saveas=str(out)
        )
        assert result.exists() and result.stat().st_size > 0

    def test_auto_names_from_source(self, tmp_path):
        src = tmp_path / "photo.png"
        from PIL import Image

        Image.fromarray(_gradient_image()).save(src)
        result = ken_burns_video(str(src), duration=0.4, fps=10)
        assert result == tmp_path / "photo_kenburns.mp4"
        assert result.exists()

    def test_output_aspect_independent_of_source(self, tmp_path):
        # 4:3 source -> 16:9 output: the spec's headline capability.
        out = tmp_path / "wide.mp4"
        path = ken_burns_path(1, output_aspect=16 / 9)
        ken_burns_video(
            _gradient_image(64, 48), path, duration=0.4, fps=10, saveas=str(out)
        )
        import imageio.v3 as iio

        frame = iio.imread(str(out), index=0)
        assert frame.shape[1] > frame.shape[0]  # wider than tall

    def test_invalid_duration_raises(self):
        with pytest.raises(ValueError, match="duration must be"):
            ken_burns_video(_gradient_image(), duration=0.0)


class TestKenBurnsFilm:
    def test_renders_multipanel(self, tmp_path):
        img = _gradient_image()
        panels = [(img, ken_burns_path(i), 0.3) for i in (1, 2, 3)]
        out = tmp_path / "film.mp4"
        result = ken_burns_film(panels, saveas=str(out), fps=10)
        assert result.exists() and result.stat().st_size > 0

    @pytest.mark.parametrize("encode_fails", [False, True])
    def test_a_film_with_audio_leaves_nothing_in_the_cwd_or_beside_it(self, tmp_path, monkeypatch, encode_fails):
        """MoviePy muxes audio through a temp file in the cwd unless told otherwise and
        removes it only after a successful encode, so a failed one left it wherever the
        caller ran (reeleehq/reelee#747); burns keeps it in a directory it removes."""
        import wave

        import moviepy.video.VideoClip as moviepy_clip

        sound = tmp_path / "in" / "tone.wav"
        sound.parent.mkdir()
        with wave.open(str(sound), "wb") as w:
            w.setnchannels(1), w.setsampwidth(2), w.setframerate(8000)
            w.writeframes(np.zeros(8000, dtype=np.int16).tobytes())
        if encode_fails:
            def broken_encoder(*args, **kwargs):
                raise OSError("encoder died")

            monkeypatch.setattr(moviepy_clip, "ffmpeg_write_video", broken_encoder)
        cwd = tmp_path / "cwd"
        cwd.mkdir()
        monkeypatch.chdir(cwd)
        out = tmp_path / "out" / "film.mp4"
        out.parent.mkdir()
        film = [(_gradient_image(), ken_burns_path(1), 0.5)]
        if encode_fails:
            with pytest.raises(OSError, match="encoder died"):
                ken_burns_film(film, saveas=str(out), fps=10, audio_path=str(sound))
        else:
            ken_burns_film(film, saveas=str(out), fps=10, audio_path=str(sound))
        assert list(cwd.iterdir()) == []
        assert [p.name for p in out.parent.iterdir()] == ([] if encode_fails else ["film.mp4"])

    def test_panel_must_be_triple(self, tmp_path):
        with pytest.raises(ValueError, match="triple"):
            ken_burns_film(
                [(_gradient_image(), ken_burns_path(1))],  # missing duration
                saveas=str(tmp_path / "x.mp4"),
            )

    def test_panel_path_must_be_burnspath(self, tmp_path):
        with pytest.raises(ValueError, match="must be a BurnsPath"):
            ken_burns_film(
                [(_gradient_image(), [(0, 0, 1)], 1.0)],
                saveas=str(tmp_path / "x.mp4"),
            )
