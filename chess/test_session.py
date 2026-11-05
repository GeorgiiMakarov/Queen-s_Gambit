#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Тесты chess/session.py и chess/pilot_analysis.py: работают без python-chess.
Запуск: python3 chess/test_session.py (код возврата 1 при FAIL)."""
import os
import random
import re
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))
import session as ss  # noqa: E402
import pilot_analysis as pa  # noqa: E402
from common import Check, stats as S  # noqa: E402
from common.simulate import simulate, synthetic_pool  # noqa: E402

c = Check()
tmp = tempfile.mkdtemp(prefix="qg_session_")

# ---- схема и идентификаторы
c("FIELDS: 20 колонок, без повторов", len(ss.FIELDS) == 20 and len(set(ss.FIELDS)) == 20)
c("FIELDS начинаются с ts, user, session и заканчиваются timeout",
  ss.FIELDS[:3] == ["ts", "user", "session"] and ss.FIELDS[-1] == "timeout")
c("FIELDS содержат hints и mode", "hints" in ss.FIELDS and "mode" in ss.FIELDS)
ids = {ss.new_session_id() for _ in range(50)}
c("id сессии: формат и уникальность", len(ids) == 50 and all(re.match(r"^\d{8}T\d{6}-[0-9a-z]{6}$", i) for i in ids))
c("метка времени ISO с миллисекундами", re.match(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{3}Z$", ss.now_iso()) is not None)

# ---- лог: создание и перенос старого формата
path = os.path.join(tmp, "new.csv")
c("ensure_log создаёт файл", ss.ensure_log(path) == "new" and ss.read_log(path) == [])
c("повторный ensure_log ничего не меняет", ss.ensure_log(path) == "ok")

OLD = ["puzzle_id", "rating", "themes", "set", "move", "solution", "confidence", "correct",
       "winning", "seconds", "expected"]
legacy = os.path.join(tmp, "legacy.csv")
with open(legacy, "w", encoding="utf-8", newline="") as f:
    f.write(",".join(OLD) + "\n")
    f.write("00008,1500,fork short,train,e2e4,e2e4,70.0,1,1,5.2,0.55\n")
    f.write("0000D,1700,pin long,train,a1a2,b1b2,40.0,0,0,9.9,0.4\n")
before = open(legacy, encoding="utf-8").read()
c("старый лог распознан и перенесён", ss.ensure_log(legacy) == "migrated")
rows = ss.read_log(legacy)
c("после переноса 2 строки, session=legacy, hints=0, user пустой",
  len(rows) == 2 and all(r["session"] == "legacy" and r["hints"] == "0" and r["user"] == "" for r in rows))
c("данные старых строк сохранены",
  rows[0]["puzzle_id"] == "00008" and rows[0]["confidence"] == "70.0" and rows[1]["correct"] == "0")
c("копия .bak содержит исходный файл", open(legacy + ".bak", encoding="utf-8").read() == before)
c("после переноса повторный вызов даёт ok", ss.ensure_log(legacy) == "ok")

# ---- решённые и выбор задач
pool = [{"id": "p%d" % i, "rating": 1000 + i, "themes": "fork", "sol": "e2e4"} for i in range(30)]
log_rows = [{"user": "alice", "set": "train", "puzzle_id": "p0"}, {"user": "alice", "set": "train", "puzzle_id": "p1"},
            {"user": "bob", "set": "train", "puzzle_id": "p2"}, {"user": "", "set": "train", "puzzle_id": "p3"},
            {"user": "alice", "set": "test", "puzzle_id": "p4"}]
c("solved_ids: свои и старые строки без пользователя",
  ss.solved_ids(log_rows, "alice") == {"p0", "p1", "p3", "p4"})
c("solved_ids: фильтр по сету", ss.solved_ids(log_rows, "alice", "train") == {"p0", "p1", "p3"})
c("solved_ids без пользователя берёт всех", len(ss.solved_ids(log_rows)) == 5)
solved = {"p%d" % i for i in range(25)}
pick = ss.pick_tasks(pool, solved, 8, random.Random(1))
c("pick_tasks: сначала непройденные, потом добор решённых без повторов",
  {p["id"] for p in pick[:5]} == {"p25", "p26", "p27", "p28", "p29"} and len({p["id"] for p in pick}) == 8)
whole = ss.pick_tasks(pool, set(), 30, random.Random(2))
c("pick_tasks: без решённых отдаёт n разных задач", len(whole) == 30 and len({p["id"] for p in whole}) == 30)
fresh = ss.pick_tasks(pool, {"p0", "p1", "p2"}, 10, random.Random(3))
c("pick_tasks: при достатке свежих ни одной решённой", all(p["id"] not in {"p0", "p1", "p2"} for p in fresh))
c("pick_tasks: n больше пула отдаёт весь пул", len(ss.pick_tasks(pool, set(), 99, random.Random(4))) == 30)
a1 = [p["id"] for p in ss.pick_tasks(pool, set(), 10, ss.rng_for(7))]
a2 = [p["id"] for p in ss.pick_tasks(pool, set(), 10, ss.rng_for(7))]
a3 = [p["id"] for p in ss.pick_tasks(pool, set(), 10, ss.rng_for(8))]
c("seed воспроизводит выборку, другой seed даёт другую", a1 == a2 and a1 != a3)
r1 = [p["id"] for p in ss.pick_tasks(pool, set(), 10, ss.rng_for(None))]
r2 = [p["id"] for p in ss.pick_tasks(pool, set(), 10, ss.rng_for(None))]
c("без seed выборки разные (раньше seed=42 давал одно и то же каждый раз)", r1 != r2)

# ---- строки до и после ответа
p = {"id": "00008", "rating": 1517, "themes": "fork middlegame", "sol": "e6e7"}
before_line = ss.prompt_line(1, 5, p, True)
c("до ответа нет рейтинга и тем", "рейтинг" not in before_line and "fork" not in before_line and "1517" not in before_line)
c("до ответа указан ход белых или чёрных", "ход белых" in before_line and "ход чёрных" in ss.prompt_line(2, 5, p, False))
hint_line = ss.prompt_line(1, 5, p, True, hints=True)
c("в режиме подсказок рейтинг и темы видны", "рейтинг 1517" in hint_line and "fork middlegame" in hint_line)
fb = ss.feedback_line(True, True, p, 0.55, 4.2)
c("после ответа есть вердикт, рейтинг, темы, ожидание", "ВЕРНО" in fb and "1517" in fb and "fork middlegame" in fb and "55%" in fb)
c("другой выигрышный ход помечен отдельно", "ВЫИГРЫШ" in ss.feedback_line(False, True, p, 0.5, 1.0))
row = ss.make_row(None, "sid", p, "train", "e6e7", 70.0, True, True, 4.234, 0.5512, False)
c("make_row: ключи равны FIELDS, user=anon, hints=0", list(row.keys()) == ss.FIELDS and row["user"] == "anon" and row["hints"] == 0)
c("make_row: округления", row["seconds"] == 4.2 and row["expected"] == 0.551 and row["correct"] == 1)

# ---- отчёт
c("пустой лог", ss.format_report([]) == "лог пуст")
rng = random.Random(77)
POOL = synthetic_pool(rng, 1000)


def as_rows(records, user="u1", hints=0, start=0):
    return [{"ts": "", "user": user, "session": "s", "puzzle_id": "x%d" % (start + i), "rating": 1500,
             "themes": r["themes"], "set": "train", "move": "a", "solution": "a",
             "confidence": r["confidence"], "correct": r["correct"], "winning": r["correct"],
             "seconds": 5, "expected": r["expected"], "hints": hints} for i, r in enumerate(records)]


hinted_only = as_rows(simulate(POOL, rng, 1600, 30), hints=1)
c("только подсказки: сообщение, не отчёт", "с подсказками" in ss.format_report(hinted_only))
null_rows = as_rows(simulate(POOL, rng, 1600, 400))
txt = ss.format_report(null_rows)
c("отчёт: заголовок, вердикт, интервалы, навык",
  txt.startswith("задач в анализе: 400") and "вердикт по калибровке:" in txt and "навык:" in txt and "[" in txt)
c("отчёт без слабых тем у идеального спортсмена не ставит флагов", "СЛАБО" not in txt and "флагов по темам нет" in txt)
mixed = null_rows + as_rows(simulate(POOL, rng, 1600, 25), hints=1, start=1000)
c("смешанный лог: подсказки исключены и посчитаны", ss.format_report(mixed).startswith("задач в анализе: 400 (с подсказками исключено: 25)"))
c("фильтр по пользователю", ss.format_report(null_rows + as_rows(simulate(POOL, rng, 1600, 50), user="u2", start=2000),
                                             user="u1").startswith("задач в анализе: 400"))
over = ss.format_report(as_rows(simulate(POOL, rng, 1600, 150, conf_shift=0.2)))
c("самоуверенный спортсмен: вердикт в отчёте", "вердикт по калибровке: самоуверенность" in over)
weak_rows = as_rows(simulate(POOL, rng, 1600, 1200, weak=("fork", 0.3), near=500))
weak_txt = ss.format_report(weak_rows)
c("настоящая слабая тема fork находится при n=1200 (флаг СЛАБО на строке fork)",
  any(l.strip().startswith("fork") and "СЛАБО" in l for l in weak_txt.splitlines()))

# ---- анализ пилота
cut = "2026-11-01T00:00:00.000Z"
def stamp(rows, ts):
    return [dict(r, ts=ts) for r in rows]
rng2 = random.Random(5)
base_all = []
post_all = []
naive_gap, honest_gap = [], []
for _ in range(60):
    b = stamp(as_rows(simulate(POOL, rng2, 1600, 200)), "2026-10-05T10:00:00.000Z")
    po = stamp(as_rows(simulate(POOL, rng2, 1600, 200)), "2026-11-20T10:00:00.000Z")
    res = pa.analyze(b + po, cut, k=3, min_n=8)
    if res:
        naive_gap.append(res["naive"])
        honest_gap.append(res["honest"])
mean = lambda x: sum(x) / len(x)
c("анализ пилота без эффекта: наивное улучшение завышено, честное около нуля (%.1f и %.1f п.п.)"
  % (100 * mean(naive_gap), 100 * mean(honest_gap)), mean(naive_gap) > 0.02 and abs(mean(honest_gap)) < 0.02)
c("анализ пилота: без данных после отсечки результат None", pa.analyze(stamp(as_rows(simulate(POOL, rng2, 1600, 50)), "2026-10-05T00:00:00.000Z"), cut) is None)
c("анализ пилота: подсказки не участвуют",
  pa.analyze(stamp(as_rows(simulate(POOL, rng2, 1600, 200), hints=1), "2026-10-05T00:00:00.000Z") +
             stamp(as_rows(simulate(POOL, rng2, 1600, 200), hints=1), "2026-11-20T00:00:00.000Z"), cut) is None)

sys.exit(0 if c.summary("chess/session selftest") else 1)
