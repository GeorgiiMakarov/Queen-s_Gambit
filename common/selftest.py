#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""common.selftest — селфтест: набор проверок, итог N/N, FAIL по имени."""


class Check:
    def __init__(self):
        self.ok = 0
        self.n = 0

    def __call__(self, label, cond):
        self.n += 1
        self.ok += 1 if cond else 0
        if not cond:
            print("FAIL:", label)
        return bool(cond)

    def summary(self, name="Selftest"):
        print("%s: %d/%d" % (name, self.ok, self.n))
        return self.ok == self.n
