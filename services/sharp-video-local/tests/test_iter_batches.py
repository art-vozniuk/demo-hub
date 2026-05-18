from pathlib import Path

from pipeline.sharp_runner import iter_batches


def test_iter_batches_even():
    items = [Path(f"f{i}.jpg") for i in range(8)]
    batches = list(iter_batches(items, 4))
    assert [len(b) for b in batches] == [4, 4]
    assert batches[0] + batches[1] == items


def test_iter_batches_remainder():
    items = [Path(f"f{i}.jpg") for i in range(7)]
    batches = list(iter_batches(items, 3))
    assert [len(b) for b in batches] == [3, 3, 1]


def test_iter_batches_empty():
    assert list(iter_batches([], 4)) == []
