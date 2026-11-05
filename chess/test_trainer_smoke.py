#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Дымовой тест trainer.run: сценарий сессии с подменой ввода и вывода.
Запуск: python3 chess/test_trainer_smoke.py (код возврата 1 при FAIL).

Если python-chess установлен, тест идёт на нём (так в CI). Если нет (например,
офлайн-песочница), подставляется минимальная заглушка: она проверяет только код тренажёра
(вывод, лог, выбор задач), но не шахматные правила. Какой режим, печатается в начале."""
import csv
import os
import re
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, ".."))

try:
    import chess  # noqa: F401
    # Без python-chess `import chess` может "удаться": корень репозитория содержит папку chess/,
    # и Python принимает её за namespace-пакет. Настоящий python-chess отличает класс Board.
    REAL = hasattr(chess, "Board")
except ImportError:
    REAL = False

if not REAL:

    class _Move:
        def __init__(self, uci):
            self.uci = uci

        def __eq__(self, o):
            return isinstance(o, _Move) and o.uci == self.uci

        def __hash__(self):
            return hash(self.uci)

        @classmethod
        def from_uci(cls, s):
            ok = 4 <= len(s) <= 5 and s[0] in "abcdefgh" and s[2] in "abcdefgh" \
                and s[1] in "12345678" and s[3] in "12345678"
            if not ok:
                raise ValueError("invalid uci: %r" % s)
            return cls(s)

    class _AnyLegal:
        def __contains__(self, m):
            return True

    class _Board:
        legal_moves = _AnyLegal()

        def __init__(self, fen=None):
            self.fen = fen
            self.turn = fen.split()[1] == "w"

        def unicode(self, borders=False):
            return "[доска %s]" % self.fen.split()[0]

    fake = types.ModuleType("chess")
    fake.Board, fake.Move = _Board, _Move
    fake.PAWN, fake.KNIGHT, fake.BISHOP, fake.ROOK, fake.QUEEN, fake.KING = 1, 2, 3, 4, 5, 6
    fake.engine = types.ModuleType("chess.engine")
    sys.modules["chess"], sys.modules["chess.engine"] = fake, fake.engine

import chess_tactics as ct  # noqa: E402
import session as ss  # noqa: E402
import trainer as tr  # noqa: E402
from common import Check  # noqa: E402

if not REAL:
    ct.is_winning = lambda fen, mv: False

print("python-chess: %s" % ("настоящий" if REAL else "заглушка (проверяется только код тренажёра)"))
c = Check()
tmp = tempfile.mkdtemp(prefix="qg_smoke_")
CSV = os.path.join(HERE, "puzzles_sample.csv")
SOL = {r["PuzzleId"]: r["Solution"] for r in csv.DictReader(open(CSV, encoding="utf-8"))}


def play(user, n, log, set_name="train", hints=False, seed=None):
    lines = []
    asked = {}

    def input_fn(prompt):
        pid = None
        for line in reversed(lines):
            m = re.match(r"^\[\d+/\d+\] (\S+)", line.lstrip("\n"))
            if m:
                pid = m.group(1)
                break
        k = asked.get(pid, 0)
        asked[pid] = k + 1
        return "garbage" if k == 0 else "%s 85" % SOL[pid]

    tr.run(CSV, user, 1600, n, set_name, log, seed=seed, hints=hints, input_fn=input_fn, out=lines.append)
    return lines


def prompts(lines):
    return [l.lstrip("\n") for l in lines if re.match(r"^\n?\[\d+/\d+\] \S+", l)]


def feedbacks(lines):
    return [l for l in lines if l.startswith("ВЕРНО")]


log = os.path.join(tmp, "log.csv")
L1 = play("alice", 6, log)
P1 = prompts(L1)
c("сессия: 6 задач показано", len(P1) == 6)
c("до ответа нет рейтинга и тем", all("рейтинг" not in p and "темы" not in p for p in P1))
c("после ответа есть рейтинг и темы", len(feedbacks(L1)) == 6 and all("Рейтинг задачи" in f and "темы:" in f for f in feedbacks(L1)))
c("мусорная строка отклонена, сессия продолжилась", sum(1 for l in L1 if l.startswith("формат:")) == 6)
c("итог сессии выведен отчётом с интервалами", any("задач в анализе: 6" in l for l in L1))

rows = ss.read_log(log)
c("лог: 6 строк, заголовок как FIELDS", len(rows) == 6 and list(csv.DictReader(open(log, encoding="utf-8")).fieldnames) == ss.FIELDS)
c("лог: user=alice, hints=0, один id сессии, все ответы верные",
  all(r["user"] == "alice" and r["hints"] == "0" and r["correct"] == "1" for r in rows) and len({r["session"] for r in rows}) == 1)
c("лог: метка времени и уверенность записаны", all(re.match(r"^\d{4}-\d\d-\d\dT", r["ts"]) and r["confidence"] == "85.0" for r in rows))

L2 = play("alice", 6, log)
ids1 = {r["puzzle_id"] for r in rows}
ids2 = {r["puzzle_id"] for r in ss.read_log(log)[6:]}
c("вторая сессия не повторяет задачи первой (раньше seed=42 повторял)", len(ids2) == 6 and not (ids1 & ids2))
c("в заголовке второй сессии 'новых 6'", any("новых 6" in l for l in L2))

LB = play("bob", 4, log)
c("другой пользователь: свои новые задачи, лог общий", sum(1 for r in ss.read_log(log) if r["user"] == "bob") == 4)

LH = play("alice", 3, log, hints=True)
PH = prompts(LH)
c("режим подсказок: рейтинг и темы видны до ответа", all("рейтинг" in p and "темы:" in p for p in PH))
hr = [r for r in ss.read_log(log) if r["hints"] == "1"]
c("режим подсказок: hints=1 в логе", len(hr) == 3)
out = []
tr.report(log, "alice", out=out.append)
c("отчёт исключает строки с подсказками (alice: 12 без подсказок, 3 с подсказками)",
  out and "задач в анализе: 12 (с подсказками исключено: 3)" in out[0])

# воспроизводимость по seed
la, lb = os.path.join(tmp, "a.csv"), os.path.join(tmp, "b.csv")
play("u", 5, la, seed=7)
play("u", 5, lb, seed=7)
c("--seed даёт ту же выборку в том же порядке",
  [r["puzzle_id"] for r in ss.read_log(la)] == [r["puzzle_id"] for r in ss.read_log(lb)])

# перенос старого лога прямо из сессии
legacy = os.path.join(tmp, "legacy.csv")
with open(legacy, "w", encoding="utf-8", newline="") as f:
    f.write("puzzle_id,rating,themes,set,move,solution,confidence,correct,winning,seconds,expected\n")
    f.write("00008,1500,fork,train,e2e4,e2e4,70.0,1,1,5.2,0.55\n")
LL = play("carol", 3, legacy)
lr = ss.read_log(legacy)
c("старый лог перенесён в сессии, прежняя строка сохранена", any("старый формат лога перенесён" in l for l in LL)
  and lr[0]["puzzle_id"] == "00008" and lr[0]["session"] == "legacy" and len(lr) == 4)
c("копия старого лога .bak создана", os.path.exists(legacy + ".bak"))
c("отчёта по несуществующему логу нет", (lambda o: (tr.report(os.path.join(tmp, "нет.csv"), out=o.append), o)[1])([])[0].startswith("лога нет"))

sys.exit(0 if c.summary("chess/trainer smoke") else 1)
