#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
trainer.py: тренажёр тактики (пункт 3). Задачи решает ЧЕЛОВЕК, а не поиск.
Показывает задачу, принимает ход (UCI) и уверенность в процентах, засекает время,
записывает итог. Рейтинг и темы задачи показываются только ПОСЛЕ ответа: в партии
никто не сообщает мотив и сложность, а рейтинг якорит уверенность.

Калибровка: интервалы и z-критерий (common/stats.py), ожидаемый шанс по Glicko-логисте
от (твой рейтинг минус рейтинг задачи). Таблица тем показывает слабость относительно
собственного уровня, флаг только при достаточном n (см. common/stats.py).

Режимы (--mode):
  classic    — текущее поведение (по умолчанию). Один ход + уверенность в одной
               строке, без лимита и фильтра рейтинга.
  intuition  — «Интуиция» (Карлсен). Любая задача, оценивается только первый ход
               решения. Жёсткий лимит --limit (по умолчанию 10 с): не успел —
               промах, уверенность = 0, пометка timeout. Уверенность спрашивать
               после хода, вне лимита. В mateIn1 засчитывается любой матующий ход.
  calc       — «Расчёт» (Накамура). Пул puzzles_calc.csv (long/veryLong, Moves >= 6).
               Игрок вводит ВСЮ линию сразу вслепую (свои ходы и ожидаемые ответы),
               без показа промежуточных позиций. Уверенность — на линию целиком.
               Мягкий лимит 180 с: только логируется. strict (вся линия верна)
               идёт в статистику; depth (сколько ходов верно до первой ошибки) —
               в отчёт. В финальной позиции мата засчитывается альтернативный
               матующий ход.
Честность: режимы с разными условиями нельзя смешивать в одной калибровке
(ожидание Glicko верно только для решения без ограничений) — отчёт разделяет
строки по mode, как уже делается для hints. Одна задача не попадает к одному
игроку дважды и в оба режима (intuition/calc исключают PuzzleId уже из лога);
рейтинг задач подбирается вокруг рейтинга игрока одинаково в обоих режимах
(полоса +-200); холдаут по хешу PuzzleId сохранён. В НИКАКОМ режиме рейтинг
и темы не показываются до ответа.

Использование:
  python3 trainer.py --user НИК --n 10              # практика (train), рейтинг из API
  python3 trainer.py --user НИК --n 10 --set test   # проверка на свежем сете
  python3 trainer.py --user НИК --n 10 --hints      # тренировка с подсказками (в отчёт не идёт)
  python3 trainer.py --user НИК --n 10 --mode intuition --limit 10
  python3 trainer.py --user НИК --n 10 --mode calc
  python3 trainer.py --report --user НИК            # отчёт по логу
  python3 trainer.py --selftest                     # селфтест режимов
Формат ввода (classic): ход (UCI) + уверенность (0-100) в одной строке.
Формат ввода (intuition): сначала ход (UCI), потом уверенность (0-100).
Формат ввода (calc): сначала линия (UCI через пробел), потом уверенность.
Выход: пустая строка. Лог: trainer_log.csv (дописывается; старый формат переносится сам).
"""
import argparse
import csv
import os
import sys
import time

import chess

import chess_tactics as ct
from common.holdout import hash_split
from session import (FIELDS, ensure_log, feedback_line, format_report, make_row,
                     new_session_id, pick_tasks, prompt_line, read_log, rng_for, solved_ids)

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import expected_p  # noqa: E402

LOG = "trainer_log.csv"
MODES = ["classic", "intuition", "calc"]
INTUITION_LIMIT_DEFAULT = 10   # жёсткий лимит, с
CALC_SOFT_LIMIT = 180          # мягкий лимит, с (только логируется)
RATING_BAND = 200              # полоса рейтинга вокруг рейтинга игрока (intuition/calc)
MIN_N_PROFILE = 100            # профиль — только при n>=100 в КАЖДОМ режиме


def fetch_rating(username):
    """Рейтинг задач Lichess по нику из открытого API (perfs.puzzle.rating).
    Не задаётся вручную, не устареет. Ник нужен и для лога, и для будущих разборов партий."""
    import json
    import urllib.error
    import urllib.request
    url = "https://lichess.org/api/user/%s" % username
    try:
        with urllib.request.urlopen(url, timeout=15) as r:
            data = json.loads(r.read().decode("utf-8"))
    except (urllib.error.URLError, ValueError, TimeoutError) as e:
        return None, "API недоступен: %s" % e
    try:
        return int(data["perfs"]["puzzle"]["rating"]), None
    except (KeyError, TypeError, ValueError):
        return None, "у пользователя нет рейтинга задач (perfs.puzzle)"


def mates(board, move_uci):
    """Даёт ли ход мат (для альтернативного мата в mateIn1 / финале линии)."""
    try:
        mv = chess.Move.from_uci(move_uci)
    except ValueError:
        return False
    if mv not in board.legal_moves:
        return False
    board.push(mv)
    m = board.is_checkmate()
    board.pop()
    return m


def score_intuition(fen, move_s, sol, themes, dt, limit):
    """Чистый скоринг intuition (без ввода). Возвращает
    (correct, winning, timeout, confidence). Таймаут — промах."""
    if dt > limit:
        return 0, 0, 1, 0
    board = chess.Board(fen)
    correct = 1 if move_s == sol else 0
    if not correct and "mateIn1" in themes and mates(board, move_s):
        correct = 1  # альтернативный матующий ход в mateIn1
    winning = correct or ct.is_winning(fen, move_s)
    return correct, int(winning), 0, None


def _final_mates(fen, sol_line_s):
    """Заканчивается ли линия решения матом (для альтернативного мата в финале)."""
    board = chess.Board(fen)
    for u in sol_line_s.split():
        try:
            mv = chess.Move.from_uci(u)
        except ValueError:
            return False
        if mv not in board.legal_moves:
            return False
        board.push(mv)
    return board.is_checkmate()


def score_calc(fen, entered_s, sol_line_s):
    """Чистый скоринг calc (без ввода). Возвращает (strict, depth).
    strict = 1, если вся линия верна (или альтернативный мат в финале);
    depth = сколько ходов верно до первой ошибки."""
    sol = sol_line_s.split()
    entered = entered_s.split()
    if entered == sol:
        return 1, len(sol)
    depth = 0
    for a, b in zip(entered, sol):
        if a == b:
            depth += 1
        else:
            break
    # альтернативный мат в финале: все, кроме последнего, совпали,
    # а последний ход (другой) тоже даёт мат
    if (depth == len(sol) - 1 and len(entered) >= len(sol)
            and _final_mates(fen, sol_line_s)):
        board = chess.Board(fen)
        ok = True
        for u in entered[:len(sol) - 1]:
            try:
                mv = chess.Move.from_uci(u)
            except ValueError:
                ok = False
                break
            if mv not in board.legal_moves:
                ok = False
                break
            board.push(mv)
        if ok and mates(board, entered[len(sol) - 1]):
            return 1, len(sol)
    return 0, depth


def load_calc(path):
    """Пул calc: puzzles_calc.csv (PuzzleId, FEN, Solution, Line, Rating, Themes).
    Холдаут по хешу PuzzleId через split_label (common/holdout), как в load_lichess."""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    puzzles = []
    for r in rows:
        puzzles.append({"id": r["PuzzleId"], "fen": r["FEN"], "sol": r["Solution"],
                        "line": r["Line"], "themes": r["Themes"],
                        "rating": int(r["Rating"])})
    train, test = hash_split(puzzles, key_fn=lambda p: p["id"])
    for p in train:
        p["set"] = "train"
    for p in test:
        p["set"] = "test"
    return train, test


def report(log_path, user=None, out=print):
    if not os.path.exists(log_path):
        out("лога нет: %s" % log_path)
        return
    rows = read_log(log_path)
    modes = [m for m in MODES if any(r.get("mode") == m for r in rows)]
    if not modes:
        out("лог пуст")
        return
    if modes == ["classic"]:
        out(format_report(rows, user).rstrip("\n"))
        return
    # режимы: отчёт по каждому отдельно (не смешивать калибровки)
    for m in modes:
        out("\n===== режим %s =====" % m)
        out(format_report(rows, user, mode=m).rstrip("\n"))
    # профиль: какой режим сильнее отстаёт от ожидания (только при n>=100 в каждом)
    if {"intuition", "calc"} <= set(modes):
        diffs = {}
        ns = {}
        for m in ("intuition", "calc"):
            mr = [r for r in rows if r.get("mode") == m and not int(r.get("hints") or 0)]
            ns[m] = len(mr)
            diffs[m] = (sum(int(r["correct"]) for r in mr) / len(mr)
                        - sum(float(r["expected"]) for r in mr) / len(mr)) if mr else 0
        if ns["intuition"] >= MIN_N_PROFILE and ns["calc"] >= MIN_N_PROFILE:
            weaker = "интуиция" if diffs["intuition"] < diffs["calc"] else "расчёт"
            out("\nпрофиль: %s слабее (разница intuition %+.1f п.п., calc %+.1f п.п.)"
                % (weaker, diffs["intuition"] * 100, diffs["calc"] * 100))
        else:
            out("\nпрофиль: выводы рано (нужно n >= %d в КАЖДОМ режиме; сейчас "
                "intuition %d, calc %d)" % (MIN_N_PROFILE, ns["intuition"], ns["calc"]))


def run(lichess_path, user, user_rating, n, set_name, log_path, seed=None, hints=False,
        input_fn=input, out=print):
    """Одна сессия (classic). input_fn и out подменяются в тестах."""
    status = ensure_log(log_path)
    if status == "migrated":
        out("старый формат лога перенесён (копия: %s.bak)" % log_path)
    train, test = ct.load_lichess(lichess_path, sample=0)
    pool = train if set_name == "train" else test
    solved = solved_ids(read_log(log_path), user, set_name)
    tasks = pick_tasks(pool, solved, n, rng_for(seed))
    fresh = sum(1 for p in tasks if p["id"] not in solved)
    session = new_session_id()
    out("тренажёр: %d задач из сета %s (новых %d), твой рейтинг %d, сессия %s%s"
        % (len(tasks), set_name, fresh, user_rating, session,
           ", РЕЖИМ ПОДСКАЗОК: в отчёт не идёт" if hints else ""))
    out("ввод: ход (UCI) + уверенность (0-100), напр. 'e2e4 70'. Пустая строка: выход.")
    with open(log_path, "a", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=FIELDS)
        for i, p in enumerate(tasks, 1):
            board = chess.Board(p["fen"])
            out("\n" + prompt_line(i, len(tasks), p, board.turn, hints))
            out(board.unicode(borders=True))
            out("твой ход:")
            t0 = time.time()
            mv, mv_s, conf = None, None, None
            while True:
                line = input_fn("> ").strip()
                if not line:
                    break
                try:
                    mv_s, conf_s = line.split()
                    conf = float(conf_s)
                except ValueError:
                    out("формат: 'e2e4 70'. Ещё раз.")
                    continue
                try:
                    mv = chess.Move.from_uci(mv_s)
                    legal = mv in board.legal_moves
                except ValueError:
                    legal = False
                if not legal:
                    out("нелегальный ход. Ещё раз (пустая строка: выход).")
                    continue
                break
            dt = time.time() - t0
            if mv is None:
                out("выход.")
                break
            correct = (mv_s == p["sol"])
            winning = correct or ct.is_winning(p["fen"], mv_s)
            exp = expected_p(user_rating, p["rating"])
            w.writerow(make_row(user, session, p, set_name, mv_s, conf, correct, winning,
                                dt, exp, hints))
            fo.flush()
            out(feedback_line(correct, winning, p, exp, dt))
    out("\n--- итог сессии ---")
    report(log_path, user, out)


def run_modes(calc_path, lichess_path, user, user_rating, n, set_name, log_path,
              mode, limit=INTUITION_LIMIT_DEFAULT, seed=None,
              input_fn=input, out=print):
    """Сессии intuition/calc. Рейтинг и темы не показываются до ответа (как в classic).
    intuition/calc исключают PuzzleId уже из лога (задача не даётся дважды и в оба
    режима); рейтинг задач — в полосе +-200 от рейтинга игрока, одинаково в обоих."""
    status = ensure_log(log_path)
    if status == "migrated":
        out("старый формат лога перенесён (копия: %s.bak)" % log_path)
    if mode == "calc":
        train, test = load_calc(calc_path)
    else:
        train, test = ct.load_lichess(lichess_path, sample=0)
    pool = train if set_name == "train" else test
    pool = [p for p in pool if abs(p["rating"] - user_rating) <= RATING_BAND]
    seen = {r["puzzle_id"] for r in read_log(log_path) if r["puzzle_id"]}
    pool = [p for p in pool if p["id"] not in seen]
    tasks = pick_tasks(pool, set(), n, rng_for(seed))
    session = new_session_id()
    out("тренажёр [%s]: %d задач из сета %s, твой рейтинг %d, сессия %s"
        % (mode, len(tasks), set_name, user_rating, session))
    if mode == "intuition":
        out("ввод: сначала ход (UCI), потом уверенность (0-100). "
            "Жёсткий лимит %d с на ход: не успел — промах. Пустая строка: выход." % limit)
    else:
        out("ввод: сначала ВСЯ линия (UCI через пробел), потом уверенность на линию. "
            "Мягкий лимит %d с (только логируется). Пустая строка: выход." % CALC_SOFT_LIMIT)
    with open(log_path, "a", newline="", encoding="utf-8") as fo:
        w = csv.DictWriter(fo, fieldnames=FIELDS)
        for i, p in enumerate(tasks, 1):
            board = chess.Board(p["fen"])
            out("\n" + prompt_line(i, len(tasks), p, board.turn, hints=False))
            out(board.unicode(borders=True))
            out("твой ход:")
            exp = expected_p(user_rating, p["rating"])
            if mode == "intuition":
                t0 = time.time()
                line = input_fn("> ход (UCI): ").strip()
                dt = time.time() - t0
                if not line:
                    out("выход.")
                    break
                mv_s = line.split()[0]
                correct, winning, timeout, conf = score_intuition(
                    p["fen"], mv_s, p["sol"], p["themes"], dt, limit)
                if timeout:
                    out("ТАЙМАУТ (%.1f с > %d с) — промах, уверенность = 0." % (dt, limit))
                else:
                    while True:
                        s = input_fn("уверенность (0-100): ").strip()
                        if not s:
                            out("выход.")
                            return
                        try:
                            conf = float(s)
                        except ValueError:
                            out("число 0-100. Ещё раз.")
                            continue
                        if 0 <= conf <= 100:
                            break
                        out("0-100. Ещё раз.")
                w.writerow(make_row(user, session, p, set_name, mv_s, conf, correct,
                                    winning, dt, exp, False, mode=mode, timeout=timeout))
                fo.flush()
                out(feedback_line(correct, winning, p, exp, dt))
            else:  # calc
                t0 = time.time()
                line = input_fn("> линия (UCI через пробел): ").strip()
                dt = time.time() - t0
                if not line:
                    out("выход.")
                    break
                strict, depth = score_calc(p["fen"], line, p["line"])
                while True:
                    s = input_fn("уверенность на линию (0-100): ").strip()
                    if not s:
                        out("выход.")
                        return
                    try:
                        conf = float(s)
                    except ValueError:
                        out("число 0-100. Ещё раз.")
                        continue
                    if 0 <= conf <= 100:
                        break
                    out("0-100. Ещё раз.")
                if dt > CALC_SOFT_LIMIT:
                    out("мягкий лимит превышен (%.1f с > %d с) — только логируется."
                        % (dt, CALC_SOFT_LIMIT))
                mv_s = line.split()[0] if line.split() else ""
                w.writerow(make_row(user, session, p, set_name, mv_s, conf, strict,
                                    strict, dt, exp, False, mode=mode, line=line,
                                    depth=depth, strict=strict))
                fo.flush()
                out("ЛИНИЯ ВЕРНА (глубина %d/%d). Решение: %s. Ожидаемый шанс: %.0f%%. Время: %.1f c."
                    % (depth, len(p["line"].split()), p["line"], exp * 100, dt)
                    if strict else
                    "ОШИБКА В ЛИНИИ (глубина %d/%d). Решение: %s. Ожидаемый шанс: %.0f%%. Время: %.1f c."
                    % (depth, len(p["line"].split()), p["line"], exp * 100, dt))
    out("\n--- итог сессии ---")
    report(log_path, user, out)


def selftest():
    """Селфтест режимов (чистый скоринг + отчёт на синтетике, без ввода)."""
    n_ok = n_fail = 0

    def check(label, cond):
        nonlocal n_ok, n_fail
        if cond:
            n_ok += 1
            print("  OK   %s" % label)
        else:
            n_fail += 1
            print("  FAIL %s" % label)

    print("selftest trainer (intuition/calc):")
    # 1. таймаут считается промахом
    c, w, t, conf = score_intuition("8/8/8/8/8/8/5k2/7K w - - 0 1", "h1g1",
                                    "h1h2", "mateIn1", 11.0, 10)
    check("таймаут = промах (correct=0, confidence=0, timeout=1)",
          (c, w, t, conf) == (0, 0, 1, 0))
    # 2. альтернативный мат засчитан (mateIn1, другой матующий ход)
    fen = "k7/2K5/8/8/8/8/1Q6/8 w - - 0 1"
    c, w, t, conf = score_intuition(fen, "b2a2", "b2b8", "mateIn1", 3.0, 10)
    check("альтернативный мат в mateIn1 засчитан", c == 1)
    # 3. depth и strict на линии с ошибкой на 2-м ходу (настоящая задача calc-пула)
    import csv as _csv
    calc_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "puzzles_calc.csv")
    rows = list(_csv.DictReader(open(calc_path, encoding="utf-8")))
    p = rows[0]
    sol = p["Line"].split()
    wrong = sol[:1] + ["a1a1"] + sol[2:]
    strict, depth = score_calc(p["FEN"], " ".join(wrong), p["Line"])
    check("depth/strict: ошибка на 2-м ходу -> depth=1, strict=0",
          (strict, depth) == (0, 1))
    strict, depth = score_calc(p["FEN"], p["Line"], p["Line"])
    check("вся линия верна -> strict=1, depth=len", strict == 1 and depth == len(sol))
    # 4. синтетика (intuition хорошо, calc плохо, n=120 в каждом) -> профиль «расчёт слабее»
    import io, contextlib
    synth = []
    for i in range(120):
        synth.append({"ts": "t", "user": "u", "session": "s", "puzzle_id": "i%d" % i,
                      "rating": 900, "themes": "crushing", "set": "train",
                      "move": "e2e4", "solution": "e2e4", "confidence": 70,
                      "correct": 1, "winning": 1, "seconds": 5, "expected": 0.5,
                      "hints": 0, "mode": "intuition", "line": "", "depth": "",
                      "strict": "", "timeout": 0})
        synth.append({"ts": "t", "user": "u", "session": "s", "puzzle_id": "c%d" % i,
                      "rating": 900, "themes": "long", "set": "train",
                      "move": "e2e4", "solution": "e2e4 e7e5", "confidence": 70,
                      "correct": 0, "winning": 0, "seconds": 60, "expected": 0.5,
                      "hints": 0, "mode": "calc", "line": "e2e4 a1a1",
                      "depth": 1, "strict": 0, "timeout": 0})
    tmp = "/tmp/selftest_synth.csv"
    with open(tmp, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(synth)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(tmp, "u", out=print)
    out_txt = buf.getvalue()
    check("синтетика 120+120 -> профиль «расчёт слабее»", "профиль: расчёт слабее" in out_txt)
    # 5. n=50 -> «выводы рано»
    tmp50 = "/tmp/selftest_synth50.csv"
    with open(tmp50, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        w.writerows(synth[:100])
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(tmp50, "u", out=print)
    check("n=50 в каждом -> «выводы рано»", "выводы рано" in buf.getvalue())
    # 6. старый лог без mode читается (как classic)
    tmp_old = "/tmp/selftest_old.csv"
    with open(tmp_old, "w", newline="", encoding="utf-8") as f:
        f.write("puzzle_id,rating,themes,set,move,solution,confidence,correct,winning,seconds,expected\n")
        f.write("00008,1811,crushing,train,e6e7,e6e7,80,1,1,12.3,0.42\n")
    ensure_log(tmp_old)
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        report(tmp_old, None, out=print)
    check("старый лог без mode читается", "задач в анализе: 1" in buf.getvalue())
    print("selftest: %d OK, %d FAIL" % (n_ok, n_fail))
    return 1 if n_fail else 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lichess", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "puzzles_sample.csv"))
    ap.add_argument("--calc", default=os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "puzzles_calc.csv"))
    ap.add_argument("--user", default=None, help="ник на Lichess (рейтинг задач берётся из API)")
    ap.add_argument("--rating", type=int, default=None,
                    help="запасной вариант, если API недоступен")
    ap.add_argument("--n", type=int, default=10)
    ap.add_argument("--set", dest="set", default="train", choices=["train", "test"])
    ap.add_argument("--log", default=LOG)
    ap.add_argument("--seed", type=int, default=None,
                    help="по умолчанию каждая сессия новая; число даёт воспроизводимую выборку")
    ap.add_argument("--hints", action="store_true",
                    help="показывать рейтинг и темы до ответа (тренировка; строки в отчёт не идут)")
    ap.add_argument("--mode", default="classic", choices=MODES)
    ap.add_argument("--limit", type=int, default=INTUITION_LIMIT_DEFAULT,
                    help="жёсткий лимит intuition, с (по умолчанию %d)" % INTUITION_LIMIT_DEFAULT)
    ap.add_argument("--report", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return selftest()
    if args.report:
        report(args.log, args.user)
        return 0
    rating = args.rating
    if args.user:
        fetched, err = fetch_rating(args.user)
        if fetched is not None:
            rating = fetched
            print("рейтинг задач %s по API Lichess: %d" % (args.user, rating))
        elif rating is not None:
            print("API: %s; беру --rating %d" % (err, rating))
        else:
            print("не могу получить рейтинг: %s; укажи --rating" % err)
            return 1
    if rating is None:
        print("укажи --user НИК (рейтинг из API) или --rating ЧИСЛО")
        return 1
    if args.mode == "classic":
        run(args.lichess, args.user, rating, args.n, args.set, args.log, args.seed, args.hints)
    else:
        run_modes(args.calc, args.lichess, args.user, rating, args.n, args.set,
                  args.log, args.mode, args.limit, args.seed)
    return 0


if __name__ == "__main__":
    sys.exit(main())
