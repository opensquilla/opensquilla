import pytest
from src.app import build_charge_payload, normalize_amount


def test_normalize_amount_rejects_negative() -> None:
    with pytest.raises(ValueError):
        normalize_amount(-1)


def test_build_charge_payload() -> None:
    assert build_charge_payload("user-1", 42) == {
        "user_id": "user-1",
        "amount": 42,
        "currency": "USD",
    }
