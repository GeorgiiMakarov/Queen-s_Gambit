#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.calibration — калибровка уверенности и таблица опасности.
log-loss уверенности (как для danger_table) + ожидаемый шанс по
Glicko-логисте от (твой рейтинг − рейтинг задачи). Темы, где факт
стабильно хуже прогноза, — таблица опасности.
Выводы (самоуверенность, хуже прогноза) — только при n >= 100 задач."""
import math
from collections import defaultdict

MIN_N_FOR_CONCLUSIONS = 100


def expected_p(user_rating, item_rating):
    """Ожидаемый шанс решить задачу: логиста от разницы рейтингов (Glicko)."""
    return 1.0 / (1.0 + 10.0 ** (-(user_rating - item_rating) / 400.0))


def log_loss(records):
    """Log-loss уверенности: -(y*log p + (1-y)*log(1-p)), p в [0.01, 0.99].
    records: dicts с полями confidence (0-100) и correct (0/1)."""
    tot = 0.0
    for r in records:
        p = min(max(float(r["confidence"]) / 100.0, 0.01), 0.99)
        y = int(r["correct"])
        tot += -(y * math.log(p) + (1 - y) * math.log(1 - p))
    return tot / len(records) if records else float("nan")


def calibration_buckets(records):
    """Корзины уверенности: (корзина, n, средняя уверенность, точность)."""
    buckets = defaultdict(list)
    for r in records:
        b = min(int(float(r["confidence"]) // 25) * 25, 75)
        buckets[b].append(r)
    out = []
    for b in sorted(buckets):
        sub = buckets[b]
        mc = sum(float(r["confidence"]) for r in sub) / len(sub)
        ac = sum(int(r["correct"]) for r in sub) / len(sub)
        out.append((b, len(sub), mc, ac))
    return out


def danger_table(records, min_n=3):
    """Таблица опасности по темам: (разрыв, тема, n, факт, прогноз).
    records: dicts с полями themes (строка через пробел), correct, expected.
    Отсортировано по разрыву (худшие первыми)."""
    by_theme = defaultdict(list)
    for r in records:
        for t in r["themes"].split():
            by_theme[t].append(r)
    out = []
    for t, sub in by_theme.items():
        if len(sub) < min_n:
            continue
        ac = sum(int(r["correct"]) for r in sub) / len(sub)
        ex = sum(float(r["expected"]) for r in sub) / len(sub)
        out.append((ac - ex, t, len(sub), ac, ex))
    return sorted(out)
