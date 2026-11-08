#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.protocol: чтение замороженного протокола пилота и привязка анализа к нему.

Протокол это JSON. Его хеш (sha256 от канонического JSON: ключи по алфавиту, без пробелов) и
хеш кода анализа (sha256 по файлам из analysis.code_files, путь и содержимое) печатаются в отчёте.
Если протокол не заморожен (остались TODO в нужных полях) или код анализа изменён после заморозки,
resolve возвращает ошибки, и chess/pilot_analysis.py отказывается считать.
"""
import hashlib
import json
import os

DEFAULT_CODE_FILES = ["chess/pilot_analysis.py", "chess/session.py", "common/stats.py", "common/group.py",
                      "common/protocol.py", "common/calibration.py", "common/holdout.py"]


def canonical(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def sha256_of(obj):
    return hashlib.sha256(canonical(obj).encode("utf-8")).hexdigest()


def load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def is_todo(v):
    return v is None or (isinstance(v, str) and (v.strip() == "" or v.strip().startswith("TODO")))


def code_sha256(root, files):
    h = hashlib.sha256()
    for rel in files:
        with open(os.path.join(root, rel), "rb") as f:
            data = f.read()
        h.update(rel.encode("utf-8") + b"\0" + data + b"\0")
    return h.hexdigest()


def _get(obj, path):
    cur = obj
    for key in path.split("."):
        if not isinstance(cur, dict) or key not in cur:
            return None
        cur = cur[key]
    return cur


def resolve(path, root):
    """(cfg, errors). cfg: protocol_sha256, code_sha256, cutoff, k, min_n, delta_pp, sensitivity_k,
    athletes_min (требуемое число проанализированных спортсменов для группового интервала)."""
    try:
        obj = load(path)
    except Exception as e:      # noqa: BLE001
        return None, ["протокол не читается: %r" % (e,)]
    errors = []
    cutoff = _get(obj, "study.phase_dates.cutoff_iso")
    k = _get(obj, "analysis.weak_themes_k")
    min_n = _get(obj, "analysis.min_n_theme_on_A")
    sens = _get(obj, "analysis.sensitivity_k")
    delta = _get(obj, "decision.delta_pp")
    ath_min = _get(obj, "study.athletes_min_for_group_ci")
    want_code = _get(obj, "analysis.script_sha256")
    files = _get(obj, "analysis.code_files") or DEFAULT_CODE_FILES
    if is_todo(cutoff) or not isinstance(cutoff, str):
        errors.append("study.phase_dates.cutoff_iso не заполнен")
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        errors.append("analysis.weak_themes_k должно быть целым числом")
    if not isinstance(min_n, int) or isinstance(min_n, bool) or min_n < 1:
        errors.append("analysis.min_n_theme_on_A должно быть целым числом")
    if not (isinstance(sens, list) and sens and all(isinstance(x, int) and not isinstance(x, bool) for x in sens)):
        errors.append("analysis.sensitivity_k должно быть непустым списком целых")
    if isinstance(delta, bool) or not isinstance(delta, (int, float)):
        errors.append("decision.delta_pp не заполнено (число в процентных пунктах)")
    if isinstance(ath_min, bool) or not isinstance(ath_min, int) or ath_min < 3:
        errors.append("study.athletes_min_for_group_ci должно быть целым числом не меньше 3")
    if is_todo(want_code) or not isinstance(want_code, str):
        errors.append("analysis.script_sha256 не заполнен (хеш кода анализа)")
    have_code = None
    try:
        have_code = code_sha256(root, files)
    except OSError as e:
        errors.append("не удалось прочитать файлы кода из analysis.code_files: %r" % (e,))
    if have_code and isinstance(want_code, str) and not is_todo(want_code) and want_code != have_code:
        errors.append("код анализа изменён после заморозки протокола: в протоколе %s, фактически %s"
                      % (want_code, have_code))
    if errors:
        return None, errors
    return {"protocol_sha256": sha256_of(obj), "code_sha256": have_code, "cutoff": cutoff, "k": k,
            "min_n": min_n, "delta_pp": float(delta), "sensitivity_k": list(sens),
            "athletes_min": ath_min}, []
