#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pilot_analysis.py: честная оценка пилота «до/после» по логу тренажёра.

  python3 chess/pilot_analysis.py trainer_log.csv --user НИК --cutoff 2026-11-01

Строки с ts раньше cutoff это база, остальные это «после». Строки с подсказками и
старые строки без времени не участвуют. База делится на половины A и B по хешу id задачи.
Слабые темы выбираются ТОЛЬКО на A, честный базовый разрыв меряется на B, итог на «после».
Так регрессия к среднему (худшая тема в базе выглядит хуже, чем есть, и «улучшается» сама)
не засчитывается за эффект обучения. Контроль: все задачи без выбранных тем.

Если эффект обучения нулевой, наивная оценка (после минус A) всё равно покажет улучшение:
у выбранных тем база была завышена отбором. Честная оценка (после минус B) около нуля.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from common import split_label, stats as S  # noqa: E402
from session import read_log  # noqa: E402


def analyze(rows, cutoff, k=3, min_n=10, user=None):
    """dict с оценками или None, если данных не хватает. cutoff: строка ISO, например 2026-11-01."""
    scoped = [r for r in rows if user is None or r.get("user") in (user, "", None)]
    use = S.without_hints(scoped)
    dated = [r for r in use if r.get("ts")]
    base = [r for r in dated if r["ts"] < cutoff]
    post = [r for r in dated if r["ts"] >= cutoff]
    a = [r for r in base if split_label(str(r["puzzle_id"]) + "|ab") == "train"]
    b = [r for r in base if split_label(str(r["puzzle_id"]) + "|ab") != "train"]
    if not (a and b and post):
        return None
    res = S.select_and_evaluate(a, b, post, k=k, min_n=min_n)
    if res is None:
        return None
    res.update(n_base=len(base), n_post=len(post), skipped_undated=len(use) - len(dated),
               skipped_hints=len(scoped) - len(use))
    return res


def format_analysis(res):
    if res is None:
        return ("мало данных: нужны строки без подсказок с временем до и после отсечки, "
                "и в первой половине базы хотя бы одна тема с n >= min-n")
    pp = lambda x: "%+.1f" % (100 * x)
    z = res["did"] / res["did_se"] if res["did_se"] else 0.0
    verdict = ("эффект на выбранных темах статистически виден" if abs(z) >= 1.96
               else "эффект не отличим от нуля при этом объёме данных")
    return "\n".join([
        "база: %d задач (половина A %d, половина B %d), после: %d задач; пропущено без времени: %d, с подсказками: %d"
        % (res["n_base"], res["n_a"], res["n_b"], res["n_post"], res["skipped_undated"], res["skipped_hints"]),
        "темы выбраны на половине A: %s" % ", ".join(res["themes"]),
        "разрыв с прогнозом на этих темах (п.п.): A (отбор, завышен) %s, B (честная база) %s, после %s"
        % (pp(res["gap_a"]), pp(res["gap_b"]), pp(res["gap_post"])),
        "наивное улучшение (после минус A): %s п.п. (содержит регрессию к среднему)" % pp(res["naive"]),
        "честное улучшение (после минус B): %s п.п. ± %s (95%%)" % (pp(res["honest"]), pp(1.96 * res["honest_se"])),
        "изменение контрольных задач (без этих тем): %s п.п." % pp(res["control_change"]),
        "разность разностей: %s п.п. ± %s (95%%), z=%+.1f" % (pp(res["did"]), pp(1.96 * res["did_se"]), z),
        "вывод: %s" % verdict,
    ]) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--cutoff", required=True, help="ISO-дата начала фазы «после», напр. 2026-11-01")
    ap.add_argument("--user", default=None)
    ap.add_argument("--k", type=int, default=3, help="сколько слабых тем выбирать")
    ap.add_argument("--min-n", type=int, default=10, help="минимум задач темы на половине A")
    args = ap.parse_args(argv)
    print(format_analysis(analyze(read_log(args.log), args.cutoff, args.k, args.min_n, args.user)), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
