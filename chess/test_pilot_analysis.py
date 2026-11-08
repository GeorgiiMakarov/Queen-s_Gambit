#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chess/test_pilot_analysis.py: селфтест CLI пилота: прежний вывод, групповой режим, delta, протокол
(гоняется в CI). Лог синтетический, в формате session.FIELDS."""
import csv
import json
import os
import random
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, ".."))
sys.path.insert(0, HERE)
sys.path.insert(0, ROOT)

import pilot_analysis as PA                                   # noqa: E402
from common import Check, group as G, protocol as P           # noqa: E402
from session import FIELDS, read_log                          # noqa: E402

CLI = os.path.join(HERE, "pilot_analysis.py")
THEMES = ["fork", "pin", "skewer", "mateIn2", "hangingPiece", "sacrifice"]
c = Check()


def synth(rng, user, n_base, n_post, base_ts="2026-10-10T10:00:00.000Z", post_ts="2026-11-10T10:00:00.000Z"):
    rows = []
    for phase, n, ts in (("b", n_base, base_ts), ("p", n_post, post_ts)):
        for i in range(n):
            e = rng.uniform(0.35, 0.85)
            themes = "short %s" % " ".join(rng.sample(THEMES, rng.choice((1, 2))))
            rows.append({"ts": ts, "user": user, "puzzle_id": "%s%s%04d" % (user, phase, i), "themes": themes,
                         "expected": e, "confidence": max(1, min(99, round(e * 100))),
                         "correct": 1 if rng.random() < e else 0, "hints": "0"})
    return rows


def write_log(path, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            out = {k: "" for k in FIELDS}
            out.update(r)
            w.writerow(out)


def run(*args):
    p = subprocess.run([sys.executable, CLI] + list(args), capture_output=True, text=True, timeout=120)
    return p.returncode, p.stdout, p.stderr


rng = random.Random(20261106)
with tempfile.TemporaryDirectory() as tmp:
    log = os.path.join(tmp, "log.csv")
    rows = []
    for u in ("a", "b", "c", "d"):
        rows += synth(rng, u, 220, 220)
    rows += synth(rng, "tiny", 6, 5)                       # слишком мало: не анализируется
    write_log(log, rows)
    cut = "2026-11-01"

    # 1. прежний режим не изменился
    rc, out, _ = run(log, "--cutoff", cut, "--user", "a")
    want = PA.format_analysis(PA.analyze(read_log(log), cut, 3, 10, "a"))
    c("прежний CLI: код 0 и вывод равен analyze+format_analysis", rc == 0 and out == want)
    c("прежний вывод не содержит строки delta", "delta" not in out)
    c("format_analysis(res) совпадает с delta=None", PA.format_analysis(PA.analyze(read_log(log), cut, 3, 10, "a"))
      == PA.format_analysis(PA.analyze(read_log(log), cut, 3, 10, "a"), None))
    rc, _, err = run(log)
    c("без --cutoff и без --protocol отказ с кодом 2", rc == 2)

    # 2. delta и три исхода
    res = {"themes": ["fork"], "n_base": 200, "n_post": 200, "skipped_undated": 0, "skipped_hints": 0, "n_a": 100,
           "n_b": 100, "gap_a": -0.1, "gap_b": -0.05, "gap_post": 0.0, "naive": 0.1, "honest": 0.05,
           "honest_se": 0.05, "control_change": 0.0, "did": 0.2, "did_se": 0.05}
    for did, se, state in ((0.2, 0.05, "confirmed"), (0.0, 0.01, "excluded_above_delta"),
                           (0.0, 0.1, "inconclusive"), (-0.3, 0.05, "worsening"),
                           (0.03, 0.005, "confirmed_below_delta")):
        txt = PA.format_analysis(dict(res, did=did, did_se=se), 0.05)
        c("delta: did=%+.2f se=%.3f даёт %s" % (did, se, state), txt.splitlines()[-1].startswith(
            "вердикт при delta=5.0 п.п.: %s" % state))

    # 3. групповой режим без протокола
    rc, out, _ = run(log, "--group", "--cutoff", cut, "--delta", "5", "--sensitivity", "1,3")
    g = PA.analyze_group(read_log(log), cut, 3, 10)
    grp = G.group_did(g["estimates"], delta=0.05)
    c("group: код 0", rc == 0)
    c("group: все четыре спортсмена в выводе", all(("спортсмен %s:" % u) in out for u in "abcd"))
    c("group: tiny не анализируется и не входит в группу", "спортсмен tiny: не анализируется" in out
      and grp["n"] == 4 and "проанализировано 4" in out)
    c("group: итог равен group_did по оценкам спортсменов", ("[%+.1f; %+.1f]" % (100 * grp["ci_low"], 100 * grp["ci_high"])) in out)
    c("group: вердикт напечатан", "вердикт при delta=5.0 п.п.: %s" % grp["verdict"] in out)
    c("group: блок чувствительности k=1 и k=3 (основной)", "  k=1:" in out and "  k=3 (основной):" in out)
    c("group: без протокола предупреждение", "протокол не задан" in out)
    rc, out2, _ = run(log, "--group", "--cutoff", cut)
    c("group: без delta сказано, что excluded_above_delta недоступен", "excluded_above_delta недоступен" in out2)

    # 4. меньше трёх спортсменов
    few = [r for r in rows if r["user"] in ("a", "b", "tiny")]
    log2 = os.path.join(tmp, "few.csv")
    write_log(log2, few)
    rc, out3, _ = run(log2, "--group", "--cutoff", cut)
    c("group: двое проанализированных дают insufficient_athletes", rc == 0 and "insufficient_athletes" in out3)

    # 5. протокол
    files = ["chess/pilot_analysis.py", "chess/session.py", "common/stats.py", "common/group.py",
             "common/protocol.py", "common/calibration.py", "common/holdout.py"]
    proto = {"study": {"athletes_min_for_group_ci": 3, "phase_dates": {"cutoff_iso": cut}},
             "analysis": {"weak_themes_k": 3, "min_n_theme_on_A": 10, "sensitivity_k": [1, 3, 5],
                          "code_files": files, "script_sha256": P.code_sha256(ROOT, files)},
             "decision": {"delta_pp": 5.0}}

    def wp(obj, name="p.json"):
        path = os.path.join(tmp, name)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return path
    pp = wp(proto)
    rc, out4, err4 = run(log, "--group", "--protocol", pp)
    c("protocol: замороженный протокол принят, код 0", rc == 0)
    c("protocol: напечатан хеш протокола", "протокол sha256: %s" % P.sha256_of(proto) in out4)
    c("protocol: напечатан хеш кода", "код sha256: %s" % P.code_sha256(ROOT, files) in out4)
    c("protocol: отсечка и delta взяты из протокола", "отсечка %s" % cut in out4 and "вердикт при delta=5.0" in out4)
    c("protocol: блок чувствительности из протокола k=1,3,5", all(("  k=%d" % k) in out4 for k in (1, 3, 5)))
    rc, out5, _ = run(log, "--protocol", pp, "--user", "a")
    c("protocol: одиночный режим печатает отчёт и хеши", rc == 0 and "протокол sha256:" in out5 and "разность разностей" in out5)
    rc, _, e = run(log, "--group", "--protocol", pp, "--k", "5")
    c("protocol: --k расходится с протоколом, код 2", rc == 2 and "расходятся" in e)
    rc, _, e = run(log, "--group", "--protocol", pp, "--cutoff", "2026-12-01")
    c("protocol: --cutoff расходится, код 2", rc == 2)
    rc, _, e = run(log, "--group", "--protocol", pp, "--k", "3", "--delta", "5")
    c("protocol: совпадающие явные параметры допустимы", rc == 0)
    bad = json.loads(json.dumps(proto))
    bad["study"]["phase_dates"]["cutoff_iso"] = "TODO"
    rc, _, e = run(log, "--group", "--protocol", wp(bad, "bad1.json"))
    c("protocol: TODO в нужном поле, код 2 и анализ не запущен", rc == 2 and "НЕ ПРИНЯТ" in e)
    bad2 = json.loads(json.dumps(proto))
    bad2["analysis"]["script_sha256"] = "f" * 64
    rc, out6, e = run(log, "--group", "--protocol", wp(bad2, "bad2.json"))
    c("protocol: хеш кода не совпал, код 2, отчёта нет", rc == 2 and "изменён" in e and out6 == "")
    rc, _, _ = run(log, "--group", "--user", "a", "--cutoff", cut)
    c("--group и --user несовместимы, код 2", rc == 2)

    # 6. протокол требует больше проанализированных спортсменов, чем есть (в логе их четверо)
    p5 = json.loads(json.dumps(proto))
    p5["study"]["athletes_min_for_group_ci"] = 5
    rc, out7, _ = run(log, "--group", "--protocol", wp(p5, "min5.json"))
    c("protocol: требуется 5, проанализировано 4: insufficient_athletes без интервала",
      rc == 0 and "insufficient_athletes" in out7 and "нужно не менее 5" in out7 and "95%-интервал" not in out7)
    p4 = json.loads(json.dumps(proto))
    p4["study"]["athletes_min_for_group_ci"] = 4
    rc, out8, _ = run(log, "--group", "--protocol", wp(p4, "min4.json"))
    c("protocol: требуется 4, проанализировано 4: интервал считается", rc == 0 and "95%-интервал" in out8)

    # 7. строки без user не берутся в группу и считаются
    anon = [dict(r, user="") for r in synth(rng, "x", 7, 6)]
    log3 = os.path.join(tmp, "anon.csv")
    write_log(log3, rows + anon)
    rc, out9, _ = run(log3, "--group", "--cutoff", cut)
    c("group: число строк без user напечатано", rc == 0 and "строк без user (в группу не берутся): 13" in out9)
    rc, out10, _ = run(log, "--group", "--cutoff", cut)
    c("group: без анонимных строк счётчик равен 0", "строк без user (в группу не берутся): 0" in out10)
sys.exit(0 if c.summary("chess/pilot_analysis cli selftest") else 1)
