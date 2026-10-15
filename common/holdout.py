#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.holdout — случайный холдаут по хешу ключа.
Детерминированный сплит (тот же ключ всегда в том же сете), как logs/logs2.
Сплит по рейтингу/сложности — НЕ холдаут: он проверяет переход к более
трудным примерам, а не обобщение. Холдаут — случайный, с одинаковым
распределением в train и test."""
import hashlib


def hash_split(items, key_fn, train_frac=0.5):
    """Разделить items на (train, test) по хешу ключа.
    key_fn(item) -> str: ключ (напр. PuzzleId, game_id)."""
    train, test = [], []
    for it in items:
        h = int(hashlib.md5(str(key_fn(it)).encode()).hexdigest(), 16) % 1000 / 1000.0
        (train if h < train_frac else test).append(it)
    return train, test
