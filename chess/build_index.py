#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""chess/build_index.py: генератор веб-тренажёра (index.html) из шаблона.

  python3 chess/build_index.py                          собрать index.html
  python3 chess/build_index.py --check                  проверить, что index.html свежий (для CI)
  python3 chess/build_index.py --calc puzzles_calc.csv
                                                        собрать с другим пулом calc

Шаблон web_trainer_template.html — исходник кода; index.html — артефакт,
его не правят руками. Генератор подставляет JSON только в строки присваивания
(var EMBEDDED = __PUZZLES_JSON__; / var EMBEDDED_CALC = __CALC_JSON__;),
а НЕ в комментарии: прежняя сборка подменяла и комментарий, и в файле лежал
дублирующий JSON (~36 КБ мёртвого веса).

Classic-пул: 100 train + 100 test из puzzles_sample.csv, сплит по MD5
(common.hash_split), выборка random.Random(42).sample для каждого сета.
Train-100 в точности совпадает с опубликованным набором; test-100
опубликованного файла воспроизвести не удалось (перебраны seed 0..5000,
shuffle/sample, numpy) — первая пересборка меняет test-100, это зафиксировано
здесь, а не скрыто. Пул classic — тренировочная подвыборка, измерение идёт
по полной выборке 2000 задач в CLI, поэтому замена допустима.

Calc-пул: все строки CSV (puzzles_calc.csv), сплит по MD5 на train/test. RD и Popularity
в веб не вшиваются: они нужны только для будущей проверки Elo-baseline.
"""
import argparse
import csv
import json
import os
import random
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from common.holdout import split_label  # noqa: E402

HERE = os.path.dirname(os.path.abspath(__file__))
SEED = 42
CLASSIC_N = 100


def classic_pool(path):
    """100 train + 100 test из выборки Lichess (как в опубликованном файле)."""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    train, test = [], []
    for r in rows:
        p = {"id": r["PuzzleId"], "fen": r["FEN"], "sol": r["Solution"],
             "rating": int(r["Rating"]), "themes": r["Themes"],
             "set": split_label(r["PuzzleId"])}
        (train if p["set"] == "train" else test).append(p)
    rng = random.Random(SEED)
    out = rng.sample(train, min(CLASSIC_N, len(train)))
    rng = random.Random(SEED)
    out += rng.sample(test, min(CLASSIC_N, len(test)))
    return out


def calc_pool(path):
    """Все строки пула calc (PuzzleId, FEN, Solution, Line, Rating, Themes)."""
    rows = list(csv.DictReader(open(path, encoding="utf-8")))
    out = []
    for r in rows:
        out.append({"id": r["PuzzleId"], "fen": r["FEN"], "sol": r["Solution"],
                    "line": r["Line"], "rating": int(r["Rating"]),
                    "themes": r["Themes"], "set": split_label(r["PuzzleId"])})
    return out


def build(template_path, classic_path, calc_path):
    with open(template_path, encoding="utf-8") as f:
        tpl = f.read()
    for token, marker in (("__PUZZLES_JSON__", "var EMBEDDED = __PUZZLES_JSON__;"),
                          ("__CALC_JSON__", "var EMBEDDED_CALC = __CALC_JSON__;")):
        if tpl.count(marker) != 1:
            raise SystemExit("в шаблоне должно быть ровно одно вхождение: %s" % marker)
        if tpl.count(token) != 2:  # комментарий + присваивание; подменяем только второе
            raise SystemExit("в шаблоне должно быть ровно два вхождения токена: %s" % token)
    classic = classic_pool(classic_path)
    calc = calc_pool(calc_path)
    out = tpl.replace("var EMBEDDED = __PUZZLES_JSON__;",
                      "var EMBEDDED = %s;" % json.dumps(classic, ensure_ascii=False), 1)
    out = out.replace("var EMBEDDED_CALC = __CALC_JSON__;",
                      "var EMBEDDED_CALC = %s;" % json.dumps(calc, ensure_ascii=False), 1)
    return out, len(classic), len(calc)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", default=os.path.join(HERE, "web_trainer_template.html"))
    ap.add_argument("--classic", default=os.path.join(HERE, "puzzles_sample.csv"))
    ap.add_argument("--calc", default=os.path.join(HERE, "puzzles_calc.csv"))
    ap.add_argument("--out", default=os.path.join(HERE, "index.html"))
    ap.add_argument("--check", action="store_true",
                    help="не писать файл, а проверить, что index.html свежий")
    args = ap.parse_args(argv)
    text, n_classic, n_calc = build(args.template, args.classic, args.calc)
    if args.check:
        current = open(args.out, encoding="utf-8").read()
        if current != text:
            print("index.html устарел: запусти python3 chess/build_index.py "
                  "(classic %d, calc %d)" % (n_classic, n_calc))
            return 1
        print("index.html свежий (classic %d, calc %d)" % (n_classic, n_calc))
        return 0
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print("собран %s (classic %d, calc %d, %d байт)"
          % (args.out, n_classic, n_calc, len(text.encode("utf-8"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
