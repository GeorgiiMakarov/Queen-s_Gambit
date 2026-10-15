"""common — общий модуль проверок: холдаут, log-loss, селфтест.
Метод, перенесённый из маджонг-движка (danger_ev). Сам движок в шахматы
не переносится — переносится только метод."""
from .holdout import hash_split
from .calibration import (MIN_N_FOR_CONCLUSIONS, danger_table,
                          calibration_buckets, expected_p, log_loss)
from .selftest import Check

__all__ = ["hash_split", "expected_p", "log_loss", "calibration_buckets",
           "danger_table", "MIN_N_FOR_CONCLUSIONS", "Check"]
