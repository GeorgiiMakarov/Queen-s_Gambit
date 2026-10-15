#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""check_logs.py — проверить раскладку логов Tenhou (логи НЕ в репо).
Ожидается:
  mahjong/raw_logs/logs/*.xml   — 400 игр (train)
  mahjong/raw_logs/logs2/*.xml  — 400 игр (test)
Сами логи положи сам (получены отдельно, в репо не кладутся)."""
import glob
import os
import sys


def main():
    base = os.path.join(os.path.dirname(__file__), "raw_logs")
    n1 = len(glob.glob(os.path.join(base, "logs", "*.xml")))
    n2 = len(glob.glob(os.path.join(base, "logs2", "*.xml")))
    print("logs: %d, logs2: %d (ожидается 400 + 400)" % (n1, n2))
    ok = (n1 == 400 and n2 == 400)
    print("OK" if ok else "логи не на месте — положи XML по раскладке выше")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
