from __future__ import annotations

from dataclasses import dataclass
from threading import Lock


@dataclass(frozen=True)
class InflightTicket:
    scope: str
    user_key: str


@dataclass(frozen=True)
class InflightDecision:
    allowed: bool
    scope: str
    total_in_flight: int
    user_in_flight: int
    ticket: InflightTicket | None


class InflightLimiter:
    def __init__(self, name: str) -> None:
        self.name = name
        self._lock = Lock()
        self._total_in_flight = 0
        self._per_user: dict[str, int] = {}

    def acquire(
        self,
        *,
        user_key: str,
        global_limit: int,
        per_user_limit: int,
    ) -> InflightDecision:
        normalized_user = user_key.strip() or "anonymous"
        with self._lock:
            current_user = self._per_user.get(normalized_user, 0)
            if global_limit > 0 and self._total_in_flight >= global_limit:
                return InflightDecision(
                    allowed=False,
                    scope="global",
                    total_in_flight=self._total_in_flight,
                    user_in_flight=current_user,
                    ticket=None,
                )
            if per_user_limit > 0 and current_user >= per_user_limit:
                return InflightDecision(
                    allowed=False,
                    scope="user",
                    total_in_flight=self._total_in_flight,
                    user_in_flight=current_user,
                    ticket=None,
                )
            self._total_in_flight += 1
            next_user = current_user + 1
            self._per_user[normalized_user] = next_user
            return InflightDecision(
                allowed=True,
                scope="granted",
                total_in_flight=self._total_in_flight,
                user_in_flight=next_user,
                ticket=InflightTicket(scope=self.name, user_key=normalized_user),
            )

    def release(self, ticket: InflightTicket | None) -> None:
        if ticket is None:
            return
        with self._lock:
            self._total_in_flight = max(self._total_in_flight - 1, 0)
            current_user = self._per_user.get(ticket.user_key, 0)
            next_user = max(current_user - 1, 0)
            if next_user <= 0:
                self._per_user.pop(ticket.user_key, None)
            else:
                self._per_user[ticket.user_key] = next_user
