"""Tests for the render-agnostic motion spec: Rect, easing, and BurnsPath.

These exercise the pure ``t -> Rect`` core (no rendering, no I/O), which is the
single source of truth a future JS/TS implementation must match.
"""

import pytest

from burns import BurnsPath, Rect, ken_burns_path, parse_easing
from burns.easing import CSS_BEZIERS


class TestRect:
    def test_full_image(self):
        full = Rect(0, 0, 1, 1)
        assert full.center == (0.5, 0.5)
        assert full.zoom == 1.0
        assert full.is_contained()

    def test_from_center_zoom_is_centered_and_contained(self):
        r = Rect.from_center_zoom(0.5, 0.5, 2.0)
        assert r == Rect(0.25, 0.25, 0.5, 0.5)
        assert r.is_contained()

    def test_clamped_rides_the_wall_keeping_size(self):
        # Sliding past an edge must keep w/h (no breathing) — only the corner moves.
        r = Rect(0.8, 0.0, 0.5, 0.5).clamped()
        assert (r.w, r.h) == (0.5, 0.5)
        assert r.x == 0.5 and r.is_contained()

    def test_to_pixels_rounds_inside_image(self):
        assert Rect(0, 0, 1, 1).to_pixels(100, 80) == (0, 0, 100, 80)
        assert Rect.from_center_zoom(0.5, 0.5, 2.0).to_pixels(100, 80) == (
            25,
            20,
            75,
            60,
        )

    def test_lerp(self):
        mid = Rect(0, 0, 1, 1).lerp(Rect(0.25, 0.25, 0.5, 0.5), 0.5)
        assert mid == Rect(0.125, 0.125, 0.75, 0.75)


class TestEasing:
    def test_named_easings_resolve(self):
        for name in CSS_BEZIERS:
            f = parse_easing(name)
            assert abs(f(0.0)) < 1e-9 and abs(f(1.0) - 1.0) < 1e-9

    def test_linear_is_identity(self):
        f = parse_easing("linear")
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            assert abs(f(t) - t) < 1e-6

    def test_ease_in_out_is_symmetric_and_slow_at_ends(self):
        f = parse_easing("ease-in-out")
        assert abs(f(0.5) - 0.5) < 1e-6  # symmetric midpoint
        assert f(0.1) < 0.1 and f(0.9) > 0.9  # slow-in, slow-out

    def test_cubic_bezier_string(self):
        f = parse_easing("cubic-bezier(0, 0, 1, 1)")
        assert abs(f(0.7) - 0.7) < 1e-6

    def test_tuple_and_callable(self):
        assert abs(parse_easing((0, 0, 1, 1))(0.3) - 0.3) < 1e-6
        assert parse_easing(lambda t: t * t)(0.5) == 0.25

    def test_unknown_raises(self):
        with pytest.raises(ValueError, match="unknown easing"):
            parse_easing("boing")


class TestBurnsPath:
    def test_evaluate_endpoints(self):
        p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5))
        assert p.evaluate(0.0) == Rect(0, 0, 1, 1)
        assert p.evaluate(1.0) == Rect(0, 0, 0.5, 0.5)

    def test_evaluate_clamps_out_of_range_t(self):
        p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5))
        assert p.evaluate(-1.0) == p.evaluate(0.0)
        assert p.evaluate(2.0) == p.evaluate(1.0)

    def test_linear_midpoint(self):
        p = BurnsPath.from_start_end(
            Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing="linear"
        )
        assert p.evaluate(0.5) == Rect(0, 0, 0.75, 0.75)

    def test_easing_composes_over_geometry(self):
        # ease-in-out: at t=0.5 progress is exactly 0.5 (symmetric), so the
        # eased midpoint equals the linear midpoint; but at t=0.1 it lags.
        eased = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 0, 0))
        linear = BurnsPath.from_start_end(
            Rect(0, 0, 1, 1), Rect(0, 0, 0, 0), easing="linear"
        )
        assert eased.evaluate(0.5).w == pytest.approx(linear.evaluate(0.5).w)
        assert eased.evaluate(0.1).w > linear.evaluate(0.1).w  # slow start

    def test_reversed_swaps_endpoints(self):
        p = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5))
        r = p.reversed()
        assert r.evaluate(0.0) == Rect(0, 0, 0.5, 0.5)
        assert r.evaluate(1.0) == Rect(0, 0, 1, 1)

    def test_multi_keyframe(self):
        p = BurnsPath(
            keyframes=(
                (0.0, Rect(0, 0, 1, 1)),
                (0.5, Rect(0.25, 0.25, 0.5, 0.5)),
                (1.0, Rect(0, 0, 1, 1)),
            ),
            easing="linear",
        )
        assert p.evaluate(0.5) == Rect(0.25, 0.25, 0.5, 0.5)

    def test_serialization_round_trip(self):
        p = BurnsPath.push_in(1.4, to=(0.6, 0.4), output_aspect=1.5)
        assert BurnsPath.from_dict(p.to_dict()) == p

    def test_serialized_shape(self):
        d = BurnsPath.from_start_end(Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5)).to_dict()
        assert d["version"] == 1
        assert d["easing"] == "ease-in-out"
        assert d["keyframes"][0] == {
            "t": 0.0,
            "rect": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0},
        }

    def test_callable_easing_is_not_serializable(self):
        p = BurnsPath.from_start_end(
            Rect(0, 0, 1, 1), Rect(0, 0, 0.5, 0.5), easing=lambda t: t
        )
        with pytest.raises(ValueError, match="not serializable"):
            p.to_dict()

    def test_bad_keyframes_raise(self):
        with pytest.raises(ValueError, match="non-empty"):
            BurnsPath(keyframes=())
        with pytest.raises(ValueError, match="strictly increase"):
            BurnsPath(keyframes=((0.0, Rect(0, 0, 1, 1)), (0.0, Rect(0, 0, 1, 1))))


class TestKenBurnsPath:
    def test_is_deterministic(self):
        assert ken_burns_path(3) == ken_burns_path(3)

    def test_two_keyframe_start_end(self):
        assert ken_burns_path(1).duration_keyframes == 2

    def test_odd_pushes_in_even_pulls_out(self):
        odd = ken_burns_path(1)
        even = ken_burns_path(2)
        # Odd: starts at the full image, ends zoomed in.
        assert odd.evaluate(0.0).zoom == pytest.approx(1.0)
        assert odd.evaluate(1.0).zoom > 1.0
        # Even: starts zoomed, ends at the full image.
        assert even.evaluate(0.0).zoom > 1.0
        assert even.evaluate(1.0).zoom == pytest.approx(1.0)

    def test_focal_offset_uses_pan(self):
        end = ken_burns_path(1, pan=0.03, zoom=1.15).evaluate(1.0)
        cx, cy = end.center
        magnitude = ((cx - 0.5) ** 2 + (cy - 0.5) ** 2) ** 0.5
        assert magnitude == pytest.approx(0.03, abs=2e-3)

    def test_drift_is_horizontal_and_alternates(self):
        odd = ken_burns_path(1, style="drift", pan=0.1)
        even = ken_burns_path(2, style="drift", pan=0.1)
        # No vertical motion.
        assert odd.evaluate(0.0).center[1] == pytest.approx(odd.evaluate(1.0).center[1])
        # Opposite horizontal directions.
        odd_dx = odd.evaluate(1.0).center[0] - odd.evaluate(0.0).center[0]
        even_dx = even.evaluate(1.0).center[0] - even.evaluate(0.0).center[0]
        assert odd_dx * even_dx < 0

    def test_easing_passthrough(self):
        assert ken_burns_path(1, easing="linear").easing == "linear"

    def test_invalid_style_raises(self):
        with pytest.raises(ValueError, match="style must be"):
            ken_burns_path(1, style="spin")

    def test_output_aspect_carried(self):
        p = ken_burns_path(1, output_aspect=16 / 9)
        assert p.output_aspect == pytest.approx(16 / 9)


class TestImageAspect:
    """burns#30: constructors built rects as if the source were square."""

    @pytest.mark.parametrize("size", [(1600, 900), (1200, 1600), (1600, 1200)])
    def test_push_in_starts_on_the_frame_the_render_fills(self, size):
        from burns._frame import sample_box

        img_w, img_h = size
        out_w, out_h = 1024, 576
        path = BurnsPath.push_in(
            1.2, output_aspect=out_w / out_h, image_aspect=img_w / img_h
        )
        x0, y0, x1, y1 = sample_box(path, 0.0, img_w, img_h, out_w, out_h)
        # zoom 1.0 is the largest output-shaped window the image holds
        full_w = min(img_w, img_h * out_w / out_h)
        assert (x1 - x0) == pytest.approx(full_w, abs=1)
        assert (y1 - y0) == pytest.approx(full_w * out_h / out_w, abs=1)

    def test_the_headline_case_is_the_full_frame(self):
        start = BurnsPath.push_in(
            1.2, to=(0.45, 0.5), output_aspect=1024 / 576, image_aspect=16 / 9
        ).evaluate(0.0)
        assert start == Rect(0.0, 0.0, 1.0, 1.0)

    def test_ken_burns_path_honours_it_too(self):
        p = ken_burns_path(1, output_aspect=16 / 9, image_aspect=16 / 9)
        assert p.evaluate(0.0) == Rect(0.0, 0.0, 1.0, 1.0)

    @pytest.mark.parametrize("style", ["push", "drift"])
    @pytest.mark.parametrize("index", [1, 2])
    @pytest.mark.parametrize(
        "size,out",
        [
            ((1600, 900), (1024, 576)),
            ((1600, 900), (576, 1024)),
            ((1600, 900), (500, 500)),
            ((3500, 500), (1024, 576)),
            ((1200, 1600), (1024, 576)),
        ],
    )
    def test_no_extra_crop_at_any_t(self, style, index, size, out):
        """The path's own window already has the output's shape, so cover-crop trims nothing."""
        from burns._frame import sample_box

        (img_w, img_h), (out_w, out_h) = size, out
        path = ken_burns_path(
            index,
            style=style,
            output_aspect=out_w / out_h,
            image_aspect=img_w / img_h,
        )
        for t in (0.0, 0.5, 1.0):
            rect = path.evaluate(t)
            x0, y0, x1, y1 = rect.to_pixels(img_w, img_h)
            assert sample_box(path, t, img_w, img_h, out_w, out_h) == pytest.approx(
                (x0, y0, x1, y1), abs=2
            )

    def test_drift_does_not_over_zoom_a_height_limited_window(self):
        p = ken_burns_path(
            1, style="drift", pan=0.3, output_aspect=9 / 16, image_aspect=16 / 9
        )
        assert p.evaluate(0.0).h > 0.9, "a 9:16 window of a 16:9 still fills its height"

    @pytest.mark.parametrize("bad", [0, -1.0, float("inf"), float("nan")])
    def test_non_positive_or_non_finite_aspects_are_refused(self, bad):
        with pytest.raises(ValueError, match="aspect"):
            BurnsPath.push_in(output_aspect=bad, image_aspect=1.0)
        with pytest.raises(ValueError, match="aspect"):
            BurnsPath.push_in(output_aspect=16 / 9, image_aspect=bad)

    def test_omitting_it_warns_and_keeps_the_square_assumption(self):
        with pytest.warns(FutureWarning, match="image_aspect"):
            legacy = BurnsPath.push_in(1.2, output_aspect=16 / 9).evaluate(0.0)
        assert legacy.h == pytest.approx(0.5625)
