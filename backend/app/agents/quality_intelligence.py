from decimal import Decimal


def has_quality_drift(
    *,
    gold_set_accuracy_pct: Decimal | None,
    iaa_krippendorff_alpha: Decimal | None,
    rework_rate_pct: Decimal | None,
) -> bool:
    return (
        (gold_set_accuracy_pct is not None and gold_set_accuracy_pct < Decimal("95.00"))
        or (iaa_krippendorff_alpha is not None and iaa_krippendorff_alpha < Decimal("0.850"))
        or (rework_rate_pct is not None and rework_rate_pct > Decimal("5.00"))
    )
