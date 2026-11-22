"""Error branches and edge cases of ``BurnsPath`` and ``Rect`` construction and serialisation."""

import pytest

from burns import BurnsPath, Rect


FULL = Rect(0, 0, 1, 1)
ZOOMED = Rect(0.25, 0.25, 0.5, 0.5)


def test_keyframes_must_be_non_empty():
    with pytest.raises(ValueError, match="non-empty"):
        BurnsPath(keyframes=())


def test_keyframe_times_must_increase():
    with pytest.raises(ValueError, match="strictly increase"):
        BurnsPath(keyframes=((0.0, FULL), (0.0, ZOOMED)))


@pytest.mark.parametrize("times", [(-0.1, 1.0), (0.0, 1.5)])
def test_keyframe_times_must_lie_in_unit_interval(times):
    with pytest.raises(ValueError, match=r"lie in \[0, 1\]"):
        BurnsPath(keyframes=((times[0], FULL), (times[1], ZOOMED)))


def test_only_linear_interp_implemented():
    with pytest.raises(ValueError, match="only interp='linear'"):
        BurnsPath(keyframes=((0.0, FULL), (1.0, ZOOMED)), interp="spline")


def test_callable_easing_is_not_serialisable():
    p = BurnsPath(keyframes=((0.0, FULL), (1.0, ZOOMED)), easing=lambda t: t)
    with pytest.raises(ValueError, match="callable easing is not serializable"):
        p.to_dict()


def test_tuple_easing_round_trips_through_the_wire():
    p = BurnsPath(keyframes=((0.0, FULL), (1.0, ZOOMED)), easing=(0.4, 0.0, 0.2, 1.0))
    d = p.to_dict()
    assert d["easing"] == [0.4, 0.0, 0.2, 1.0]
    back = BurnsPath.from_dict(d)
    assert back.easing == (0.4, 0.0, 0.2, 1.0)
    assert back.keyframes == p.keyframes


def test_rect_aspect_is_width_over_height():
    assert Rect(0, 0, 0.5, 0.25).aspect == 2.0


def test_from_center_zoom_portrait_and_invalid_zoom():
    r = Rect.from_center_zoom(0.5, 0.5, 2.0, aspect=0.5)
    assert (r.h, r.w) == (0.5, 0.25)
    with pytest.raises(ValueError, match="zoom must be > 0"):
        Rect.from_center_zoom(0.5, 0.5, 0)


def test_clamped_oversized_window_is_centred():
    from burns.rect import _clamp_corner

    assert _clamp_corner(0.3, 1.5) == -0.25
    assert _clamp_corner(-1.0, 0.5) == 0.0
    assert _clamp_corner(0.9, 0.5) == 0.5
