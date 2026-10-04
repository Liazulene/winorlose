"""Independent finite geometry check; not a formal rules proof or game sample.

Enumerate occupied-point subsets without importing the game implementation.
Run from any directory; JSON evidence is printed to standard output.
"""
from collections import Counter
import hashlib
from itertools import combinations
import json
from math import comb
from pathlib import Path
import platform


def main():
    size = 5
    points = size * size
    occupied_count = 7
    full = (1 << points) - 1
    adjacent = []
    for point in range(points):
        row, col = divmod(point, size)
        neighbors = []
        if row > 0:
            neighbors.append(point - size)
        if row + 1 < size:
            neighbors.append(point + size)
        if col > 0:
            neighbors.append(point - 1)
        if col + 1 < size:
            neighbors.append(point + 1)
        adjacent.append(sum(1 << neighbor for neighbor in neighbors))
    histogram = Counter()
    maximum_isolated = -1
    example = None
    tested = 0
    for occupied in combinations(range(points), occupied_count):
        mask = sum(1 << point for point in occupied)
        empty = full ^ mask
        isolated = sum(bool(empty & (1 << point)) and not (adjacent[point] & empty)
                       for point in range(points))
        histogram[isolated] += 1
        tested += 1
        if isolated > maximum_isolated:
            maximum_isolated = isolated
            example = list(occupied)
    minimum_with_empty_neighbor = points - occupied_count - maximum_isolated
    problems = []
    if tested != comb(points, occupied_count):
        problems.append("enumeration count mismatch")
    if sum(histogram.values()) != tested:
        problems.append("histogram total mismatch")
    if maximum_isolated != 5 or minimum_with_empty_neighbor != 13:
        problems.append("unexpected geometric bound")
    result = {
        "purpose": "Independent exhaustive geometric sanity check, not a formal proof, engine test, pilot game, or experimental sample.",
        "imports_game_engine": False,
        "board_size": size,
        "occupied_point_count": occupied_count,
        "subsets_enumerated": tested,
        "expected_subset_count": comb(points, occupied_count),
        "isolated_empty_histogram": dict(sorted(histogram.items())),
        "maximum_isolated_empty_points": maximum_isolated,
        "first_maximum_example_occupied_indices": example,
        "minimum_empty_points_adjacent_to_an_empty_point": minimum_with_empty_neighbor,
        "interpretation": [
            "Adding occupied points cannot increase the number of empty points having an empty neighbor, so the lower bound also applies to subsets with fewer than seven occupied points.",
            "Any empty point with an empty neighbor is nonsuicidal after placement regardless of colors; opponent captures cannot remove that empty liberty.",
            "Before action nine of an empty-board game, at most seven stones and eight historical positions can exist. Distinct placements give distinct successor boards because only the selected empty point becomes occupied.",
            "Even the loose eight-position superko-exclusion bound leaves at least five legal nonpass moves. This reasoning assumes correct state counters and history propagation and is not a verification of the engine implementation.",
            "Arbitrary from_board fixtures may contain histories or boards unreachable in seven actions, and can still exercise NoLegalActionError."
        ],
        "python_version": platform.python_version(),
        "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
        "problems": problems,
    }
    print(json.dumps(result, indent=2, sort_keys=True))
    return int(bool(problems))


if __name__ == "__main__":
    raise SystemExit(main())
