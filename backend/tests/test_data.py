from collections import Counter

from scripts.dataset import TEST_PATH, TRAIN_PATH, load

LANGUAGES = {"en", "hinglish", "hi", "ta", "bn"}


def test_split_sizes_and_mix() -> None:
    for path, size in ((TRAIN_PATH, 600), (TEST_PATH, 250)):
        rows = load(path)
        assert len(rows) == size
        mix = Counter(r.category for r in rows)
        assert abs(mix["emergency"] / size - 0.60) < 0.02
        assert abs(mix["non_urgent"] / size - 0.25) < 0.02
        assert abs(mix["prank"] / size - 0.15) < 0.02
        assert {r.language for r in rows} == LANGUAGES


def test_no_text_overlap_between_splits() -> None:
    train = {r.text for r in load(TRAIN_PATH)}
    assert not train & {r.text for r in load(TEST_PATH)}


def test_hard_cases_and_hidden_rows() -> None:
    train, test = load(TRAIN_PATH), load(TEST_PATH)
    assert sum(r.hard is not None for r in train + test) >= 20
    assert sum(r.silent_sos for r in test) >= 3
    assert sum(r.hidden for r in test) == 50
    assert not any(r.hidden for r in train)


def test_labels_are_consistent() -> None:
    for row in load(TRAIN_PATH) + load(TEST_PATH):
        assert row.is_emergency == (row.category == "emergency")
        if row.category == "prank":
            assert row.department == "none" and row.severity == 1
