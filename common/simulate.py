#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.simulate: модель спортсмена для проверки статистики на заведомо известной правде.

Спортсмен решает задачу с вероятностью q. По умолчанию q равна ожиданию по Elo-логисте, то есть
слабых тем нет и калибровка идеальна. Дальше можно подмешать:
  weak=("fork", 0.25)   настоящий провал по теме на 25 пунктов
  bias={2: .05, 3: .12} первый ход проще полного решения (смещение по длине задачи)
  conf_shift=0.15       самоуверенность: уверенность выше реального шанса на 15 пунктов
Так проверяется, что отчёт не выдумывает слабые места и находит настоящие.
"""
import random

from .calibration import expected_p
from .stats import length_class

MOTIFS = [("fork", .12), ("sacrifice", .10), ("defensiveMove", .09), ("mateIn1", .08),
          ("mateIn2", .08), ("quietMove", .08), ("hangingPiece", .08), ("pin", .07),
          ("discoveredAttack", .04), ("deflection", .04), ("skewer", .03),
          ("rookEndgame", .06), ("attraction", .03), ("trappedPiece", .03)]
LENGTHS = [("oneMove", .08), ("short", .45), ("long", .35), ("veryLong", .12)]
PHASES = ["opening", "middlegame", "endgame"]
GOALS = ["advantage", "crushing", "equality"]


def synthetic_pool(rng, n=1000):
    """Пул задач, похожий на выборку Lichess: рейтинг 800-3000, длина, фаза, исход, 1-2 мотива."""
    pool = []
    names = [m for m, _ in MOTIFS]
    weights = [w for _, w in MOTIFS]
    for i in range(n):
        tags = [rng.choices([l for l, _ in LENGTHS], [w for _, w in LENGTHS])[0],
                rng.choice(PHASES), rng.choice(GOALS)]
        for _ in range(rng.choice((1, 1, 2))):
            t = rng.choices(names, weights)[0]
            if t not in tags:
                tags.append(t)
        pool.append({"id": "s%04d" % i, "rating": rng.randint(800, 3000),
                     "themes": " ".join(tags)})
    return pool


def simulate(pool, rng, user_rating, n, weak=None, bias=None, conf_shift=0.0, near=None):
    """n записей лога. near=300 берёт задачи с рейтингом user_rating +- 300."""
    src = pool if near is None else [p for p in pool if abs(p["rating"] - user_rating) <= near]
    out = []
    for p in rng.choices(src, k=n):
        e = expected_p(user_rating, p["rating"])
        q = e
        if bias:
            q = min(0.99, q + bias.get(length_class(p["themes"]), 0.0))
        if weak and weak[0] in p["themes"].split():
            q = max(0.01, q - weak[1])
        out.append({"themes": p["themes"], "correct": 1 if rng.random() < q else 0,
                    "expected": e,
                    "confidence": max(1, min(99, round((e + conf_shift) * 100)))})
    return out
