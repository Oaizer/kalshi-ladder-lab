import unittest
from decimal import Decimal

from scanner import analyze, ask_levels, compatible, fee, price_pair


def market(ticker, strike, rule=None):
    return {
        "ticker": ticker, "event_ticker": "TEMP-DAY", "status": "active",
        "strike_type": "greater", "floor_strike": strike,
        "title": f"Will temperature exceed {strike}?",
        "rules_primary": rule or f"If the high at Station A is greater than {strike} degrees, Yes resolves.",
        "close_time": "2026-10-08T05:00:00Z",
        "yes_bid_dollars": "0.40", "yes_ask_dollars": "0.50",
    }


class ScannerTests(unittest.TestCase):
    def test_yes_ask_is_complement_of_no_bid(self):
        book = {"orderbook_fp": {"no_dollars": [["0.60", "3.75"]], "yes_dollars": [["0.22", "4.00"]]}}
        self.assertEqual(ask_levels(book, "yes"), [(Decimal("0.40"), 3)])
        self.assertEqual(ask_levels(book, "no"), [(Decimal("0.78"), 4)])

    def test_fee_rounds_up_per_lot(self):
        self.assertEqual(fee(Decimal("0.50"), 1, Decimal("0.07")), Decimal("0.02"))

    def test_pair_checks_depth_and_fee(self):
        result = price_pair([(Decimal("0.40"), 2), (Decimal("0.60"), 8)],
                            [(Decimal("0.45"), 3)], Decimal("0.07"), 10)
        self.assertEqual(result.count, 2)
        self.assertEqual(result.cost, Decimal("1.70"))
        self.assertEqual(result.fees, Decimal("0.08"))
        self.assertEqual(result.profit, Decimal("0.22"))

    def test_compatibility_rejects_different_settlement_source(self):
        a, b = market("A", 70), market("B", 75)
        from scanner import contract
        self.assertTrue(compatible(contract(a), contract(b)))
        b["rules_primary"] = "If the high at Station B is greater than 75 degrees, Yes resolves."
        self.assertFalse(compatible(contract(a), contract(b)))

    def test_compatibility_preserves_other_numbers(self):
        from scanner import contract
        a = market("A", 70, "If the high at Station 1 is greater than 70 degrees on day 3, Yes resolves.")
        b = market("B", 75, "If the high at Station 2 is greater than 75 degrees on day 3, Yes resolves.")
        self.assertFalse(compatible(contract(a), contract(b)))

    def test_analysis_ignores_midpoint_inversion_without_executable_edge(self):
        a, b = market("A", 70), market("B", 75)
        books = {"A": {"orderbook_fp": {"no_dollars": [["0.45", "5"]], "yes_dollars": []}},
                 "B": {"orderbook_fp": {"yes_dollars": [["0.40", "5"]], "no_dollars": []}}}
        result = analyze([a, b], books, Decimal("0.07"))
        self.assertEqual(result["pairs_checked"], 1)
        self.assertEqual(result["opportunities"], [])

    def test_analysis_reports_positive_certificate(self):
        a, b = market("A", 70), market("B", 75)
        books = {"A": {"orderbook_fp": {"no_dollars": [["0.60", "2"]], "yes_dollars": []}},
                 "B": {"orderbook_fp": {"yes_dollars": [["0.55", "2"]], "no_dollars": []}}}
        result = analyze([a, b], books, Decimal("0.07"))
        self.assertEqual(result["opportunities"][0]["count"], 2)
        self.assertGreater(Decimal(result["opportunities"][0]["worst_profit"]), 0)


if __name__ == "__main__":
    unittest.main()
