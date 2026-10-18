#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты common.stats: на известных значениях и на симуляции с заведомо известной правдой.
Запуск: python3 common/test_stats.py (без pytest, код возврата 1 при FAIL)."""
import hashlib
import math
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import Check, hash_split, split_label, stats as S  # noqa: E402
from common import make_golden  # noqa: E402
from common.simulate import simulate, synthetic_pool  # noqa: E402

c = Check()
rng = random.Random(4242)
POOL = synthetic_pool(rng, 1000)
BIAS = {2: .05, 3: .12, 4: .2}

# ---- интервал Уилсона
lo, hi = S.wilson(5, 10)
c("wilson 5/10 около (0.237, 0.763)", abs(lo - 0.2366) < 1e-3 and abs(hi - 0.7634) < 1e-3)
c("wilson при n=0 это (0, 1)", S.wilson(0, 0) == (0.0, 1.0))
c("wilson 0/10: нижняя граница 0", S.wilson(0, 10)[0] == 0.0 and 0.25 < S.wilson(0, 10)[1] < 0.30)
c("wilson 10/10: верхняя граница 1", abs(S.wilson(10, 10)[1] - 1.0) < 1e-12 and 0.70 < S.wilson(10, 10)[0] < 0.75)

# ---- сводка калибровки на детерминированных данных
def fixed(conf, n_correct, n):
    return [{"confidence": conf, "correct": 1 if i < n_correct else 0} for i in range(n)]

s = S.calibration_summary(fixed(50, 50, 100))
c("константа 50%% при точности 50%%: Brier 0.25, навык 0",
  abs(s["brier"] - 0.25) < 1e-12 and abs(s["skill"]) < 1e-9 and abs(s["log_loss"] - math.log(2)) < 1e-12)
c("самоуверенность: уверенность 90, точность 60, n=100",
  S.calibration_summary(fixed(90, 60, 100))["verdict"] == "самоуверенность")
c("недоуверенность: уверенность 30, точность 70, n=100",
  S.calibration_summary(fixed(30, 70, 100))["verdict"] == "недоуверенность")
c("калибровка в норме: уверенность 70, точность 70",
  S.calibration_summary(fixed(70, 70, 100))["verdict"] == "в пределах шума")
c("n=20 даёт 'мало данных', даже при явной самоуверенности",
  S.calibration_summary(fixed(95, 5, 20))["verdict"] == "мало данных")
c("пустой список не падает", S.calibration_summary([])["verdict"] == "нет данных")
c("строковые поля из CSV читаются",
  S.calibration_summary([{"confidence": "80", "correct": "1"}, {"confidence": "20.0", "correct": "0"}])["n"] == 2)

# ---- корзины и подсказки
rec = simulate(POOL, rng, 1600, 200)
rel = S.reliability(rec)
c("корзины: сумма n равна числу записей", sum(b["n"] for b in rel) == len(rec))
c("корзины: точность внутри своего интервала", all(b["acc_lo"] <= b["acc"] <= b["acc_hi"] for b in rel))
hinted = [dict(r, hints=1) for r in rec[:50]] + [dict(r, hints=0) for r in rec[50:]] + [dict(rec[0])]
c("without_hints убирает строки с подсказками", len(S.without_hints(hinted)) == 151)

# ---- таблица тем: служебные теги и структура
tt = S.theme_table(simulate(POOL, rng, 1600, 400))
themes = {r["theme"] for r in tt["rows"]}
c("служебные теги не попадают в таблицу", not (themes & S.SERVICE_TAGS))
c("у строк с n>=20 есть усадка, у остальных нет",
  all((r["shrunk"] is not None) == (r["n"] >= 20) for r in tt["rows"]))
c("интервал разрыва содержит разрыв", all(r["lo"] <= r["gap"] <= r["hi"] for r in tt["rows"]))

# ---- ложные срабатывания при идеально откалиброванном спортсмене без слабых тем
def share(fn, sims):
    return sum(1 for _ in range(sims) if fn()) / sims

fa400 = share(lambda: any(r["flag"] == "weak" for r in
                          S.theme_table(simulate(POOL, rng, 1600, 400))["rows"]), 300)
c("нулевая гипотеза, n=400: ложный флаг темы не чаще 3%% (было %.1f%%)" % (100 * fa400), fa400 <= 0.03)
fa100 = share(lambda: any(r["flag"] == "weak" for r in
                          S.theme_table(simulate(POOL, rng, 1600, 100))["rows"]), 300)
c("нулевая гипотеза, n=100: ложный флаг темы не чаще 3%% (было %.1f%%)" % (100 * fa100), fa100 <= 0.03)
fv = share(lambda: S.calibration_summary(simulate(POOL, rng, 1600, 100))["verdict"]
           in ("самоуверенность", "недоуверенность"), 300)
c("нулевая гипотеза, n=100: ложный вердикт калибровки не чаще 9%% (было %.1f%%)" % (100 * fv), fv <= 0.09)

# ---- смещение «первый ход проще полного решения»: центровка по длине спасает
def any_flag(center):
    t = S.theme_table(simulate(POOL, rng, 1600, 400, bias=BIAS), center=center)
    return any(r["flag"] for r in t["rows"])
with_c = share(lambda: any_flag(True), 200)
without_c = share(lambda: any_flag(False), 200)
c("смещение по длине: с центровкой флагов не больше 10%% (%.1f%%)" % (100 * with_c), with_c <= 0.10)
c("смещение по длине: без центровки флагов не меньше 50%% (%.1f%%)" % (100 * without_c), without_c >= 0.50)

# ---- мощность: реальные проблемы находятся
pw = share(lambda: any(r["theme"] == "fork" and r["flag"] == "weak" for r in S.theme_table(
    simulate(POOL, rng, 1600, 800, weak=("fork", 0.25), near=400))["rows"]), 150)
c("слабая тема fork на 25 пунктов находится при n=800 не реже, чем в 60%% (%.0f%%)" % (100 * pw), pw >= 0.60)
po = share(lambda: S.calibration_summary(simulate(POOL, rng, 1600, 100, conf_shift=0.15))["verdict"]
           == "самоуверенность", 200)
c("самоуверенность на 15 пунктов находится при n=100 не реже, чем в 80%% (%.0f%%)" % (100 * po), po >= 0.80)

# ---- регрессия к среднему: выбор на одной половине, оценка на другой
naive, honest = [], []
for _ in range(200):
    a = simulate(POOL, rng, 1600, 100)
    b = simulate(POOL, rng, 1600, 100)
    p = simulate(POOL, rng, 1600, 200)
    r = S.select_and_evaluate(a, b, p, k=3, min_n=8)
    if r:
        naive.append(r["naive"])
        honest.append(r["honest"])
m = lambda x: sum(x) / len(x)
c("без обучения наивное улучшение завышено, не меньше +3 п.п. (%.1f)" % (100 * m(naive)), m(naive) >= 0.03)
c("без обучения честная оценка около нуля, в пределах 2 п.п. (%.1f)" % (100 * m(honest)), abs(m(honest)) <= 0.02)

# ---- планирование
c("mde(100) около 0.198, mde(500) около 0.089",
  abs(S.mde(100) - 0.198) < 0.002 and abs(S.mde(500) - 0.0886) < 0.001)
c("tasks_for_gap: 0.15 -> 132, 0.25 -> 48", S.tasks_for_gap(0.15) == 132 and S.tasks_for_gap(0.25) == 48)

# ---- сплит: поведение hash_split не изменилось, метка совпадает со старой формулой
def old_label(key):
    return "train" if int(hashlib.md5(str(key).encode()).hexdigest(), 16) % 1000 / 1000.0 < 0.5 else "test"
keys = ["k%d" % i for i in range(2000)]
c("split_label совпадает со старой формулой", all(split_label(k) == old_label(k) for k in keys))
tr, te = hash_split(keys, key_fn=lambda k: k)
c("hash_split: train и test не пересекаются и покрывают всё",
  not (set(tr) & set(te)) and len(tr) + len(te) == len(keys) and 900 < len(tr) < 1100)

# ---- свежесть общих векторов для JS
c("golden/*.json свежие (python3 common/make_golden.py)",
   make_golden.main(["--check"]) == 0)

sys.exit(0 if c.summary("common.stats selftest") else 1)
