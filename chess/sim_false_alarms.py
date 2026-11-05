#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""sim_false_alarms.py: воспроизводит числа аудита на реальной выборке puzzles_sample.csv.

  python3 chess/sim_false_alarms.py [--sims 600]

Модель: спортсмен рейтинга 1600 решает задачи с вероятностью, равной ожиданию Glicko,
и называет уверенность, равную этому ожиданию. Слабых тем нет, калибровка идеальна.
Любой флаг по теме или вердикт о самоуверенности здесь ложная тревога.

Колонки: старый отчёт (тема с n>=3 и разрывом хуже -15 п.п., как в первой версии trainer.report),
новый отчёт (common.stats). Потом мощность на настоящей слабости и эффект отбора худшей темы.
"""
import csv
import os
import random
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, ".."))
from common import hash_split, stats as S  # noqa: E402
from common.calibration import danger_table as old_table  # noqa: E402
from common.simulate import simulate  # noqa: E402


def load_pool(path):
    rows = csv.DictReader(open(path, encoding="utf-8"))
    pool = [{"id": r["PuzzleId"], "rating": int(r["Rating"]), "themes": r["Themes"]} for r in rows]
    return hash_split(pool, key_fn=lambda p: p["id"])


def share(fn, sims):
    return 100.0 * sum(1 for _ in range(sims) if fn()) / sims


def rng_for(seed, name):
    """Свой генератор на каждый раздел: правка одного раздела не сдвигает числа других.
    Строковый seed стабилен между запусками и версиями Python 3.x."""
    return random.Random("%s:%s" % (seed, name))


def main(argv=None):
    argv = argv or []
    sims = int(argv[argv.index("--sims") + 1]) if "--sims" in argv else 600
    seed = int(argv[argv.index("--seed") + 1]) if "--seed" in argv else 2026
    train, test = load_pool(os.path.join(HERE, "puzzles_sample.csv"))
    near = [p for p in train if abs(p["rating"] - 1600) <= 400]
    print("пул train: %d задач, рядом с рейтингом 1600 (±400): %d; прогонов на ячейку: %d; seed %d; Python %s"
          % (len(train), len(near), sims, seed, sys.version.split()[0]))
    print("ошибка симуляции около ±2 п.п. для долей порядка 50%; другой seed сдвигает числа в этих пределах\n")

    print("ЛОЖНЫЕ ТРЕВОГИ: идеальный спортсмен без слабых тем, доля сессий с хотя бы одним флагом")
    print("задач  старый флаг темы  новый флаг СЛАБО  ложный вердикт калибровки (новый)")
    for n in (100, 200, 400, 800):
        rng = rng_for(seed, "false-%d" % n)
        old = share(lambda: any(x[0] < -0.15 for x in old_table(simulate(train, rng, 1600, n))), sims)
        new = share(lambda: any(r["flag"] == "weak" for r in S.theme_table(simulate(train, rng, 1600, n))["rows"]), sims)
        cal = share(lambda: S.calibration_summary(simulate(train, rng, 1600, n))["verdict"]
                    in ("самоуверенность", "недоуверенность"), sims)
        print("%5d  %14.1f%%  %15.1f%%  %24.1f%%" % (n, old, new, cal))

    print("\nЗАДАЧИ ПО РЕЙТИНГУ ИГРОКА (1300-1900), 100 и 200 задач:")
    for n in (100, 200):
        rng = rng_for(seed, "near-%d" % n)
        old = share(lambda: any(x[0] < -0.15 for x in old_table(simulate(near, rng, 1600, n))), sims)
        new = share(lambda: any(r["flag"] == "weak" for r in S.theme_table(simulate(near, rng, 1600, n))["rows"]), sims)
        print("%5d  старый %.1f%%  новый %.1f%%" % (n, old, new))

    print("\nСМЕЩЕНИЕ «первый ход проще полного решения» (по длине +5, +12, +20 п.п.), 400 задач:")
    bias = {2: .05, 3: .12, 4: .2}
    for center in (True, False):
        rng = rng_for(seed, "bias-%s" % center)
        weak = anyf = 0
        for _ in range(sims):
            t = S.theme_table(simulate(train, rng, 1600, 400, bias=bias), center=center)["rows"]
            weak += 1 if any(r["flag"] == "weak" for r in t) else 0
            anyf += 1 if any(r["flag"] for r in t) else 0
        print("  центровка по длине %-5s: ложный СЛАБО в %.1f%% сессий, любой флаг (СЛАБО или СИЛЬНО) в %.1f%%"
              % (center, 100.0 * weak / sims, 100.0 * anyf / sims))

    print("\nМОЩНОСТЬ: настоящая слабость fork на 25 п.п., задачи рядом с рейтингом")
    for n in (200, 400, 800, 1600):
        rng = rng_for(seed, "power-%d" % n)
        hit = share(lambda: any(r["theme"] == "fork" and r["flag"] == "weak" for r in S.theme_table(
            simulate(near, rng, 1600, n, weak=("fork", 0.25)))["rows"]), sims)
        print("  %4d задач: fork найден в %.0f%% сессий" % (n, hit))
    print("САМОУВЕРЕННОСТЬ на 15 п.п. (уверенность выше реального шанса):")
    for n in (30, 50, 100, 200):
        rng = rng_for(seed, "overconf-%d" % n)
        hit = share(lambda: S.calibration_summary(simulate(train, rng, 1600, n, conf_shift=0.15))["verdict"]
                    == "самоуверенность", sims)
        print("  %4d задач: вердикт в %.0f%% сессий" % (n, hit))

    rtm_runs = max(sims, 3000)   # среднее по 600 прогонам плавает на +-0,5 п.п., по 3000 на +-0,2
    print("\nРЕГРЕССИЯ К СРЕДНЕМУ: эффекта обучения нет, база 100+100 задач, после 200, прогонов %d" % rtm_runs)
    m = lambda x: 100.0 * sum(x) / len(x)
    for k in (1, 3):
        rng = rng_for(seed, "rtm-%d" % k)
        naive, honest = [], []
        for _ in range(rtm_runs):
            a, b = simulate(train, rng, 1600, 100), simulate(train, rng, 1600, 100)
            p = simulate(test, rng, 1600, 200)
            r = S.select_and_evaluate(a, b, p, k=k, min_n=8 if k == 3 else 10)
            if r:
                naive.append(r["naive"])
                honest.append(r["honest"])
        mu = sum(honest) / len(honest)
        se = 100.0 * (sum((h - mu) ** 2 for h in honest) / (len(honest) - 1)) ** 0.5 / len(honest) ** 0.5
        print("  худших тем %d: наивное улучшение %+.1f п.п., честное %+.1f п.п. (ошибка среднего %.1f, прогонов %d)"
              % (k, m(naive), m(honest), se, len(naive)))
    print("  минимальный заметный сдвиг точности: 100+100 задач %.0f п.п., 500+500 задач %.0f п.п."
          % (100 * S.mde(100), 100 * S.mde(500)))
    print("  задач одной темы для провала в 25 / 15 / 10 п.п.: %d / %d / %d"
          % (S.tasks_for_gap(0.25), S.tasks_for_gap(0.15), S.tasks_for_gap(0.10)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
