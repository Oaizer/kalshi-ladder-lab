"""Small local HTTP server for the read-only scanner. No credentials or orders."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from decimal import Decimal
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.parse import parse_qs, urlsplit

from scanner import analyze, contract, get_event_markets, get_json, get_series_events


STATIC = Path(__file__).parent / "static"
TICKER = re.compile(r"^[A-Z0-9-]{3,100}$")
CONTENT_TYPES = {".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".svg": "image/svg+xml"}


class Handler(BaseHTTPRequestHandler):
    def send_json(self, payload: dict, code: int = 200) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        args = parse_qs(url.query)
        if url.path.startswith("/api/"):
            try:
                self.api(url.path, args)
            except (ValueError, KeyError) as exc:
                self.send_json({"error": str(exc)}, 400)
            except Exception as exc:
                self.send_json({"error": f"Kalshi request failed: {exc}"}, 502)
            return
        name = "index.html" if url.path == "/" else url.path.lstrip("/")
        path = (STATIC / name).resolve()
        if not path.is_relative_to(STATIC.resolve()) or not path.is_file() or path.suffix not in CONTENT_TYPES:
            self.send_error(404)
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", CONTENT_TYPES[path.suffix] + "; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def api(self, path: str, args: dict[str, list[str]]) -> None:
        if path == "/api/example":
            common = {"event_ticker": "EXAMPLE-THRESHOLDS", "status": "active",
                      "strike_type": "greater", "close_time": "2030-01-01T00:00:00Z"}
            low = {**common, "ticker": "EXAMPLE-T70", "floor_strike": 70,
                   "title": "Will the value exceed 70?", "rules_primary": "If the value at Source A is greater than 70, Yes resolves.",
                   "yes_bid_dollars": "0.38", "yes_ask_dollars": "0.40"}
            high = {**common, "ticker": "EXAMPLE-T75", "floor_strike": 75,
                    "title": "Will the value exceed 75?", "rules_primary": "If the value at Source A is greater than 75, Yes resolves.",
                    "yes_bid_dollars": "0.55", "yes_ask_dollars": "0.57"}
            books = {"EXAMPLE-T70": {"orderbook_fp": {"yes_dollars": [["0.38", "5"]], "no_dollars": [["0.60", "5"]]}},
                     "EXAMPLE-T75": {"orderbook_fp": {"yes_dollars": [["0.55", "5"]], "no_dollars": [["0.43", "5"]]}}}
            result = analyze([low, high], books, Decimal("0.07"), 5)
            result.update({"event": "WORKED EXAMPLE", "sampled_at": datetime.now(timezone.utc).isoformat(),
                           "markets_in_event": 2, "books_loaded": 2, "book_errors": [], "fee_rate": "0.07", "cap": 5,
                           "synthetic": True})
            self.send_json(result)
            return
        if path == "/api/events":
            series = args.get("series", ["KXCPI"])[0].upper().strip()
            if not TICKER.fullmatch(series):
                raise ValueError("Enter a valid Kalshi series ticker.")
            self.send_json({"series": series, "events": get_series_events(series)})
            return
        if path == "/api/analyze":
            event = args.get("event", [""])[0].upper().strip()
            if not TICKER.fullmatch(event):
                raise ValueError("Choose a valid event ticker.")
            rate = Decimal(args.get("fee_rate", ["0.07"])[0])
            if not rate.is_finite() or not 0 <= rate <= Decimal("0.5"):
                raise ValueError("Fee coefficient must be between 0 and 0.5.")
            cap = int(args.get("cap", ["100"])[0])
            if not 1 <= cap <= 1000:
                raise ValueError("Contract cap must be between 1 and 1000.")
            markets = get_event_markets(event)
            ladder = [row for market in markets if (row := contract(market))]
            ladder = sorted(ladder, key=lambda row: row["strike"])[:30]
            selected = {row["ticker"] for row in ladder}
            markets = [market for market in markets if market.get("ticker") in selected]
            books: dict[str, dict] = {}
            errors = []
            with ThreadPoolExecutor(max_workers=6) as pool:
                jobs = {pool.submit(get_json, f"/markets/{ticker}/orderbook"): ticker for ticker in selected}
                for job in as_completed(jobs):
                    ticker = jobs[job]
                    try:
                        books[ticker] = job.result()
                    except Exception as exc:
                        errors.append(f"{ticker}: {exc}")
            result = analyze(markets, books, rate, cap)
            result.update({"event": event, "sampled_at": datetime.now(timezone.utc).isoformat(),
                           "markets_in_event": len(markets), "books_loaded": len(books),
                           "book_errors": errors, "fee_rate": str(rate), "cap": cap})
            self.send_json(result)
            return
        self.send_json({"error": "Unknown endpoint"}, 404)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run Kalshi Ladder Lab locally")
    parser.add_argument("--port", type=int, default=8765)
    options = parser.parse_args()
    server = ThreadingHTTPServer(("127.0.0.1", options.port), Handler)
    print(f"Open http://127.0.0.1:{options.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.server_close()
