#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Сэмплер задач Lichess: потоком из lichess_db_puzzle.csv.zst.
Формат Lichess: FEN + Moves, где Moves[0] — setup-ход стороны из FEN,
а решение — Moves[1:]. Позиция задачи = FEN + Moves[0], ход-решение = Moves[1].
Выборка: стратификация по рейтингу (по N в каждой корзине), фильтр —
минимум 2 хода, решение легально в позиции задачи.
Выход: puzzles_sample.csv (PuzzleId, FEN, Solution, Rating, Themes)."""
import csv
import random
import sys

import chess
import zstandard as zstd

BUCKETS = [(800, 1200), (1200, 1600), (1600, 2000), (2000, 2400), (2400, 4000)]
PER_BUCKET = 400


def main(src, dst, per_bucket=PER_BUCKET, seed=42):
    random.seed(seed)
    want = {b: per_bucket for b in BUCKETS}
    got = {b: 0 for b in BUCKETS}
    out = []
    dctx = zstd.ZstdDecompressor()
    with open(src, "rb") as f, open(dst, "w", newline="", encoding="utf-8") as fo:
        w = csv.writer(fo)
        w.writerow(["PuzzleId", "FEN", "Solution", "Rating", "Themes"])
        reader = dctx.stream_reader(f)
        buf = b""
        header = True
        while True:
            chunk = reader.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode("utf-8", "replace")
                if header:
                    header = False
                    continue
                parts = text.split(",")
                if len(parts) < 8:
                    continue
                pid, fen, moves, rating = parts[0], parts[1], parts[2], parts[3]
                themes = parts[7]
                try:
                    rating = int(rating)
                except ValueError:
                    continue
                mv = moves.split()
                if len(mv) < 2:
                    continue
                bucket = None
                for b in BUCKETS:
                    if b[0] <= rating < b[1]:
                        bucket = b
                        break
                if bucket is None or got[bucket] >= want[bucket]:
                    continue
                # позиция задачи = FEN + setup-ход
                try:
                    board = chess.Board(fen)
                    setup = chess.Move.from_uci(mv[0])
                    if setup not in board.legal_moves:
                        continue
                    board.push(setup)
                    sol = chess.Move.from_uci(mv[1])
                    if sol not in board.legal_moves:
                        continue
                except (ValueError, IndexError):
                    continue
                got[bucket] += 1
                w.writerow([pid, board.fen(), mv[1], rating, themes])
                if all(got[b] >= want[b] for b in BUCKETS):
                    print("sample done:", got)
                    return
        print("sample partial (EOF):", got)


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "lichess_db_puzzle.csv.zst",
         sys.argv[2] if len(sys.argv) > 2 else "puzzles_sample.csv")
