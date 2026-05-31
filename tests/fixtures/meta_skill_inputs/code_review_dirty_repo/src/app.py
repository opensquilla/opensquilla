def normalize_amount(amount: int) -> int:
    if amount < 0:
        raise ValueError("amount must be non-negative")
    return amount


def build_charge_payload(user_id: str, amount: int) -> dict[str, object]:
    return {
        "user_id": user_id,
        "amount": normalize_amount(amount),
        "currency": "USD",
    }
