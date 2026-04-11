"""
Risk: API Quota Tracker
Persists daily API call counts and enforces time-based windows to
distribute calls across active market hours instead of burning quota
in the first cycles of the day.

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

DAILY_LIMITS: dict[str, int] = {
    # Gemini free tier: each model has its own separate quota
    # Combined chain: 2.5-flash(20) + 2.5-flash-lite(20) + 2.0-flash(200) + 1.5-flash(1500)
    # Tracker counts total calls across all models — conservative limit is 20 (worst model)
    # In practice the fallback chain means we have ~1740 combined, but we cap at 50
    # to avoid burning through all models in a single day
    "gemini_flash":  50,
    "gemini_pro":    50,
    "alpha_vantage": 25,   # 25 calls/day → 8 reports max (3 calls each)
}

# UTC hours when Alpha Vantage calls are permitted.
# Chosen to coincide with key market transitions (PT = UTC+1 summer):
#   00 UTC (01 PT) — Asian open
#   07 UTC (08 PT) — Before European open
#   09 UTC (10 PT) — European session active
#   13 UTC (14 PT) — US pre-market
#   14 UTC (15 PT) — NYSE open
#   17 UTC (18 PT) — European close / US midday
#   20 UTC (21 PT) — US session active
#   21 UTC (22 PT) — Pre-NYSE close
# 8 windows × 3 calls = 24 calls ≤ 25 daily limit
ALLOWED_WINDOWS: dict[str, set] = {
    "alpha_vantage": {0, 7, 9, 13, 14, 17, 20, 21},
}

SAFETY_PCT = 0.90


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _now_ts() -> float:
    return _now_utc().timestamp()


def _next_window(current_hour: int, windows: set) -> int:
    """Returns the next allowed UTC hour after current_hour."""
    future = sorted(h for h in windows if h > current_hour)
    return future[0] if future else sorted(windows)[0]


class QuotaTracker:
    """
    Persistent daily quota tracker. Survives restarts.

    Enforces per service:
      1. Daily call count  — never exceed DAILY_LIMITS × SAFETY_PCT
      2. Active windows    — calls only permitted at specific UTC hours
                             (one use per window per day)
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
        return {"date": date.today().isoformat(), "counts": {}, "last_used": {}, "used_windows": {}}

    def _save(self) -> None:
        QUOTA_FILE.parent.mkdir(parents=True, exist_ok=True)
        self._state.setdefault("last_used", {})
        self._state.setdefault("used_windows", {})
        QUOTA_FILE.write_text(
            json.dumps(self._state, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

    def _reset_if_new_day(self) -> None:
        today = date.today().isoformat()
        if self._state.get("date") != today:
            self._state = {
                "date":         today,
                "counts":       {},
                "last_used":    {},
                "used_windows": {},   # resets daily — each window available once/day
            }
            self._save()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def check_and_consume(self, service: str, units: int = 1) -> tuple:
        """
        Checks quota + active window, then consumes N calls if both pass.

        Args:
            service: Service name (e.g. "alpha_vantage").
            units:   Number of API calls to consume (default 1).

        Returns:
            (allowed: bool, reason: str)
        """
        self._state.setdefault("last_used", {})
        self._state.setdefault("used_windows", {})

        limit = DAILY_LIMITS.get(service)
        if limit is None:
            return True, ""  # Unknown service — no limit enforced

        now     = _now_utc()
        windows = ALLOWED_WINDOWS.get(service)

        # ── 1. Active window check ────────────────────────────────────
        if windows:
            current_hour = now.hour

            if current_hour not in windows:
                next_h = _next_window(current_hour, windows)
                # How many minutes until next window
                if next_h > current_hour:
                    wait_min = (next_h - current_hour) * 60 - now.minute
                else:  # wraps to next day
                    wait_min = (24 - current_hour + next_h) * 60 - now.minute
                return False, (
                    f"{service} outside active window — "
                    f"next at {next_h:02d}:00 UTC (~{wait_min}min)"
                )

            # One use per window per day
            used_key = f"{service}_{current_hour:02d}"
            if self._state["used_windows"].get(used_key):
                next_h   = _next_window(current_hour, windows)
                wait_min = (
                    (next_h - current_hour) * 60 - now.minute
                    if next_h > current_hour
                    else (24 - current_hour + next_h) * 60 - now.minute
                )
                return False, (
                    f"{service} window {current_hour:02d}:00 UTC already used — "
                    f"next at {next_h:02d}:00 UTC (~{wait_min}min)"
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
        self._state["last_used"][service] = now.timestamp()
        if windows:
            self._state["used_windows"][f"{service}_{now.hour:02d}"] = True
        self._save()
        return True, ""

    def mark_exhausted(self, service: str) -> None:
        """Marks a service as quota-exhausted (real API returned rate-limit error)."""
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

    def summary(self) -> dict:
        self._state.setdefault("used_windows", {})
        now = _now_utc()
        out = {"date": self._state["date"], "usage": {}}
        for service, limit in DAILY_LIMITS.items():
            windows    = ALLOWED_WINDOWS.get(service)
            in_window  = windows is not None and now.hour in windows
            used_key   = f"{service}_{now.hour:02d}"
            win_used   = bool(self._state["used_windows"].get(used_key))
            next_h     = _next_window(now.hour, windows) if windows else None

            out["usage"][service] = {
                "used":        self._state["counts"].get(service, 0),
                "limit":       limit,
                "remaining":   self.remaining(service),
                "in_window":   in_window,
                "window_used": win_used,
                "next_window": f"{next_h:02d}:00 UTC" if next_h is not None else None,
            }
        return out
