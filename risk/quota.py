"""
Risk: API Quota Tracker
Persists daily API call counts to prevent exhausting limited quotas.

Currently tracked:
  - gemini_pro:   100 req/day (free tier) — ManagerAgent
  - gemini_flash: 1500 req/day (free tier) — InvestigatorAgent
  - alpha_vantage: 25 req/day (free tier)

Resets counts automatically at midnight UTC.
"""

import json
from datetime import date
from pathlib import Path

QUOTA_FILE = Path(__file__).parent.parent / "memory" / "quota-state.json"

# Daily limits per service.
# NOTE: alpha_vantage limit is in real API calls (not reports).
# get_technical_report() uses 3 calls per ticker — check_and_consume() is
# called with units=3 so this limit is properly respected.
DAILY_LIMITS: dict[str, int] = {
    "gemini_pro":    100,
    "gemini_flash":  1500,
    "alpha_vantage": 25,   # 25 real calls/day → ~8 full reports (3 calls each)
}

# Safety threshold — stop at this % of limit to leave headroom
SAFETY_PCT = 0.90


class QuotaTracker:
    """
    Persistent daily quota tracker. Survives restarts.
    Call check_and_consume() before each API call.
    """

    def __init__(self):
        self._state = self._load()
        self._reset_if_new_day()

    def _load(self) -> dict:
        if QUOTA_FILE.exists():
            try:
                data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
                # Validate structure — if corrupt, reset (safe side)
                if isinstance(data.get("counts"), dict) and isinstance(data.get("date"), str):
                    return data
                print("[QuotaTracker] WARNING — corrupt quota file, resetting to zero")
            except Exception:
                print("[QuotaTracker] WARNING — could not read quota file, resetting to zero")
        return {"date": date.today().isoformat(), "counts": {}}

    def _save(self) -> None:
        QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        QUOTA_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _reset_if_new_day(self) -> None:
        today = date.today().isoformat()
        if self._state.get("date") != today:
            self._state = {"date": today, "counts": {}}
            self._save()

    def check_and_consume(self, service: str, units: int = 1) -> tuple[bool, str]:
        """
        Checks quota and consumes N calls if available.

        Args:
            service: Service name (e.g. "gemini_pro").
            units:   Number of API calls to consume (default 1).

        Returns:
            (allowed: bool, reason: str)
        """
        limit = DAILY_LIMITS.get(service)
        if limit is None:
            return True, ""  # Unknown service — no limit enforced

        current = self._state["counts"].get(service, 0)

        # Hard cap — never exceed 100% regardless of any bug
        if current >= limit:
            return False, (
                f"{service} HARD LIMIT reached ({current}/{limit}) — "
                f"no more calls allowed today"
            )

        # Safety threshold — stop early to leave headroom for manual use
        threshold = int(limit * SAFETY_PCT)
        if current >= threshold:
            remaining = limit - current
            return False, (
                f"{service} safety threshold reached "
                f"({current}/{limit} used, {remaining} reserved)"
            )

        self._state["counts"][service] = current + units
        self._save()
        return True, ""

    def remaining(self, service: str) -> int:
        """Returns remaining calls for a service today."""
        limit = DAILY_LIMITS.get(service, 0)
        used = self._state["counts"].get(service, 0)
        return max(0, limit - used)

    def summary(self) -> dict:
        return {
            "date": self._state["date"],
            "usage": {
                service: {
                    "used":      self._state["counts"].get(service, 0),
                    "limit":     limit,
                    "remaining": self.remaining(service),
                }
                for service, limit in DAILY_LIMITS.items()
            },
        }
