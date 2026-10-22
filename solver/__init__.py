"""世帯条件から栄養制約付きの整数計画で備蓄量を求める。"""

from .model import InfeasiblePlanError, solve

__all__ = ["solve", "InfeasiblePlanError"]
