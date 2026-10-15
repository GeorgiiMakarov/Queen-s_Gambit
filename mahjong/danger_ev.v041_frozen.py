# FROZEN v0.4.1 — placement (pt + очки/1000) проверен на оорасу: 51,2% vs 52,7% у очков.
# Вердикт: placement ВЫКЛЮЧЕН (Cfg.placement_oorasu=False). Не менять без решения Георгия.
# Дальше — шахматы.
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
danger_ev.py  v0.3.0-draft

Простой EV-калькулятор опасности сбросов для риичи-маджонга
и задачи для теста чиитойцу. Один файл, без зависимостей.

Запуск: python danger_ev.py          selftest и разбор флагманской задачи T1
        python danger_ev.py --all    плюс разбор остальных задач

Состав
1. Нотация: 11m88m22p57p33s77s1z7z. Масти m p s z, 0 = красная пятёрка (ака-дора:
   в 34-счётчике считается как 5, для скоринга учитывается отдельно, 1 ака на масть).
   Внутри счётчик из 34 плиток: 0-8 man, 9-17 pin, 18-26 sou, 27-33 honors.
2. Эталонный shanten = min(стандарт, чиитойцу, кокуши), одинаков для 13 и 14 плиток.
   Нужен, чтобы файл работал сам. Свой движок подключается так:
       import danger_ev
       danger_ev.SHANTEN = lambda c: твой_shanten(danger_ev.to_dict(c))
3. Опасность: шанс рона на плитке от одного риичи-игрока по формам ожидания
   (рьянмен, канчан, пенчан, шанпон, танки). Генбуцу даёт 0, суджи вычёркивает рьянмен,
   счётчик показанных копий режет вес каждой формы (кабе и ван-чанс получаются сами).
4. EV каждого сброса: гонка на T ходов, на каждом сбросе риск вылета.
   EV(сброс) = P_win * цена_победы - P_loss * цена_вылета.
   Строка fold показывает, что даёт полный отказ от атаки.

Важно. Все числа в таблицах W_* и в Cfg это стартовые приоры по порядку величины,
а не статистика Houou. Калибровать по своим логам: править нужно только их.
Цена победы считается по хан/фу для каждого сброса (тенпай — точно, 1-шантен —
среднее по улучшениям, 2+ — fallback 3200); чужие тенпаи без риичи не считаются,
рон по нашему ожиданию сведён в один коэффициент k_win, будущий риск зависит от
шантена (тенпай 0.036, 1-шантен 0.012, 2+ 0.005).
Укейре после первого улучшения заменено потолком uk_later, а ожидание на последнем шаге
берётся по форме руки (w_final). Лучший сброс почти не зависит от параметров, а вердикт
push или fold сильнее всего зависит от future_hazard: проверяй его на своих логах первым.
"""
from __future__ import annotations

import sys
from dataclasses import dataclass, field
from functools import lru_cache
from itertools import product
from math import comb

SUIT = "mpsz"
N = 34
YAOCHU = (0, 8, 9, 17, 18, 26, 27, 28, 29, 30, 31, 32, 33)


# ------------------------------------------------------------------ нотация

def parse(s):
    """'11m88m22p57p33s77s1z7z' -> счётчик из 34 плиток."""
    c = [0] * N
    digits = []
    for ch in s:
        if ch.isspace():
            continue
        if ch.isdigit():
            digits.append(ch)
        elif ch in SUIT:
            base = SUIT.index(ch) * 9
            top = 7 if ch == "z" else 9
            for d in digits:
                r = 5 if (d == "0" and ch != "z") else int(d)
                if not 1 <= r <= top:
                    raise ValueError("нет такой плитки: %s%s" % (d, ch))
                c[base + r - 1] += 1
            digits = []
        else:
            raise ValueError("лишний символ: %r" % ch)
    if digits:
        raise ValueError("у цифр нет масти: " + "".join(digits))
    return c


def parse_aka(s):
    """Ака-доры в нотации: '0m'/'0p'/'0s' = красная пятёрка. Возвращает {плитка: число}.
    В 34-счётчике ака считается как обычная 5 (шантен/опасность не меняются),
    для скоринга ака передаётся отдельно."""
    aka = {}
    digits = []
    for ch in s:
        if ch.isspace():
            continue
        if ch.isdigit():
            digits.append(ch)
        elif ch in SUIT:
            if ch != "z":
                base = SUIT.index(ch) * 9
                for d in digits:
                    if d == "0":
                        t = base + 4
                        aka[t] = aka.get(t, 0) + 1
            digits = []
    return aka


AKA_PER_SUIT = 1   # красных пятёрок каждой масти в игре (стандарт Houou)


def name(t):
    return "%d%s" % (t % 9 + 1, SUIT[t // 9])


def fmt(c):
    """счётчик -> '1188m 2257p 3377s 17z'"""
    out = []
    for s in range(4):
        n = 7 if s == 3 else 9
        digs = "".join(str(r + 1) * c[s * 9 + r] for r in range(n))
        if digs:
            out.append(digs + SUIT[s])
    return " ".join(out)


def to_dict(c):
    """счётчик -> {'1m': 2, ...} для движков, которые принимают словарь"""
    return {name(t): c[t] for t in range(N) if c[t]}


def tiles_of(s):
    if not s:
        return frozenset()
    c = parse(s)
    return frozenset(t for t in range(N) if c[t])


# ------------------------------------------------------------------ шантен

def _prune(states):
    return frozenset(
        r for r in states
        if not any(q != r and q[0] >= r[0] and q[1] >= r[1] and q[2] >= r[2] for q in states)
    )


@lru_cache(maxsize=None)
def _go(cc, honor):
    """Все достижимые (мельды, заготовки, голова) для одной масти."""
    n = len(cc)
    i = 0
    while i < n and cc[i] == 0:
        i += 1
    if i == n:
        return frozenset({(0, 0, 0)})
    out = set()

    def take(drop, dm, dt, dp):
        L = list(cc)
        for j, k in drop:
            L[j] -= k
        for (m, t, p) in _go(tuple(L), honor):
            if p + dp <= 1:
                out.add((m + dm, min(t + dt, 4), p + dp))

    x = cc[i]
    if x >= 3:
        take([(i, 3)], 1, 0, 0)
    if not honor and i + 2 < n and cc[i + 1] and cc[i + 2]:
        take([(i, 1), (i + 1, 1), (i + 2, 1)], 1, 0, 0)
    if x >= 2:
        take([(i, 2)], 0, 0, 1)      # пара как голова
        take([(i, 2)], 0, 1, 0)      # пара как заготовка
    if not honor and i + 1 < n and cc[i + 1]:
        take([(i, 1), (i + 1, 1)], 0, 1, 0)
    if not honor and i + 2 < n and cc[i + 2]:
        take([(i, 1), (i + 2, 1)], 0, 1, 0)
    take([(i, 1)], 0, 0, 0)          # одиночная плитка
    return _prune(out)


def shanten_standard(c):
    st = {(0, 0, 0)}
    for s in range(4):
        a = tuple(c[27:34]) if s == 3 else tuple(c[s * 9:s * 9 + 9])
        opts = _go(a, s == 3)
        st = {(m + m2, min(t + t2, 4), p + p2)
              for (m, t, p) in st for (m2, t2, p2) in opts if p + p2 <= 1}
    return min(8 - 2 * m - min(t, 4 - m) - p for (m, t, p) in st)


def shanten_chiitoi(c):
    # четыре одинаковых = одна пара, виды считаем только по x > 0 (нули в счётчике не мешают)
    pairs = sum(1 for x in c if x >= 2)
    kinds = sum(1 for x in c if x >= 1)
    return 6 - pairs + max(0, 7 - kinds)


def shanten_kokushi(c):
    kinds = sum(1 for t in YAOCHU if c[t] >= 1)
    pair = 1 if any(c[t] >= 2 for t in YAOCHU) else 0
    return 13 - kinds - pair


def shanten_all(c):
    return shanten_standard(c), shanten_chiitoi(c), shanten_kokushi(c)


def shanten(c):
    return min(shanten_all(c))


SHANTEN = shanten    # точка подмены на свой движок


def ukeire(c, vis):
    """Плитки, снижающие шантен руки c (13 плиток). vis[t] = сколько копий t уже видно."""
    base = SHANTEN(c)
    tiles = {}
    for t in range(N):
        left = 4 - vis[t]
        if left <= 0:
            continue
        c[t] += 1
        if SHANTEN(c) < base:
            tiles[t] = left
        c[t] -= 1
    return sum(tiles.values()), tiles


# ------------------------------------------------------------------ опасность
# Вклад каждой формы ожидания: шанс, что риичи-игрок ждёт именно эту плитку именно
# этой формой, когда о ней ничего не известно. Порядок величины, не статистика.

W_RYAN = {2: .051, 3: .068, 4: .085, 5: .085, 6: .068, 7: .051}   # ключ a: рьянмен (a, a+1) ждёт a-1 и a+2
W_KAN = {2: .015, 3: .021, 4: .024, 5: .024, 6: .024, 7: .021, 8: .015}   # ключ r: канчан (r-1, r+1) ждёт r
W_PEN = .015                                                       # 12 ждёт 3, 89 ждёт 7
W_SHAN = {1: .00975, 2: .011, 3: .009, 4: .009, 5: .009, 6: .009, 7: .009, 8: .011, 9: .00975}
W_TANKI = {1: .01125, 2: .012, 3: .010, 4: .010, 5: .010, 6: .010, 7: .010, 8: .012, 9: .01125}
W_HONOR_SHAN = .012
W_HONOR_TANKI = .012
DORA_MULT = 1.4
YAKU_MULT = 1.2
RIICHI_LATE_TURN = 12   # риичи с этого хода: чаще хорошее ожидание
RIICHI_LATE_MULT = 2.0
DANGER_CAP = 0.15       # потолок прогноза: самые опасные плитки переоценивались (15%+ vs факт 11%)


def danger_table(safe, vis, dora=frozenset(), yaku=frozenset(), riichi_turn=None):
    """Шанс рона на каждой из 34 плиток от одного риичи-игрока.
    safe: плитки, безопасные против него. vis: сколько копий каждой плитки видно нам.
    riichi_turn: ход объявления риичи; с RIICHI_LATE_TURN опасность умножается на RIICHI_LATE_MULT."""
    u = [max(0, 4 - v) for v in vis]                      # сколько копий ещё не показано
    f2 = lambda x, y: min(2.0, x * y / 9.0)               # обе плитки формы могут быть у него
    fs = lambda x: comb(x, 2) / 3.0                       # шанпон: у него пара этой плитки
    ft = lambda x: x / 3.0                                # танки: у него одна такая плитка
    out = [0.0] * N
    for t in range(N):
        if t in safe:
            continue
        if t >= 27:
            d = W_HONOR_SHAN * fs(u[t]) + W_HONOR_TANKI * ft(u[t])
        else:
            b, r = (t // 9) * 9, t % 9 + 1
            d = 0.0
            for a, w in W_RYAN.items():
                lo, hi = a - 1, a + 2
                if r not in (lo, hi):
                    continue
                other = hi if r == lo else lo
                if b + other - 1 in safe:                 # суджи: второе ожидание безопасно, он был бы в фуритене
                    continue
                d += w * f2(u[b + a - 1], u[b + a])
            if r in W_KAN:
                d += W_KAN[r] * f2(u[b + r - 2], u[b + r])
            if r == 3:
                d += W_PEN * f2(u[b], u[b + 1])
            if r == 7:
                d += W_PEN * f2(u[b + 7], u[b + 8])
            d += W_SHAN[r] * fs(u[t]) + W_TANKI[r] * ft(u[t])
        if t in dora:
            d *= DORA_MULT
        if t in yaku:
            d *= YAKU_MULT
        if riichi_turn is not None and riichi_turn >= RIICHI_LATE_TURN:
            d *= RIICHI_LATE_MULT
        out[t] = min(d, DANGER_CAP)
    return out


# ------------------------------------------------------------------ хан / фу
# Цена победы для каждого сброса: хан/фу вместо одной win_value.
# Допущения: рука закрытая, риичи объявлен (толкаем до тенпая — ставим риичи),
# цена — рон (цумо платит больше, разница свёрнута в k_win), без ура-доры
# (она скрыта). Без канов. yaku_set — ёкухай (драконы + ветра); пара/триплет любого из них
# = +2 фу / +1 хан (двойной ветер +4 не различаем).
# Ака: 0m/0p/0s в нотации, +1 хан за каждую в руке; плита выигрыша 5 может
# быть ака — считаем матожидание (1 ака на масть). win_value=None в Cfg —
# считать по хан/фу; int — override для всех сбросов.

FALLBACK_WIN_VALUE = 3200   # для 2+ шантена, когда win_value=None: цена неизвестна


def _ceil100(x):
    return ((x + 99) // 100) * 100


def _decompositions(c14):
    """Все разложения 14 плиток на 4 сета + пару. Сет: ('shun', t) / ('kou', t)."""
    res = []
    c = list(c14)
    for p in range(N):
        if c[p] < 2:
            continue
        c[p] -= 2
        _sets(c, [], res, p)
        c[p] += 2
    return res


def _sets(c, acc, res, pair):
    if len(acc) == 4:
        if not any(c):
            res.append((tuple(acc), pair))
        return
    t = next((i for i, v in enumerate(c) if v), None)
    if t is None:
        return
    if c[t] >= 3:
        c[t] -= 3
        acc.append(("kou", t))
        _sets(c, acc, res, pair)
        acc.pop()
        c[t] += 3
    if t < 27 and t % 9 <= 6 and c[t + 1] and c[t + 2]:
        c[t] -= 1
        c[t + 1] -= 1
        c[t + 2] -= 1
        acc.append(("shun", t))
        _sets(c, acc, res, pair)
        acc.pop()
        c[t] += 1
        c[t + 1] += 1
        c[t + 2] += 1


def _wait_fu(kind, a, w):
    """Фу за ожидание. kind: 'shan' (шанпон), 'shun' (последовательность с началом a)."""
    if kind == "shan":
        return 2
    if w == a + 1:
        return 2                       # канчан
    if w == a and a == 7:
        return 2                       # пенчан: 89 ждёт 7
    if w == a + 2 and a == 1:
        return 2                       # пенчан: 12 ждёт 3
    return 0                           # рьянмен


def _yakuman_points(count, is_dealer):
    return (48000 if is_dealer else 32000) * count


def _points(han, fu, is_dealer):
    """Очки рона по хан/фу (han — всего, включая дору)."""
    if han >= 13:
        return 48000 if is_dealer else 32000
    if han >= 11:
        return 36000 if is_dealer else 24000
    if han >= 8:
        return 24000 if is_dealer else 16000
    if han >= 6:
        return 18000 if is_dealer else 12000
    if han >= 5 or (han == 4 and fu >= 40) or (han == 3 and fu >= 70):
        return 12000 if is_dealer else 8000
    return _ceil100(fu * (1 << (2 + han)) * (6 if is_dealer else 4))


def _han_standard(c14, sets, pair, yaku_set, riichi):
    """(хан за яку без доры, число якуманов) для стандартной формы. None — нет яку."""
    dragons = (31, 32, 33)
    winds = (27, 28, 29, 30)
    kou = [t for kind, t in sets if kind == "kou"]
    # --- якуман по разложению (раньше хан: якуман перекрывает всё)
    if sum(1 for t in kou if t in dragons) == 3:
        return 0, 1                                        # дайсанген
    n_wind = sum(1 for t in kou if t in winds)
    if n_wind == 4:
        return 0, 1                                        # дайсуусии
    if n_wind == 3 and pair in winds:
        return 0, 1                                        # сёсуусии
    if all(t in YAOCHU for t in range(N) if c14[t]):
        return 0, 1                                        # цууиисоу / хонроуто
    han = 0
    if riichi:
        han += 1
    if all(t not in YAOCHU for t in range(N) if c14[t]):
        han += 1                                           # таняо
    shuns = [t for kind, t in sets if kind == "shun"]
    seen, iip = set(), 0
    for t in shuns:
        if t in seen:
            iip += 1
            seen.discard(t)
        else:
            seen.add(t)
    if iip == 2:
        han += 3                                           # рьянпейко
    elif iip == 1:
        han += 1                                           # ийпейко
    for a in range(1, 8):                                  # сансёку додзюн
        if all((s * 9 + a - 1) in shuns for s in range(3)):
            han += 2
            break
    for s in range(3):                                     # итцу
        b = s * 9
        if all((b + a - 1) in shuns for a in (1, 4, 7)):
            han += 2
            break

    def has_yao(kind, t):
        return t in YAOCHU if kind == "kou" else t % 9 in (0, 6)

    def has_term(kind, t):
        return t % 9 in (0, 8) if kind == "kou" else t % 9 in (0, 6)
    if all(has_yao(k, t) for k, t in sets) and pair in YAOCHU:
        if all(has_term(k, t) for k, t in sets) and pair < 27 and pair % 9 in (0, 8):
            han += 3                                       # дзюнчан
        else:
            han += 2                                       # хончантай
    if all(k == "kou" for k, _ in sets):
        han += 2                                           # тойтой
    if len(kou) >= 3:
        han += 2                                           # сананко (рука закрытая)
    for r in range(1, 10):                                 # сансёку доко
        if all((s * 9 + r - 1) in kou for s in range(3)):
            han += 2
            break
    n_drag = sum(1 for t in kou if t in dragons)
    shousangen = n_drag == 2 and pair in dragons
    if shousangen:
        han += 2
    for t in kou:                                          # ёкухай (кроме сёсангена)
        if t in yaku_set and not (shousangen and t in dragons):
            han += 1
    if han == 0:
        return None
    return han, 0


def _score_hand(c13, win_tile, dora_set, yaku_set, is_dealer, riichi, aka=None):
    """Цена рона: 13-плиточная рука + плита выигрыша. 0, если яку нет.
    aka: {плитка: число} красных пятёрок в 13-плиточной руке (+1 хан за каждую)."""
    c14 = list(c13)
    c14[win_tile] += 1
    # кокуши
    if (all(c14[t] >= 1 for t in YAOCHU)
            and sum(c14[t] for t in YAOCHU) == 14
            and sum(1 for t in YAOCHU if c14[t] == 2) == 1):
        thirteen = all(c13[t] == 1 for t in YAOCHU)       # 13-стороннее ожидание
        return _yakuman_points(2 if thirteen else 1, is_dealer)
    dora_han = sum(c14[t] for t in dora_set)
    aka_han = sum((aka or {}).values())
    best = 0
    # чиитойцу: 7 пар
    if sum(1 for t in range(N) if c14[t] == 2) == 7:
        han = 2 + (1 if riichi else 0) + aka_han
        if han > 0:
            best = max(best, _points(han + dora_han, 25, is_dealer))
    # стандарт: все разложения, все выигрышные группы, максимум
    for sets, pair in _decompositions(c14):
        base = _han_standard(c14, sets, pair, yaku_set, riichi)
        if base is None:
            continue
        han, yaku = base
        if yaku:
            best = max(best, _yakuman_points(yaku, is_dealer))
            continue
        groups = []
        for kind, t in sets:
            if kind == "kou" and t == win_tile:
                groups.append(("shan", t))
            if kind == "shun" and t <= win_tile <= t + 2:
                groups.append(("shun", t))
        if pair == win_tile:
            groups.append(("tanki", pair))
        for gkind, gt in groups:
            h = han
            if (gkind == "shun" and all(k == "shun" for k, _ in sets)
                    and pair not in yaku_set
                    and _wait_fu("shun", gt, win_tile) == 0):
                h += 1                                     # пинфу
            fu = 20 + 10                                   # база + закрытый рон
            if pair in yaku_set:
                fu += 2
            for kind, t in sets:
                if kind == "kou":
                    fu += 8 if t in YAOCHU else 4
            fu += 2 if gkind in ("shan", "tanki") else _wait_fu("shun", gt, win_tile)
            fu = ((fu + 9) // 10) * 10   # фу округляется вверх до 10 (чиитойцу 25 — отдельно)
            best = max(best, _points(h + dora_han + aka_han, fu, is_dealer))
    return best


def tenpai_value(c13, vis, dora_set, yaku_set, is_dealer=False, riichi=True, aka=None):
    """Ожидаемая цена победы для тенпай-руки (13 плиток): среднее по ждущим.
    aka: {плитка: число} красных пятёрок в руке. Для ожидания 5m/5p/5s плита
    выигрыша может быть ака: считаем матожидание (ака / не ака)."""
    aka = aka or {}
    total, weight = 0.0, 0
    for t in range(N):
        left = 4 - vis[t]
        if left <= 0:
            continue
        c13[t] += 1
        complete = SHANTEN(c13) < 0
        c13[t] -= 1
        if not complete:
            continue
        if t in (4, 13, 22) and aka.get(t, 0) < AKA_PER_SUIT:
            # плита выигрыша может быть ака
            p_aka = (AKA_PER_SUIT - aka.get(t, 0)) / left
            aka_win = dict(aka)
            aka_win[t] = aka_win.get(t, 0) + 1
            sc = (p_aka * _score_hand(c13, t, dora_set, yaku_set, is_dealer, riichi, aka_win)
                  + (1.0 - p_aka) * _score_hand(c13, t, dora_set, yaku_set, is_dealer, riichi, aka))
        else:
            sc = _score_hand(c13, t, dora_set, yaku_set, is_dealer, riichi, aka)
        total += left * sc
        weight += left
    return total / weight if weight else 0.0


def hand_value(c13, vis, dora_set, yaku_set, cfg, is_dealer=False, riichi=True, aka=None):
    """Цена победы для 13-плиточной руки после сброса: тенпай — точно,
    1-шантен — среднее по улучшающим плитам (лучший сброс после улучшения),
    2+ — fallback. win_value=int в Cfg — override для всех сбросов.
    aka: {плитка: число} красных пятёрок в руке (сброс пятёрки уводит ака,
    только если все копии этой пятёрки — ака)."""
    if cfg.win_value is not None:
        return cfg.win_value
    aka = aka or {}
    s = SHANTEN(c13)
    if s == 0:
        v = tenpai_value(c13, vis, dora_set, yaku_set, is_dealer, riichi, aka)
        return v if v > 0 else FALLBACK_WIN_VALUE
    if s == 1:
        total, weight = 0.0, 0
        for u in range(N):
            left = 4 - vis[u]
            if left <= 0:
                continue
            c13[u] += 1
            if SHANTEN(c13) < s:
                # лучший сброс после улучшения: максимум по тенпай-сбросам
                best = 0.0
                for d in range(N):
                    if not c13[d]:
                        continue
                    c13[d] -= 1
                    if SHANTEN(c13) == 0:
                        vis2 = list(vis)
                        vis2[u] += 1   # вытянутая плита уже в руке
                        vis2[d] += 1   # сброшенная — в реке
                        aka2 = dict(aka)
                        if d in (4, 13, 22) and c13[d] + 1 == aka.get(d, 0):
                            aka2[d] = aka2[d] - 1
                            if aka2[d] <= 0:
                                del aka2[d]
                        best = max(best, tenpai_value(c13, vis2, dora_set, yaku_set,
                                                      is_dealer, riichi, aka2))
                    c13[d] += 1
                total += left * best
                weight += left
            c13[u] -= 1
        return total / weight if weight else FALLBACK_WIN_VALUE
    return FALLBACK_WIN_VALUE


# ------------------------------------------------------------------ EV

@dataclass
class Cfg:
    turns: int = 5                # эффективных ходов впереди после раннего риичи (измерено: 5.01)
    turns_late: int = 3           # то же после риичи на 12-м ходу и позже (измерено: 3.02)
    late_turn: int = 12           # граница раннего/позднего риичи
    win_value: int | None = None  # цена победы: None — считать по хан/фу на каждый сброс, int — override
    k_prog: float = 1.0           # улучшение за ход = k_prog * укейре / невидимые плитки
    uk_later: dict = field(default_factory=lambda: {"std": 14, "chi": 8, "kok": 8})   # потолок укейре на втором и дальше шагах
    k_win: float = 1.6            # победа за ход: свой тяг плюс рон с чужих сбросов (измерено vs риичи 1.57)
    future_hazard: dict = field(default_factory=lambda: {0: 0.036, 1: 0.012, 2: 0.005})
    # риск вылета на каждом следующем сбросе, пока атакуем, по шантену
    # (измерено под 1 риичи, все сбросы: тенпай 3.61%, 1-шантен 1.21%, 2+ 0.52%)
    fold_hazard: float = 0.002    # то же при полном отказе от атаки (измерено: P(рон|сброс фолдера) = 0.0017)
    loss_nondealer: int = 6000    # средняя цена рона риичи не дилера (измерено 5950, медиана 5200 — оставить)
    loss_dealer: int = 8000       # то же для дилера (измерено 7961, медиана 7700)
    maw_thr: float = 0.03         # маваши сбрасывает только плитки с p_deal <= порога
    maw_hazard: float = 0.010     # риск за последующий сброс при маваши (хонор ~1%, судзи ~2.5-4%, генбуцу 0)
    k_maw: float = 0.8            # доля скорости прогресса при маваши: опасные плитки придётся держать
    placement_oorasu: bool = False   # placement (pt + очки/1000) на Юг-4; выкл, пока не побьёт 52,7%
    w_final: dict = field(default_factory=lambda: {"std": 5.5, "chi": 2.5, "kok": 3.0})


@dataclass(frozen=True)
class Threat:
    safe: frozenset
    dealer: bool = False
    value: int = 0
    riichi_turn: int | None = None   # ход объявления риичи (для множителя позднего риичи)

    def loss(self, cfg):
        return self.value or (cfg.loss_dealer if self.dealer else cfg.loss_nondealer)


def threat(safe_tiles, dealer=False, value=0, riichi_turn=None):
    """safe_tiles: его река плюс всё, что другие сбросили после его риичи, а он пропустил.
    riichi_turn: ход объявления риичи."""
    return Threat(tiles_of(safe_tiles), dealer, value, riichi_turn)


def turns_for(threats, cfg, draws_left=None):
    """Сколько ходов осталось в раздаче против данных угроз.
    После позднего риичи (12+) стена короче: 3 хода вместо 5.
    draws_left: если известна стена, она важнее (не больше её)."""
    rt = [t.riichi_turn for t in threats if getattr(t, "riichi_turn", None)]
    n = cfg.turns_late if rt and max(rt) >= cfg.late_turn else cfg.turns
    if draws_left is not None:
        n = min(n, draws_left)
    return max(1, n)


def _haz(h_next, sh):
    """Риск вылета на сбросе при шантене sh. h_next: число (постоянный) или
    словарь {0: тенпай, 1: 1-шантен, 2: 2+ шантен}."""
    if isinstance(h_next, dict):
        return h_next[min(sh, 2)]
    return h_next


def race(stages, h_first, h_next, turns):
    """Гонка за выигрыш. Возвращает (P_win, P_loss, P_none).
    stages[k]: шанс шага за один ход, последний шаг = победа.
    h_first: риск вылета на сбросе прямо сейчас, h_next: на каждом следующем
    (число — постоянный, словарь — по шантену руки на этой стадии)."""
    n = len(stages)
    s = n - 1                                    # начальный шантен
    state = [0.0] * n
    state[0] = 1.0 - h_first
    loss, win = h_first, 0.0
    for _ in range(turns):
        new = [0.0] * n
        for k in range(n):
            pr = state[k]
            if pr == 0.0:
                continue
            q = stages[k]
            h = _haz(h_next, s - k)              # шантен на стадии k: s - k
            if k == n - 1:
                win += pr * q
                rest = pr * (1.0 - q)
                loss += rest * h
                new[k] += rest * (1.0 - h)
            else:
                loss += pr * h
                new[k + 1] += pr * q * (1.0 - h)
                new[k] += pr * (1.0 - q) * (1.0 - h)
        state = new
    return win, loss, sum(state)


@dataclass
class Row:
    tile: int
    sh: int          # шантен руки после сброса
    form: str        # std / chi / kok: какая форма держит шантен
    uk: int          # укейре (у тенпая это число ждущих плиток)
    p_deal: float    # шанс вылета на самом сбросе
    p_win: float
    p_loss: float
    ev: float
    stages: list = None   # стадии гонки (чтобы маваши не пересчитывал укейре)
    value: float = 0.0    # цена победы этого сброса (хан/фу или override)


@dataclass
class Result:
    hand: str
    rows: list
    base: tuple
    U: int
    cfg: Cfg
    n_threats: int
    decision: str    # attack (угроз нет) / push / fold / mawashi
    tile: int        # что сбросить по решению
    fold_tile: int
    fold_ev: float
    maw_ev: float = None   # EV лучшего маваши (None, если стратегия недоступна)
    maw_tile: int = None   # сброс лучшего маваши
    placement: dict = None   # pt по стратегиям {push, fold, mawashi} (только оорасу)
    placement_ev: float = None   # pt выбранной стратегии (только оорасу)


def mawashi_ev(rows, L, cfg, T):
    """Лучший маваши-сброс: низкая опасность сейчас, форма жива, дальше осторожно.
    Возвращает (ev, row, p_win, p_loss) или (None, None, 0.0, 0.0), если безопасных сбросов нет.
    Прогресс замедлен в k_maw раз (опасные плитки придётся держать),
    риск последующих сбросов — maw_hazard (хоноры/судзи, не генбуцу)."""
    best = (None, None, 0.0, 0.0)
    for r in rows:
        if r.p_deal > cfg.maw_thr:
            continue
        st = [min(0.95, q * cfg.k_maw) for q in r.stages]
        pw, pl, _ = race(st, r.p_deal, cfg.maw_hazard, T)
        ev = pw * r.value - pl * L
        if best[0] is None or ev > best[0]:
            best = (ev, r, pw, pl)
    return best


# ------------------------------------------------------------------
# Placement (П.5, оорасу) — модуль Hark, вшит сюда, чтобы danger_ev.py
# остался одним файлом. Источник: placement/placement.py.
# EV в очках места Tenhou pt (90/45/0/-135) вместо очков.
# ------------------------------------------------------------------
UMA_HOUOU = (90, 45, 0, -135)
# Остаток 1 - p_win - p_loss по исходам из логов Houou (800 игр, 13 989 набл.):
# «я вылетел не-риичи» (2,8%) свёрнут в «третий» (рон не-риичи с меня ≈ рон третьего с риичи).
SPLIT = {"tsumo": 0.312, "draw": 0.222, "third": 0.253, "ron_other": 0.212}


def ranks(scores, kicha):
    """Место каждого (0=1-е) по очкам; равенство — ближе к первому дилеру (kicha)."""
    order = sorted(range(4), key=lambda q: (-scores[q], (q - kicha) % 4))
    r = [0] * 4
    for i, q in enumerate(order):
        r[q] = i
    return r


def final_pt(scores, sticks_left, kicha, me, uma=UMA_HOUOU):
    """Полезность: pt + очки/1000 (Hark, один шаг).
    При равных pt ничья разрешается случайно и часто в пуш; +очки/1000
    отдаёт такие случаи очкам. 1000 очков = 1 pt, место доминирует."""
    s = list(scores)
    r = ranks(s, kicha)
    if sticks_left:
        top = r.index(0)
        s[top] += sticks_left * 1000
    return uma[ranks(s, kicha)[me]] + s[me] / 1000.0


def _apply(scores, deltas):
    return [a + b for a, b in zip(scores, deltas)]


def placement_outcomes(scores, me, oya, rp, sticks, honba, V_me, L, L_third,
                       me_from_riichi=0.5, p_tenpai=0.0, p_other_tenpai=0.3):
    """Список (вес внутри класса, класс, дельты, палочки_остались)."""
    others = [q for q in range(4) if q not in (me, rp)]
    bonus = sticks * 1000 + honba * 300
    out = []
    for frm, w in [(rp, me_from_riichi)] + [(q, (1 - me_from_riichi) / 2) for q in others]:
        d = [0] * 4
        d[me] += V_me + bonus
        d[frm] -= V_me + honba * 300
        out.append((w, "win", d, 0))
    d = [0] * 4
    d[rp] += L + bonus
    d[me] -= L + honba * 300
    out.append((1.0, "loss", d, 0))
    d = [0] * 4
    d[rp] += L + bonus
    for q in (q for q in range(4) if q != rp):
        share = L / 3 if rp == oya else (L / 2 if q == oya else L / 4)
        d[q] -= share + honba * 100
    out.append((1.0, "tsumo", d, 0))
    for q in others:
        d = [0] * 4
        d[rp] += L + bonus
        d[q] -= L + honba * 300
        out.append((0.5, "ron_other", d, 0))
    for q in others:
        d = [0] * 4
        d[q] += L_third + bonus
        d[rp] -= L_third + honba * 300
        out.append((0.5, "third", d, 0))
    o = others
    for t_me, t1, t2 in product((0, 1), repeat=3):
        w = (p_tenpai if t_me else 1 - p_tenpai) * \
            (p_other_tenpai if t1 else 1 - p_other_tenpai) * \
            (p_other_tenpai if t2 else 1 - p_other_tenpai)
        if w == 0:
            continue
        ten = {rp: 1, me: t_me, o[0]: t1, o[1]: t2}
        k = sum(ten.values())
        d = [0] * 4
        if 0 < k < 4:
            for q, t in ten.items():
                d[q] += 3000 // k if t else -3000 // (4 - k)
        out.append((w, "draw", d, sticks))
    return out


def placement_ev(scores, me, oya, rp, kicha, sticks, honba,
                 p_win, p_loss, V_me, L, L_third=5950,
                 uma=UMA_HOUOU, p_tenpai=0.0, split=SPLIT, me_from_riichi=0.5):
    """Матожидание pt для одной стратегии.
    scores: очки ПОСЛЕ ставки риичи; sticks: палочки на столе, включая его ставку."""
    rest = max(0.0, 1.0 - p_win - p_loss)
    cls_p = {"win": p_win, "loss": p_loss}
    for k, v in split.items():
        cls_p[k] = rest * v
    ev = 0.0
    for w, cls, d, left in placement_outcomes(scores, me, oya, rp, sticks, honba,
                                              V_me, L, L_third,
                                              me_from_riichi, p_tenpai):
        ev += cls_p[cls] * w * final_pt(_apply(scores, d), left, kicha, me, uma)
    return ev


def p_tenpai_for(sh):
    """Приор: вероятность быть тенпай к ничьей по шантену после сброса."""
    return 0.9 if sh == 0 else (0.5 if sh == 1 else 0.2)


def evaluate(hand, visible="", threats=(), cfg=None, dora="", yaku="", dealer=False, game=None):
    """EV каждого возможного сброса из руки в 14 плиток.
    visible: все видимые плитки кроме своей руки (реки, мельды, индикаторы доры).
    threats: список Threat. dora, yaku: плитки-дора и ёкухай (строкой в нотации).
    dealer: мы дилер (цена рона x1.5). Цена победы — по хан/фу на каждый сброс,
    если cfg.win_value is None, иначе override для всех сбросов."""
    cfg = cfg or Cfg()
    c = parse(hand)
    aka_hand = parse_aka(hand)
    if sum(c) != 14:
        raise ValueError("нужно 14 плиток, а не %d" % sum(c))
    seen = parse(visible) if visible else [0] * N
    vis = [a + b for a, b in zip(c, seen)]
    if max(vis) > 4:
        raise ValueError("у какой-то плитки больше 4 копий")
    base = shanten_all(c)
    U = 136 - sum(vis)
    dset, yset = tiles_of(dora), tiles_of(yaku)
    tabs = [danger_table(th.safe, vis, dset, yset, riichi_turn=th.riichi_turn) for th in threats]
    L = sum(th.loss(cfg) for th in threats) / len(threats) if threats else 0.0
    h_next = cfg.future_hazard if threats else 0.0
    T = turns_for(threats, cfg)   # одно число для push и fold; стена неизвестна, draws_left не передаём

    rows = []
    for t in range(N):
        if not c[t]:
            continue
        c[t] -= 1
        s = SHANTEN(c)
        uk, _ = ukeire(c, vis)
        std, chi, kok = shanten_all(c)
        aka13 = dict(aka_hand)
        if t in (4, 13, 22) and c[t] + 1 == aka_hand.get(t, 0):
            # сбрасываем пятёрку, а все её копии — ака: ака уходит
            aka13[t] = aka13[t] - 1
            if aka13[t] <= 0:
                del aka13[t]
        wv = hand_value(c, vis, dset, yset, cfg, is_dealer=dealer, aka=aka13)
        c[t] += 1
        smin = min(std, chi, kok)
        form = "chi" if chi == smin else ("std" if std == smin else "kok")
        miss = 1.0
        for tab in tabs:
            miss *= 1.0 - tab[t]
        p_d = 1.0 - miss
        w_fin = uk if s == 0 else cfg.w_final[form]
        q_win = min(0.95, cfg.k_win * w_fin / U)
        q_first = min(0.95, cfg.k_prog * uk / U)
        q_later = min(0.95, cfg.k_prog * min(uk, cfg.uk_later[form]) / U)
        stages = ([q_first] + [q_later] * (s - 1) if s >= 1 else []) + [q_win]
        pw, pl, _ = race(stages, p_d, h_next, T)
        rows.append(Row(t, s, form, uk, p_d, pw, pl, pw * wv - pl * L, stages, wv))
    rows.sort(key=lambda r: -r.ev)

    best = rows[0]
    if not threats:
        return Result(fmt(c), rows, base, U, cfg, 0, "attack", best.tile, best.tile, 0.0)
    safest = min(rows, key=lambda r: (r.p_deal, r.sh, -r.uk))
    fold_pl = race([0.0], safest.p_deal, cfg.fold_hazard, T)[1]
    fold_ev = -fold_pl * L
    maw_ev, maw_row, maw_pw, maw_pl = mawashi_ev(rows, L, cfg, T)

    # --- оорасу: решение по очкам места, а не по очкам ---
    # game = {scores (после ставки риичи), me, oya, rp, kicha, sticks (вкл. ставку),
    #         honba, is_oorasu}. placement_ev берёт p_win/p_loss из race().
    if game and game.get("is_oorasu") and cfg.placement_oorasu:
        pl = placement_ev(game["scores"], game["me"], game["oya"], game["rp"],
                          game["kicha"], game["sticks"], game["honba"],
                          best.p_win, best.p_loss, best.value, L,
                          p_tenpai=p_tenpai_for(best.sh))
        fl = placement_ev(game["scores"], game["me"], game["oya"], game["rp"],
                          game["kicha"], game["sticks"], game["honba"],
                          0.0, fold_pl, 0, L,
                          p_tenpai=p_tenpai_for(safest.sh))
        opts = [(pl, "push", best.tile), (fl, "fold", safest.tile)]
        placement = {"push": pl, "fold": fl, "mawashi": None}
        if maw_row is not None and maw_row.tile != best.tile:
            ml = placement_ev(game["scores"], game["me"], game["oya"], game["rp"],
                              game["kicha"], game["sticks"], game["honba"],
                              maw_pw, maw_pl, maw_row.value, L,
                              p_tenpai=p_tenpai_for(maw_row.sh))
            opts.append((ml, "mawashi", maw_row.tile))
            placement["mawashi"] = ml
        ev, decision, tile = max(opts)
        return Result(fmt(c), rows, base, U, cfg, len(threats), decision, tile,
                      safest.tile, fold_ev, maw_ev,
                      maw_row.tile if maw_row is not None else None,
                      placement, ev)

    options = [(best.ev, "push", best.tile), (fold_ev, "fold", safest.tile)]
    if maw_row is not None and maw_row.tile != best.tile:   # иначе это просто push
        options.append((maw_ev, "mawashi", maw_row.tile))
    ev, decision, tile = max(options)
    return Result(fmt(c), rows, base, U, cfg, len(threats), decision, tile,
                  safest.tile, fold_ev, maw_ev,
                  maw_row.tile if maw_row is not None else None)


def show(res, title="", answer=""):
    c = res.cfg
    if title:
        print("=== %s ===" % title)
    print("рука: %s" % res.hand)
    print("шантен: стандарт %d / чиитойцу %d / кокуши %d" % res.base)
    if min(res.base) < 0:
        print("рука уже собрана: это победа, а не сброс")
        return
    print("невидимых плиток %d, ходов %d, цена победы %s, угроз %d"
          % (res.U, c.turns,
             ("override %d" % c.win_value) if c.win_value is not None else "хан/фу",
             res.n_threats))
    print("сброс  шант  укейре   опасн.   P_win  P_loss     цена        EV")
    for r in res.rows:
        print("%-5s %5d %7d %7.1f%% %6.1f%% %6.1f%% %7.0f %9.0f"
              % (name(r.tile), r.sh, r.uk, r.p_deal * 100, r.p_win * 100,
                 r.p_loss * 100, r.value, r.ev))
    if res.n_threats:
        print("fold: сброс %s, дальше только безопасное, EV %.0f" % (name(res.fold_tile), res.fold_ev))
    if res.placement is not None:
        print("placement pt: " + ", ".join(
            "%s %.1f" % (k, v) for k, v in res.placement.items() if v is not None))
    if res.maw_ev is not None:
        print("mawashi: сброс %s, EV %.0f" % (name(res.maw_tile), res.maw_ev))
    best = res.rows[0]
    if res.decision == "attack":
        print("решение: угроз нет, сбрасывай %s (максимум EV)" % name(res.tile))
    elif res.decision == "push":
        print("решение: PUSH, сбрось %s и продолжай атаку (EV %.0f против fold %.0f)"
              % (name(res.tile), best.ev, res.fold_ev))
    elif res.decision == "mawashi":
        print("решение: MAWASHI, сбрось %s — низкая опасность, форма жива (EV %.0f против push %.0f, fold %.0f)"
              % (name(res.tile), res.maw_ev, best.ev, res.fold_ev))
    else:
        print("решение: FOLD, сбрось %s и дальше только безопасное (fold %.0f против лучшего push %.0f)"
              % (name(res.tile), res.fold_ev, best.ev))
    if answer:
        print("ответ задачи: %s, калькулятор: %s %s"
              % (answer, name(res.tile), "OK" if name(res.tile) == answer else "РАСХОЖДЕНИЕ"))


# ------------------------------------------------------------------ задачи

@dataclass
class Task:
    name: str
    hand: str
    visible: str = ""
    threats: list = field(default_factory=list)
    cfg: Cfg = field(default_factory=Cfg)
    dora: str = ""
    yaku: str = ""
    answer: str = ""
    why: str = ""


RIVER_A = "3z9s4p1z6m8s2s"   # риичи-игрок A (не дилер), последняя плитка = объявление риичи
RIVER_B = "4z8m5m9m3s1p"
RIVER_C = "2z6s9p7m4s5z"
RIVER_ME = "9m1s3p8p5z"      # наши прошлые сбросы
SEEN = RIVER_A + RIVER_B + RIVER_C + RIVER_ME + "3m"   # плюс индикатор доры 3m, дора 4m
HAND_FORK = "11m88m22p57p33s77s1z7z"       # развилка из ответа Gemini: 5 пар
HAND_TENPAI = "11m33m55p99p22s66s1z7z"     # тенпай чиитойцу: 6 пар и две одиночки

T1 = Task(
    "T1 Развилка чиитойцу под риичи", HAND_FORK, SEEN, [threat(RIVER_A)], Cfg(), "4m", "567z", "1z",
    "Рука: стандарт 3, чиитойцу 1, кокуши 9. Любой сброс из пары даёт шантен 2. Из одиночек "
    "5p 7p 7z 1z выбирай 1z: генбуцу против A и укейре 9 против 8 у остальных (у 1z две копии уже видны, "
    "поэтому оставлять её хуже, а сбрасывать лучше). Калькулятор советует fold: после 1z только безопасное.")
T2 = Task(
    "T2 Какую одиночку оставить (угроз нет)", HAND_TENPAI, SEEN, [], Cfg(), "4m", "567z", "1z",
    "Тенпай чиитойцу. Оставляем 7z: ждём 3 копии вместо 2 у 1z.")
T3 = Task(
    "T3 Кан-ловушка", "1111m22p33p44s55s6z7z", "", [], Cfg(), "", "", "1m",
    "Четыре 1m это одна пара, а не две: чиитойцу 1, не 0. Сбрасываем лишнюю 1m, ждём 6z или 7z (укейре 6).")
T4A = Task(
    "T4a Тенпай чиитойцу против риичи, дешёвая рука", HAND_TENPAI, SEEN, [threat(RIVER_A)],
    Cfg(win_value=1600), "4m", "567z", "1z",
    "Те же 1z, но дальше ждать дорого: при цене 1600 калькулятор не пушит, а держит тенпай генбуцу (mawashi) вместо полного фолда.")
T4B = Task(
    "T4b Тенпай чиитойцу против риичи, дорогая рука", HAND_TENPAI, SEEN, [threat(RIVER_A)],
    Cfg(win_value=8000), "4m", "567z", "1z",
    "При цене 8000 (ханеман) ожидание окупается: push.")
TASKS = [T1, T2, T3, T4A, T4B]


def run(task, game=None):
    return evaluate(task.hand, task.visible, task.threats, task.cfg, task.dora, task.yaku,
                    game=game)


# ------------------------------------------------------------------ selftest

def selftest(verbose=True):
    res = {"ok": 0, "n": 0}

    def check(label, cond):
        res["n"] += 1
        res["ok"] += 1 if cond else 0
        if verbose and not cond:
            print("FAIL: " + label)

    P = parse
    # формы руки
    check("S1 развилка: (3, 1, 9)", shanten_all(P(HAND_FORK)) == (3, 1, 9))
    check("S2 19m19p19s1234567z: кокуши 0, стандарт 8",
          shanten(P("19m19p19s1234567z")) == 0 and shanten_standard(P("19m19p19s1234567z")) == 8)
    check("S3 кан-ловушка: чиитойцу 1, не 0", shanten_chiitoi(P("1111m22p33p44s55s6z7z")) == 1)
    check("S4 поправка на виды: 1111m2222p3333s4z -> 6", shanten_chiitoi(P("1111m2222p3333s4z")) == 6)
    check("S5 готовое чиитойцу -1", shanten(P("1133m5599p2266s44z")) == -1)
    check("S6 готовое кокуши -1", shanten(P("119m19p19s1234567z")) == -1)
    check("S7 готовая стандартная -1", shanten_standard(P("123m456p789s11122z")) == -1)
    check("S8 стандартный тенпай 0", shanten(P("123m456p789s1112z")) == 0)
    c = P(HAND_FORK)
    c[0] -= 1
    check("S9 сброс из пары: шантен 2", shanten(c) == 2)
    c = P(HAND_FORK)
    c[13] -= 1   # 5p
    check("S10 сброс одиночки: шантен 1", shanten(c) == 1)
    check("S11 нули в счётчике не ломают виды", shanten_chiitoi([0] * 34) == 6 + 7)
    check("S12 to_dict и parse согласованы", to_dict(P("11m5p")) == {"1m": 2, "5p": 1})

    # модель опасности
    v1 = [1] * 34
    d = danger_table(frozenset(), v1)
    check("D1 генбуцу = 0", danger_table(frozenset({4}), v1)[4] == 0.0)
    check("D2 порядок без суджи: 5 >= 4 > 3 > 2 > 1", d[4] >= d[3] > d[2] > d[1] > d[0])
    check("D3 суджи режет опасность 1m", danger_table(frozenset({3}), v1)[0] < d[0])
    half = danger_table(frozenset({1}), v1)[4]
    full = danger_table(frozenset({1, 7}), v1)[4]
    check("D4 полное суджи < полусуджи < без суджи у 5m", full < half < d[4])
    vk = [1] * 34
    vk[5] = 4
    check("D5 кабе (все 6m видны) режет 5m", danger_table(frozenset(), vk)[4] < d[4])
    hs = []
    for k in (1, 2, 3, 4):
        vh = [1] * 34
        vh[27] = k
        hs.append(danger_table(frozenset(), vh)[27])
    check("D6 честь: больше копий видно, меньше риск, при 4 нуль",
          hs[0] > hs[1] > hs[2] > hs[3] == 0.0)
    two = evaluate(HAND_FORK, SEEN, [threat(RIVER_A), threat("")], Cfg(), "4m", "567z")
    one = evaluate(HAND_FORK, SEEN, [threat(RIVER_A)], Cfg(), "4m", "567z")
    p_two = {r.tile: r.p_deal for r in two.rows}
    p_one = {r.tile: r.p_deal for r in one.rows}
    check("D7 две угрозы опаснее одной", p_two[13] > p_one[13] and p_two[27] > p_one[27])

    # ход риичи доходит до решений: поздний риичи (12+) опаснее раннего
    r_early = evaluate(HAND_FORK, SEEN, [threat(RIVER_A, riichi_turn=5)], Cfg(), "4m", "567z")
    r_late = evaluate(HAND_FORK, SEEN, [threat(RIVER_A, riichi_turn=12)], Cfg(), "4m", "567z")
    p_early = {r.tile: r.p_deal for r in r_early.rows}
    p_late = {r.tile: r.p_deal for r in r_late.rows}
    check("D8 ход риичи доходит до решений: 12+ опаснее 5 (7p, 7z)",
          p_late[15] > p_early[15] and p_late[33] > p_early[33])
    check("D9 turns_for: ранний риичи 5, поздний 3, стена режет, без угроз 5",
          turns_for([threat("", riichi_turn=6)], Cfg()) == 5
          and turns_for([threat("", riichi_turn=13)], Cfg()) == 3
          and turns_for([threat("", riichi_turn=6)], Cfg(), draws_left=2) == 2
          and turns_for([], Cfg()) == 5)

    # маваши
    check("M0 пустые строки -> (None, None, 0, 0)",
          mawashi_ev([], 6000, Cfg(), 5) == (None, None, 0.0, 0.0))
    row_m = Row(0, 1, "std", 5, 0.02, 0.0, 0.0, 0.0, [0.1, 0.2], 3200)
    c_maw = Cfg(k_maw=1.0, maw_hazard=Cfg().future_hazard, maw_thr=0.03)
    pw_m, pl_m, _ = race([0.1, 0.2], 0.02, Cfg().future_hazard, 5)
    check("M1 при k_maw=1 и maw_hazard=future_hazard маваши = push на той же плитке",
          abs(mawashi_ev([row_m], 6000, c_maw, 5)[0] - (pw_m * 3200 - pl_m * 6000)) < 1e-9)
    check("M2 при maw_thr=0 и p_deal>0 стратегия недоступна",
          mawashi_ev([row_m], 6000, Cfg(maw_thr=0.0), 5) == (None, None, 0.0, 0.0))

    # placement (П.5, оорасу): сценарий Hark — push бьёт fold (pt + очки/1000)
    sc = [24300, 26000, 31000, 17700]
    fold_pt = placement_ev(sc, 0, 2, 3, 0, 1, 0, 0.0, 0.05, 0, 6000)
    push_pt = placement_ev(sc, 0, 2, 3, 0, 1, 0, 0.20, 0.15, 2000, 6000)
    check("P1 оорасу: push > fold (цумо риичи и так роняет в 4-е)",
          abs(fold_pt + 37.1) < 1.0 and abs(push_pt + 24.5) < 1.0 and push_pt > fold_pt)
    check("P2 равенство очков: решает порядок от kicha",
          ranks([25000, 25000, 25000, 25000], 2) == [2, 3, 0, 1])
    game = {"scores": sc, "me": 0, "oya": 2, "rp": 3, "kicha": 0,
            "sticks": 1, "honba": 0, "is_oorasu": True}
    r_pl = evaluate(T4A.hand, T4A.visible, T4A.threats, Cfg(placement_oorasu=True),
                    T4A.dora, T4A.yaku, game=game)
    check("P3 evaluate() с game + placement_oorasu: решение по placement EV",
          r_pl.placement is not None and r_pl.placement_ev is not None)

    # хан / фу: цена победы по руке
    yaku = tiles_of("567z")
    check("H1 пинфу+таняо+риичи 3хан 30фу = 3900",
          _score_hand(P("234m345m456p67s55p"), 22, frozenset(), yaku, False, True) == 3900)
    check("H2 та же рука дилером = 5800",
          _score_hand(P("234m345m456p67s55p"), 22, frozenset(), yaku, True, True) == 5800)
    check("H3 +3 доры 5p (одна в 456p + две в паре) = 6 хан, ханеман 12000",
          _score_hand(P("234m345m456p67s55p"), 22, tiles_of("5p"), yaku, False, True) == 12000)
    check("H4 чиитойцу+риичи 3хан 25фу = 3200",
          _score_hand(P("11m22m33p44p55s66s7z"), 33, frozenset(), yaku, False, True) == 3200)
    check("H5 кокуши одиночка = 32000",
          _score_hand(P("19m19p19s1123456z"), 33, frozenset(), yaku, False, True) == 32000)
    check("H6 кокуши 13-стороннее = двойной якуман 64000",
          _score_hand(P("19m19p19s1234567z"), 0, frozenset(), yaku, False, True) == 64000)
    check("H7 без яку = 0 (только дора не считается)",
          _score_hand(P("123m456p789s1122z"), 27, frozenset(), yaku, False, False) == 0)
    check("H8 тенпай чиитойцу T4 = 3200",
          tenpai_value(P("11m33m55p99p22s66s7z"), [1] * 34, tiles_of("4m"), yaku) == 3200)
    # ака-дора
    check("A1 parse_aka: 0m0p0s -> {4,13,22}, без нулей -> {}",
          parse_aka("0m0p0s") == {4: 1, 13: 1, 22: 1} and parse_aka("11m") == {})
    check("A2 ака в руке: пинфу+таняо+риичи+ака 4хан 30фу = 7700",
          _score_hand(P("234m345m456p67s50p"), 22, frozenset(), yaku, False, True, {13: 1}) == 7700)
    vis_a = list(P("234m345m456s46p55s"))
    vis_a[13] += 3   # из 4 пятёрок три видно, живая одна — и это ака
    check("A3 ожидание 5p, живая плита — ака: 3хан 40фу = 5200",
          tenpai_value(P("234m345m456s46p55s"), vis_a, frozenset(), yaku, False, True, {}) == 5200)

    # гонка
    w0 = race([.1], 0, 0, 6)[0]
    w1 = race([.1, .1], 0, 0, 6)[0]
    w2 = race([.1, .1, .1], 0, 0, 6)[0]
    check("R1 больше шагов, меньше шанс победы", w0 > w1 > w2)
    pw, pl, pn = race([.1, .1], .05, .04, 6)
    check("R2 вероятности дают 1", abs(pw + pl + pn - 1) < 1e-9)
    w_dict = race([.1, .1, .1], 0, {0: 0.036, 1: 0.012, 2: 0.005}, 6)
    w_scal = race([.1, .1, .1], 0, 0.046, 6)
    check("R3 hazard по шантену: ниже риск — выше P_win, ниже P_loss",
          w_dict[0] > w_scal[0] and w_dict[1] < w_scal[1])

    # задачи
    r1 = run(T1)
    by1 = {name(r.tile): r for r in r1.rows}
    check("T1 лучший сброс 1z", name(r1.rows[0].tile) == "1z")
    check("T1 опасность 1z = 0", by1["1z"].p_deal == 0.0)
    check("T1 сброс любой пары даёт шантен 2",
          all(by1[k].sh == 2 for k in ("1m", "8m", "2p", "3s", "7s")))
    check("T1 укейре: 9 у 1z, по 8 у 5p 7p 7z",
          by1["1z"].uk == 9 and all(by1[k].uk == 8 for k in ("5p", "7p", "7z")))
    check("T1 порядок опасности: 1z < 7z < 7p < 5p (после калибровки Houou: хоноры x0.4, пенчан/канчан x1.5)",
          by1["1z"].p_deal < by1["7z"].p_deal < by1["7p"].p_deal < by1["5p"].p_deal)
    check("T1 решение fold", r1.decision == "fold" and name(r1.tile) == "1z")
    r2 = run(T2)
    by2 = {name(r.tile): r for r in r2.rows}
    check("T2 сбросить 1z, ждать на 7z (укейре 3 против 2)",
          name(r2.rows[0].tile) == "1z" and by2["1z"].uk == 3 and by2["7z"].uk == 2)
    r3 = run(T3)
    by3 = {name(r.tile): r for r in r3.rows}
    check("T3 кан-ловушка: после 1m шантен 1 (не тенпай), укейре 6, тенпая нет ни в одной строке",
          by3["1m"].sh == 1 and by3["1m"].uk == 6 and all(r.sh >= 1 for r in r3.rows))
    check("T3 инвариант: EV-лучший сброс держит минимальный шантен",
          r3.rows[0].sh == min(r.sh for r in r3.rows))
    ra, rb = run(T4A), run(T4B)
    check("T4 дёшево mawashi (держать тенпай генбуцу), дорого push, сброс везде 1z",
          ra.decision == "mawashi" and rb.decision == "push"
          and name(ra.tile) == "1z" and name(rb.tile) == "1z")

    print("Selftest: %d/%d" % (res["ok"], res["n"]))
    return res["ok"] == res["n"]


def main(argv):
    ok = selftest()
    print()
    show(run(T1), T1.name, T1.answer)
    if "--all" in argv:
        for t in TASKS[1:]:
            print()
            show(run(t), t.name, t.answer)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
