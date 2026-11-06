#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chess/expectation_check.py — проверка модели ожидания (P0, GPT-6).

Что проверяется. Тренажёр считает ожидаемый шанс решить задачу формулой
    expected_p = 1 / (1 + 10^(-(рейтинг игрока - рейтинг задачи)/400))
Это логиста Эло (шкала 400), а не полный Glicko-2: члена с RD (неопределённостью
рейтинга) в формуле нет, поэтому в отчётах она называется «Elo-baseline»,
а не доказанным эталоном. Два известных смещения:
  1. Ожидание считается для ПОЛНОГО решения, а classic-режим меряет только
     ПЕРВЫЙ ход. Для многоходовых задач факт систематически выше прогноза.
     Поэтому проверка всегда идёт в разрезе класса длины (oneMove/short/
     long/veryLong) — см. common.stats.length_class.
  2. RD рейтинга игрока и задачи не учитываются: формула treats рейтинги как
     точные. Колонки RatingDeviation в classic-выборке не сохранены (см. аудит v1);
     для Calc-пула RD есть в sidecar puzzles_calc_rd.csv.

Что делает скрипт. Читает лог тренажёра (trainer_log.csv, строки без hints),
группирует записи по корзинам предсказанного ожидания и сравнивает среднее
предсказание с фактической точностью в каждой корзине (reliability diagram
в тексте) + ECE (expected calibration error). Дополнительно:
  - сплит train/test по хешу puzzle_id (как holdout): параметры перекалибровки
    подбираются на train, проверяются на test;
  - альтернативная калибровка: сдвиг логита на константу (intercept-only),
    подобранный на train, против исходной формулы.

Использование:
    python3 chess/expectation_check.py --log trainer_log.csv
    python3 chess/expectation_check.py --selftest

Выводы — только при n >= 100 (как везде в проекте); при меньшем n скрипт
печатает корзины, но вердикт не ставит.
"""
import argparse
import csv
import hashlib
import math
import sys
from collections import defaultdict

sys.path.insert(0, ".")
from common.stats import wilson, length_class  # noqa: E402

MIN_N_VERDICT = 100
EDGES = [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.01]


def _hash_split(puzzle_id):
    """Сплит по хешу PuzzleId, как common.holdout.split_label (mod 2)."""
    h = int(hashlib.md5(str(puzzle_id).encode()).hexdigest(), 16)
    return "train" if h % 2 == 0 else "test"


def _bin_index(p):
    for j in range(len(EDGES) - 1):
        if p < EDGES[j + 1]:
            return j
    return len(EDGES) - 2


def reliability_by_expected(records):
    """Корзины ожидания: (lo, hi, n, mean_pred, acc, acc_lo, acc_hi)."""
    bins = defaultdict(list)
    for r in records:
        bins[_bin_index(float(r["expected"]))].append(r)
    out = []
    for j in range(len(EDGES) - 1):
        sub = bins.get(j, [])
        if not sub:
            continue
        n = len(sub)
        mp = sum(float(r["expected"]) for r in sub) / n
        kk = sum(int(r["correct"]) for r in sub)
        lo, hi = wilson(kk, n)
        out.append({"lo": EDGES[j], "hi": EDGES[j + 1], "n": n,
                    "mean_pred": mp, "acc": kk / n, "acc_lo": lo, "acc_hi": hi})
    return out


def ece(records):
    """Expected calibration error: взвешенное |mean_pred - acc| по корзинам."""
    if not records:
        return float("nan")
    tot = 0.0
    for b in reliability_by_expected(records):
        tot += b["n"] * abs(b["mean_pred"] - b["acc"])
    return tot / len(records)


def _logit(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return math.log(p / (1 - p))


def _sigmoid(x):
    return 1.0 / (1.0 + math.exp(-x))


def fit_shift(records):
    """Подбор сдвига логита на train: mean(logit(pred)) -> mean(logit(acc)).

    Возвращает сдвиг d: calibrated = sigmoid(logit(pred) + d). При пустых
    данных или вырожденной точности возвращает 0.0.
    """
    if not records:
        return 0.0
    acc = sum(int(r["correct"]) for r in records) / len(records)
    if acc <= 0.0 or acc >= 1.0:
        return 0.0
    mp = sum(float(r["expected"]) for r in records) / len(records)
    return _logit(acc) - _logit(mp)


def load_log(path):
    """Чтение лога, без строк с hints (как везде в проекте)."""
    rows = []
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if int(r.get("hints") or 0):
                continue
            if "expected" not in r or "correct" not in r:
                continue
            rows.append(r)
    return rows


def report(records, out):
    """Печать reliability diagram + ECE + train/test + сдвиг. Возвращает ECE."""
    n = len(records)
    out(f"записей (без hints): {n}")
    if n == 0:
        return float("nan")
    out("\nкорзина ожидания | n | среднее предск. | точность | интервал Уилсона")
    for b in reliability_by_expected(records):
        out(f"  {b['lo']:.1f}-{b['hi']:.1f} | {b['n']:4d} | {b['mean_pred']:.3f} | "
            f"{b['acc']:.3f} | [{b['acc_lo']:.3f}, {b['acc_hi']:.3f}]")
    e = ece(records)
    out(f"\nECE (все): {e:.4f}")
    # разрез по длине: показывает смещение первый ход vs полное решение
    by_len = defaultdict(list)
    for r in records:
        by_len[length_class(r.get("themes", ""))].append(r)
    names = {0: "без тега", 1: "oneMove", 2: "short", 3: "long", 4: "veryLong"}
    out("ECE по классу длины:")
    for lc in sorted(by_len):
        sub = by_len[lc]
        if not sub:
            continue
        acc = sum(int(r["correct"]) for r in sub) / len(sub)
        mp = sum(float(r["expected"]) for r in sub) / len(sub)
        out(f"  {names.get(lc, lc)}: n={len(sub)}, предск. {mp:.3f}, факт {acc:.3f}, "
            f"разрыв {acc - mp:+.3f}, ECE {ece(sub):.4f}")
    # train/test: сдвиг на train, проверка на test
    tr = [r for r in records if _hash_split(r.get("puzzle_id", "")) == "train"]
    te = [r for r in records if _hash_split(r.get("puzzle_id", "")) == "test"]
    if tr and te:
        d = fit_shift(tr)
        cal = [{"expected": _sigmoid(_logit(float(r["expected"])) + d),
                "correct": r["correct"]} for r in te]
        out(f"\ntrain n={len(tr)}, test n={len(te)}")
        out(f"сдвиг логита на train: {d:+.3f}")
        out(f"ECE на test: исходная {ece(te):.4f}, со сдвигом {ece(cal):.4f}")
    if n < MIN_N_VERDICT:
        out(f"\nвердикт: мало данных (нужно n >= {MIN_N_VERDICT})")
    elif e <= 0.03:
        out("\nвердикт: baseline калиброван (ECE <= 0.03)")
    elif e <= 0.07:
        out("\nвердикт: baseline приблизительно калиброван (ECE <= 0.07)")
    else:
        out("\nвердикт: baseline НЕ калиброван (ECE > 0.07) — нужен пересмотр")
    return e


def selftest():
    """Синтетика: идеальная калибровка, систематическое смещение, сплит."""
    import random
    rng = random.Random(42)
    # 1. Идеальная калибровка: факт ~ Bernoulli(pred).
    recs = []
    for i in range(2000):
        p = rng.choice([0.2, 0.4, 0.5, 0.6, 0.8])
        recs.append({"puzzle_id": f"s{i}", "expected": p,
                     "correct": 1 if rng.random() < p else 0, "themes": ""})
    e1 = ece(recs)
    assert e1 < 0.03, f"идеальная калибровка: ECE {e1}"
    # 2. Систематическое смещение вверх (как первый ход vs полное решение):
    #    факт на 15 п.п. выше прогноза во всех корзинах.
    recs2 = []
    for i in range(2000):
        p = rng.choice([0.2, 0.4, 0.5, 0.6, 0.8])
        recs2.append({"puzzle_id": f"b{i}", "expected": p,
                      "correct": 1 if rng.random() < min(p + 0.15, 0.99) else 0,
                      "themes": ""})
    e2 = ece(recs2)
    assert e2 > 0.10, f"смещение должно дать ECE > 0.10, получили {e2}"
    # 3. Сдвиг на train чинит смещение на test.
    tr = [r for r in recs2 if _hash_split(r["puzzle_id"]) == "train"]
    te = [r for r in recs2 if _hash_split(r["puzzle_id"]) == "test"]
    d = fit_shift(tr)
    assert d > 0.3, f"сдвиг должен быть положительным, получили {d}"
    cal = [{"expected": _sigmoid(_logit(float(r["expected"])) + d),
            "correct": r["correct"]} for r in te]
    assert ece(cal) < ece(te), "сдвиг должен уменьшить ECE на test"
    # 4. Сплит примерно пополам.
    assert 800 < len(tr) < 1200, f"сплит не пополам: train {len(tr)}"
    print("expectation_check selftest: 4/4")
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", help="путь к trainer_log.csv")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if not args.log:
        ap.error("нужен --log или --selftest")
    records = load_log(args.log)
    report(records, print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
