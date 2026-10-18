#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.holdout — случайный холдаут по хешу ключа.
Детерминированный сплит (тот же ключ всегда в том же сете), как logs/logs2.
Сплит по рейтингу/сложности — НЕ холдаут: он проверяет переход к более
трудным примерам, а не обобщение. Холдаут — случайный, с одинаковым
распределением в train и test."""
import hashlib


def split_label(key, train_frac=0.5):
    """Метка сета для ключа: "train" или "test". Точное целое md5 mod 1000, без float.
    Эту же функцию в точности повторяет JS (chess/index.html, hashSet): проверяется
    общими векторами common/golden/holdout_vectors.json."""
    h = int(hashlib.md5(str(key).encode()).hexdigest(), 16) % 1000 / 1000.0
    return "train" if h < train_frac else "test"


def hash_split(items, key_fn, train_frac=0.5):
    """Разделить items на (train, test) по хешу ключа.
    key_fn(item) -> str: ключ (напр. PuzzleId, game_id)."""
    train, test = [], []
    for it in items:
        (train if split_label(key_fn(it), train_frac) == "train" else test).append(it)
    return train, test
