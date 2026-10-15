#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common/test_common.py — селфтест общего модуля (гоняется в CI)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from common import (Check, calibration_buckets, danger_table, expected_p,
                    hash_split, log_loss)

c = Check()
# holdout: детерминированный, примерно 50/50
items = [{"id": str(i)} for i in range(200)]
tr1, te1 = hash_split(items, key_fn=lambda p: p["id"])
tr2, te2 = hash_split(items, key_fn=lambda p: p["id"])
c("holdout: детерминированный",
  [p["id"] for p in tr1] == [p["id"] for p in tr2])
c("holdout: ~50/50", 80 <= len(tr1) <= 120 and 80 <= len(te1) <= 120)
c("holdout: без потерь", len(tr1) + len(te1) == 200)
# calibration: логиста
c("expected_p: равный рейтинг = 0.5", abs(expected_p(1600, 1600) - 0.5) < 1e-9)
c("expected_p: выше рейтинг — выше шанс", expected_p(1800, 1600) > 0.5)
# log-loss: уверенный и правый — низкий, уверенный и неправый — высокий
good = [{"confidence": 90, "correct": 1}]
bad = [{"confidence": 90, "correct": 0}]
c("log-loss: правый < неправого", log_loss(good) < log_loss(bad))
c("log-loss: 90% правый ~ 0.105", abs(log_loss(good) - 0.105) < 0.01)
# danger_table: сортировка по разрыву, худшие первыми
rows = [
    {"themes": "pin", "correct": 0, "expected": 0.5},
    {"themes": "pin", "correct": 0, "expected": 0.5},
    {"themes": "pin", "correct": 0, "expected": 0.5},
    {"themes": "mate", "correct": 1, "expected": 0.5},
    {"themes": "mate", "correct": 1, "expected": 0.5},
    {"themes": "mate", "correct": 1, "expected": 0.5},
]
dt = danger_table(rows)
c("danger_table: худшая тема первая", dt[0][1] == "pin" and dt[0][0] < 0)
# calibration_buckets: корзины по уверенности
brows = [
    {"confidence": 80, "correct": 1},
    {"confidence": 30, "correct": 0},
]
bk = calibration_buckets(brows)
c("calibration_buckets: две корзины", len(bk) == 2)
sys.exit(0 if c.summary("common selftest") else 1)
