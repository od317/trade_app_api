# returns/utils.py
from __future__ import annotations

from typing import Dict
from .models import ReturnRequest, ReturnedProduct

# Default weights (you can override from settings if you want)
DEFAULT_PENALTY_WEIGHTS: Dict[str, int] = {
    "damaged": 5,
    "missing_parts": 3,
    "unsaleable": 7,
    # NOTE: we do NOT penalize: "new", "open_box", "used"
}

def compute_penalty_points(return_request: ReturnRequest, weights: Dict[str, int] | None = None) -> int:
    """
    Calculate penalty points for a given ReturnRequest based on ReturnedProduct statuses.
    Only penalizes 'damaged', 'missing_parts', and 'unsaleable'.
    Points are proportional to quantities.

    Example:
      damaged: 2 units * 5 pts  = 10
      missing_parts: 1 * 3 pts  = 3
      unsaleable: 0 * 7 pts     = 0
      => total = 13
    """
    weights = weights or DEFAULT_PENALTY_WEIGHTS

    total = 0
    # Pull all classifications recorded for this request
    rp_qs = ReturnedProduct.objects.filter(return_request=return_request)

    for rp in rp_qs:
        status_code = rp.status
        qty = int(rp.quantity or 0)
        if qty <= 0:
            continue
        # apply weight only for penalized statuses
        weight = weights.get(status_code)
        if weight:
            total += qty * int(weight)

    return total
