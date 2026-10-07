# Kalshi Ladder Lab

A read-only scanner for threshold markets on Kalshi. It looks for pairs of contracts with a simple payoff guarantee: if both contracts refer to the same measured outcome, buying **YES on `X > a`** and **NO on `X > b`**, where `a < b`, pays at least $1 at settlement. The scanner compares that floor with the displayed order-book cost and a configurable fee estimate.

This is a research tool. It does not place orders, access an account, or promise that a displayed pair can be filled.

## Run locally

Python 3.11 or newer is sufficient. There are no third-party packages or API keys.

```bash
python server.py
```

Open `http://127.0.0.1:8765`. The default series is `KXCPI`, which currently has several `greater` thresholds per monthly event. Load its open events, select one, and click **Analyze event**. You can enter another Kalshi series ticker if it has comparable `greater` threshold contracts.

**View a worked example** loads two invented contracts with a positive certificate. It is useful for checking the payout arithmetic when the live book has no opportunity. The interface labels it as illustrative data.

To run the unit tests:

```bash
python -m unittest discover -s tests -v
```

## What the scanner actually checks

For thresholds `a < b`, the event `X > b` implies `X > a`. The following settlement table holds when both contracts use the same underlying measurement and rules:

| Outcome | YES(`X > a`) | NO(`X > b`) | Total payout |
| --- | ---: | ---: | ---: |
| `X ≤ a` | 0 | 1 | $1 |
| `a < X ≤ b` | 1 | 1 | $2 |
| `X > b` | 1 | 0 | $1 |

The scanner groups contracts by event ticker, requires the same close time, and compares their primary rule text after replacing numeric values. That rule comparison is a guardrail, **not a legal interpretation of the contracts**. Review the contract terms before acting on a result.

The chart uses displayed YES bid and ask quotes. Its midpoint ordering is a diagnostic: a midpoint inversion is **not** treated as an executable trade. Candidate trades use the order book. Kalshi publishes YES and NO bids; the scanner converts a NO bid at `p` into a YES ask at `1-p`, and vice versa. It walks the available price levels, ignores fractional displayed size, and tries every integer pair count up to the selected cap. A pair is displayed only when its minimum payout exceeds modeled purchase cost plus modeled fees.

The default fee coefficient is `0.07`, the general prediction-market taker coefficient in [Kalshi's published October 2025 schedule](https://kalshi.com/docs/kalshi-fee-schedule.pdf). For each displayed price level, the model rounds `rate × contracts × price × (1 − price)` up to the next cent. Some markets have different fees or waivers, and the schedule can change. Change the coefficient to study sensitivity and check the [current fee schedule](https://kalshi.com/fee-schedule) and market-specific fee before treating a result as actionable. The result is an estimate, not a fee quote from Kalshi.

## Data flow and limits

`server.py` serves the browser UI and proxies public Kalshi market requests. `scanner.py` contains the payoff, order-book, and fee logic. `static/` holds the interface. The server binds to `127.0.0.1` and stores no market or account data.

The series lookup reads up to five pages of open markets. An event analysis reads up to ten pages and analyzes the first 30 qualifying thresholds in strike order. It fetches their books concurrently. Book failures are shown in the interface and can make the results incomplete.

Order books are fetched in separate HTTP requests. They are **not an atomic snapshot**. A profitable combination on screen can vanish before both legs execute, and partial fills can leave an outright position. Displayed size can change or cancel. The tool does not account for queue position, order latency, capital requirements, or market-specific fees beyond the chosen coefficient. No backtest is claimed; historical order-book reconstruction would require a separate recorded data set.

## Sources

- [Kalshi Get Markets API](https://docs.kalshi.com/api-reference/market/get-markets)
- [Kalshi Get Market Orderbook API](https://docs.kalshi.com/api-reference/market/get-market-orderbook)
- [Kalshi fee schedule](https://kalshi.com/fee-schedule)

Kalshi Ladder Lab is independent software and is not affiliated with Kalshi.
