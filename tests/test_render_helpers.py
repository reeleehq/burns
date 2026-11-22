"""Pure helper branches of ``burns.render`` (no encoding): image loading, output naming, input validation."""

import numpy as np
import pytest
from PIL import Image

from burns import BurnsPath, Rect, ken_burns_film, ken_burns_video
from burns import render


def _arr(w=8, h=6):
    return np.zeros((h, w, 3), dtype=np.uint8)


# --- _load_image ------------------------------------------------------------


def test_load_image_from_path_reports_source(tmp_path):
    p = tmp_path / "a.png"
    Image.new("RGBA", (8, 6)).save(p)
    arr, w, h, src = render._load_image(str(p), where="t")
    assert (w, h, arr.shape, src) == (8, 6, (6, 8, 3), p)


def test_load_image_from_ndarray_and_pil():
    arr, w, h, src = render._load_image(_arr(), where="t")
    assert (w, h, src) == (8, 6, None)
    arr, w, h, src = render._load_image(Image.new("L", (4, 2)), where="t")
    assert (w, h, arr.shape) == (4, 2, (2, 4, 3))


def test_load_image_rejects_other_types():
    with pytest.raises(ValueError, match="where-label: unsupported image type"):
        render._load_image(42, where="where-label")


# --- _resolve_output --------------------------------------------------------


def test_resolve_output_explicit_forces_video_extension(tmp_path):
    assert render._resolve_output(str(tmp_path / "x.mp4"), None).suffix == ".mp4"
    assert render._resolve_output(str(tmp_path / "x"), None).suffix == ".mp4"
    assert render._resolve_output(str(tmp_path / "x.txt"), None).suffix == ".mp4"


def test_resolve_output_without_source_goes_to_tempdir():
    out = render._resolve_output(None, None)
    assert out.name.startswith("kenburns_") and out.suffix == ".mp4"


def test_resolve_output_auto_names_beside_source_and_avoids_collision(tmp_path):
    src = tmp_path / "pic.png"
    first = render._resolve_output(None, src)
    assert first.parent == tmp_path and first.suffix == ".mp4"
    first.write_bytes(b"x")
    second = render._resolve_output(None, src)
    assert second != first and second.parent == tmp_path


# --- validation -------------------------------------------------------------


def _path():
    return BurnsPath.push_in(1.5)


def test_video_rejects_non_positive_duration():
    with pytest.raises(ValueError, match="duration must be > 0"):
        ken_burns_video(_arr(), _path(), duration=0)


@pytest.mark.parametrize(
    "panel, msg",
    [
        ("nope", "expected \\(image, path, duration_s\\) triple"),
        ((_arr(), "notapath", 1.0), "path must be a BurnsPath"),
    ],
)
def test_film_rejects_malformed_panels(panel, msg, tmp_path):
    with pytest.raises(ValueError, match=msg):
        ken_burns_film([panel], saveas=str(tmp_path / "f.mp4"))


def test_film_rejects_non_positive_panel_duration(tmp_path):
    with pytest.raises(ValueError, match="duration_s must be > 0"):
        ken_burns_film([(_arr(), _path(), 0)], saveas=str(tmp_path / "f.mp4"))


def test_film_rejects_empty_panels(tmp_path):
    with pytest.raises(ValueError, match="non-empty"):
        ken_burns_film([], saveas=str(tmp_path / "f.mp4"))
