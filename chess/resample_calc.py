"""Resample the Calc pool from the full Lichess puzzle DB.

The pool file itself (puzzles_calc.csv) is primary: it is the only
copy of the pool in the repo. It is NOT reproducible from
the script alone — it needs the DB snapshot used to build it:
  lichess_db_puzzle.csv.zst, 309751173 bytes,
  md5 454dffe9b213cd962cad6897bcc0564b, downloaded 2026-11-05,
  content = Lichess puzzle DB release 2026-11-03 (CC0,
  database.lichess.org). The snapshot lives outside the repo
  (chess/_db/, gitignored); a different snapshot gives a different
  pool, and the base 300 rows exist nowhere else in the repo
  (a backup copy is kept outside the repo).

Current pool: 1800 rows, rating 705-2982, bands 700-1100 (297 rows
plus 3 rows rated exactly 1100, which band_of puts in 1100-1500),
1100-1500, 1500-1800, 1800-2100, 2100-2500, 2500-3000.
The 700-1100 band is frozen: this script never adds rows there
(need = 0); the band keeps the existing rows.

Official format (database.lichess.org, checked 2026-11-05):
  PuzzleId,FEN,Moves,Rating,RatingDeviation,Popularity,NbPlays,Themes,...
  FEN is the position BEFORE the opponent's move; the position to present
  is after applying Moves[0]; Moves[1] is the first solution move.

Local format (load_calc in trainer.py):
  PuzzleId,FEN,Solution,Line,Rating,Themes
  FEN = presented position, Solution = first player move,
  Line = full solution line starting with Solution.

Conversion: presented FEN = official FEN + Moves[0];
             Solution = Moves[1]; Line = Moves[1:].

Usage:
  python resample_calc.py --db <lichess_db_puzzle.csv.zst> \
      --existing puzzles_calc.csv --out <new-pool>.csv \
      [--per-band 300] [--seed 20261105]
  --out is required (except for --validate-existing) and must differ
  from --existing unless --force is given (overwriting the input file
  is refused otherwise).
  A rerun on an already topped-up pool is a no-op: every unfrozen
  band already holds per-band rows, so need = 0 everywhere and the
  output is byte-identical to the input.

--validate-existing only checks that the conversion reproduces the
existing rows from the full DB (FEN/Solution/Line), and exits.
It needs no --out: validation runs before everything else.
Rating drift is reported separately (rating_drift, max_drift) and
does not fail the check: pool ratings are stale against newer
snapshots, while the conversion itself still reproduces.
A run tops up each unfrozen band to --per-band rows
(need = max(0, per-band - have), have counted with band_of),
excluding the existing PuzzleIds, plus an RD sidecar for the Elo-baseline
work (RatingDeviation is not in the local schema).
Note: the sidecar is NOT part of the no-op guarantee — RD and
Popularity come from the passed snapshot, so a rerun with a newer
snapshot rewrites the sidecar even when the pool file is unchanged.
"""
import argparse
import csv
import io
import os
import random
import sys

import chess
import zstandard

BANDS = [(700, 1100), (1100, 1500), (1500, 1800),
         (1800, 2100), (2100, 2500), (2500, 3000)]
FIELDNAMES = ["PuzzleId", "FEN", "Solution", "Line", "Rating", "Themes"]


def band_of(rating):
    for lo, hi in BANDS:
        if lo <= rating < hi:
            return (lo, hi)
    return None


def convert(row):
    """Official DB row -> local-format dict, or None if unusable."""
    themes = row["Themes"].split()
    if "long" not in themes and "veryLong" not in themes:
        return None
    moves = row["Moves"].split()
    if len(moves) < 6:  # need Line = Moves[1:] of >=5 plies, as in existing pool
        return None
    try:
        board = chess.Board(row["FEN"])
        board.push_uci(moves[0])
        fen = board.fen()
        # verify the whole solution line is legal from the presented FEN
        for m in moves[1:]:
            board.push_uci(m)
    except (ValueError, chess.InvalidMoveError, chess.IllegalMoveError):
        return None
    return {
        "PuzzleId": row["PuzzleId"],
        "FEN": fen,
        "Solution": moves[1],
        "Line": " ".join(moves[1:]),
        "Rating": row["Rating"],
        "Themes": row["Themes"],
        "RatingDeviation": row["RatingDeviation"],
        "Popularity": row["Popularity"],
    }


def stream_db(path):
    dctx = zstandard.ZstdDecompressor()
    with open(path, "rb") as fh:
        with dctx.stream_reader(fh) as reader:
            text = io.TextIOWrapper(reader, encoding="utf-8")
            yield from csv.DictReader(text)


def validate_existing(db_path, existing_path):
    existing = {r["PuzzleId"]: r for r in
                csv.DictReader(open(existing_path, encoding="utf-8"))}
    found, ok, bad, drift = 0, 0, [], []
    for row in stream_db(db_path):
        pid = row["PuzzleId"]
        if pid not in existing:
            continue
        found += 1
        conv = convert(row)
        exp = existing[pid]
        if conv and conv["FEN"] == exp["FEN"] and conv["Solution"] == exp["Solution"] \
                and conv["Line"] == exp["Line"]:
            ok += 1
            if conv["Rating"] != exp["Rating"]:
                drift.append(abs(int(conv["Rating"]) - int(exp["Rating"])))
        else:
            bad.append(pid)
        if found == len(existing):
            break
    print(f"existing={len(existing)} found_in_db={found} "
          f"conversion_reproduced={ok} mismatched={bad[:10]} "
          f"rating_drift={len(drift)} max_drift={max(drift, default=0)}")
    return found == len(existing) and ok == len(existing)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", required=True)
    ap.add_argument("--existing", default="puzzles_calc.csv")
    ap.add_argument("--out", default=None,
                    help="required unless --validate-existing")
    ap.add_argument("--per-band", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20261105)
    ap.add_argument("--force", action="store_true",
                    help="allow --out to be the same file as --existing")
    ap.add_argument("--validate-existing", action="store_true")
    args = ap.parse_args()

    if args.validate_existing:
        sys.exit(0 if validate_existing(args.db, args.existing) else 1)

    if args.out is None:
        ap.error("--out is required")

    if os.path.abspath(args.out) == os.path.abspath(args.existing) \
            and not args.force:
        print(f"refusing to overwrite {args.existing}: --out == --existing "
              f"(pass --force to confirm)", file=sys.stderr)
        sys.exit(2)

    existing = list(csv.DictReader(open(args.existing, encoding="utf-8")))
    existing_ids = {r["PuzzleId"] for r in existing}
    # Top-up needs per band, counted with the same band_of() the script
    # uses to lay out new tasks. The 700-1100 band is frozen (need = 0):
    # it keeps the existing rows, so the three rows rated exactly 1100
    # (which band_of puts in 1100-1500) never make any band look short.
    have = {b: 0 for b in BANDS}
    for r in existing:
        b = band_of(int(r["Rating"]))
        if b is not None:
            have[b] += 1
    need = {b: 0 if b == (700, 1100) else max(0, args.per_band - have[b])
            for b in BANDS}
    rng = random.Random(args.seed)
    # reservoir sample per band to bound memory on a 6.2M-row stream
    avail = {b: 0 for b in BANDS}
    pool = {b: [] for b in BANDS}
    existing_rd = {}
    for row in stream_db(args.db):
        if row["PuzzleId"] in existing_ids and row["PuzzleId"] not in existing_rd:
            existing_rd[row["PuzzleId"]] = row
        try:
            rating = int(row["Rating"])
        except ValueError:
            continue
        b = band_of(rating)
        if b is None or row["PuzzleId"] in existing_ids:
            continue
        conv = convert(row)
        if conv is None or need[b] == 0:
            continue
        avail[b] += 1
        lst = pool[b]
        if len(lst) < need[b]:
            lst.append(conv)
        elif rng.random() < need[b] / avail[b]:
            lst[rng.randrange(need[b])] = conv

    new_rows, rd_map = [], {}
    for pid, er in existing_rd.items():
        rd_map[pid] = (er.get("RatingDeviation", ""),
                       er.get("Popularity", ""))
    for b in BANDS:
        print(f"band {b[0]}-{b[1]}: long available={avail[b]} "
              f"sampled={len(pool[b])}")
        for r in pool[b]:
            new_rows.append({k: r[k] for k in FIELDNAMES})
            rd_map[r["PuzzleId"]] = (r["RatingDeviation"], r["Popularity"])
    out_rows = existing + [r for r in new_rows
                           if band_of(int(r["Rating"])) != (700, 1100)]
    # the 700-1100 band keeps the existing 300 (already complete there)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=FIELDNAMES)
        w.writeheader()
        w.writerows(out_rows)
    rd_path = args.out.replace(".csv", "_rd.csv")
    # Sidecar строго 1:1 к выводу: только id из out_rows, Rating = рейтинг
    # пула (join-консистентность). RD/Popularity — из текущей базы; у старых
    # строк это смесь снапшотов (рейтинг старый, RD текущий) — см. README.
    with open(rd_path, "w", encoding="utf-8", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["PuzzleId", "Rating",
                                           "RatingDeviation", "Popularity"])
        w.writeheader()
        missing_rd = 0
        for r in out_rows:
            rd, pop = rd_map.get(r["PuzzleId"], ("", ""))
            if rd == "" or pop == "":
                missing_rd += 1
            w.writerow({"PuzzleId": r["PuzzleId"], "Rating": r["Rating"],
                        "RatingDeviation": rd, "Popularity": pop})
    print(f"sidecar rows without RD/Popularity: {missing_rd}")
    if missing_rd:
        print(f"WARNING: {missing_rd} sidecar rows have empty "
              f"RD/Popularity", file=sys.stderr)
    print(f"wrote {args.out}: {len(out_rows)} rows "
          f"({len(existing)} existing + {len(out_rows) - len(existing)} new)")
    print(f"wrote {rd_path}: RD sidecar for the Elo-baseline check")


if __name__ == "__main__":
    main()
