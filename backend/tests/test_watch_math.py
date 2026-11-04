"""The arithmetic behind verified watching, tested on its own."""

import math
import random

import pytest

from apps.progress import watch
from apps.progress.watch import BadClaim, clean_ranges, merge, refill, subtract, trim_to_budget


class TestCleanRanges:
    def test_accepts_ordered_disjoint_ranges_inside_the_video(self):
        assert clean_ranges([[0, 10], [20, 30.5]], 100) == [(0, 10), (20, 30.5)]
        assert clean_ranges([], 100) == []
        assert clean_ranges([(5, 6)], 100) == [(5, 6)]

    def test_touching_ranges_are_fine(self):
        assert clean_ranges([[0, 10], [10, 20]], 100) == [(0, 10), (10, 20)]

    def test_the_end_is_clamped_to_the_video_within_a_hair(self):
        assert clean_ranges([[90, 100.4]], 100) == [(90, 100)]

    @pytest.mark.parametrize(
        "raw",
        [
            "nope",
            None,
            {"0": 5},
            42,
            [[0, 5], "x"],
            [[0]],
            [[0, 5, 9]],
            [[None, 5]],
            [["0", "5"]],
            [[True, 5]],
            [[-1, 5]],
            [[5, 5]],  # empty
            [[5, 4]],  # backwards
            [[0, 101]],  # past the end (beyond the hair of slack)
            [[0, math.inf]],
            [[0, math.nan]],
            [[-math.inf, 5]],
            [[0, 10], [5, 15]],  # overlapping
            [[20, 30], [0, 10]],  # out of order
            [[0, 1e12]],
            [[0, 10]] * 2,  # duplicates overlap
            [[i, i + 0.5] for i in range(watch.MAX_RANGES + 1)],  # too many
        ],
    )
    def test_malformed_claims_are_refused_outright(self, raw):
        with pytest.raises(BadClaim):
            clean_ranges(raw, 100)

    def test_a_single_stretch_cannot_be_longer_than_the_limit(self):
        with pytest.raises(BadClaim):
            clean_ranges([[0, watch.MAX_RANGE_SECONDS + 1]], 10_000)
        assert clean_ranges([[0, watch.MAX_RANGE_SECONDS]], 10_000)


class TestIntervals:
    def test_merge(self):
        assert merge([(5, 8), (0, 3), (3, 4), (7, 10)]) == [(0, 4), (5, 10)]
        assert merge([]) == []

    def test_measure(self):
        assert watch.measure([(0, 3), (10, 12.5)]) == 5.5

    @pytest.mark.parametrize(
        "claimed,credited,expected",
        [
            ([(0, 10)], [], [(0, 10)]),
            ([(0, 10)], [(0, 10)], []),
            ([(0, 10)], [(2, 4)], [(0, 2), (4, 10)]),
            ([(0, 10)], [(-5, 3), (8, 20)], [(3, 8)]),
            ([(0, 10), (20, 30)], [(5, 25)], [(0, 5), (25, 30)]),
            ([(0, 5)], [(10, 20)], [(0, 5)]),
            ([], [(0, 5)], []),
        ],
    )
    def test_subtract(self, claimed, credited, expected):
        assert subtract(claimed, credited) == expected


class TestBucket:
    def test_it_fills_with_real_time_at_the_credited_speed_and_tolerance(self):
        assert refill(0, 10, 1.0) == pytest.approx(11.0)
        assert refill(0, 10, 2.0) == pytest.approx(22.0)
        assert refill(5, 0, 1.0) == 5

    def test_it_never_holds_more_than_its_capacity(self):
        assert refill(0, 10**6, 1.0) == watch.BUCKET_CAPACITY
        assert refill(80, 100, 1.0) == watch.BUCKET_CAPACITY

    def test_time_never_runs_backwards(self):
        assert refill(5, -100, 1.0) == 5

    @pytest.mark.parametrize(
        "new,budget,kept,refused",
        [
            ([(0, 10)], 20, [(0, 10)], 0),
            ([(0, 10), (50, 60)], 15, [(0, 10), (50, 55)], 5),
            ([(0, 10), (50, 60)], 10, [(0, 10)], 10),
            ([(0, 10)], 0, [], 10),
            ([(0, 10)], -3, [], 10),
            ([], 99, [], 0),
        ],
    )
    def test_trim(self, new, budget, kept, refused):
        assert trim_to_budget(new, budget) == (kept, refused)


class TestNumbers:
    @pytest.mark.parametrize("bad", [None, "1", True, [1], math.nan, math.inf, -1, 1e9])
    def test_number_refuses_the_unreasonable(self, bad):
        with pytest.raises(BadClaim):
            watch.number(bad, low=0, high=100)

    def test_number_accepts_ints_and_floats_in_range(self):
        assert watch.number(5, low=0, high=10) == 5.0
        assert watch.number(0.25, low=0, high=10) == 0.25


class TestRandomClaimsNeverBeatTheBound:
    """Whatever is claimed, in whatever order, the credited total stays within
    what real time allows, and inside what was claimed."""

    @pytest.mark.parametrize("seed", range(40))
    def test_the_bound_holds(self, seed):
        rng = random.Random(seed)
        duration = 600.0
        cap = rng.choice([0.5, 1.0, 2.0])
        credited: list = []
        claimed_union: list = []
        level, spent, elapsed_total = watch.INITIAL_BUDGET, 0.0, 0.0
        for _ in range(80):
            dt = rng.choice([0, 0, 0.1, 1, 5, 15, 15, 40, 400])
            elapsed_total += dt
            level = refill(level, dt, cap)
            claim = []
            cursor = 0.0
            for _ in range(rng.randint(0, 6)):
                start = cursor + rng.uniform(0, 100)
                end = start + rng.uniform(0.2, 90)
                if end > duration:
                    break
                claim.append((start, end))
                cursor = end
            claimed_union = merge([*claimed_union, *claim])
            kept, _ = trim_to_budget(subtract(claim, credited), level)
            got = watch.measure(kept)
            level -= got
            spent += got
            credited = merge([*credited, *kept])

            assert watch.measure(credited) == pytest.approx(spent)
            assert spent <= watch.INITIAL_BUDGET + elapsed_total * cap * watch.TOLERANCE + 1e-6
            assert not subtract(credited, claimed_union), "credited something nobody claimed"
            assert all(0 <= s < e <= duration for s, e in credited)
