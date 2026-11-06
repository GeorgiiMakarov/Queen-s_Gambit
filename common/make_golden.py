#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.make_golden: общие векторы для проверки, что Python и JS считают одно и то же.

  python3 common/make_golden.py          перезаписать common/golden/*.json
  python3 common/make_golden.py --check  проверить, что файлы свежие (для CI)

JS-версия лежит в chess/index.html. Её проверяет chess/test_web.js: пересчитывает
эти векторы и сравнивает с точностью 1e-9. Если менял формулы в stats.py, перегенерируй
векторы и поправь JS, иначе тест веба упадёт.
"""
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from common import split_label, stats as S  # noqa: E402
from common.simulate import simulate, synthetic_pool  # noqa: E402

GOLDEN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "golden")
ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def holdout_vectors():
    rng = random.Random(1001)
    ids = ["00008", "0000D", "0000H", "0009B", "000aY", "000hf"]
    ids += ["".join(rng.choice(ALPHABET) for _ in range(5)) for _ in range(300)]
    return [[i, split_label(i)] for i in ids]


def _clean(x):
    """float('nan') и None в JSON как null."""
    if isinstance(x, float) and x != x:
        return None
    return x


def _dataset(name, records):
    table = S.theme_table(records)
    return {
        "name": name,
        "records": [{"themes": r["themes"], "correct": r["correct"],
                     "expected": r["expected"], "confidence": r["confidence"]}
                    for r in records],
        "summary": S.calibration_summary(records),
        "reliability": S.reliability(records),
        "theme_table": {"rows": table["rows"], "tau2": table["tau2"],
                        "grand": table["grand"], "k": table["k"], "n": table["n"]},
    }


def stats_vectors():
    rng = random.Random(2002)
    pool = synthetic_pool(rng, 1000)
    wil = [[k, n] + list(S.wilson(k, n)) for k, n in
           [(0, 0), (0, 1), (1, 1), (0, 10), (10, 10), (5, 10), (3, 7), (50, 100), (1, 200), (199, 200)]]
    sets = [
        _dataset("calibrated", simulate(pool, rng, 1600, 150)),
        _dataset("overconfident", simulate(pool, rng, 1600, 120, conf_shift=0.2)),
        _dataset("weak_fork_with_length_bias",
                 simulate(pool, rng, 1600, 320, weak=("fork", 0.3),
                          bias={2: .05, 3: .12, 4: .2}, near=500)),
        _dataset("tiny", simulate(pool, rng, 1200, 12)),
    ]
    return {"wilson": wil, "datasets": sets}


def mode_vectors():
    """Векторы скоринга режимов (trainer.score_intuition / score_calc).
    Генерируются настоящим Python-скорингом на настоящей python-chess,
    а не вручную: JS (chess/index.html) должен совпасть с этими значениями
    на всех векторах (проверяет chess/test_web.js). Случаи подобраны
    детерминированно — первый подходящий в порядке файла.

    intuition: верный ход; неверный; другой выигрыш; таймаут (dt > limit);
    dt == limit (не таймаут); альтернативный мат в mateIn1; неверный ход
    в mateIn1; нелегальный (но well-formed) UCI; превращение.
    calc: вся линия верна; ошибка на 2-м ходу; ошибка на последнем ходу
    (линия без мата); альтернативный мат в финале; только префикс линии;
    линия + лишние ходы; пустой ввод; неверный последний ход там, где
    решение заканчивается матом."""
    import csv
    chess_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "chess")
    sys.path.insert(0, chess_dir)
    import trainer  # noqa: E402  (нужен python-chess)
    import chess_tactics as ct  # noqa: E402

    sample_path = os.path.join(chess_dir, "puzzles_sample.csv")
    calc_path = os.path.join(chess_dir, "puzzles_calc.csv")
    sample = list(csv.DictReader(open(sample_path, encoding="utf-8")))
    calc = list(csv.DictReader(open(calc_path, encoding="utf-8")))

    def legal_moves(fen):
        import chess
        b = chess.Board(fen)
        return [m.uci() for m in b.legal_moves]

    def first_nonwinning_legal(r):
        for mv in legal_moves(r["FEN"]):
            if mv != r["Solution"] and not ct.is_winning(r["FEN"], mv):
                return mv
        return None

    intu = []

    def add_intu(r, move, dt, limit=10):
        c, w, t, conf = trainer.score_intuition(
            r["FEN"], move, r["Solution"], r["Themes"], dt, limit)
        intu.append({"fen": r["FEN"], "move": move, "sol": r["Solution"],
                     "themes": r["Themes"], "dt": dt, "limit": limit,
                     "correct": c, "winning": w, "timeout": t, "confidence": conf})

    r0 = sample[0]  # 00008
    add_intu(r0, r0["Solution"], 3.0)                       # верный ход
    add_intu(r0, first_nonwinning_legal(r0), 3.0)           # неверный, не выигрыш
    add_intu(r0, r0["Solution"], 11.0)                      # таймаут при верном ходе
    add_intu(r0, r0["Solution"], 10.0)                      # dt == limit: не таймаут
    add_intu(r0, "e2e5", 3.0)                              # нелегальный UCI
    for r in sample:  # другой выигрыш (не решение, захват >= ладьи или мат)
        win = None
        for mv in legal_moves(r["FEN"]):
            if mv != r["Solution"] and ct.is_winning(r["FEN"], mv):
                win = mv
                break
        if win:
            add_intu(r, win, 3.0)
            break
    for r in sample:  # альтернативный мат в mateIn1 + неверный ход там же
        if "mateIn1" not in r["Themes"]:
            continue
        import chess
        b = chess.Board(r["FEN"])
        mates = []
        for m in b.legal_moves:
            b.push(m)
            if b.is_checkmate():
                mates.append(m.uci())
            b.pop()
        alt = [m for m in mates if m != r["Solution"]]
        if alt:
            add_intu(r, alt[0], 3.0)
            wrong = first_nonwinning_legal(r)
            if wrong and wrong not in mates:
                add_intu(r, wrong, 3.0)
            break
    for r in sample:  # превращение — решение с суффиксом
        if len(r["Solution"]) == 5:
            add_intu(r, r["Solution"], 3.0)
            break

    cal = []

    def add_calc(r, entered):
        strict, depth = trainer.score_calc(r["FEN"], entered, r["Line"])
        cal.append({"fen": r["FEN"], "entered": entered, "sol_line": r["Line"],
                    "strict": strict, "depth": depth})

    c0 = calc[0]  # CYCpm
    sol0 = c0["Line"].split()
    add_calc(c0, c0["Line"])                                # вся линия верна
    add_calc(c0, " ".join(sol0[:1] + ["a1a1"] + sol0[2:]))  # ошибка на 2-м ходу
    add_calc(c0, " ".join(sol0[:3]))                        # только префикс
    add_calc(c0, c0["Line"] + " a1a1 h2h3")                 # линия + лишние ходы
    add_calc(c0, "")                                        # пустой ввод
    non_mate = next(r for r in calc if not _ends_in_mate(r["FEN"], r["Line"]))
    sol_nm = non_mate["Line"].split()
    add_calc(non_mate, " ".join(sol_nm[:-1] + ["a1a1"]))    # ошибка на последнем ходу
    for r in calc:  # альтернативный мат в финале + неверный последний ход там же
        line = r["Line"].split()
        alt = _alt_final_mate(r["FEN"], line)
        if alt:
            add_calc(r, " ".join(line[:-1] + [alt]))
            add_calc(r, " ".join(line[:-1] + ["a1a1"]))
            break
    return {"intuition": intu, "calc": cal}


def _ends_in_mate(fen, line):
    import chess
    b = chess.Board(fen)
    for u in line.split():
        mv = chess.Move.from_uci(u)
        if mv not in b.legal_moves:
            return False
        b.push(mv)
    return b.is_checkmate()


def _alt_final_mate(fen, line):
    """Альтернативный матующий ход на последнем полуходе линии (или None)."""
    import chess
    if not _ends_in_mate(fen, " ".join(line)):
        return None
    b = chess.Board(fen)
    for u in line[:-1]:
        b.push(chess.Move.from_uci(u))
    for m in b.legal_moves:
        if m.uci() == line[-1]:
            continue
        b.push(m)
        mate = b.is_checkmate()
        b.pop()
        if mate:
            return m.uci()
    return None


def render(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                      default=_clean) + "\n"


def build():
    return {"holdout_vectors.json": render(holdout_vectors()),
            "stats_vectors.json": render(stats_vectors()),
            "mode_vectors.json": render(mode_vectors())}


def main(argv):
    files = build()
    if "--check" in argv:
        bad = []
        for fn, text in files.items():
            path = os.path.join(GOLDEN_DIR, fn)
            if not os.path.exists(path) or open(path, encoding="utf-8").read() != text:
                bad.append(fn)
        if bad:
            print("векторы устарели: %s. Запусти python3 common/make_golden.py" % ", ".join(bad))
            return 1
        print("golden: свежие")
        return 0
    os.makedirs(GOLDEN_DIR, exist_ok=True)
    for fn, text in files.items():
        with open(os.path.join(GOLDEN_DIR, fn), "w", encoding="utf-8", newline="\n") as f:
            f.write(text)
        print("записан %s (%d байт)" % (fn, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
