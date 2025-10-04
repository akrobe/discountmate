# Tiny synthetic model for discount recommendation
import numpy as np
from sklearn.tree import DecisionTreeRegressor

TIERS = ["bronze", "silver", "gold", "platinum"]
TIER_INDEX = {t:i for i,t in enumerate(TIERS)}

def _synthetic_training_data(n=400, seed=42):
    rng = np.random.default_rng(seed)
    totals = rng.uniform(5, 500, size=n)      # basket total
    items  = rng.integers(1, 30, size=n)      # number of items
    tiers  = rng.integers(0, 4, size=n)       # 0..3
    # heuristic target: more total/items/tier → higher discount, plus noise
    y = (totals/1000.0) + (items/200.0) + (tiers*0.05) + rng.normal(0, 0.01, size=n)
    y = np.clip(y, 0.0, 0.5)
    X = np.column_stack([totals, items, tiers])
    return X, y

class DiscountModel:
    def __init__(self):
        X, y = _synthetic_training_data()
        self.model = DecisionTreeRegressor(max_depth=4, random_state=7)
        self.model.fit(X, y)

    def predict(self, total: float, items: int, tier: str) -> float:
        ti = TIER_INDEX.get(str(tier).lower(), 0)
        pred = float(self.model.predict([[total, items, ti]])[0])
        return float(max(0.0, min(pred, 0.5)))