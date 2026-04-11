"""
Risk: API Quota Tracker
Persists daily API call counts AND last-used timestamps to prevent
exhausting limited quotas and to spread calls evenly across the day.

Currently tracked:
  - gemini_pro:    100 req/day (free tier) — ManagerAgent
  - gemini_flash: 1500 req/day (free tier) — InvestigatorAgent
  - alpha_vantage:  25 req/day (free tier) — 3 calls/ticker

Resets counts automatically at midnight UTC.
"""

import json
import math
from datetime import date, datetime, timezone
from pathlib import Path

QUOTA_FILE = Path(__file__).parent.parent / "memory" / "quota-state.json"

# Daily limits per service.
# alpha_vantage: limit is real API calls. get_technical_report() uses 3
# calls/ticker — check_and_consume() is called with units=3.
DAILY_LIMITS: dict[str, int] = {
    "gemini_pro":    100,
    "gemini_flash":  1500,
    "alpha_vantage": 25,   # 25 calls/day → ~8 full reports (3 each)
}

# Minimum seconds between consecutive uses of each service.
# Ensures calls are spread evenly across 24h instead of burning the
# quota in the first few cycles.
#
# alpha_vantage: floor(25 / 3) = 8 max reports/day
#   → 24h / 8 = 3h minimum between reports (10 800s)
# gemini_flash/pro: limits are generous — no interval enforced (0)
MIN_INTERVAL_SECONDS: dict[str, int] = {
    "gemini_pro":    0,
    "gemini_flash":  0,
    "alpha_vantage": 10_800,  # 3 hours
}

# Safety threshold — stop at this % of daily limit to leave headroom
SAFETY_PCT = 0.90


def _now_ts() -> float:
    return datetime.now(timezone.utc).timestamp()


class QuotaTracker:
    """
    Persistent daily quota tracker. Survives restarts.

    Enforces two independent guards per service:
      1. Daily call count  — never exceed DAILY_LIMITS × SAFETY_PCT
      2. Minimum interval  — never call again before MIN_INTERVAL_SECONDS
    """

    def __init__(self):
        self._state = self._load()
        self._reset_if_new_day()

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self) -> dict:
        if QUOTA_FILE.exists():
            try:
                data = json.loads(QUOTA_FILE.read_text(encoding="utf-8"))
                if isinstance(data.get("counts"), dict) and isinstance(data.get("date"), str):
                    return data
                print("[QuotaTracker] WARNING — corrupt quota file, resetting")
            except Exception:
                print("[QuotaTracker] WARNING — could not read quota file, resetting")
        return {"date": date.today().isoformat(), "counts": {}, "last_used": {}}

    def _save(self) -> None:
        QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        # Ensure both keys always exist
        self._state.setdefault("last_used", {})
        QUOTA_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _reset_if_new_day(self) -> None:
        today = date.today().isoformat()
        if self._state.get("date") != today:
            # Preserve last_used across midnight so interval guard works correctly
            last_used = self._state.get("last_used", {})
            self._state = {"date": today, "counts": {}, "last_used": last_used}
            self._save()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_consume(self, service: str, units: int = 1) -> tuple:
        """
        Checks quota + interval, then consumes N calls if both pass.

        Args:
            service: Service name (e.g. "alpha_vantage").
            units:   Number of API calls to consume (default 1).

        Returns:
            (allowed: bool, reason: str)
        """
        self._state.setdefault("last_used", {})
        limit = DAILY_LIMITS.get(service)

        if limit is None:
            return True, ""  # Unknown service — no limit enforced

        now = _now_ts()

        # ── 1. Minimum interval check ─────────────────────────────────
        min_interval = MIN_INTERVAL_SECONDS.get(service, 0)
        if min_interval > 0:
            last_ts = self._state["last_used"].get(service, 0)
            elapsed = now - last_ts
            if elapsed < min_interval:
                wait_min = math.ceil((min_interval - elapsed) / 60)
                return False, (
                    f"{service} rate-spaced — next use in {wait_min}min "
                    f"(interval: {min_interval//3600}h)"
                )

        # ── 2. Daily count check ──────────────────────────────────────
        current = self._state["counts"].get(service, 0)

        if current >= limit:
            return False, f"{service} daily limit reached ({current}/{limit})"

        threshold = int(limit * SAFETY_PCT)
        if current >= threshold:
            remaining = limit - current
            return False, (
                f"{service} safety threshold reached "
                f"({current}/{limit} used, {remaining} reserved)"
            )

        # ── 3. Consume ────────────────────────────────────────────────
        self._state["counts"][service] = current + units
        self._state["last_used"][service] = now
        self._save()
        return True, ""

    def mark_exhausted(self, service: str) -> None:
        """
        Marks a service as quota-exhausted for today.
        Called when the real API returns a rate-limit error.
        """
        limit = DAILY_LIMITS.get(service)
        if limit is not None:
            self._state.setdefault("last_used", {})
            self._state["counts"][service] = limit
            self._state["last_used"][service] = _now_ts()
            self._save()

    def remaining(self, service: str) -> int:
        """Returns remaining calls for a service today."""
        limit = DAILY_LIMITS.get(service, 0)
        used  = self._state["counts"].get(service, 0)
        return max(0, limit - used)

    def next_available_in(self, service: str) -> int:
        """
        Returns seconds until the service is available again.
        Considers both interval and daily limit (0 if already available).
        """
        self._state.setdefault("last_used", {})
        min_interval = MIN_INTERVAL_SECONDS.get(service, 0)
        if min_interval == 0:
            return 0
        last_ts = self._state["last_used"].get(service, 0)
        wait = min_interval - (_now_ts() - last_ts)
        return max(0, int(wait))

    def summary(self) -> dict:
        self._state.setdefault("last_used", {})
        out = {"date": self._state["date"], "usage": {}}
        for service, limit in DAILY_LIMITS.items():
            wait_s = self.next_available_in(service)
            out["usage"][service] = {
                "used":           self._state["counts"].get(service, 0),
                "limit":          limit,
                "remaining":      self.remaining(service),
                "next_avail_min": round(wait_s / 60, 1) if wait_s else 0,
            }
        return out
