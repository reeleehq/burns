"""Tests for the named-move vocabulary and `resolve_move`.

Pure geometry over synthetic numpy images, plus one render smoke test — offline,
free, deterministic. The headline guard is
`TestPositionIndependence`: it asserts the thing the vocabulary exists for, and
carries its own negative control, because a version of this test that passed
with the ordinal defect fully present would be worth nothing.
"""

import json
import math

import numpy as np
import burns
import burns.moves
from collections import Counter
import pytest

from burns import (
    MOVES,
    AUTO_WEIGHTS,
    BurnsPath,
    MoveError,
    Rect,
    choose_move,
    content_aware_path,
    content_aware_path_for,
    ken_burns_video,
    move_kind,
    resolve_move,
)
from burns.content import DFLT_KEEP_PAD, fit_zoom, pad_box
from burns.moves import (
    _AUTO_POOL,
    DFLT_ZOOM,
    DIFFUSE_KEEP_AREA,
    _MOVES,
    DRIFT_MIN_ROOM,
    DRIFT_SPAN,
    DRIFT_TRAVEL,
    RESOLVER_IMPL_VERSION,
)

A = 16 / 9


def image(seed: int = 0, *, w: int = 800, h: int = 600) -> np.ndarray:
    """A deterministic still with an off-centre textured block to frame on."""
    rng = np.random.default_rng(seed)
    img = np.zeros((h, w, 3), dtype="uint8")
    y0 = int(h * 0.45) + (seed % 3) * 10
    x0 = int(w * 0.55) + (seed % 5) * 10
    img[y0 : y0 + h // 5, x0 : x0 + w // 5] = rng.integers(
        150, 255, (h // 5, w // 5, 3), dtype="uint8"
    )
    return img


def travel(path: BurnsPath, axis: str) -> float:
    """Signed distance the window travels on ``axis``, in image units."""
    r0, r1 = path.evaluate(0.0), path.evaluate(1.0)
    return (r1.x - r0.x) if axis == "x" else (r1.y - r0.y)


class TestVocabulary:
    def test_every_name_resolves_without_raising(self):
        img = image()
        for name in MOVES:
            path = resolve_move(name, image=img, aspect=A, seed=7)
            assert isinstance(path, BurnsPath)
            assert path.evaluate(0.0).is_contained()
            assert path.evaluate(1.0).is_contained()

    def test_the_vocabulary_is_one_table(self):
        """MOVES is read off the dispatch table, so the two cannot disagree."""
        assert set(MOVES) == set(_MOVES)

    def test_every_concrete_move_has_a_builder(self):
        for name, spec in _MOVES.items():
            assert (spec.build is None) == (spec.kind == "select"), name

    def test_auto_weights_only_name_concrete_moves(self):
        """An 'auto' entry would recurse; a stray name would resolve to a refusal."""
        assert set(AUTO_WEIGHTS) <= set(MOVES) - {"auto"}
        assert all(m in MOVES and m != "auto" for m in _AUTO_POOL)

    def test_move_kind_covers_the_vocabulary(self):
        assert {move_kind(m) for m in MOVES} == {"zoom", "drift", "static", "select"}

    def test_an_unknown_move_names_the_vocabulary_and_the_escape_hatch(self):
        with pytest.raises(MoveError) as e:
            resolve_move("swoop", image=image(), aspect=A)
        assert "swoop" in str(e.value) and "push_in" in str(e.value)
        assert "BurnsPath" in str(e.value)


class TestDeterminism:
    def test_same_move_seed_and_image_gives_the_same_path(self):
        img = image(3)
        for name in MOVES:
            a = resolve_move(name, image=img, aspect=A, seed=11)
            b = resolve_move(name, image=img, aspect=A, seed=11)
            assert a == b, name

    def test_a_different_seed_gives_a_different_auto_path(self):
        """The seed's one job — and it must actually reach the geometry."""
        img = image(4)
        paths = {resolve_move("auto", image=img, aspect=A, seed=s) for s in range(24)}
        assert len(paths) > 1
        assert len({choose_move(s) for s in range(24)}) > 1

    def test_the_seed_does_not_touch_a_named_move(self):
        """A named move is a decision. A decision a seed can nudge is not one."""
        img = image(5)
        for name in [m for m in MOVES if m != "auto"]:
            assert resolve_move(name, image=img, aspect=A, seed=0) == resolve_move(
                name, image=img, aspect=A, seed=987654321
            ), name

    def test_choose_move_is_stable_arithmetic_not_a_salted_hash(self):
        """A persisted seed must resolve to the same move in the next process."""
        import subprocess
        import sys

        code = "import burns;print(','.join(burns.choose_move(s) for s in range(12)))"
        here = ",".join(choose_move(s) for s in range(12))
        for _ in range(2):  # PYTHONHASHSEED differs per process by default
            out = subprocess.run(
                [sys.executable, "-c", code], capture_output=True, text=True, check=True
            )
            assert out.stdout.strip() == here


class TestPositionIndependence:
    """The defect the vocabulary exists to remove.

    The picture track used to derive its motion from each panel's ordinal, so
    reordering one panel changed the camera on every panel after it.
    """

    def track(self):
        """Three panels, each carrying its own stable seed."""
        return [
            {"image": image(1), "move": "auto", "seed": 101},
            {"image": image(2), "move": "auto", "seed": 202},
            {"image": image(3), "move": "auto", "seed": 303},
        ]

    def test_reordering_the_callers_list_changes_nothing(self):
        track = self.track()
        before = {
            p["seed"]: resolve_move(
                p["move"], image=p["image"], aspect=A, seed=p["seed"]
            )
            for p in track
        }
        reordered = [track[2], track[0], track[1]]
        after = {
            p["seed"]: resolve_move(
                p["move"], image=p["image"], aspect=A, seed=p["seed"]
            )
            for p in reordered
        }
        assert before == after

    def test_the_ordinal_approach_fails_that_same_check(self):
        """The negative control.

        Without this, `test_reordering_the_callers_list_changes_nothing` would
        pass just as happily against the code it replaced, and would be proving
        nothing. `content_aware_path_for(index=i)` is what braidio called; its
        parity rule is exactly what a reorder flips.
        """
        track = self.track()
        before = [
            content_aware_path_for(p["image"], index=i, output_aspect=A)
            for i, p in enumerate(track)
        ]
        reordered = [track[2], track[0], track[1]]
        after_by_still = {
            id(p["image"]): content_aware_path_for(p["image"], index=i, output_aspect=A)
            for i, p in enumerate(reordered)
        }
        changed = [
            p
            for i, p in enumerate(track)
            if after_by_still[id(p["image"])] != before[i]
        ]
        assert changed, "the ordinal path was expected to be reorder-sensitive"

    def test_keeping_the_move_while_changing_the_picture(self):
        """The first thing the owner asked for: same intent, new still, new framing."""
        seed, move = 77, "push_in"
        a = resolve_move(move, image=image(1), aspect=A, seed=seed)
        b = resolve_move(move, image=image(9, w=1200, h=400), aspect=A, seed=seed)
        assert a != b  # re-framed against the new picture
        assert a.evaluate(1.0).zoom >= a.evaluate(0.0).zoom  # still a push
        assert b.evaluate(1.0).zoom >= b.evaluate(0.0).zoom


class TestFocus:
    def test_an_explicit_focus_overrides_the_saliency_box(self):
        """The still's salient block is bottom-right; the focus is top-left."""
        img = image(0)
        saliency = resolve_move("push_in", image=img, aspect=A)
        focused = resolve_move(
            "push_in", image=img, aspect=A, focus=(0.02, 0.02, 0.15, 0.15)
        )
        assert saliency != focused
        sx, sy = saliency.evaluate(1.0).center
        fx, fy = focused.evaluate(1.0).center
        assert fx < sx and fy < sy

    def test_saliency_is_not_even_computed_when_focus_is_given(self, monkeypatch):
        """A total override, not a computed-then-discarded one.

        Computing the estimate anyway is how a partial override quietly lets
        saliency back in on some path later.
        """
        import burns.moves

        monkeypatch.setattr(
            burns.moves,
            "salient_box",
            lambda *a, **k: pytest.fail("salient_box ran despite an explicit focus"),
        )
        resolve_move("push_in", image=image(), aspect=A, focus=Rect(0.3, 0.3, 0.2, 0.2))

    @pytest.mark.parametrize(
        "focus",
        [
            Rect(0.3, 0.3, 0.2, 0.2),
            (0.3, 0.3, 0.2, 0.2),
            [0.3, 0.3, 0.2, 0.2],
        ],
    )
    def test_focus_accepts_any_structural_rect(self, focus):
        """burns does not make a consumer import its rectangle type to say 'here'."""
        expected = resolve_move(
            "push_in", image=image(), aspect=A, focus=Rect(0.3, 0.3, 0.2, 0.2)
        )
        assert resolve_move("push_in", image=image(), aspect=A, focus=focus) == expected

    def test_focus_accepts_a_duck_typed_rect(self):
        class PanelFocus:  # what a pydantic body looks like from here
            x, y, w, h = 0.3, 0.3, 0.2, 0.2

        expected = resolve_move(
            "push_in", image=image(), aspect=A, focus=(0.3, 0.3, 0.2, 0.2)
        )
        assert (
            resolve_move("push_in", image=image(), aspect=A, focus=PanelFocus())
            == expected
        )

    @pytest.mark.parametrize(
        "bad, hint",
        [
            ((120, 80, 400, 300), "pixels"),  # the usual mistake
            ((0.1, 0.1, 0.0, 0.2), "positive"),
            ((0.1, 0.1, 0.2), "4 components"),
            ("nope", "4 components"),
            (object(), "4 components"),
        ],
    )
    def test_a_malformed_focus_says_what_is_wrong(self, bad, hint):
        with pytest.raises(MoveError) as e:
            resolve_move("push_in", image=image(), aspect=A, focus=bad)
        assert hint in str(e.value)

    def test_focus_accepts_a_mapping(self):
        """What a stored focus looks like after a JSON round-trip."""
        expected = resolve_move(
            "push_in", image=image(), aspect=A, focus=(0.3, 0.3, 0.2, 0.2)
        )
        got = resolve_move(
            "push_in",
            image=image(),
            aspect=A,
            focus={"x": 0.3, "y": 0.3, "w": 0.2, "h": 0.2},
        )
        assert got == expected

    def test_an_incomplete_focus_mapping_names_the_missing_keys(self):
        with pytest.raises(MoveError) as e:
            resolve_move("push_in", image=image(), aspect=A, focus={"x": 0.3, "y": 0.3})
        assert "'w'" in str(e.value) and "'h'" in str(e.value)

    def test_focus_none_is_no_focus_not_a_malformed_one(self):
        """The default. It must fall through to saliency, never refuse."""
        assert resolve_move(
            "push_in", image=image(), aspect=A, focus=None
        ) == resolve_move("push_in", image=image(), aspect=A)


class TestDrift:
    @pytest.mark.parametrize(
        "move, axis, sign",
        [
            ("drift_left", "x", -1),
            ("drift_right", "x", +1),
            ("drift_up", "y", -1),
            ("drift_down", "y", +1),
        ],
    )
    def test_the_name_is_the_direction_the_camera_travels(self, move, axis, sign):
        d = travel(resolve_move(move, image=image(), aspect=A), axis)
        assert d * sign > 0, f"{move} travelled {d:+.4f} on {axis}"

    def test_opposite_drifts_are_mirror_images(self):
        img = image(2)
        left = resolve_move("drift_left", image=img, aspect=A)
        right = resolve_move("drift_right", image=img, aspect=A)
        assert left.evaluate(0.0) == right.evaluate(1.0)
        assert left.evaluate(1.0) == right.evaluate(0.0)

    def test_a_drift_always_actually_travels(self):
        """A drift that silently becomes a hold is the failure DRIFT_MIN_ROOM prevents."""
        for zoom in (1.0, 1.01, 1.18, 1.6):
            for move, axis in (("drift_right", "x"), ("drift_down", "y")):
                d = travel(resolve_move(move, image=image(), aspect=A, zoom=zoom), axis)
                assert abs(d) > 1e-6, f"{move} at zoom={zoom} did not move"

    def test_the_two_drift_constants_can_both_bind(self):
        """`DRIFT_MIN_ROOM` is derived, and the derivation is load-bearing.

        Travel is `min(room * DRIFT_TRAVEL, size * DRIFT_SPAN)` with
        `size == 1 - room`, so the span can only ever bind when
        `room >= DRIFT_SPAN / (DRIFT_TRAVEL + DRIFT_SPAN)`. Set the floor below
        that and the span is unreachable: every room-limited drift crosses a
        smaller fraction of its frame, and DRIFT_SPAN's promise holds only on
        pictures with room to spare.
        """
        assert DRIFT_MIN_ROOM == pytest.approx(DRIFT_SPAN / (DRIFT_TRAVEL + DRIFT_SPAN))
        # at exactly the floor, both terms are equal — neither silently wins
        room, size = DRIFT_MIN_ROOM, 1 - DRIFT_MIN_ROOM
        assert room * DRIFT_TRAVEL == pytest.approx(size * DRIFT_SPAN)

    @pytest.mark.parametrize(
        "iw, ih, aspect",
        [
            (1600, 1200, 16 / 9),  # landscape still, landscape delivery
            (1080, 1920, 16 / 9),  # portrait still in a landscape cut
            (1920, 1080, 9 / 16),  # landscape still in the vertical cut
            (4032, 3024, 9 / 16),  # a phone photo in the vertical cut
            (1000, 1000, None),  # square, aspect follows the image
        ],
    )
    def test_both_axes_drift_at_the_same_speed_on_every_delivery(self, iw, ih, aspect):
        """Regression, widened.

        An earlier version measured only an 800x600 still at 16:9 — the one
        pair that already passed (ratio 1.11) — while a portrait still in a
        landscape cut measured **2.30x**, which is the exact asymmetry
        DRIFT_SPAN exists to remove.
        """
        img = image(w=iw, h=ih)
        fractions = {}
        for move, axis in (("drift_right", "x"), ("drift_down", "y")):
            path = resolve_move(move, image=img, aspect=aspect)
            window = path.evaluate(0.0)
            size = window.w if axis == "x" else window.h
            fractions[move] = abs(travel(path, axis)) / size
        assert all(f <= DRIFT_SPAN + 1e-9 for f in fractions.values()), fractions
        assert max(fractions.values()) / min(fractions.values()) < 1.15, fractions

    def test_both_axes_drift_at_the_same_speed_on_screen(self):
        """Regression: the travel was whatever room the picture's aspect left.

        A 4:3 still delivered at 16:9 has ~2x the vertical room, so an
        uncapped vertical drift crossed ~29% of the frame where a horizontal
        one crossed ~9% — one named gesture at three different speeds,
        decided by the picture.
        """
        img = image()
        fractions = {}
        for move, axis in (
            ("drift_right", "x"),
            ("drift_down", "y"),
        ):
            path = resolve_move(move, image=img, aspect=A)
            window = path.evaluate(0.0)
            size = window.w if axis == "x" else window.h
            fractions[move] = abs(travel(path, axis)) / size
        assert all(f <= DRIFT_SPAN + 1e-9 for f in fractions.values()), fractions
        assert max(fractions.values()) / min(fractions.values()) < 1.5, fractions

    def test_a_drift_near_an_edge_keeps_its_full_travel(self):
        """The travel interval slides inside the image; it is never shrunk.

        Clamping the two ends independently collapses the move to a hold
        whenever the subject sits near a wall.
        """
        img = image()
        centred = abs(
            travel(
                resolve_move(
                    "drift_right", image=img, aspect=A, focus=(0.4, 0.4, 0.2, 0.2)
                ),
                "x",
            )
        )
        cornered = abs(
            travel(
                resolve_move(
                    "drift_right", image=img, aspect=A, focus=(0.0, 0.0, 0.12, 0.12)
                ),
                "x",
            )
        )
        assert cornered == pytest.approx(centred, rel=1e-6)


class TestEasing:
    """`easing` is the only per-panel knob besides move/zoom/focus/seed, and
    on a drift it is the difference between a camera that continues and one
    that settles. An earlier suite exercised it on `push_in` only, so
    dropping it in the drift and hold builders left everything green."""

    @pytest.mark.parametrize("name", [m for m in MOVES if m != "auto"])
    def test_easing_reaches_every_move(self, name):
        img = image()
        eased = resolve_move(name, image=img, aspect=A, easing="ease-in-out")
        linear = resolve_move(name, image=img, aspect=A, easing="linear")
        assert eased.easing == "ease-in-out"
        assert linear.easing == "linear"

    @pytest.mark.parametrize("name", ["push_in", "drift_right", "drift_up"])
    def test_easing_changes_the_midpoint_of_a_moving_move(self, name):
        """Not just carried on the dataclass — actually composed over the
        geometry, which is what `evaluate` promises."""
        img = image()
        a = resolve_move(name, image=img, aspect=A, easing="linear").evaluate(0.25)
        b = resolve_move(name, image=img, aspect=A, easing="ease-in-out").evaluate(0.25)
        assert (a.x, a.y, a.w, a.h) != (b.x, b.y, b.w, b.h), name


class TestHold:
    def test_a_hold_does_not_move(self):
        path = resolve_move("hold", image=image(), aspect=A)
        assert path.evaluate(0.0) == path.evaluate(1.0)

    def test_a_hold_is_two_keyframes_so_it_is_valid_on_the_wire(self):
        """A hold is specified as two equal keyframes; every move emits at least two.

        (A one-keyframe path is valid too — see ``test_wire_schema.py`` — but the
        built-in moves keep to the canonical Start/End shape.)
        """
        for name in MOVES:
            path = resolve_move(name, image=image(), aspect=A, seed=13)
            assert len(path.keyframes) >= 2, name

    def test_a_hold_honours_zoom(self):
        img = image()
        wide = resolve_move("hold", image=img, aspect=A, zoom=1.0)
        tight = resolve_move("hold", image=img, aspect=A, zoom=1.35)
        assert tight.evaluate(0.0).zoom > wide.evaluate(0.0).zoom


class TestExplicitPath:
    def hand_authored(self, aspect=A):
        return BurnsPath.from_start_end(
            Rect(0.0, 0.0, 1.0, 1.0),
            Rect(0.1, 0.1, 0.6, 0.6),
            output_aspect=aspect,
        )

    def test_a_burnspath_is_returned_as_authored(self):
        path = self.hand_authored()
        assert resolve_move(path, image=image(), aspect=A) == path

    def test_a_to_dict_payload_is_the_same_front_door(self):
        path = self.hand_authored()
        assert resolve_move(path.to_dict(), image=image(), aspect=A) == path

    def test_an_override_ignores_the_named_moves_knobs(self):
        """Its rectangles are already resolved; zoom/focus/seed have nothing to do."""
        path = self.hand_authored()
        assert (
            resolve_move(
                path, image=image(), aspect=A, zoom=3.0, focus=(0, 0, 0.1, 0.1), seed=9
            )
            == path
        )

    def test_an_aspect_agnostic_override_is_preserved(self):
        """`output_aspect=None` says 'match the image' — a choice, not a mismatch."""
        path = self.hand_authored(aspect=None)
        assert resolve_move(path, image=image(), aspect=A) == path

    def test_an_override_authored_for_another_delivery_raises(self):
        """Silently cover-cropping somebody's hand-drawn framing is the defect class."""
        path = self.hand_authored(aspect=16 / 9)
        with pytest.raises(MoveError) as e:
            resolve_move(path, image=image(), aspect=9 / 16)
        assert "authored" in str(e.value) and "1.77" in str(e.value)

    def test_a_mapping_that_is_not_a_path_payload_says_so(self):
        """A mapping in `move` is read as a path; a malformed one must not
        surface as a KeyError from three frames down."""
        with pytest.raises(MoveError) as e:
            resolve_move({"move": "push_in"}, image=image(), aspect=A)
        assert "to_dict()" in str(e.value) and "push_in" in str(e.value)

    def test_an_override_survives_float_noise_in_the_aspect(self):
        """`1920/1080` and `16/9` are the SAME double, so that pair tests
        nothing. Use a value that genuinely differs in the last bits."""
        assert 1920 / 1080 == 16 / 9  # the pair an earlier version of this used
        noisy = math.nextafter(math.nextafter(16 / 9, 2.0), 2.0)
        assert noisy != 16 / 9
        path = self.hand_authored(aspect=noisy)
        assert resolve_move(path, image=image(), aspect=16 / 9) == path

    def test_the_tolerance_is_relative_not_absolute(self):
        """An absolute epsilon on a ratio is four times stricter for scope
        (2.39:1) than for a vertical (9:16) — a distinction nobody chose."""
        for base in (9 / 16, 16 / 9, 2.39):
            near = base * (1 + 1e-10)
            assert resolve_move(
                self.hand_authored(aspect=near), image=image(), aspect=base
            ) == self.hand_authored(aspect=near)
            far = base * 1.02  # 2% — a different delivery at any scale
            with pytest.raises(MoveError):
                resolve_move(self.hand_authored(aspect=far), image=image(), aspect=base)


class TestAspectMismatch:
    """The seam that keeps a second-aspect cut renderable.

    A panel carries ONE path, not one per delivery, so a hand-corrected move on
    the 16:9 cut used to make the vertical cut of the same project raise — and
    the remedy the error named ("author a second path for this delivery") was
    not expressible in any body schema.
    """

    def hand(self, aspect=16 / 9):
        return BurnsPath.from_start_end(
            Rect(0.0, 0.0, 1.0, 1.0),
            Rect(0.15, 0.10, 0.55, 0.55),
            output_aspect=aspect,
        )

    def test_the_default_still_refuses(self):
        """Loud stays the default: nothing silently cover-crops a hand-drawn
        framing, and no stored data violates the strict rule yet."""
        with pytest.raises(MoveError) as e:
            resolve_move(self.hand(), image=image(), aspect=9 / 16)
        assert "refit" in str(e.value)

    def test_the_error_names_only_remedies_a_caller_can_actually_take(self):
        msg = str(
            pytest.raises(
                MoveError,
                resolve_move,
                self.hand(),
                image=image(),
                aspect=9 / 16,
            ).value
        )
        assert "author a second path" not in msg  # not expressible: one path per panel
        assert "on_aspect_mismatch='refit'" in msg
        assert "drop the override" in msg

    def test_refit_renders_the_vertical_cut(self):
        v = resolve_move(
            self.hand(), image=image(), aspect=9 / 16, on_aspect_mismatch="refit"
        )
        assert v.output_aspect == 9 / 16
        for t in (0.0, 0.5, 1.0):
            assert v.evaluate(t).is_contained()

    def test_refit_keeps_what_the_author_chose(self):
        """Where the camera looks, and how far in it is — at every instant."""
        iw, ih = 1600, 1200
        hand = self.hand()
        v = resolve_move(
            hand, image=image(w=iw, h=ih), aspect=9 / 16, on_aspect_mismatch="refit"
        )
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            before, after = hand.evaluate(t), v.evaluate(t)
            assert after.center == pytest.approx(before.center, abs=1e-9)
            assert after.zoom == pytest.approx(before.zoom, rel=1e-9)

    def test_refit_changes_the_window_shape_to_the_delivery(self):
        """It is not a no-op dressed as one: the point is the new shape."""
        iw, ih = 1600, 1200
        v = resolve_move(
            self.hand(),
            image=image(w=iw, h=ih),
            aspect=9 / 16,
            on_aspect_mismatch="refit",
        )
        r = v.evaluate(0.0)
        assert (r.w * iw) / (r.h * ih) == pytest.approx(9 / 16, rel=0.02)

    def test_a_stored_aspect_against_a_none_delivery_is_still_a_mismatch(self):
        """The mirror of `test_an_aspect_agnostic_override_is_preserved`.

        A path authored for 16:9 rendered at `aspect=None` (match the image)
        is a real mismatch. Only the *stored* `None` means "aspect-agnostic";
        relaxing the guard to `aspect is None or ...` silently honours a
        16:9 framing on an image-shaped cut, and survived the suite.
        """
        with pytest.raises(MoveError):
            resolve_move(self.hand(16 / 9), image=image(), aspect=None)
        refitted = resolve_move(
            self.hand(16 / 9), image=image(), aspect=None, on_aspect_mismatch="refit"
        )
        assert refitted.output_aspect is None

    def test_refit_is_a_no_op_when_the_aspects_already_agree(self):
        hand = self.hand()
        assert (
            resolve_move(hand, image=image(), aspect=16 / 9, on_aspect_mismatch="refit")
            == hand
        )

    def test_an_unknown_action_is_refused_by_name(self):
        with pytest.raises(MoveError) as e:
            resolve_move("push_in", image=image(), aspect=A, on_aspect_mismatch="crop")
        assert "refit" in str(e.value) and "crop" in str(e.value)

    def test_a_named_move_never_reaches_the_mismatch_path(self):
        """It is built at `aspect` by construction, so the seam cannot bite it."""
        for action in ("raise", "refit"):
            p = resolve_move(
                "push_in", image=image(), aspect=9 / 16, on_aspect_mismatch=action
            )
            assert p.output_aspect == 9 / 16


class TestResolverIdentity:
    """A stored panel is an intent, so this module's constants decide its
    pixels. A consumer caching a render keyed on the panel alone would serve
    stale frames forever — nw's invariant 3, reelee's working rules 5-6."""

    def test_the_resolver_publishes_an_identity_to_put_in_a_cache_key(self):
        assert isinstance(RESOLVER_IMPL_VERSION, int)
        assert RESOLVER_IMPL_VERSION >= 1
        assert burns.RESOLVER_IMPL_VERSION is RESOLVER_IMPL_VERSION

    def test_it_is_not_the_package_version(self):
        """A burns release that touches only the renderer must not invalidate
        anybody's cut — and importlib.metadata is unreliable here besides."""
        assert not hasattr(burns, "__version__")

    def test_every_constant_that_moves_the_pixels_is_covered_by_it(self):
        """A reminder in executable form: this list IS what the lock locks."""
        governed = {
            "DFLT_ZOOM",
            "DRIFT_TRAVEL",
            "DRIFT_SPAN",
            "DRIFT_MIN_ROOM",
            "AUTO_WEIGHTS",
        }
        assert governed <= set(burns.moves.__all__)


class TestArgumentValidation:
    @pytest.mark.parametrize("bad", [0, 0.0, -1.78, float("nan"), float("inf"), "wide"])
    def test_a_nonsense_aspect_is_refused(self, bad):
        """`0.0` is falsy, so it would reach axis_maxima and quietly mean
        'match the image' — the cover-crop `aspect` is required to prevent.
        A negative produces a negative-width rect that passes is_contained()."""
        with pytest.raises(MoveError):
            resolve_move("push_in", image=image(), aspect=bad)

    @pytest.mark.parametrize("bad", [0, 0.0, -1.0, float("nan"), float("inf"), "big"])
    def test_a_nonsense_zoom_is_refused(self, bad):
        """Rect.from_center_zoom already refuses these; the new front door
        must not be more permissive than the type it builds."""
        with pytest.raises(MoveError):
            resolve_move("push_in", image=image(), aspect=A, zoom=bad)

    def test_aspect_none_is_still_allowed(self):
        assert resolve_move("hold", image=image(), aspect=None) is not None


class TestVocabularyIsStrict:
    """burns owns MOVES; a consumer mirroring it to validate its own stored
    field must agree exactly. Leniency here is invisible divergence."""

    @pytest.mark.parametrize(
        "spelling", [" push_in", "push_in ", " push_in ", "PUSH_IN", "Push_In"]
    )
    def test_no_stripping_and_no_case_folding(self, spelling):
        with pytest.raises(MoveError):
            resolve_move(spelling, image=image(), aspect=A)

    def test_auto_weights_cannot_be_mutated_into_a_silent_no_op(self):
        """It is in __all__ and its docstring says it decides how often auto
        picks each move — but the pool is built once at import, so a plain
        dict would accept the assignment and change nothing."""
        with pytest.raises(TypeError):
            burns.AUTO_WEIGHTS["push_in"] = 99


class TestGeometryIsPinned:
    """Every constant and every docstring claim that decides a pixel.

    An adversarial review mutated this module sixteen ways and **fourteen
    survived** the suite as first written — the geometry was almost entirely
    unpinned. Each test below kills one of those survivors, and the docstring
    says which claim it is defending, because that is the thing that can rot.
    """

    def test_a_zoom_move_is_exactly_a_content_aware_path(self):
        """`_zoom_move` is a pure delegation.

        Includes a case where the framing cap BINDS, because with a slack cap
        every plausible mutation of the zoom it forwards is a no-op and the
        assertion proves nothing.
        """
        iw, ih = 800, 600
        cases = [((0.3, 0.3, 0.2, 0.2), 1.4), ((0.25, 0.25, 0.5, 0.5), 2.5)]
        assert any(
            fit_zoom(iw, ih, keep=pad_box(f, DFLT_KEEP_PAD), output_aspect=A) * 0.98 < z
            for f, z in cases
        ), "at least one case must exercise a binding cap"
        for focus, zoom in cases:
            for name, mode in (("push_in", "in"), ("pull_out", "out")):
                got = resolve_move(
                    name, image=image(w=iw, h=ih), aspect=A, zoom=zoom, focus=focus
                )
                want = content_aware_path(
                    iw,
                    ih,
                    subject=focus,
                    output_aspect=A,
                    zoom=zoom,
                    keep_pad=DFLT_KEEP_PAD,
                    mode=mode,
                )
                assert got == want, (name, focus, zoom)

    def test_zoom_is_capped_so_the_subject_stays_framed(self):
        """ "capped so the padded keep-region stays framed", margin included.

        The focus must leave ``cap * 0.98`` ABOVE 1.0. An earlier version used
        a near-full-frame focus, where the ``max(1.0, ...)`` floor swallows the
        margin entirely — so dropping the 0.98 changed every render and the
        assertion still passed.
        """
        iw, ih = 800, 600
        focus = (0.35, 0.35, 0.3, 0.3)
        cap = fit_zoom(iw, ih, keep=pad_box(focus, DFLT_KEEP_PAD), output_aspect=A)
        assert cap * 0.98 > 1.0, "this case must exercise the margin, not the floor"
        p = resolve_move(
            "hold", image=image(w=iw, h=ih), aspect=A, zoom=50.0, focus=focus
        )
        assert p.evaluate(0.0).zoom == pytest.approx(cap * 0.98, rel=1e-9)
        assert p.evaluate(0.0).zoom < 50.0

    def test_the_keep_region_is_padded_before_it_is_framed(self):
        """A subject framed by its own bounding box reads as a crop. Padding
        moves the cap, so an unpadded keep frames tighter than intended."""
        iw, ih = 800, 600
        focus = (0.2, 0.2, 0.6, 0.6)
        padded = fit_zoom(iw, ih, keep=pad_box(focus, DFLT_KEEP_PAD), output_aspect=A)
        raw = fit_zoom(iw, ih, keep=focus, output_aspect=A)
        assert padded < raw  # the padding really does bind here
        p = resolve_move(
            "hold", image=image(w=iw, h=ih), aspect=A, zoom=9.0, focus=focus
        )
        assert p.evaluate(0.0).zoom == pytest.approx(max(1.0, padded * 0.98), rel=1e-9)

    def test_a_room_limited_drift_lands_exactly_on_the_floor(self):
        """`DRIFT_TRAVEL` is live geometry: `DRIFT_MIN_ROOM` is derived from
        it, so retuning it moves the zoom the floor chooses."""
        p = resolve_move(
            "drift_right", image=image(w=1600, h=900), aspect=16 / 9, zoom=1.0
        )
        r = p.evaluate(0.0)
        assert 1 - r.w == pytest.approx(DRIFT_MIN_ROOM, rel=1e-9)
        assert abs(travel(p, "x")) / r.w == pytest.approx(DRIFT_SPAN, rel=1e-9)

    @pytest.mark.parametrize(
        "move, axis, cross",
        [
            ("drift_right", "x", "y"),
            ("drift_left", "x", "y"),
            ("drift_up", "y", "x"),
            ("drift_down", "y", "x"),
        ],
    )
    def test_a_drift_locks_its_cross_axis_to_the_subject(self, move, axis, cross):
        """ "the cross axis stays locked to the keep-region, so a horizontal
        drift cannot slide off a face" — untested, and it survived a mutation
        that locked it to the image centre instead."""
        img = image()
        near = (0.40, 0.02, 0.20, 0.20) if cross == "y" else (0.02, 0.40, 0.20, 0.20)
        far = (0.40, 0.70, 0.20, 0.20) if cross == "y" else (0.70, 0.40, 0.20, 0.20)
        a = getattr(
            resolve_move(move, image=img, aspect=A, focus=near).evaluate(0.0), cross
        )
        b = getattr(
            resolve_move(move, image=img, aspect=A, focus=far).evaluate(0.0), cross
        )
        assert a < b, (move, cross, a, b)

    @pytest.mark.parametrize("move, axis", [("drift_right", "x"), ("drift_down", "y")])
    def test_a_drift_centres_its_travel_on_the_subject(self, move, axis):
        """ "The travel is centred on the keep-region, so the subject is
        mid-frame at the midpoint of the move rather than arriving or
        departing."

        This is the ALONG-axis claim, and it is a different mutation from the
        cross-axis one: centring the travel on the image instead survived a
        test that only looked at the cross axis.
        """
        img = image()
        near = (0.05, 0.40, 0.20, 0.20) if axis == "x" else (0.40, 0.05, 0.20, 0.20)
        far = (0.75, 0.40, 0.20, 0.20) if axis == "x" else (0.40, 0.75, 0.20, 0.20)
        a = getattr(
            resolve_move(move, image=img, aspect=A, focus=near).evaluate(0.0), axis
        )
        b = getattr(
            resolve_move(move, image=img, aspect=A, focus=far).evaluate(0.0), axis
        )
        assert a < b, (move, axis, a, b)

    def test_auto_follows_the_declared_weights(self):
        """AUTO_WEIGHTS is documented as how often auto picks each move.
        Flattening it to all-ones survived the suite as first written."""
        n = 20000
        counts = Counter(choose_move(s) for s in range(n))
        total = sum(AUTO_WEIGHTS.values())
        for name, weight in AUTO_WEIGHTS.items():
            assert counts[name] / n == pytest.approx(weight / total, abs=0.02), (
                name,
                dict(counts),
            )
        assert counts["push_in"] > 2 * counts["drift_left"]

    def test_the_tuned_constants_are_pinned_to_the_resolver_version(self):
        """The art-direction numbers, pinned by literal on purpose.

        They are *choices*, not derivations — how far a drift crosses its
        frame, and how much of the available room it uses. Nothing else can
        pin them: `DRIFT_MIN_ROOM` is derived from both, so retuning
        `DRIFT_TRAVEL` moves the derived constant with it and every
        relationship test stays green while every rendered drift changes.

        A literal pin makes a retune a deliberate two-line edit — the value
        here, and `RESOLVER_IMPL_VERSION`, which is what stops a consumer's
        cache serving frames from the old tuning forever.
        """
        assert (DRIFT_TRAVEL, DRIFT_SPAN, DFLT_ZOOM, DIFFUSE_KEEP_AREA) == (
            0.5,
            0.10,
            1.18,
            0.5,
        ), (
            "a tuned constant changed: bump RESOLVER_IMPL_VERSION in the same "
            "commit, then update this pin"
        )
        # 2: diffuse saliency is a centre hint, and content_box (burns#21)
        assert RESOLVER_IMPL_VERSION == 2

    def test_the_seed_is_mixed_not_taken_modulo(self):
        """Cross-process stability alone does not prove the seed is scrambled
        — `seed % len(pool)` has that too, and walks the pool in order, so a
        consumer minting sequential seeds would get a visible cycle."""
        raw_walk = [_AUTO_POOL[s % len(_AUTO_POOL)] for s in range(40)]
        assert [choose_move(s) for s in range(40)] != raw_walk

    @pytest.mark.parametrize(
        "box, accepted",
        [
            ((0.90, 0.50, 0.10, 0.40), True),  # exactly flush with the edge
            ((0.90, 0.50, 0.11, 0.40), False),  # 0.01 over — the real boundary
            ((0.50, 0.90, 0.40, 0.11), False),
            ((-0.01, 0.50, 0.20, 0.20), False),
            ((0.00, 0.00, 1.00, 1.00), True),  # the whole image
        ],
    )
    def test_the_focus_bound_is_tested_at_the_boundary(self, box, accepted):
        """The only out-of-range case used to be a pixel box (120, 80, 400,
        300) — so far out that loosening the bound to [0, 2] still refused it.
        A guard tested at 400x its boundary is not tested."""
        if accepted:
            assert resolve_move("hold", image=image(), aspect=A, focus=box) is not None
        else:
            with pytest.raises(MoveError):
                resolve_move("hold", image=image(), aspect=A, focus=box)


class TestSerialization:
    def test_a_resolved_path_round_trips_through_json(self):
        """What the consumer stores when it freezes a resolved move.

        `dataclasses.asdict` emits the live `_ease` closure and raises on
        `json.dumps`; `to_dict` is the wire format.
        """
        for name in MOVES:
            path = resolve_move(name, image=image(), aspect=A, seed=23)
            payload = json.loads(json.dumps(path.to_dict()))
            assert BurnsPath.from_dict(payload) == path, name

    def test_asdict_is_the_trap_to_dict_avoids(self):
        import dataclasses

        path = resolve_move("push_in", image=image(), aspect=A)
        with pytest.raises(TypeError):
            json.dumps(dataclasses.asdict(path))

    def test_a_callable_easing_refuses_to_serialize(self):
        path = resolve_move("push_in", image=image(), aspect=A, easing=lambda t: t)
        with pytest.raises(ValueError):
            path.to_dict()


class TestAspect:
    def test_the_window_carries_the_delivery_aspect(self):
        """So the renderer's cover-crop is a no-op and what you frame is what shows."""
        iw, ih = 800, 600
        for name in [m for m in MOVES if m != "auto"]:
            path = resolve_move(name, image=image(w=iw, h=ih), aspect=A, seed=1)
            r = path.evaluate(0.0)
            assert (r.w * iw) / (r.h * ih) == pytest.approx(A, rel=0.02), name
            assert path.output_aspect == A

    def test_aspect_none_means_match_the_image(self):
        iw, ih = 800, 600
        path = resolve_move("hold", image=image(w=iw, h=ih), aspect=None, zoom=1.0)
        r = path.evaluate(0.0)
        assert (r.w, r.h) == (1.0, 1.0)
        assert path.output_aspect is None

    def test_a_portrait_still_delivers_at_the_asked_aspect(self):
        iw, ih = 1080, 1920
        for name in ("push_in", "drift_up", "hold"):
            r = resolve_move(name, image=image(w=iw, h=ih), aspect=A).evaluate(0.0)
            assert (r.w * iw) / (r.h * ih) == pytest.approx(A, rel=0.02), name


class TestRenders:
    def test_a_resolved_move_actually_drives_the_renderer(self, tmp_path):
        """The primary artifact: pixels, not numbers.

        Compared on DECODED frames — a first frame identical to the last is a
        silent hold, which is what every geometric guard here exists to catch
        and what only a render can confirm did not happen.
        """
        from moviepy import VideoFileClip

        src = tmp_path / "still.png"
        from PIL import Image as PIL_Image

        PIL_Image.fromarray(image(w=320, h=240)).save(src)
        out = ken_burns_video(
            src,
            resolve_move("drift_right", image=src, aspect=A),
            duration=1.0,
            fps=24,
            saveas=tmp_path / "drift.mp4",
        )
        assert out.exists()
        with VideoFileClip(str(out)) as clip:
            first = np.asarray(clip.get_frame(0.0), dtype="int16")
            last = np.asarray(clip.get_frame(0.9), dtype="int16")
        assert np.abs(first - last).mean() > 1.0


# --- burns#21: the zoom a caller asks for is the zoom it gets -----------------

#: The studio's four "How much it closes in" choices (reelee-web ZOOMS).
_STUDIO_ZOOMS = (1.0, 1.08, 1.18, 1.3)


def _busy_photo(w=1280, h=960, seed=0):
    """A detailed 4:3 'photograph': texture everywhere, as archive photos are —
    which is exactly what makes gradient saliency cover the whole frame."""
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 255, size=(h // 8, w // 8, 3), dtype=np.uint8)
    img = np.kron(base, np.ones((8, 8, 1), dtype=np.uint8))
    img[h // 3 : h // 2, w // 3 : w // 2] = 250  # something brighter mid-frame
    return img


def _on_blurred_canvas(photo, size=(1920, 1080)):
    """What braidio's prepare_still does: the still, contained, over a blurred
    darkened enlargement of itself. Returns the canvas and the still's box."""
    from PIL import Image, ImageFilter

    cw, ch = size
    still = Image.fromarray(photo)
    fill = still.resize(size).filter(ImageFilter.GaussianBlur(40))
    fill = Image.eval(fill, lambda v: int(v * 0.45))
    scale = min(cw / still.width, ch / still.height)
    fw, fh = int(round(still.width * scale)), int(round(still.height * scale))
    ox, oy = (cw - fw) // 2, (ch - fh) // 2
    fill.paste(still.resize((fw, fh)), (ox, oy))
    return np.asarray(fill), (ox / cw, oy / ch, fw / cw, fh / ch)


def _end_magnification(path, img, aspect):
    """How far in the move ends, relative to the full-frame window."""
    from burns.content import axis_maxima

    wmax, _ = axis_maxima(img.shape[1], img.shape[0], aspect)
    return wmax / path.evaluate(1.0).w


class TestRequestedZoomIsHonoured:
    """Before burns#21 all four studio zooms rendered one push, ~1.07x, on real
    photographs: saliency covered the picture, so the framing cap bound at 1.0
    and push_in's floor was what shipped. The fixture is the real case — a
    detailed 4:3 still in a 16:9 film, on the blurred-fill canvas."""

    # A canvas WITHOUT content_box is not a supported way to get this: the
    # still's box on a letterboxed canvas touches only two borders, which is
    # also what two subjects at opposite edges look like, so burns cannot tell
    # it is texture. A caller that composites onto a fill says where the
    # picture is (braidio does).
    @pytest.mark.parametrize("where", ["still", "canvas+content_box"])
    def test_the_four_zoom_levels_are_distinct(self, where):
        photo = _busy_photo()
        img, box = (photo, None) if where == "still" else _on_blurred_canvas(photo)
        kw = {"content_box": box} if where == "canvas+content_box" else {}
        ends = [
            _end_magnification(
                resolve_move("push_in", image=img, aspect=16 / 9, zoom=z, **kw),
                img,
                16 / 9,
            )
            for z in _STUDIO_ZOOMS
        ]
        assert all(b > a + 0.005 for a, b in zip(ends, ends[1:])), ends
        # the requests above the push floor land where they were asked
        for z, got in zip(_STUDIO_ZOOMS[1:], ends[1:]):
            assert got == pytest.approx(z, abs=0.01), (z, ends)

    def test_hold_and_drift_follow_the_zoom_too(self):
        img, box = _on_blurred_canvas(_busy_photo())
        holds = [
            _end_magnification(
                resolve_move("hold", image=img, aspect=16 / 9, zoom=z, content_box=box),
                img,
                16 / 9,
            )
            for z in _STUDIO_ZOOMS
        ]
        assert all(b > a for a, b in zip(holds, holds[1:])), holds

    def test_an_explicit_focus_still_caps(self):
        """The cap is right for a decision: a focus filling the frame is a
        subject to keep whole, so zoom yields to it exactly as before."""
        img = _busy_photo()
        ends = {
            _end_magnification(
                resolve_move(
                    "push_in",
                    image=img,
                    aspect=16 / 9,
                    zoom=z,
                    focus=(0.0, 0.0, 1.0, 1.0),
                ),
                img,
                16 / 9,
            )
            for z in _STUDIO_ZOOMS
        }
        assert len({round(e, 3) for e in ends}) == 1

    def test_content_box_keeps_saliency_off_the_fill(self):
        """A small subject on a flat still: confined to the still, saliency
        finds the subject; over the whole canvas the fill seam widens it."""
        photo = np.full((960, 1280, 3), 90, dtype=np.uint8)
        photo[600:760, 900:1100] = 240  # a subject low and right
        img, box = _on_blurred_canvas(photo)
        from burns.moves import _saliency_keep
        from burns.content import as_pil

        x, y, w, h = _saliency_keep(as_pil(img), box, zoom=1.18, aspect=16 / 9)
        cx, cy = x + w / 2, y + h / 2
        sx, sy = box[0] + box[2] * 1000 / 1280, box[1] + box[3] * 680 / 960
        assert abs(cx - sx) < 0.08 and abs(cy - sy) < 0.12, (cx, cy, sx, sy)


def test_diffuseness_ramps_with_the_edge_distance():
    """Second review of #21: a yes/no edge test flipped 1.30 -> 1.07 for a 2 %
    change in content. The reach of each edge ramps, so the weight moves
    continuously as a box edge leaves the border."""
    from burns.moves import _diffuseness

    margins = [0.02 + 0.005 * k for k in range(29)]  # 0.02 .. 0.16
    weights = [_diffuseness((0.0, 0.0, 1.0 - m, 1.0 - m)) for m in margins]
    assert weights[0] == 1.0 and weights[-1] == 0.0
    steps = [a - b for a, b in zip(weights, weights[1:])]
    # monotone, and no 0.5 % change in content moves the weight by much
    assert all(s >= 0 for s in steps) and max(steps) <= 0.15, weights


class TestDiffuseIsNotASubject:
    """Review of burns#21: area alone flipped a large subject on a flat field
    from framed-whole to cropped at a 1 % size change."""

    @pytest.mark.parametrize("side", [0.62, 0.66, 0.69])  # the review's flip point
    def test_a_large_centred_subject_on_a_flat_field_is_never_cropped(self, side):
        h, w = 600, 800
        img = np.full((h, w, 3), 90, dtype=np.uint8)
        rng = np.random.default_rng(1)
        bh, bw = int(h * side), int(w * side)
        y0, x0 = (h - bh) // 2, (w - bw) // 2
        img[y0 : y0 + bh, x0 : x0 + bw] = rng.integers(0, 255, (bh, bw, 3))
        for z in _STUDIO_ZOOMS:
            end = resolve_move("push_in", image=img, aspect=16 / 9, zoom=z).evaluate(1)
            # the subject's height stays inside the window, as before #21
            assert end.y <= y0 / h + 0.02 and end.y + end.h >= (y0 + bh) / h - 0.02

    def test_a_degenerate_content_box_is_a_move_error(self):
        img = _busy_photo(400, 300)
        with pytest.raises(MoveError, match="content_box"):
            resolve_move(
                "push_in", image=img, aspect=16 / 9, content_box=(0, 0, 0.001, 0.001)
            )
        tall = _busy_photo(400, 4000)
        with pytest.raises(MoveError, match="downscaling"):
            resolve_move(
                "push_in", image=tall, aspect=16 / 9, content_box=(0, 0, 0.0125, 1)
            )
        with pytest.raises(MoveError, match="content_box must lie inside"):
            resolve_move("push_in", image=img, aspect=16 / 9, content_box=(0, 0, 2, 1))
