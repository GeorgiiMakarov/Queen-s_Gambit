"""common — общий модуль проверок: холдаут, log-loss, селфтест.
Метод, перенесённый из маджонг-движка (danger_ev). Сам движок в шахматы
не переносится — переносится только метод."""
from .holdout import hash_split, split_label
from .calibration import (MIN_N_FOR_CONCLUSIONS, danger_table,
                          calibration_buckets, expected_p, log_loss)
from .selftest import Check
from . import stats

__all__ = ["hash_split", "split_label", "stats", "expected_p", "log_loss", "calibration_buckets",
           "danger_table", "MIN_N_FOR_CONCLUSIONS", "Check"]
