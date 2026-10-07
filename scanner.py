"""Read-only analysis of Kalshi threshold ladders.

The certificate uses only the implication {X > high} subset {X > low}.
It does not forecast X or assume that midpoints are tradable.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, ROUND_CEILING
import json
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_URL = "https://external-api.kalshi.com/trade-api/v2"
USER_AGENT = "KalshiLadderLab/1.0 (read-only research tool)"


def get_json(path: str, params: dict | None = None) -> dict:
    url = BASE_URL + path
    if params:
        url += "?" + urlencode(params)
    request = Request(url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
    with urlopen(request, timeout=18) as response:
        return json.load(response)


def get_event_markets(event_ticker: str) -> list[dict]:
    markets: list[dict] = []
    cursor = None
    for _ in range(10):
        params = {"event_ticker": event_ticker, "limit": 100}
        if cursor:
            params["cursor"] = cursor
        page = get_json("/markets", params)
        markets.extend(page.get("markets", []))
        cursor = page.get("cursor")
        if not cursor:
            break
    return markets


def get_series_events(series_ticker: str) -> list[dict]:
    events: dict[str, dict] = {}
    cursor = None
    for _ in range(5):
        params = {"status": "open", "series_ticker": series_ticker, "limit": 100, "mve_filter": "exclude"}
        if cursor:
            params["cursor"] = cursor
        page = get_json("/markets", params)
        for market in page.get("markets", []):
            event = market.get("event_ticker")
            if event:
                row = events.setdefault(event, {"ticker": event, "count": 0, "close_time": market.get("close_time", "")})
                row["count"] += 1
        cursor = page.get("cursor")
        if not cursor:
            break
    return sorted(events.values(), key=lambda row: row["close_time"])


def decimal(value) -> Decimal | None:
    try:
        return Decimal(str(value)) if value is not None else None
    except (ValueError, ArithmeticError):
        return None


def contract(market: dict) -> dict | None:
    if market.get("status") != "active" and market.get("status") != "open":
        return None
    if market.get("strike_type") != "greater":
        return None
    strike = decimal(market.get("floor_strike"))
    if strike is None:
        return None
    return {
        "ticker": market["ticker"],
        "event_ticker": market["event_ticker"],
        "strike": strike,
        "title": market.get("title", ""),
        "rules": market.get("rules_primary", ""),
        "close_time": market.get("close_time", ""),
        "yes_bid": decimal(market.get("yes_bid_dollars")),
        "yes_ask": decimal(market.get("yes_ask_dollars")),
        "no_bid": decimal(market.get("no_bid_dollars")),
        "no_ask": decimal(market.get("no_ask_dollars")),
    }


def rule_signature(rule: str) -> str:
    # Remove only the number following the threshold phrase. Dates, station
    # identifiers, and other settlement details must still match exactly.
    return re.sub(r"((?:greater|more) than\s+)-?\d+(?:\.\d+)?", r"\1#", rule.lower(), count=1).strip()


def compatible(low: dict, high: dict) -> bool:
    return (
        low["event_ticker"] == high["event_ticker"]
        and low["close_time"] == high["close_time"]
        and low["strike"] < high["strike"]
        and bool(low["rules"])
        and rule_signature(low["rules"]) == rule_signature(high["rules"])
        and "than #" in rule_signature(low["rules"])
    )


def ask_levels(orderbook: dict, side: str) -> list[tuple[Decimal, int]]:
    """An ask for YES is a NO bid at 1-price, and vice versa."""
    source = "no_dollars" if side == "yes" else "yes_dollars"
    book = orderbook.get("orderbook_fp", orderbook.get("orderbook", {}))
    levels = []
    for raw_price, raw_size, *_ in book.get(source, []):
        bid, size = decimal(raw_price), decimal(raw_size)
        if bid is None or size is None or bid <= 0 or bid >= 1:
            continue
        count = int(size)  # Conservative: ignore fractional displayed size.
        if count > 0:
            levels.append((Decimal(1) - bid, count))
    return sorted(levels)


def fee(price: Decimal, count: int, rate: Decimal) -> Decimal:
    if count == 0:
        return Decimal(0)
    raw = rate * count * price * (Decimal(1) - price)
    return raw.quantize(Decimal("0.01"), rounding=ROUND_CEILING)


@dataclass
class Fill:
    count: int
    cost: Decimal
    fees: Decimal
    worst_payout: Decimal
    profit: Decimal
    yes_lots: list[dict]
    no_lots: list[dict]


def price_pair(yes_levels: list[tuple[Decimal, int]], no_levels: list[tuple[Decimal, int]],
               rate: Decimal, max_contracts: int = 100) -> Fill | None:
    """Find the most profitable common quantity, including per-level rounded fees.

    Every YES(low) + NO(high) pair pays at least $1. We walk both books
    together; a deeper level is never used before a cheaper level.
    """
    if not yes_levels or not no_levels or max_contracts < 1:
        return None
    yi = ni = 0
    yr = yes_levels[0][1]
    nr = no_levels[0][1]
    count = 0
    cost = Decimal(0)
    best: Fill | None = None
    yes_lots: list[dict] = []
    no_lots: list[dict] = []
    while yi < len(yes_levels) and ni < len(no_levels) and count < max_contracts:
        yp, np = yes_levels[yi][0], no_levels[ni][0]
        # Evaluate every integer quantity: cent rounding can make an interior
        # quantity better than the end of a displayed price level.
        take = 1
        count += take
        cost += take * (yp + np)
        yr -= take
        nr -= take
        if yes_lots and yes_lots[-1]["price"] == yp:
            yes_lots[-1]["count"] += take
        else:
            yes_lots.append({"price": yp, "count": take})
        if no_lots and no_lots[-1]["price"] == np:
            no_lots[-1]["count"] += take
        else:
            no_lots.append({"price": np, "count": take})
        fees = sum((fee(lot["price"], lot["count"], rate) for lot in yes_lots + no_lots), Decimal(0))
        profit = Decimal(count) - cost - fees
        if best is None or profit > best.profit:
            best = Fill(count, cost, fees, Decimal(count), profit,
                        [lot.copy() for lot in yes_lots], [lot.copy() for lot in no_lots])
        if yr == 0:
            yi += 1
            if yi < len(yes_levels):
                yr = yes_levels[yi][1]
        if nr == 0:
            ni += 1
            if ni < len(no_levels):
                nr = no_levels[ni][1]
    return best


def analyze(markets: list[dict], books: dict[str, dict], rate: Decimal, max_contracts: int = 100) -> dict:
    ladder = sorted((row for market in markets if (row := contract(market))), key=lambda row: row["strike"])
    opportunities = []
    for i, low in enumerate(ladder):
        for high in ladder[i + 1:]:
            if not compatible(low, high):
                continue
            fill = price_pair(ask_levels(books.get(low["ticker"], {}), "yes"),
                              ask_levels(books.get(high["ticker"], {}), "no"), rate, max_contracts)
            if fill is None or fill.profit <= 0:
                continue
            opportunities.append({
                "low_ticker": low["ticker"], "high_ticker": high["ticker"],
                "low_strike": str(low["strike"]), "high_strike": str(high["strike"]),
                "count": fill.count, "cost": str(fill.cost), "fees": str(fill.fees),
                "worst_payout": str(fill.worst_payout), "worst_profit": str(fill.profit),
                "yes_lots": [{"price": str(x["price"]), "count": x["count"]} for x in fill.yes_lots],
                "no_lots": [{"price": str(x["price"]), "count": x["count"]} for x in fill.no_lots],
            })
    opportunities.sort(key=lambda row: Decimal(row["worst_profit"]), reverse=True)
    return {
        "ladder": [{k: str(v) if isinstance(v, Decimal) else v for k, v in row.items() if k != "rules"} for row in ladder],
        "opportunities": opportunities,
        "pairs_checked": sum(compatible(low, high) for i, low in enumerate(ladder) for high in ladder[i + 1:]),
    }
