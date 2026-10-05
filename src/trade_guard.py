from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class TradeGuardState:
    last_side: str = "FLAT"  # LONG / SHORT / FLAT
    last_flat_ts: float = 0.0
    last_trade_ts: float = 0.0


class TradeGuard:
    """Anti-whipsaw: flip cooldown + max step size toward larger risk."""

    def __init__(
        self,
        path: Path,
        flip_cooldown_seconds: int = 7200,
        max_step_fraction: float = 0.15,
    ) -> None:
        self.path = path
        self.flip_cooldown_seconds = flip_cooldown_seconds
        self.max_step_fraction = max_step_fraction
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.state = TradeGuardState()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self.state = TradeGuardState(
                last_side=str(raw.get("last_side", "FLAT")),
                last_flat_ts=float(raw.get("last_flat_ts", 0)),
                last_trade_ts=float(raw.get("last_trade_ts", 0)),
            )
        except (OSError, ValueError, TypeError):
            self.state = TradeGuardState()

    def _save(self) -> None:
        self.path.write_text(json.dumps(asdict(self.state)), encoding="utf-8")

    @staticmethod
    def _side(frac: float, eps: float = 0.02) -> str:
        if frac > eps:
            return "LONG"
        if frac < -eps:
            return "SHORT"
        return "FLAT"

    def filter_target(self, current: float, desired: float) -> tuple[float, str]:
        """Return (adjusted_target, reason). Reducing risk always allowed."""
        cur_side = self._side(current)
        des_side = self._side(desired)
        now = time.time()

        # Track flatten moment for flip cooldown.
        if cur_side != "FLAT" and des_side == "FLAT":
            self.state.last_side = cur_side
            self.state.last_flat_ts = now
            self._save()

        # Flip: LONG↔SHORT or open after opposite flatten within cooldown.
        flipping = (
            (cur_side == "LONG" and des_side == "SHORT")
            or (cur_side == "SHORT" and des_side == "LONG")
            or (
                cur_side == "FLAT"
                and des_side != "FLAT"
                and self.state.last_side not in {"FLAT", des_side}
                and self.state.last_flat_ts > 0
                and (now - self.state.last_flat_ts) < self.flip_cooldown_seconds
            )
        )
        if flipping and self.flip_cooldown_seconds > 0:
            # First flatten if still in a position; otherwise stay flat.
            if cur_side != "FLAT":
                return 0.0, f"flip_cooldown_flatten (wait {self.flip_cooldown_seconds}s)"
            remain = int(self.flip_cooldown_seconds - (now - self.state.last_flat_ts))
            return 0.0, f"flip_cooldown_block ({remain}s left)"

        # Cap how fast we add risk (toward larger |position|).
        step = self.max_step_fraction
        if abs(desired) > abs(current) + 1e-9:
            if desired > current:
                capped = min(desired, current + step)
            else:
                capped = max(desired, current - step)
            if abs(capped - desired) > 1e-9:
                return capped, f"step_cap maxΔ={step:.2f}"
        return desired, "ok"

    def note_fill(self, resulting_frac: float) -> None:
        side = self._side(resulting_frac)
        self.state.last_trade_ts = time.time()
        if side == "FLAT":
            if self.state.last_side != "FLAT":
                self.state.last_flat_ts = self.state.last_trade_ts
        else:
            self.state.last_side = side
        self._save()
