#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session.py: чистая логика тренажёра без python-chess, чтобы её можно было тестировать где угодно.

Что здесь живёт
  FIELDS            схема лога (в том же порядке, что LOG_FIELDS в index.html)
  ensure_log        создать лог или перенести старый формат (с копией .bak)
  solved_ids        какие задачи пользователь уже решал
  pick_tasks        сначала непройденные, повторы только если свежих не хватило
  prompt_line       строка задачи ДО ответа: без рейтинга и тем (если нет режима подсказок)
  feedback_line     строка ПОСЛЕ ответа: тут рейтинг и темы показать уже можно
  format_report     отчёт с интервалами на common.stats
"""
import csv
import os
import random
import shutil
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common import stats as S  # noqa: E402

FIELDS = ["ts", "user", "session", "puzzle_id", "rating", "themes", "set", "move",
          "solution", "confidence", "correct", "winning", "seconds", "expected", "hints",
          "mode", "line", "depth", "strict", "timeout"]
_ALNUM = "0123456789abcdefghijklmnopqrstuvwxyz"


# ------------------------------------------------------------------ идентификаторы и время

def new_session_id(now=None, rng=None):
    """Например 20261016T101500-k3x9ab. Уникален для каждой сессии."""
    now = now or datetime.now(timezone.utc)
    rng = rng or random.SystemRandom()
    return now.strftime("%Y%m%dT%H%M%S") + "-" + "".join(rng.choice(_ALNUM) for _ in range(6))


def now_iso(now=None):
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + "%03dZ" % (now.microsecond // 1000)


def rng_for(seed):
    """seed=None: каждая сессия новая (по умолчанию). Число: воспроизводимая выборка."""
    return random.Random(seed) if seed is not None else random.SystemRandom()


# ------------------------------------------------------------------ лог

def read_log(path):
    """Строки лога как dict со всеми FIELDS (чего нет в старом файле, пустая строка;
    пустой mode читается как classic)."""
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        rows = [{k: (r.get(k) or "") for k in FIELDS} for r in csv.DictReader(f)]
    for r in rows:
        if not r["mode"]:
            r["mode"] = "classic"
    return rows


def ensure_log(path):
    """Создать лог с заголовком. Старый формат (без user, ts, session, hints, mode)
    переносится: строки сохраняются, session=legacy, hints=0, mode=classic,
    исходный файл копируется в path.bak. Возвращает new, ok или migrated."""
    if not os.path.exists(path) or os.path.getsize(path) == 0:
        with open(path, "w", newline="", encoding="utf-8") as f:
            csv.DictWriter(f, fieldnames=FIELDS).writeheader()
        return "new"
    with open(path, newline="", encoding="utf-8") as f:
        rd = csv.DictReader(f)
        header = list(rd.fieldnames or [])
        rows = list(rd)
    if header == FIELDS:
        return "ok"
    bak = path + ".bak"
    if not os.path.exists(bak):
        shutil.copyfile(path, bak)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in rows:
            out = {k: (r.get(k) or "") for k in FIELDS}
            out["session"] = out["session"] or "legacy"
            out["hints"] = out["hints"] or "0"
            out["mode"] = out["mode"] or "classic"
            w.writerow(out)
    return "migrated"


def solved_ids(rows, user=None, set_name=None):
    """Задачи, которые пользователь уже решал. Строки старого формата (user пустой)
    считаются его собственными: раньше лог был однопользовательским."""
    out = set()
    for r in rows:
        if user is not None and r["user"] not in (user, ""):
            continue
        if set_name is not None and r["set"] != set_name:
            continue
        out.add(r["puzzle_id"])
    return out


def pick_tasks(pool, solved, n, rng):
    """Сначала непройденные в случайном порядке, потом (если не хватило) уже решённые."""
    fresh = [p for p in pool if p["id"] not in solved]
    stale = [p for p in pool if p["id"] in solved]
    rng.shuffle(fresh)
    rng.shuffle(stale)
    return (fresh + stale)[:n]


def make_row(user, session, p, set_name, move, confidence, correct, winning, seconds,
             expected, hints, mode="classic", line="", depth="", strict="", timeout=0,
             now=None):
    return {"ts": now_iso(now), "user": user or "anon", "session": session,
            "puzzle_id": p["id"], "rating": p["rating"], "themes": p["themes"],
            "set": set_name, "move": move, "solution": p["sol"], "confidence": confidence,
            "correct": int(correct), "winning": int(winning), "seconds": round(seconds, 1),
            "expected": round(expected, 3), "hints": 1 if hints else 0,
            "mode": mode, "line": line, "depth": depth, "strict": strict,
            "timeout": timeout}


# ------------------------------------------------------------------ вывод

def prompt_line(i, n, p, white_to_move, hints=False):
    """Строка перед ходом. Рейтинг и темы только в режиме подсказок: в партии никто
    не сообщает мотив и сложность, а рейтинг якорит уверенность."""
    s = "[%d/%d] %s" % (i, n, p["id"])
    if hints:
        s += "  рейтинг %d  темы: %s" % (p["rating"], p["themes"])
    return s + "  (%s)" % ("ход белых" if white_to_move else "ход чёрных")


def feedback_line(correct, winning, p, expected, seconds):
    verdict = "ВЕРНО" if correct else ("ВЫИГРЫШ (другой ход)" if winning else "МИМО")
    return ("%s (решение %s). Рейтинг задачи %d, темы: %s. Ожидаемый шанс: %.0f%%. Время: %.1f c."
            % (verdict, p["sol"], p["rating"], p["themes"], expected * 100, seconds))


def _pct(x, d=0):
    return ("%." + str(d) + "f%%") % (x * 100)


def _pp(x, d=0):
    return ("%+." + str(d) + "f") % (x * 100)


def format_report(all_rows, user=None, mode=None):
    """Отчёт: точность с интервалом, калибровка с вердиктом, корзины, таблица тем.
    Строки с подсказками в статистику не идут. Режимы (intuition/calc) с разными
    условиями нельзя смешивать в одной калибровке: ожидание Glicko верно только
    для решения без ограничений, поэтому mode фильтрует строки (как hints)."""
    scoped = [r for r in all_rows if user is None or r.get("user") in (user, "", None)]
    if mode is not None:
        scoped = [r for r in scoped if r.get("mode") == mode]
    rows = S.without_hints(scoped)
    hinted = len(scoped) - len(rows)
    n = len(rows)
    if not n:
        return "все строки лога с подсказками: в статистику не идут" if scoped else "лог пуст"
    cs = S.calibration_summary(rows)
    out = ["задач в анализе: %d%s" % (n, " (с подсказками исключено: %d)" % hinted if hinted else ""),
           "точность: %s [%s-%s]  средняя уверенность: %s"
           % (_pct(cs["acc"], 1), _pct(cs["acc_lo"]), _pct(cs["acc_hi"]), _pct(cs["mean_conf"])),
           "смещение: %s п.п., z=%+.1f" % (_pp(cs["bias"], 1), cs["bias_z"]),
           "log-loss: %.3f (константа %.3f)  Brier: %.3f  навык: %+.2f"
           % (cs["log_loss"], cs["log_loss_base"], cs["brier"], cs["skill"]),
           "вердикт по калибровке: %s%s" % (cs["verdict"], " (нужно n >= %d)" % S.MIN_N_CALIBRATION
                                            if cs["verdict"] == "мало данных" else ""),
           "корзины уверенности (n, уверенность, точность [95%]):"]
    for b in S.reliability(rows):
        out.append("  %d-%d: n=%d  %s  %s [%s-%s]" % (b["lo"], b["hi"], b["n"], _pct(b["mean_conf"]),
                                                      _pct(b["acc"]), _pct(b["acc_lo"]), _pct(b["acc_hi"])))
    tt = S.theme_table(rows)
    out.append("темы (только мотивы; прогноз Glicko, остатки центрированы по длине задачи):")
    flagged = 0
    for r in [r for r in tt["rows"] if r["n"] >= 5][:12]:
        flagged += 1 if r["flag"] else 0
        tail = (" усадка %s" % _pp(r["shrunk"])) if r["shrunk"] is not None else " n<%d" % S.MIN_N_THEME
        mark = "  <-- СЛАБО" if r["flag"] == "weak" else ("  <-- СИЛЬНО" if r["flag"] == "strong" else "")
        out.append("  %-17s n=%-3d факт %s прогноз %s разрыв %s [%s..%s]%s%s"
                   % (r["theme"], r["n"], _pct(r["acc"]), _pct(r["exp"]), _pp(r["gap"]),
                      _pp(r["lo"]), _pp(r["hi"]), tail, mark))
    if not flagged:
        out.append("флагов по темам нет: на этом объёме слабые темы статистически не видны "
                   "(провал в 15 п.п. по одной теме замечается примерно с %d задач этой темы)"
                   % S.tasks_for_gap(0.15))
    return "\n".join(out) + "\n"
