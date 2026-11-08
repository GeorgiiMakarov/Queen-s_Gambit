#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""pilot_analysis.py: честная оценка пилота «до/после» по логу тренажёра.

  python3 chess/pilot_analysis.py trainer_log.csv --user НИК --cutoff 2026-11-01
  python3 chess/pilot_analysis.py trainer_log.csv --group --protocol PROTOCOL.json

Строки с ts раньше cutoff это база, остальные это «после». Строки с подсказками и
старые строки без времени не участвуют. База делится на половины A и B по хешу id задачи.
Слабые темы выбираются ТОЛЬКО на A, честный базовый разрыв меряется на B, итог на «после».
Так регрессия к среднему (худшая тема в базе выглядит хуже, чем есть, и «улучшается» сама)
не засчитывается за эффект обучения. Контроль: все задачи без выбранных тем.

Если эффект обучения нулевой, наивная оценка (после минус A) всё равно покажет улучшение:
у выбранных тем база была завышена отбором. Честная оценка (после минус B) около нуля.

--group считает всех спортсменов лога и группу целиком: среднее разностей по спортсменам и
t-интервал (common/group.py), единица анализа спортсмен. --delta (п.п.) задаёт наименьший
интересный эффект и включает третий исход excluded_above_delta («значимого эффекта нет»).
--protocol берёт отсечку, k, min-n, delta и список чувствительности из замороженного протокола,
отказывается считать (код возврата 2), если параметры командной строки расходятся с ним, если
в нужных полях остались TODO или если код анализа изменён после заморозки, и печатает хеши
протокола и кода. Без --protocol параметры свободные, результат предварительный.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
from common import group as GR, protocol as PR, split_label, stats as S  # noqa: E402
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


def _format_core(res):
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


def format_analysis(res, delta=None):
    """Отчёт по одному спортсмену. delta=None даёт прежний вывод без изменений; delta (доля, 0.05 это
    5 п.п.) добавляет строку трёхстороннего вердикта по интервалу разности разностей."""
    text = _format_core(res)
    if delta is None or res is None:
        return text
    h = 1.96 * res["did_se"]
    state = GR.verdict(res["did"] - h, res["did"] + h, delta)
    return text + "вердикт при delta=%.1f п.п.: %s (%s)\n" % (100 * delta, state, GR.GLOSS[state])


def analyze_group(rows, cutoff, k=3, min_n=10):
    """Все спортсмены лога. Строки без user в группу не берутся (иначе они попали бы к каждому)."""
    rows_g = [r for r in rows if r.get("user")]
    users = sorted({r["user"] for r in rows_g})
    athletes = [(u, analyze(rows_g, cutoff, k, min_n, user=u)) for u in users]
    return {"athletes": athletes, "estimates": [res["did"] for _, res in athletes if res]}


def format_group(rows, cutoff, k=3, min_n=10, delta=None, sens_ks=None, cfg=None, min_athletes=3):
    pp = lambda x: "%+.1f" % (100 * x)
    g = analyze_group(rows, cutoff, k, min_n)
    grp = GR.group_did(g["estimates"], delta=delta, min_athletes=min_athletes)
    out = ["группа: спортсменов в логе %d, проанализировано %d (k=%d, min-n=%d, отсечка %s)"
           % (len(g["athletes"]), len(g["estimates"]), k, min_n, cutoff),
           "строк без user (в группу не берутся): %d" % sum(1 for r in rows if not r.get("user"))]
    for u, res in g["athletes"]:
        if res is None:
            out.append("  спортсмен %s: не анализируется (нет темы с n >= %d на половине A или нет строк без "
                       "подсказок с временем до и после отсечки)" % (u, min_n))
        else:
            z = res["did"] / res["did_se"] if res["did_se"] else 0.0
            out.append("  спортсмен %s: разность разностей %s п.п. ± %s (95%%), z=%+.1f"
                       % (u, pp(res["did"]), pp(1.96 * res["did_se"]).lstrip("+"), z))
    if grp["verdict"] == "insufficient_athletes":
        out.append("групповая оценка: нужно не менее %d проанализированных спортсменов, есть %d"
                   % (grp["min_athletes"], grp["n"]))
    else:
        out.append("групповая оценка (t-интервал по %d спортсменам, df=%d): %s п.п., 95%%-интервал [%s; %s]"
                   % (grp["n"], grp["n"] - 1, pp(grp["mean"]), pp(grp["ci_low"]), pp(grp["ci_high"])))
    if delta is None:
        out.append("вердикт (delta не задана, исход excluded_above_delta недоступен): %s (%s)"
                   % (grp["verdict"], GR.GLOSS[grp["verdict"]]))
    else:
        out.append("вердикт при delta=%.1f п.п.: %s (%s)" % (100 * delta, grp["verdict"], GR.GLOSS[grp["verdict"]]))
    if sens_ks:
        out.append("чувствительность к числу выбираемых тем k (группа, интервал, вердикт):")
        for kk in sens_ks:
            gg = analyze_group(rows, cutoff, kk, min_n)
            r = GR.group_did(gg["estimates"], delta=delta, min_athletes=min_athletes)
            mark = " (основной)" if kk == k else ""
            if r["verdict"] == "insufficient_athletes":
                out.append("  k=%d%s: проанализировано %d, нужно не менее %d" % (kk, mark, r["n"], r["min_athletes"]))
            else:
                out.append("  k=%d%s: %s п.п. [%s; %s], %s, спортсменов %d"
                           % (kk, mark, pp(r["mean"]), pp(r["ci_low"]), pp(r["ci_high"]), r["verdict"], r["n"]))
    if cfg:
        out.append("протокол sha256: %s" % cfg["protocol_sha256"])
        out.append("код sha256: %s" % cfg["code_sha256"])
    else:
        out.append("протокол не задан: параметры заданы вручную, результат предварительный")
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("log")
    ap.add_argument("--cutoff", default=None, help="ISO-дата начала фазы «после», напр. 2026-11-01")
    ap.add_argument("--user", default=None)
    ap.add_argument("--k", type=int, default=None, help="сколько слабых тем выбирать (по умолчанию 3)")
    ap.add_argument("--min-n", type=int, default=None, help="минимум задач темы на половине A (по умолчанию 10)")
    ap.add_argument("--group", action="store_true", help="все спортсмены лога и группа целиком")
    ap.add_argument("--delta", type=float, default=None, help="наименьший интересный эффект, п.п.")
    ap.add_argument("--sensitivity", default=None, help="k для блока чувствительности, например 1,3,5")
    ap.add_argument("--protocol", default=None, help="замороженный протокол пилота (JSON)")
    args = ap.parse_args(argv)
    if args.group and args.user:
        ap.error("--group и --user несовместимы")
    sens = None
    if args.sensitivity:
        try:
            sens = [int(x) for x in args.sensitivity.split(",") if x.strip()]
        except ValueError:
            ap.error("--sensitivity: список целых через запятую")
    cfg = None
    if args.protocol:
        cfg, errors = PR.resolve(args.protocol, ROOT)
        if errors:
            sys.stderr.write("ПРОТОКОЛ НЕ ПРИНЯТ, анализ не запущен:\n" + "".join("  %s\n" % e for e in errors))
            return 2
        mism = []
        for flag, given, fixed in (("--cutoff", args.cutoff, cfg["cutoff"]), ("--k", args.k, cfg["k"]),
                                   ("--min-n", args.min_n, cfg["min_n"]), ("--delta", args.delta, cfg["delta_pp"]),
                                   ("--sensitivity", sens, cfg["sensitivity_k"])):
            if given is not None and given != fixed:
                mism.append("%s=%s, а в протоколе %s" % (flag, given, fixed))
        if mism:
            sys.stderr.write("параметры командной строки расходятся с протоколом, анализ не запущен:\n" +
                             "".join("  %s\n" % m for m in mism))
            return 2
        cutoff, k, min_n, delta_pp, sens = cfg["cutoff"], cfg["k"], cfg["min_n"], cfg["delta_pp"], cfg["sensitivity_k"]
        min_ath = cfg["athletes_min"]
    else:
        if not args.cutoff:
            ap.error("--cutoff обязателен без --protocol")
        cutoff, k, min_n, delta_pp = args.cutoff, args.k or 3, args.min_n or 10, args.delta
        min_ath = GR.MIN_ATHLETES
    delta = None if delta_pp is None else delta_pp / 100.0
    rows = read_log(args.log)
    if args.group:
        print(format_group(rows, cutoff, k, min_n, delta, sens, cfg, min_ath), end="")
        return 0
    print(format_analysis(analyze(rows, cutoff, k, min_n, args.user), delta), end="")
    if cfg:
        print("протокол sha256: %s" % cfg["protocol_sha256"])
        print("код sha256: %s" % cfg["code_sha256"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
