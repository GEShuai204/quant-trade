from __future__ import annotations

import hashlib
import hmac
import time
from typing import Any, Optional
from urllib.parse import urljoin

import requests


class RoostooError(RuntimeError):
    """HTTP failure or Roostoo Success=false."""


def encode_params(payload: dict[str, Any]) -> str:
    """Alphabetically join key=value. This exact string is signed and sent."""
    return "&".join(f"{k}={payload[k]}" for k in sorted(payload.keys()))


class RoostooClient:
    def __init__(
        self,
        api_key: str,
        api_secret: str,
        base_url: str = "https://mock-api.roostoo.com",
        timeout: int = 15,
    ) -> None:
        self.api_key = api_key
        self._secret = api_secret.encode("utf-8")
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout = timeout
        self.offset_ms = 0
        self._session = requests.Session()

    def sync_time(self) -> int:
        server_time = int(self.get_server_time()["ServerTime"])
        local = int(time.time() * 1000)
        self.offset_ms = server_time - local
        return self.offset_ms

    def timestamp_ms(self) -> str:
        return str(int(time.time() * 1000) + self.offset_ms)

    def _sign(self, total_params: str) -> str:
        return hmac.new(self._secret, total_params.encode("utf-8"), hashlib.sha256).hexdigest()

    def _headers(self, total_params: str | None = None, signed: bool = False) -> dict[str, str]:
        headers = {}
        if signed:
            if total_params is None:
                raise ValueError("signed request requires total_params")
            headers["RST-API-KEY"] = self.api_key
            headers["MSG-SIGNATURE"] = self._sign(total_params)
        return headers

    def _url(self, path: str) -> str:
        return urljoin(self.base_url, path.lstrip("/"))

    def _parse(self, response: requests.Response, require_success: bool = True) -> dict[str, Any]:
        try:
            response.raise_for_status()
        except requests.RequestException as exc:
            body = ""
            if exc.response is not None:
                body = exc.response.text[:500]
            raise RoostooError(f"HTTP error: {exc}; body={body}") from exc
        try:
            data = response.json()
        except ValueError as exc:
            raise RoostooError(f"Non-JSON response: {response.text[:500]}") from exc
        if require_success and isinstance(data, dict) and "Success" in data and not data.get("Success"):
            err = data.get("ErrMsg") or "Roostoo request failed"
            raise RoostooError(f"{err} | response={data}")
        return data

    def _get(
        self,
        path: str,
        payload: Optional[dict[str, Any]] = None,
        signed: bool = False,
        require_success: bool = True,
    ) -> dict[str, Any]:
        payload = dict(payload or {})
        total = encode_params(payload) if payload else ""
        url = self._url(path)
        if total:
            url = f"{url}?{total}"
        headers = self._headers(total if signed else None, signed=signed)
        response = self._session.get(url, headers=headers, timeout=self.timeout)
        return self._parse(response, require_success=require_success)

    def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        total = encode_params(payload)
        headers = self._headers(total, signed=True)
        headers["Content-Type"] = "application/x-www-form-urlencoded"
        response = self._session.post(
            self._url(path),
            headers=headers,
            data=total,
            timeout=self.timeout,
        )
        return self._parse(response, require_success=True)

    def get_server_time(self) -> dict[str, Any]:
        return self._get("/v3/serverTime", require_success=False)

    def get_exchange_info(self) -> dict[str, Any]:
        return self._get("/v3/exchangeInfo", require_success=False)

    def get_ticker(self, pair: Optional[str] = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"timestamp": self.timestamp_ms()}
        if pair:
            payload["pair"] = pair
        return self._get("/v3/ticker", payload=payload, signed=False)

    def get_balance(self) -> dict[str, Any]:
        return self._get(
            "/v3/balance",
            payload={"timestamp": self.timestamp_ms()},
            signed=True,
        )

    def get_short_positions(self) -> dict[str, Any]:
        return self._get(
            "/v6/short_positions",
            payload={"timestamp": self.timestamp_ms()},
            signed=True,
        )

    def query_order(
        self,
        pair: Optional[str] = None,
        pending_only: Optional[bool] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"timestamp": self.timestamp_ms()}
        if pair:
            payload["pair"] = pair
        if pending_only is not None:
            payload["pending_only"] = "TRUE" if pending_only else "FALSE"
        try:
            return self._post("/v3/query_order", payload)
        except RoostooError as exc:
            if "no order matched" in str(exc).lower():
                return {"Success": True, "ErrMsg": str(exc), "OrderMatched": []}
            raise

    def place_order(
        self,
        pair: str,
        side: str,
        quantity: str,
        order_type: str = "MARKET",
        price: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pair": pair,
            "side": side.upper(),
            "type": order_type.upper(),
            "quantity": str(quantity),
            "timestamp": self.timestamp_ms(),
        }
        if order_type.upper() == "LIMIT":
            if price is None:
                raise ValueError("LIMIT orders require price")
            payload["price"] = str(price)
        return self._post("/v3/place_order", payload)

    def short_open(
        self,
        pair: str,
        collateral: str,
        order_type: str = "MARKET",
        price: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pair": pair,
            "collateral": str(collateral),
            "timestamp": self.timestamp_ms(),
        }
        if order_type.upper() == "LIMIT":
            payload["order_type"] = "LIMIT"
            if price is None:
                raise ValueError("LIMIT short open requires price")
            payload["price"] = str(price)
        return self._post("/v6/short_open", payload)

    def short_close(
        self,
        pair: str,
        close_pct: Optional[str] = None,
        close_qty: Optional[str] = None,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "pair": pair,
            "timestamp": self.timestamp_ms(),
        }
        if close_qty is not None:
            payload["close_qty"] = str(close_qty)
        elif close_pct is not None:
            payload["close_pct"] = str(close_pct)
        return self._post("/v6/short_close", payload)
