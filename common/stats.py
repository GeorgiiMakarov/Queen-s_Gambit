#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.stats: интервалы и честная статистика для калибровки и таблицы опасности.

Только стандартная библиотека. Формулы намеренно простые, чтобы переписать их в JS
один в один (chess/index.html). Паритет Python и JS проверяют общие векторы
common/golden/stats_vectors.json (их генерирует make_golden.py).

Что исправляет по сравнению с calibration.danger_table и старым отчётом тренажёра.

1. Тема без доверительной оценки. У темы с n=5 разрыв прыгает на десятки пунктов
   от одного шума. Здесь у каждой темы есть z-оценка и интервал, а флаг ставится
   только при n >= 20, z <= -3 и разрыве не меньше 5 пунктов после усадки.
2. Служебные теги (фаза, длина, исход) не темы: их разрыв описывает выборку, а не
   тактику. Они не попадают в таблицу.
3. Смещение прогноза. Ожидание Glicko описывает решение всей задачи, а тренажёр
   проверяет первый ход, поэтому факт систематически выше прогноза, причём сильнее
   у длинных задач. Остатки центрируются внутри класса длины, и таблица показывает
   слабость относительно собственного уровня, а не абсолютный разрыв с рейтингом.
4. Самоуверенность. Вердикт по z-критерию смещения (средняя уверенность минус точность),
   а не по порогу в 15 пунктов на корзине из 25 задач.
5. Отбор худшей темы на тех же данных, где она потом измеряется, завышает улучшение
   (регрессия к среднему). select_and_evaluate выбирает тему на одной половине базы,
   а меряет на другой, и сравнивает с контрольными задачами.

Честная граница: до нескольких сотен задач таблица по темам почти ничего не флагует.
Это не поломка, а размер выборки. Смотри tasks_for_gap и mde.
"""
import math

Z95 = 1.959963984540054         # двусторонний 95%
Z_POWER80 = 0.8416212335729143  # мощность 80%

MIN_N_CALIBRATION = 30   # меньше этого вердикта о самоуверенности нет
MIN_N_THEME = 20         # меньше этого флага по теме нет
Z_CRIT_THEME = 3.0       # консервативно: хватает на ~18 тем при общем уровне ошибки 5%
MIN_GAP_THEME = 0.05     # практическая значимость: не меньше 5 пунктов после усадки

# Теги Lichess, которые не являются тактическими темами.
SERVICE_TAGS = frozenset([
    "advantage", "crushing", "equality",          # исход
    "opening", "middlegame", "endgame",           # фаза
    "oneMove", "short", "long", "veryLong",       # длина
    "mate",                                       # общий тег, дублирует mateInN
    "master", "masterVsMaster", "superGM",        # происхождение партии
])
LENGTH_CLASS = {"oneMove": 1, "short": 2, "long": 3, "veryLong": 4}


# ------------------------------------------------------------------ мелочи

def _conf(r):
    """Уверенность из записи как вероятность в [0.01, 0.99]."""
    return min(max(float(r["confidence"]) / 100.0, 0.01), 0.99)


def _hit(r):
    return 1 if int(float(r["correct"])) else 0


def _exp(r):
    return min(max(float(r["expected"]), 0.01), 0.99)


def _is_hint(r):
    v = str(r.get("hints", "") or "0").strip().lower()
    return v not in ("0", "0.0", "false", "")


def without_hints(records):
    """Строки, где спортсмену не показывали рейтинг и темы до ответа."""
    return [r for r in records if not _is_hint(r)]


def length_class(themes):
    """Класс длины задачи по тегам Lichess: 1 oneMove, 2 short, 3 long, 4 veryLong, 0 нет тега."""
    for t in themes.split():
        if t in LENGTH_CLASS:
            return LENGTH_CLASS[t]
    return 0


def wilson(k, n, z=Z95):
    """Интервал Уилсона для доли k/n. При n=0 возвращает (0, 1)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    z2 = z * z
    denom = 1.0 + z2 / n
    centre = (p + z2 / (2.0 * n)) / denom
    half = z * math.sqrt(p * (1.0 - p) / n + z2 / (4.0 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


# ------------------------------------------------------------------ калибровка

def calibration_summary(records):
    """Сводка калибровки: точность с интервалом, log-loss, Brier, навык и вердикт.

    Навык = 1 - log-loss / log-loss константного прогноза (средняя точность спортсмена).
    Положительный навык значит, что уверенность различает верные и неверные ответы.
    Смещение = средняя уверенность - точность. z = (сумма уверенностей - число верных)
    / sqrt(сумма p(1-p)): при идеальной калибровке это примерно стандартное нормальное.
    """
    n = len(records)
    out = {"n": n, "acc": None, "acc_lo": None, "acc_hi": None, "mean_conf": None,
           "bias": None, "bias_z": None, "log_loss": None, "log_loss_base": None,
           "skill": None, "brier": None, "verdict": "нет данных"}
    if n == 0:
        return out
    ys = [_hit(r) for r in records]
    ps = [_conf(r) for r in records]
    k = sum(ys)
    acc = k / n
    lo, hi = wilson(k, n)
    mean_conf = sum(ps) / n
    ll = sum(-(y * math.log(p) + (1 - y) * math.log(1 - p)) for y, p in zip(ys, ps)) / n
    pb = min(max(acc, 0.01), 0.99)
    ll_base = sum(-(y * math.log(pb) + (1 - y) * math.log(1 - pb)) for y in ys) / n
    brier = sum((p - y) ** 2 for y, p in zip(ys, ps)) / n
    var = sum(p * (1 - p) for p in ps)
    z = (sum(ps) - k) / math.sqrt(var)
    bias = mean_conf - acc
    if n < MIN_N_CALIBRATION:
        verdict = "мало данных"
    elif z >= 2.0 and bias >= 0.05:
        verdict = "самоуверенность"
    elif z <= -2.0 and bias <= -0.05:
        verdict = "недоуверенность"
    else:
        verdict = "в пределах шума"
    out.update(acc=acc, acc_lo=lo, acc_hi=hi, mean_conf=mean_conf, bias=bias, bias_z=z,
               log_loss=ll, log_loss_base=ll_base, skill=1.0 - ll / ll_base,
               brier=brier, verdict=verdict)
    return out


def reliability(records, edges=(0, 20, 40, 60, 80, 100)):
    """Корзины уверенности с интервалами Уилсона для точности. Пустые корзины пропущены."""
    k = len(edges) - 1
    bins = [[] for _ in range(k)]
    for r in records:
        c = float(r["confidence"])
        i = k - 1
        for j in range(k):
            if c < edges[j + 1]:
                i = j
                break
        bins[i].append(r)
    out = []
    for i, sub in enumerate(bins):
        if not sub:
            continue
        n = len(sub)
        kk = sum(_hit(r) for r in sub)
        lo, hi = wilson(kk, n)
        out.append({"lo": edges[i], "hi": edges[i + 1], "n": n,
                    "mean_conf": sum(float(r["confidence"]) for r in sub) / n / 100.0,
                    "acc": kk / n, "acc_lo": lo, "acc_hi": hi})
    return out


# ------------------------------------------------------------------ таблица тем

def _dl_tau2(gaps, variances):
    """Дисперсия между темами по DerSimonian-Laird. Возвращает (tau2, взвешенное среднее)."""
    k = len(gaps)
    if k == 0:
        return 0.0, 0.0
    w = [1.0 / max(v, 1e-12) for v in variances]
    sw = sum(w)
    grand = sum(wi * gi for wi, gi in zip(w, gaps)) / sw
    if k < 2:
        return 0.0, grand
    q = sum(wi * (gi - grand) ** 2 for wi, gi in zip(w, gaps))
    c = sw - sum(wi * wi for wi in w) / sw
    tau2 = max(0.0, (q - (k - 1)) / c) if c > 0 else 0.0
    return tau2, grand


def _residuals(records, center):
    """Остатки y - expected и дисперсии e(1-e). С center вычитается среднее остатка
    своего класса длины (если в классе меньше 10 задач, общее среднее)."""
    res, var = [], []
    for r in records:
        e = _exp(r)
        res.append(_hit(r) - e)
        var.append(e * (1.0 - e))
    if center and res:
        allmean = sum(res) / len(res)
        groups = {}
        for r, x in zip(records, res):
            groups.setdefault(length_class(r["themes"]), []).append(x)
        means = {c: (sum(v) / len(v) if len(v) >= 10 else allmean) for c, v in groups.items()}
        res = [x - means[length_class(r["themes"])] for r, x in zip(records, res)]
    return res, var


def theme_table(records, min_n=MIN_N_THEME, z_crit=Z_CRIT_THEME,
                min_gap=MIN_GAP_THEME, center=True):
    """Таблица тем: факт, прогноз, разрыв с интервалом, z, разрыв после усадки, флаг.

    records: dicts с themes (строка через пробел), correct, expected.
    Строка темы: theme, n, acc, exp, gap, se, z, lo, hi, shrunk, flag.
    shrunk и flag заполнены только у тем с n >= min_n. flag: weak, strong или пусто.
    Темы в таблице с n >= 3, но выводы допустимы только у тех, где shrunk не None.
    """
    res, var = _residuals(records, center)
    acc_t = {}
    for r, x, v in zip(records, res, var):
        e = _exp(r)
        for t in r["themes"].split():
            if t in SERVICE_TAGS:
                continue
            s = acc_t.setdefault(t, [0, 0, 0.0, 0.0, 0.0])
            s[0] += 1
            s[1] += _hit(r)
            s[2] += e
            s[3] += x
            s[4] += v
    rows = []
    for t, (n, k, sum_e, sum_r, sum_v) in acc_t.items():
        if n < 3:
            continue
        sd = math.sqrt(sum_v)
        gap = sum_r / n
        se = sd / n
        rows.append({"theme": t, "n": n, "acc": k / n, "exp": sum_e / n, "gap": gap,
                     "se": se, "z": sum_r / sd, "lo": gap - Z95 * se, "hi": gap + Z95 * se,
                     "shrunk": None, "flag": ""})
    elig = [r for r in rows if r["n"] >= min_n]
    tau2, grand = _dl_tau2([r["gap"] for r in elig], [r["se"] ** 2 for r in elig])
    for r in elig:
        s2 = r["se"] ** 2
        b = tau2 / (tau2 + s2) if tau2 + s2 > 0 else 0.0
        r["shrunk"] = grand + b * (r["gap"] - grand)
        if r["z"] <= -z_crit and r["shrunk"] <= -min_gap:
            r["flag"] = "weak"
        elif r["z"] >= z_crit and r["shrunk"] >= min_gap:
            r["flag"] = "strong"
    rows.sort(key=lambda r: (0 if r["shrunk"] is not None else 1,
                             r["shrunk"] if r["shrunk"] is not None else r["gap"],
                             r["theme"]))
    return {"rows": rows, "tau2": tau2, "grand": grand, "k": len(elig), "n": len(records)}


# ------------------------------------------------------------------ планирование и пилот

def mde(n1, n2=None, p=0.5, z_alpha=Z95, z_power=Z_POWER80):
    """Минимальный заметный сдвиг доли (мощность 80%, уровень 5%, независимые выборки)."""
    n2 = n1 if n2 is None else n2
    return (z_alpha + z_power) * math.sqrt(p * (1.0 - p) * (1.0 / n1 + 1.0 / n2))


def tasks_for_gap(gap, var=0.2, z_crit=Z_CRIT_THEME, z_power=Z_POWER80):
    """Сколько задач ОДНОЙ темы нужно, чтобы заметить провал на gap (доля, например 0.15).
    var = средняя e(1-e) по задачам, около 0.2."""
    return int(math.ceil(((z_crit + z_power) ** 2) * var / (gap * gap)))


def _pool_gap(records, themes):
    """(n, разрыв, se) по задачам, у которых есть хотя бы одна тема из themes (без центровки).
    themes=None даёт все задачи; themes=set даёт пересечение; отрицание задаёт caller."""
    n = 0
    sum_r = 0.0
    sum_v = 0.0
    for r in records:
        if themes is not None and not (set(r["themes"].split()) & themes):
            continue
        e = _exp(r)
        n += 1
        sum_r += _hit(r) - e
        sum_v += e * (1.0 - e)
    if n == 0:
        return 0, 0.0, float("nan")
    return n, sum_r / n, math.sqrt(sum_v) / n


def _pool_gap_not(records, themes):
    n = 0
    sum_r = 0.0
    sum_v = 0.0
    for r in records:
        if set(r["themes"].split()) & themes:
            continue
        e = _exp(r)
        n += 1
        sum_r += _hit(r) - e
        sum_v += e * (1.0 - e)
    if n == 0:
        return 0, 0.0, float("nan")
    return n, sum_r / n, math.sqrt(sum_v) / n


def select_and_evaluate(base_a, base_b, post, k=3, min_n=10):
    """Оценка эффекта обучения на слабых темах без завышения от отбора.

    Худшие k тем выбираются ТОЛЬКО по base_a (первая половина базовой фазы).
    Честный базовый разрыв меряется на base_b, итоговый на post.
      naive  = post - base_a   завышено отбором (регрессия к среднему)
      honest = post - base_b   без смещения отбора
      did    = honest - изменение контрольных задач (без выбранных тем)
    Возвращает dict или None, если не из чего выбирать.
    """
    res, _ = _residuals(base_a, True)
    acc = {}
    for r, x in zip(base_a, res):
        for t in r["themes"].split():
            if t in SERVICE_TAGS:
                continue
            s = acc.setdefault(t, [0, 0.0])
            s[0] += 1
            s[1] += x
    cand = sorted((v[1] / v[0], t) for t, v in acc.items() if v[0] >= min_n)
    if not cand:
        return None
    chosen = set(t for _, t in cand[:k])
    na, ga, sa = _pool_gap(base_a, chosen)
    nb, gb, sb = _pool_gap(base_b, chosen)
    np_, gp, sp = _pool_gap(post, chosen)
    _, cb, scb = _pool_gap_not(base_b, chosen)
    _, cp, scp = _pool_gap_not(post, chosen)
    honest = gp - gb
    honest_se = math.sqrt(sp ** 2 + sb ** 2)
    did = honest - (cp - cb)
    did_se = math.sqrt(sp ** 2 + sb ** 2 + scp ** 2 + scb ** 2)
    return {"themes": sorted(chosen), "n_a": na, "n_b": nb, "n_post": np_,
            "gap_a": ga, "gap_b": gb, "gap_post": gp,
            "naive": gp - ga, "honest": honest, "honest_se": honest_se,
            "control_change": cp - cb, "did": did, "did_se": did_se}
