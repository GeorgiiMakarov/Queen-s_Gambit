#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
mcp_server.py — тренажёр как MCP-инструмент (фича 1 из ARTEMIS).
AI-ассистент (Claude Code, Antigravity, Cursor и др.) читает лог тренажёра
и строит отчёт, не трогая консоль. Зависимостей нет: MCP — это JSON-RPC
поверх stdio, реализован на stdlib.

Инструменты:
  trainer_summary      — n, точность, log-loss
  trainer_report       — полный отчёт (как trainer.py --report)
  trainer_danger_table — таблица опасности по темам
  trainer_log          — последние N строк лога

Запуск (stdio, для MCP-клиента):
  python3 mcp_server.py
Лог по умолчанию: trainer_log.csv рядом с trainer.py (или --log PATH).
"""
import argparse
import csv
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import (MIN_N_FOR_CONCLUSIONS, calibration_buckets, danger_table,
                    log_loss)

FIELDS = ["puzzle_id", "rating", "themes", "set", "move", "solution",
          "confidence", "correct", "winning", "seconds", "expected"]


def load_log(path):
    if not os.path.exists(path):
        return [], "лога нет: %s" % path
    with open(path, encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    return rows, None


def tool_summary(path):
    rows, err = load_log(path)
    if err:
        return err
    n = len(rows)
    if not n:
        return "лог пуст"
    acc = sum(int(r["correct"]) for r in rows) / n
    return ("задач: %d  точность: %.1f%%  log-loss уверенности: %.3f"
            % (n, acc * 100, log_loss(rows)))


def tool_report(path):
    rows, err = load_log(path)
    if err:
        return err
    n = len(rows)
    if not n:
        return "лог пуст"
    acc = sum(int(r["correct"]) for r in rows) / n
    out = ["задач: %d  точность: %.1f%%  log-loss уверенности: %.3f"
           % (n, acc * 100, log_loss(rows))]
    conclusions = n >= MIN_N_FOR_CONCLUSIONS
    if not conclusions:
        out.append("ВНИМАНИЕ: n < %d — выводы рано, нужно 100–200 задач."
                   % MIN_N_FOR_CONCLUSIONS)
    out.append("калибровка (корзина уверенности: n, средняя уверенность, точность):")
    for b, cnt, mc, ac in calibration_buckets(rows):
        flag = "САМОУВЕРЕННОСТЬ" if conclusions and mc / 100 > ac + 0.15 else ""
        out.append("  %3d-%3d: n=%3d  уверенность %.0f%%  точность %.0f%%  %s"
                   % (b, b + 24, cnt, mc, ac * 100, flag))
    out.append("таблица опасности по темам (факт vs прогноз Glicko):")
    for gap, t, cnt, ac, ex in danger_table(rows):
        flag = " <-- ХУЖЕ ПРОГНОЗА" if conclusions and gap < -0.15 else ""
        out.append("  %-18s n=%3d  факт %.0f%%  прогноз %.0f%%  разрыв %+.0f%%%s"
                   % (t, cnt, ac * 100, ex * 100, gap * 100, flag))
    return "\n".join(out)


def tool_danger_table(path):
    rows, err = load_log(path)
    if err:
        return err
    out = []
    for gap, t, cnt, ac, ex in danger_table(rows):
        out.append({"theme": t, "n": cnt, "fact": round(ac, 3),
                    "expected": round(ex, 3), "gap": round(gap, 3)})
    return json.dumps(out, ensure_ascii=False, indent=1)


def tool_log(path, limit):
    rows, err = load_log(path)
    if err:
        return err
    return json.dumps(rows[-limit:], ensure_ascii=False, indent=1)


TOOLS = [
    {"name": "trainer_summary", "description": "n, точность, log-loss уверенности по логу тренажёра",
     "inputSchema": {"type": "object", "properties": {"log": {"type": "string"}}, "required": []}},
    {"name": "trainer_report", "description": "Полный отчёт: калибровка по корзинам уверенности + таблица опасности по темам",
     "inputSchema": {"type": "object", "properties": {"log": {"type": "string"}}, "required": []}},
    {"name": "trainer_danger_table", "description": "Таблица опасности по темам (факт vs прогноз Glicko), JSON",
     "inputSchema": {"type": "object", "properties": {"log": {"type": "string"}}, "required": []}},
    {"name": "trainer_log", "description": "Последние N строк лога тренажёра, JSON",
     "inputSchema": {"type": "object", "properties": {"log": {"type": "string"}, "limit": {"type": "integer"}}, "required": []}},
]


def call_tool(name, args, default_log):
    path = args.get("log") or default_log
    if name == "trainer_summary":
        return tool_summary(path)
    if name == "trainer_report":
        return tool_report(path)
    if name == "trainer_danger_table":
        return tool_danger_table(path)
    if name == "trainer_log":
        return tool_log(path, int(args.get("limit") or 20))
    raise ValueError("неизвестный инструмент: %s" % name)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default=os.path.join(
        os.path.dirname(__file__), "trainer_log.csv"))
    args = ap.parse_args()
    # MCP over stdio: JSON-RPC, по одному сообщению на строку. В stdout —
    # только JSON-RPC, никаких print (иначе протокол сломается).
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            continue
        mid = msg.get("id")
        method = msg.get("method", "")
        params = msg.get("params") or {}
        if method == "initialize":
            res = {"protocolVersion": "2024-11-05",
                   "capabilities": {"tools": {}},
                   "serverInfo": {"name": "queen-gambit-trainer", "version": "0.1.0"}}
        elif method in ("notifications/initialized", "notifications/cancelled"):
            continue  # уведомление, ответа нет
        elif method == "ping":
            res = {}
        elif method == "tools/list":
            res = {"tools": TOOLS}
        elif method == "tools/call":
            try:
                text = call_tool(params.get("name"), params.get("arguments") or {}, args.log)
                res = {"content": [{"type": "text", "text": text}], "isError": False}
            except Exception as e:
                res = {"content": [{"type": "text", "text": "ошибка: %s" % e}], "isError": True}
        else:
            res = {"error": {"code": -32601, "message": "метод не поддерживается: %s" % method}}
        if mid is not None:
            sys.stdout.write(json.dumps({"jsonrpc": "2.0", "id": mid, "result": res},
                                        ensure_ascii=False) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    sys.exit(main())
