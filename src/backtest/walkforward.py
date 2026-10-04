"""Walk-forward split logic — chronological, non-overlapping, leak-free.

The final evaluation segment must remain untouched during model
development. This module produces the skeleton; parameter fitting happens
strictly on train segments, selection on validation, and reporting on test.
"""

from __future__ import annotations

from typing import Sequence


def walk_forward_splits(
    dates: Sequence,
    n_folds: int,
    test_size: int,
    val_size: int,
) -> list[dict]:
    """Rolling-origin splits over a sorted, de-duplicated date index.

    Fold i (0-based, oldest first):
        test  : the i-th block from the end, each of length test_size
        val   : the val_size dates immediately before that test block
        train : everything before the val block

    Raises ValueError if any train/val segment would be empty or if the
    date axis is too short for the requested geometry.
    """
    dates = sorted(set(dates))
    n = len(dates)
    min_len = n_folds * test_size + val_size + 1
    if n < min_len:
        raise ValueError(
            f"Need >= {min_len} sessions for n_folds={n_folds}, "
            f"test_size={test_size}, val_size={val_size}; got {n}"
        )

    folds = []
    for i in range(n_folds):
        test_end = n - (n_folds - 1 - i) * test_size
        test_start = test_end - test_size
        val_start = test_start - val_size
        train_end = val_start
        if train_end <= 0 or val_start <= 0:
            raise ValueError("train/val segment would be empty")
        folds.append({
            "fold": i,
            "train": dates[:train_end],
            "val": dates[val_start:test_start],
            "test": dates[test_start:test_end],
        })
    assert_no_leakage(folds)
    return folds


def assert_no_leakage(folds: list[dict]) -> None:
    """Chronology guards: train < val < test within a fold; folds ordered."""
    prev_test_last = None
    for f in folds:
        tr, va, te = f["train"], f["val"], f["test"]
        if not tr or not va or not te:
            raise ValueError(f"fold {f['fold']} has an empty segment")
        if max(tr) >= min(va):
            raise ValueError(f"fold {f['fold']}: train/val overlap")
        if max(va) >= min(te):
            raise ValueError(f"fold {f['fold']}: val/test overlap")
        if prev_test_last is not None and min(te) <= prev_test_last:
            raise ValueError("folds must advance forward in time")
        prev_test_last = max(te)
