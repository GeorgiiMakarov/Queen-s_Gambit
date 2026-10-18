#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.make_golden: общие векторы для проверки, что Python и JS считают одно и то же.

  python3 common/make_golden.py          перезаписать common/golden/*.json
  python3 common/make_golden.py --check  проверить, что файлы свежие (для CI)

JS-версия лежит в chess/index.html. Её проверяет chess/test_web.js: пересчитывает
эти векторы и сравнивает с точностью 1e-9. Если менял формулы в stats.py, перегенерируй
векторы и поправь JS, иначе тест веба упадёт.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import split_label, stats as S  # noqa: E402
from common.simulate import simulate, synthetic_pool  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def holdout_vectors():
    rng = random.Random(1001)
    ids = ["00008", "0000D", "0000H", "0009B", "000aY", "000hf"]
    ids += ["".join(rng.choice(ALPHABET) for _ in range(5)) for _ in range(300)]
    return [[i, split_label(i)] for i in ids]


def _clean(x):
    """float('nan') и None в JSON как null."""
    if isinstance(x, float) and x != x:
        return None
    return x


def _dataset(name, records):
    table = S.theme_table(records)
    return {
        "name": name,
        "records": [{"themes": r["themes"], "correct": r["correct"],
                     "expected": r["expected"], "confidence": r["confidence"]}
                    for r in records],
        "summary": S.calibration_summary(records),
        "reliability": S.reliability(records),
        "theme_table": {"rows": table["rows"], "tau2": table["tau2"],
                        "grand": table["grand"], "k": table["k"], "n": table["n"]},
    }


def stats_vectors():
    rng = random.Random(2002)
    pool = synthetic_pool(rng, 1000)
    wil = [[k, n] + list(S.wilson(k, n)) for k, n in
           [(0, 0), (0, 1), (1, 1), (0, 10), (10, 10), (5, 10), (3, 7), (50, 100), (1, 200), (199, 200)]]
    sets = [
        _dataset("calibrated", simulate(pool, rng, 1600, 150)),
        _dataset("overconfident", simulate(pool, rng, 1600, 120, conf_shift=0.2)),
        _dataset("weak_fork_with_length_bias",
                 simulate(pool, rng, 1600, 320, weak=("fork", 0.3),
                          bias={2: .05, 3: .12, 4: .2}, near=500)),
        _dataset("tiny", simulate(pool, rng, 1200, 12)),
    ]
    return {"wilson": wil, "datasets": sets}


def render(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=_clean) + "\n"


def build():
    return {"holdout_vectors.json": render(holdout_vectors()),
            "stats_vectors.json": render(stats_vectors())}


def main(argv):
    files = build()
    if "--check" in argv:
        bad = []
        for fn, text in files.items():
            path = os.path.join(GOLDEN_DIR, fn)
            if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
                bad.append(fn)
        if bad:
            print("векторы устарели: %s. Запусти python3 common/make_golden.py" % ", ".join(bad))
            return 1
        print("golden: свежие")
        return 0
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for fn, text in files.items():
        with open(os.path.join(GOLDEN_DIR, fn), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("записан %s (%d байт)" % (fn, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
