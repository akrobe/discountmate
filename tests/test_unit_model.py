from app.model import DiscountModel

def test_basic_monotonicity():
    m = DiscountModel()
    d_low  = m.predict(50,  2, "bronze")
    d_high = m.predict(300, 10, "gold")
    assert 0.0 <= d_low <= 0.5
    assert 0.0 <= d_high <= 0.5
    assert d_high >= d_low  # more spend/items/tier → higher or equal discount