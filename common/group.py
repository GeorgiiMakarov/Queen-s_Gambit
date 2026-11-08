#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.group: групповая оценка пилота. Единица анализа спортсмен.

Основной критерий плана пилота это интервал «по группе». Здесь он считается так: по каждому
спортсмену берётся разность разностей (chess/pilot_analysis.py), дальше среднее по спортсменам и
t-интервал с n-1 степенями свободы. Задачи спортсменов НЕ складываются в одну выборку: пул задач
сузил бы интервал и не учёл бы, что эффект у разных людей разный.

Вердикт (заранее заданный delta, доля, например 0.05):
  worsening              интервал целиком ниже нуля
  confirmed              интервал целиком выше нуля (критерий успеха плана)
  confirmed_below_delta  то же, но верхняя граница ниже delta: эффект есть, но малый
  excluded_above_delta   интервал не содержит нуля, но эффект больше delta исключён
                         (информативный ноль). Без delta этого исхода нет.
  inconclusive           иначе: при таком объёме данных ответа нет
  insufficient_athletes  проанализировано меньше требуемого числа спортсменов (не меньше MIN_ATHLETES, и не
                         меньше study.athletes_min_for_group_ci протокола): группового ответа нет
"""
import math

T975 = {1: 12.706, 2: 4.303, 3: 3.182, 4: 2.776, 5: 2.571, 6: 2.447, 7: 2.365, 8: 2.306,
        9: 2.262, 10: 2.228, 11: 2.201, 12: 2.179, 13: 2.160, 14: 2.145, 15: 2.131,
        16: 2.120, 17: 2.110, 18: 2.101, 19: 2.093, 20: 2.086, 25: 2.060, 30: 2.042,
        40: 2.021, 60: 2.000, 120: 1.980}
MIN_ATHLETES = 3

GLOSS = {
    "worsening": "ухудшение: интервал целиком ниже нуля",
    "confirmed": "подтверждено: интервал целиком выше нуля",
    "confirmed_below_delta": "подтверждено, но эффект меньше delta: интервал выше нуля и ниже delta",
    "excluded_above_delta": "эффект больше delta исключён: значимого эффекта нет",
    "inconclusive": "ответа нет при таком объёме данных",
    "insufficient_athletes": "проанализировано меньше требуемого числа спортсменов: группового ответа нет",
}


def t_crit(df):
    """Двусторонний 95%-й квантиль Стьюдента; между табличными df линейная интерполяция."""
    if df in T975:
        return T975[df]
    keys = sorted(T975)
    if df > keys[-1]:
        return 1.960
    lo = max(k for k in keys if k < df)
    hi = min(k for k in keys if k > df)
    return T975[lo] + (T975[hi] - T975[lo]) * (df - lo) / (hi - lo)


def verdict(ci_low, ci_high, delta=None):
    if ci_high < 0:
        return "worsening"
    if ci_low > 0:
        return "confirmed_below_delta" if (delta is not None and ci_high < delta) else "confirmed"
    if delta is not None and ci_high < delta:
        return "excluded_above_delta"
    return "inconclusive"


def athlete_t(estimates, min_athletes=MIN_ATHLETES):
    """dict(method, n, mean, se, ci_low, ci_high) или None, если спортсменов меньше требуемого числа.
    Требуемое число не бывает меньше MIN_ATHLETES, как бы его ни задали."""
    n = len(estimates)
    if n < max(min_athletes, MIN_ATHLETES):
        return None
    m = sum(estimates) / n
    var = sum((x - m) ** 2 for x in estimates) / (n - 1)
    se = math.sqrt(var / n)
    h = t_crit(n - 1) * se
    return {"method": "athlete_t", "n": n, "mean": m, "se": se, "ci_low": m - h, "ci_high": m + h}


def group_did(estimates, ses=None, delta=None, min_athletes=MIN_ATHLETES):
    """Групповой итог по оценкам разности разностей спортсменов (доли, не проценты).
    ses принимается для совместимости с методами, которым нужны стандартные ошибки; athlete_t
    их не использует. min_athletes это требуемое протоколом число проанализированных спортсменов.
    Всегда возвращает dict с ключами method, n, verdict; при достаточном числе спортсменов ещё mean, se,
    ci_low, ci_high; при недостаточном ещё min_athletes (сколько требовалось)."""
    est = list(estimates)
    g = athlete_t(est, min_athletes)
    if g is None:
        return {"method": "athlete_t", "n": len(est), "verdict": "insufficient_athletes",
                "min_athletes": max(min_athletes, MIN_ATHLETES)}
    g["verdict"] = verdict(g["ci_low"], g["ci_high"], delta)
    return g
