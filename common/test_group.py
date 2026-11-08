#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common/test_group.py: селфтест групповой оценки и протокола (гоняется в CI)."""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from common import Check, group as G, protocol as P   # noqa: E402

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
c = Check()
close = lambda a, b, tol=1e-9: abs(a - b) <= tol

c("t_crit df=4 равно 2.776", close(G.t_crit(4), 2.776))
c("t_crit большой df стремится к 1.96", close(G.t_crit(500), 1.960))
c("t_crit интерполяция монотонна", G.t_crit(25) < G.t_crit(22) < G.t_crit(20))
est = [0.01, 0.03, -0.02, 0.05, 0.0]
r = G.athlete_t(est)
c("athlete_t: среднее 0.014", close(r["mean"], 0.014))
c("athlete_t: se", close(r["se"], 0.012083045973594574))
c("athlete_t: интервал = среднее +- t*se", close(r["ci_high"] - r["mean"], 2.776 * r["se"]))
c("athlete_t: меньше трёх спортсменов даёт None", G.athlete_t([0.1, 0.2]) is None)
g = G.group_did([0.1, 0.2])
c("group_did: меньше трёх даёт insufficient_athletes", g["verdict"] == "insufficient_athletes" and g["n"] == 2)
g = G.group_did(est, delta=0.05)
c("group_did: ключи", all(k in g for k in ("method", "n", "mean", "se", "ci_low", "ci_high", "verdict")))
c("group_did: ses не влияет на athlete_t", G.group_did(est, ses=[1, 2, 3, 4, 5]) == G.group_did(est))
cases = [((-0.05, 0.04, 0.05), "excluded_above_delta"), ((0.01, 0.2, 0.05), "confirmed"),
         ((0.01, 0.04, 0.05), "confirmed_below_delta"), ((-0.02, 0.06, 0.05), "inconclusive"),
         ((-0.1, -0.01, 0.05), "worsening"), ((0.0, 0.1, 0.05), "inconclusive"),
         ((-0.05, 0.04, None), "inconclusive"), ((0.001, 0.2, None), "confirmed")]
for args, want in cases:
    c("verdict%s -> %s" % (args, want), G.verdict(*args) == want)
g5 = G.group_did(est, delta=0.05, min_athletes=5)
c("group_did: ровно требуемое число спортсменов достаточно", g5["verdict"] != "insufficient_athletes" and g5["n"] == 5)
g6 = G.group_did(est, delta=0.05, min_athletes=6)
c("group_did: меньше требуемого протоколом числа даёт insufficient_athletes",
  g6["verdict"] == "insufficient_athletes" and g6["min_athletes"] == 6 and g6["n"] == 5)
c("group_did: требуемое число не бывает меньше трёх", G.group_did([0.1, 0.2], min_athletes=2)["verdict"] == "insufficient_athletes")
c("athlete_t: min_athletes выше числа спортсменов даёт None", G.athlete_t(est, 6) is None)
c("у каждого состояния есть пояснение", all(s in G.GLOSS for s in
  ("worsening", "confirmed", "confirmed_below_delta", "excluded_above_delta", "inconclusive",
   "insufficient_athletes")))

# протокол: заморозка и привязка к коду
files = ["common/group.py", "common/protocol.py"]
full = {"study": {"athletes_min_for_group_ci": 5, "phase_dates": {"cutoff_iso": "2026-11-01"}},
        "analysis": {"weak_themes_k": 3, "min_n_theme_on_A": 10, "sensitivity_k": [1, 3, 5],
                     "code_files": files, "script_sha256": P.code_sha256(ROOT, files)},
        "decision": {"delta_pp": 5.0}}
with tempfile.TemporaryDirectory() as tmp:
    def write(obj):
        path = os.path.join(tmp, "p.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(obj, f, ensure_ascii=False)
        return path
    cfg, errs = P.resolve(write(full), ROOT)
    c("protocol: полный протокол принят", cfg is not None and not errs)
    c("protocol: хеш протокола равен sha256_of", cfg and cfg["protocol_sha256"] == P.sha256_of(full))
    c("protocol: хеш кода равен code_sha256", cfg and cfg["code_sha256"] == P.code_sha256(ROOT, files))
    c("protocol: delta в п.п. как число", cfg and cfg["delta_pp"] == 5.0)
    c("protocol: требуемое число спортсменов прочитано", cfg and cfg["athletes_min"] == 5)
    for badmin in (2, "TODO", None, 4.5, True):
        bm = json.loads(json.dumps(full))
        bm["study"]["athletes_min_for_group_ci"] = badmin
        cfgm, errsm = P.resolve(write(bm), ROOT)
        c("protocol: athletes_min_for_group_ci=%r отклоняется" % (badmin,), cfgm is None and any("athletes_min" in e for e in errsm))
    todo = json.loads(json.dumps(full))
    todo["study"]["phase_dates"]["cutoff_iso"] = "TODO"
    cfg2, errs2 = P.resolve(write(todo), ROOT)
    c("protocol: TODO в cutoff отклоняется", cfg2 is None and any("cutoff" in e for e in errs2))
    bad = json.loads(json.dumps(full))
    bad["analysis"]["script_sha256"] = "0" * 64
    cfg3, errs3 = P.resolve(write(bad), ROOT)
    c("protocol: чужой хеш кода отклоняется", cfg3 is None and any("изменён" in e for e in errs3))
    nodelta = json.loads(json.dumps(full))
    nodelta["decision"]["delta_pp"] = "TODO"
    cfg4, errs4 = P.resolve(write(nodelta), ROOT)
    c("protocol: TODO в delta отклоняется", cfg4 is None and any("delta" in e for e in errs4))
    c("protocol: хеш не зависит от порядка ключей",
      P.sha256_of({"a": 1, "b": [1, 2]}) == P.sha256_of({"b": [1, 2], "a": 1}))
    c("protocol: нечитаемый файл даёт ошибку", P.resolve(os.path.join(tmp, "нет.json"), ROOT)[0] is None)
sys.exit(0 if c.summary("common.group selftest") else 1)
