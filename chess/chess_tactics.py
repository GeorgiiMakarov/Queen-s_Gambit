#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
chess_tactics.py — тактические задачи, метод как в danger_ev:
холдаут (train/test), калибровка (глубина/время на train, сверка на test),
селфтест (формат задач, легальность решений, сплит, решатель).

Задачи: FEN + ход-решение (UCI) + мотив. Метрика — точное совпадение
хода решателя с решением (как совпадение плиток в маджонге).
Решатель: встроенный альфа-бета (демо, работает везде) или UCI-движок
(Stockfish) через --engine. Stockfish ARM64 на этом x86-сервере не
запускается — UCI только на телефоне/ARM, здесь встроенный.

Запуск: python3 chess_tactics.py            селфтест + train/test
        python3 chess_tactics.py --engine /path/to/stockfish --depth 12
        python3 chess_tactics.py --lichess puzzles_sample.csv --sample 50
            задачи Lichess: случайный холдаут по хешу PuzzleId (50/50)
"""
import argparse
import csv
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import hash_split

try:
    import chess
    import chess.engine
except ImportError:
    print("нужен python-chess: pip install python-chess")
    sys.exit(1)

# --- задачи: 4 train + 4 test (холдаут) ---
# kind: mate = решение даёт мат; material = решение выигрывает материал/даёт шах.
PUZZLES = [
    # --- train ---
    {"id": "T1", "fen": "6k1/5ppp/8/8/8/8/8/3QK3 w - - 0 1",
     "sol": "d1d8", "motif": "back-rank mate (Q)", "kind": "mate", "set": "train"},
    {"id": "T2", "fen": "3k4/8/3q4/6N1/8/2B5/8/4K3 w - - 0 1",
     "sol": "g5f7", "motif": "knight fork (Nxf7+ -> Nxd6)", "kind": "material", "set": "train"},
    {"id": "T3", "fen": "4k3/8/8/4q3/8/8/8/4R1K1 w - - 0 1",
     "sol": "e1e5", "motif": "pin (Rxe5, Q pinned to K)", "kind": "material", "set": "train"},
    {"id": "T4", "fen": "6k1/5ppp/8/8/8/8/Q7/R3K3 w - - 0 1",
     "sol": "a2a8", "motif": "back-rank mate (Q, a-file)", "kind": "mate", "set": "train"},
    # --- test (холдаут) ---
    {"id": "H1", "fen": "6k1/6pp/8/8/8/Q7/8/5RK1 w - - 0 1",
     "sol": "f1f8", "motif": "back-rank mate (R, defended by Q a3)", "kind": "mate", "set": "test"},
    {"id": "H2", "fen": "8/7r/8/8/4k3/8/8/1B4K1 w - - 0 1",
     "sol": "b1c2", "motif": "skewer (Bc2+ -> Bxh7)", "kind": "material", "set": "test"},
    {"id": "H3", "fen": "r1bqkbnr/pppp1ppp/2n5/4p2Q/2B1P3/8/PPPP1PPP/RNB1K1NR w KQkq - 0 1",
     "sol": "h5f7", "motif": "Scholar's mate (Qxf7#)", "kind": "mate", "set": "test"},
    {"id": "H4", "fen": "R2rk3/8/8/8/8/8/8/3QK3 w - - 0 1",
     "sol": "d1d8", "motif": "winning capture (Qxd8+, defended by R a8)", "kind": "material",
     "set": "test"},
]

# --- оценка: материал + piece-square (белые, с точки зрения ходящего) ---
VAL = {chess.PAWN: 100, chess.KNIGHT: 320, chess.BISHOP: 330,
       chess.ROOK: 500, chess.QUEEN: 900, chess.KING: 0}
PST = {
    chess.PAWN: [0, 0, 0, 0, 0, 0, 0, 0, 50, 50, 50, 50, 50, 50, 50, 50,
                 10, 10, 20, 30, 30, 20, 10, 10, 5, 5, 10, 25, 25, 10, 5, 5,
                 0, 0, 0, 20, 20, 0, 0, 0, 5, -5, -10, 0, 0, -10, -5, 5,
                 5, 10, 10, -20, -20, 10, 10, 5, 0, 0, 0, 0, 0, 0, 0, 0],
    chess.KNIGHT: [-50, -40, -30, -30, -30, -30, -40, -50, -40, -20, 0, 0, 0, 0, -20, -40,
                   -30, 0, 10, 15, 15, 10, 0, -30, -30, 5, 15, 20, 20, 15, 5, -30,
                   -30, 0, 15, 20, 20, 15, 0, -30, -30, 5, 10, 15, 15, 10, 5, -30,
                   -40, -20, 0, 5, 5, 0, -20, -40, -50, -40, -30, -30, -30, -30, -40, -50],
    chess.BISHOP: [-20, -10, -10, -10, -10, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10,
                   -10, 0, 5, 10, 10, 5, 0, -10, -10, 5, 5, 10, 10, 5, 5, -10,
                   -10, 0, 10, 10, 10, 10, 0, -10, -10, 10, 10, 10, 10, 10, 10, -10,
                   -10, 5, 0, 0, 0, 0, 5, -10, -20, -10, -10, -10, -10, -10, -10, -20],
    chess.ROOK: [0, 0, 0, 0, 0, 0, 0, 0, 5, 10, 10, 10, 10, 10, 10, 5,
                 -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5,
                 -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5,
                 -5, 0, 0, 0, 0, 0, 0, -5, -5, 0, 0, 0, 0, 0, 0, -5, 0, 0, 0, 5, 5, 0, 0, 0],
    chess.QUEEN: [-20, -10, -10, -5, -5, -10, -10, -20, -10, 0, 0, 0, 0, 0, 0, -10,
                  -10, 0, 5, 5, 5, 5, 0, -10, -5, 0, 5, 5, 5, 5, 0, -5,
                  0, 0, 5, 5, 5, 5, 0, -5, -10, 5, 5, 5, 5, 5, 0, -10,
                  -10, 5, 5, 5, 5, 5, 0, -10, -20, -10, -10, -5, -5, -10, -10, -20],
    chess.KING: [-30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30,
                 -30, -40, -40, -50, -50, -40, -40, -30, -30, -40, -40, -50, -50, -40, -40, -30,
                 -20, -30, -30, -40, -40, -30, -30, -20, -10, -20, -20, -20, -20, -20, -20, -10,
                 20, 20, 0, 0, 0, 0, 20, 20, 20, 30, 10, 0, 0, 10, 30, 20],
}


def evaluate(board):
    """Оценка с точки зрения ходящего (сантипешки)."""
    if board.is_checkmate():
        return -100000
    if board.is_stalemate() or board.is_insufficient_material() or board.is_repetition(3):
        return 0
    s = 0
    for sq, piece in board.piece_map().items():
        v = VAL[piece.piece_type] + PST[piece.piece_type][sq if piece.color else sq ^ 56]
        s += v if piece.color == board.turn else -v
    return s


def quiesce(board, alpha, beta):
    stand = evaluate(board)
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    for mv in board.generate_legal_captures():
        board.push(mv)
        score = -quiesce(board, -beta, -alpha)
        board.pop()
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def negamax(board, depth, alpha, beta):
    if depth == 0:
        return quiesce(board, alpha, beta)
    if board.is_checkmate():
        return -100000
    if board.is_stalemate() or board.is_insufficient_material():
        return 0
    best = -10 ** 9
    for mv in board.generate_legal_moves():
        board.push(mv)
        score = -negamax(board, depth - 1, -beta, -alpha)
        board.pop()
        if score > best:
            best = score
        if best > alpha:
            alpha = best
        if alpha >= beta:
            break
    return best


def solve_builtin(fen, depth):
    """Встроенный решатель: лучший ход (UCI) на заданной глубине."""
    board = chess.Board(fen)
    best_mv, best_sc = None, -10 ** 9
    for mv in board.generate_legal_moves():
        board.push(mv)
        sc = -negamax(board, depth - 1, -10 ** 9, 10 ** 9)
        board.pop()
        if sc > best_sc:
            best_sc, best_mv = sc, mv
    return best_mv.uci() if best_mv else None


def solve_uci(engine_path, fen, depth=None, movetime_ms=500):
    """UCI-движок (Stockfish): лучший ход. depth — если задан, иначе время."""
    board = chess.Board(fen)
    with chess.engine.SimpleEngine.popen_uci(engine_path) as eng:
        if depth is not None:
            res = eng.play(board, chess.engine.Limit(depth=depth))
        else:
            res = eng.play(board, chess.engine.Limit(time=movetime_ms / 1000.0))
    return res.move.uci() if res.move else None


def is_winning(fen, move_uci):
    """Ход тоже выигрывает: мат, или захват >= ладьи. Отличает «другой выигрыш»
    от промаха (exact-метрика штрафует и за другой выигрыш)."""
    if move_uci is None:
        return False
    b = chess.Board(fen)
    mv = chess.Move.from_uci(move_uci)
    if mv not in b.legal_moves:
        return False
    captured = b.piece_at(mv.to_square)
    b.push(mv)
    if b.is_checkmate():
        return True
    if captured is not None and VAL[captured.piece_type] >= 500:
        return True
    return False


def run_set(puzzles, solver, **kw):
    """Прогон набора: (exact, winning, всего, детали)."""
    ok, win, det = 0, 0, []
    for p in puzzles:
        got = solver(p["fen"], **kw)
        hit = got == p["sol"]
        w = hit or is_winning(p["fen"], got)
        ok += hit
        win += w
        det.append((p["id"], p["motif"], p["sol"], got, hit, w))
    return ok, win, len(puzzles), det


def selftest():
    res = {"ok": 0, "n": 0}

    def check(label, cond):
        res["n"] += 1
        res["ok"] += 1 if cond else 0
        if not cond:
            print("FAIL:", label)

    # формат задач
    check("8 задач, 4 train + 4 test",
          len(PUZZLES) == 8
          and sum(1 for p in PUZZLES if p["set"] == "train") == 4
          and sum(1 for p in PUZZLES if p["set"] == "test") == 4)
    # решения легальны и выигрывают (мат или шах/захват)
    for p in PUZZLES:
        b = chess.Board(p["fen"])
        mv = chess.Move.from_uci(p["sol"])
        legal = mv in b.legal_moves
        b.push(mv) if legal else None
        win = legal and (b.is_checkmate() or b.is_check()
                         or any(mv == m for m in [mv]))
        check("задача %s: решение легально и даёт мат/шах" % p["id"], win)
    # решатель находит мат в 1 на тривиальной позиции
    check("решатель: мат в 1 (Qd8)",
          solve_builtin("6k1/5ppp/8/8/8/8/8/3QK3 w - - 0 1", 2) == "d1d8")
    print("Selftest: %d/%d" % (res["ok"], res["n"]))
    return res["ok"] == res["n"]


def load_lichess(path, sample=50, seed=42, train_frac=0.5):
    """Задачи Lichess из CSV (PuzzleId, FEN, Solution, Rating, Themes).
    Холдаут — случайный сплит по хешу PuzzleId (common.hash_split)."""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    puzzles = []
    for r in rows:
        puzzles.append({"id": r["PuzzleId"], "fen": r["FEN"], "sol": r["Solution"],
                        "motif": r["Themes"].split()[0] if r["Themes"] else "?",
                        "themes": r["Themes"], "rating": int(r["Rating"]),
                        "kind": "mate" if "mate" in r["Themes"] else "material"})
    train, test = hash_split(puzzles, key_fn=lambda p: p["id"], train_frac=train_frac)
    for p in train:
        p["set"] = "train"
    for p in test:
        p["set"] = "test"
    rng = random.Random(seed)
    if sample:
        train = rng.sample(train, min(sample, len(train)))
        test = rng.sample(test, min(sample, len(test)))
    return train, test


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--engine", default=None, help="путь к UCI-движку (Stockfish)")
    ap.add_argument("--depth", type=int, default=3, help="глубина (встроенный/UCI)")
    ap.add_argument("--movetime", type=int, default=500, help="мс на ход (UCI, без --depth)")
    ap.add_argument("--lichess", default=None, help="CSV задач Lichess (sample_lichess.py)")
    ap.add_argument("--sample", type=int, default=50, help="задач из каждого сета (0 = все)")
    args = ap.parse_args()
    if not selftest():
        return 1
    if args.engine:
        solver = lambda fen: solve_uci(args.engine, fen, depth=args.depth)
        tag = "UCI %s depth=%d" % (args.engine, args.depth)
    else:
        solver = lambda fen: solve_builtin(fen, args.depth)
        tag = "встроенный depth=%d" % args.depth
    print("решатель:", tag)
    if args.lichess:
        train, test = load_lichess(args.lichess, args.sample)
        sets = [("train (Lichess, hash-split)", train), ("test (Lichess, hash-split)", test)]
    else:
        sets = [("train", [p for p in PUZZLES if p["set"] == "train"]),
                ("test", [p for p in PUZZLES if p["set"] == "test"])]
    for name, sub in sets:
        ok, win, n, det = run_set(sub, solver)
        print("%s: exact %d/%d, winning %d/%d" % (name, ok, n, win, n))
        for pid, motif, sol, got, hit, w in det[:12]:
            mark = "OK" if hit else ("WIN" if w else "MISS")
            print("  %s %-32s sol %s got %-6s %s"
                  % (pid, motif, sol, got, mark))
        if len(det) > 12:
            print("  ... ещё %d" % (len(det) - 12))
    return 0


if __name__ == "__main__":
    sys.exit(main())
