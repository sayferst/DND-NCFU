"""Durable conservative inference accounting; unknown requests retain their reservation."""

import json
import os
from decimal import Decimal, InvalidOperation
from pathlib import Path


class SpendJournal:
    def __init__(self, path, prior, cap):
        self.path = Path(path)
        if self.path.exists():
            raise FileExistsError("Use a new journal; carry its final accounted total forward")
        if not all(isinstance(x, Decimal) and x.is_finite() for x in (prior, cap)):
            raise ValueError("Finite decimal amounts required")
        if not 0 <= prior < cap <= 150:
            raise ValueError("The cumulative authorized cap is 150 RUB")
        self.prior, self.cap, self.rows = prior, cap, []
        self._write()

    @property
    def accounted(self):
        return self.prior + sum((Decimal(r["accounted_rub"]) for r in self.rows), Decimal(0))

    def _write(self):
        data = {
            "prior_accounted_rub": str(self.prior),
            "cap_rub": str(self.cap),
            "accounted_total_rub": str(self.accounted),
            "rows": self.rows,
        }
        temporary = self.path.with_suffix(".temporary")
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, self.path)

    def reserve(self, identifier, bound):
        if not isinstance(bound, Decimal) or not bound.is_finite() or bound <= 0:
            raise ValueError("A positive verified upper bound is required")
        if any(r["id"] == identifier for r in self.rows):
            raise ValueError("Duplicate request; automatic retries are prohibited")
        if self.accounted + bound > self.cap:
            raise ValueError("Cumulative authorized budget exhausted")
        self.rows.append(
            {
                "id": identifier,
                "bound_rub": str(bound),
                "accounted_rub": str(bound),
                "settled": False,
            }
        )
        self._write()

    def settle(self, identifier, usage, quote):
        row = next(r for r in self.rows if r["id"] == identifier)
        if row["settled"]:
            raise ValueError("Request already settled")
        # The public token quote alone underestimated actual RouterAI usage.cost.
        # Release a reservation only with valid cost AND usage; retain the larger
        # of the reported ruble charge and the uncached token estimate.
        if not isinstance(usage, dict):
            return
        counts = [usage.get(k) for k in ("prompt_tokens", "completion_tokens")]
        if not all(type(n) is int and 0 <= n <= 10_000_000 for n in counts):
            return
        if not counts[0]:
            return
        raw_cost = usage.get("cost")
        if isinstance(raw_cost, bool) or not isinstance(raw_cost, (str, int, float, Decimal)):
            return
        try:
            reported = Decimal(str(raw_cost))
        except InvalidOperation:
            return
        if not reported.is_finite() or reported < 0:
            return
        token_quote = (
            Decimal(counts[0]) * quote.prompt_rub + Decimal(counts[1]) * quote.completion_rub
        )
        charge = max(reported, token_quote)
        row.update(reported_cost_rub=str(reported), token_quote_rub=str(token_quote))
        if charge > Decimal(row["bound_rub"]):
            # Persist the unexpected overrun and stop; never conceal a quote mismatch.
            row.update(accounted_rub=str(charge), status="QUOTE_BOUND_EXCEEDED")
            self._write()
            raise ValueError("Provider reported cost exceeded the verified request bound")
        row.update(accounted_rub=str(charge), settled=True)
        self._write()
