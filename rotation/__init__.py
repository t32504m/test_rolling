"""ソルバーの結果から、12か月の消費の割り振りを決める（Issue #22）。

使い方は rotation/README.md を参照。
"""

from .allocate import MONTHS, allocate, build_plan

__all__ = ["MONTHS", "allocate", "build_plan"]
