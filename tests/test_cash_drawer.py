"""
Cash drawer rules: float on open, expected cash, count/variance, and who may do what.

Run from the project folder:   python -m unittest tests.test_cash_drawer -v

Uses a throwaway data folder (MERCHANTPOS_HOME), so it never touches real data.
"""
import os
import sys
import tempfile
import unittest

_TMP = tempfile.mkdtemp(prefix="pos_test_")
os.environ["MERCHANTPOS_HOME"] = _TMP
os.makedirs(os.path.join(_TMP, "data"), exist_ok=True)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import init_all_databases                      # noqa: E402
init_all_databases()

from core import db_checkout as K, db_config as C, db_users as U   # noqa: E402
from core import cash_drawer as CD                                  # noqa: E402

_n = [0]


def _user(role):
    _n[0] += 1
    return U.add_user(f"{role} {_n[0]}", f"{role}{_n[0]}", "pass1234", role)


def _sale(uid, sid, total, method="cash", card=None, qty=2):
    """One-line receipt; qty 2 so a partial refund of 1 is exactly half."""
    item = {"product_id": None, "barcode": "1", "product_name": "Thing", "quantity": qty,
            "unit_price": total / qty, "gct_amount": 0, "line_total": total, "discount_amount": 0}
    cash_in = total if method == "cash" else (total - card if method == "split" else None)
    return K.save_receipt(uid, sid, [item], total, 0, 0, total, method, cash_in, card, 0)


def _refund_half(receipt, by):
    it = K.get_receipt_by_id(receipt["id"])["items"][0]
    K.refund_receipt(receipt["id"], by, "returned", [{"receipt_item_id": it["id"], "quantity": 1}], "partial")


class OpenSessionFloat(unittest.TestCase):
    def setUp(self):
        C.set_many({"cash_drawer_enabled": "0", "cash_drawer_float": "0"})

    def test_migration_added_columns(self):
        with U._conn() as con:
            cols = {r[1] for r in con.execute("PRAGMA table_info(sessions)")}
        self.assertTrue({"float_amount", "counted_cash", "counted_by", "counted_at"} <= cols)

    def test_tracking_off_records_no_float(self):
        s = U.get_session_by_id(U.open_session(_user("cashier")))
        self.assertIsNone(s["float_amount"])
        self.assertIsNone(CD.session_cash_summary(s))

    def test_standard_float_is_saved_on_the_session(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        sid = U.open_session(_user("cashier"))
        C.set_many({"cash_drawer_float": "150"})                      # change the standard later
        self.assertEqual(U.get_session_by_id(sid)["float_amount"], 100.0)   # old session unchanged
        self.assertEqual(U.get_session_by_id(U.open_session(_user("cashier")))["float_amount"], 150.0)

    def test_per_session_override_and_no_float(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        self.assertEqual(U.get_session_by_id(U.open_session(_user("cashier"), float_amount=40))["float_amount"], 40.0)
        self.assertEqual(U.get_session_by_id(U.open_session(_user("cashier"), float_amount=0))["float_amount"], 0.0)

    def test_negative_float_rejected(self):
        with self.assertRaises(ValueError):
            U.open_session(_user("cashier"), float_amount=-5)


class ExpectedCash(unittest.TestCase):
    def setUp(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        self.cashier, self.sup = _user("cashier"), _user("supervisor")
        self.sid = U.open_session(self.cashier, opened_by=self.sup)

    def summary(self):
        return CD.session_cash_summary(U.get_session_by_id(self.sid))

    def test_float_only(self):
        s = self.summary()
        self.assertEqual((s["float"], s["cash_sales"], s["cash_refunds"], s["expected"]), (100, 0, 0, 100))

    def test_cash_card_and_split(self):
        _sale(self.cashier, self.sid, 110, "cash")
        _sale(self.cashier, self.sid, 200, "card")
        _sale(self.cashier, self.sid, 100, "split", card=40)       # 60 of this is cash
        s = self.summary()
        self.assertEqual(s["cash_sales"], 170)
        self.assertEqual(s["expected"], 270)

    def test_voided_sale_is_not_cash(self):
        keep = _sale(self.cashier, self.sid, 80, "cash")
        gone = _sale(self.cashier, self.sid, 50, "cash")
        K.void_receipt(gone["id"], self.sup, "mistake")
        self.assertEqual(self.summary()["expected"], 100 + 80)

    def test_partial_refund_comes_out_of_cash_in_proportion(self):
        cash_r = _sale(self.cashier, self.sid, 60, "cash")          # refund 30, all cash
        split_r = _sale(self.cashier, self.sid, 100, "split", card=40)   # refund 50, 60% cash = 30
        card_r = _sale(self.cashier, self.sid, 200, "card")         # refund 100, card: no cash
        for r in (cash_r, split_r, card_r):
            _refund_half(r, self.sup)
        s = self.summary()
        self.assertEqual(s["cash_refunds"], 60.0)                   # 30 + 30 + 0
        self.assertEqual(s["expected"], 100 + (60 + 60) - 60)       # float + cash sales - refunds

    def test_fully_refunded_receipt_is_not_subtracted_twice(self):
        r = _sale(self.cashier, self.sid, 60, "cash", qty=1)
        it = K.get_receipt_by_id(r["id"])["items"][0]
        K.refund_receipt(r["id"], self.sup, "all back", [{"receipt_item_id": it["id"], "quantity": 1}], "full")
        self.assertEqual(K.get_receipt_by_id(r["id"])["status"], "refunded")
        s = self.summary()
        self.assertEqual((s["cash_sales"], s["cash_refunds"], s["expected"]), (0, 0, 100))

    def test_matches_dashboard_cash_line(self):
        _sale(self.cashier, self.sid, 110, "cash")
        _sale(self.cashier, self.sid, 100, "split", card=40)
        self.assertEqual(self.summary()["cash_sales"], K.session_tender_summary(self.sid)["cash"])

    def test_dashboard_data_carries_the_summary(self):
        self.assertEqual(K.session_dashboard_data(self.sid)["cash"]["float"], 100)


class CountAndPermissions(unittest.TestCase):
    def setUp(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        self.cashier, self.sup, self.mgr = _user("cashier"), _user("supervisor"), _user("manager")
        self.sid = U.open_session(self.cashier)
        _sale(self.cashier, self.sid, 50, "cash")                   # expected = 150

    def close(self):
        U.close_session(self.sid, 50, closed_by=self.sup)

    def summary(self):
        return CD.session_cash_summary(U.get_session_by_id(self.sid))

    def test_cannot_count_an_open_session(self):
        with self.assertRaises(ValueError):
            U.set_session_count(self.sid, 150, self.sup)

    def test_cashier_cannot_change_float_or_count(self):
        with self.assertRaises(PermissionError):
            U.set_session_float(self.sid, 10, self.cashier)
        self.close()
        with self.assertRaises(PermissionError):
            U.set_session_count(self.sid, 150, self.cashier)

    def test_pending_then_variance(self):
        self.close()
        self.assertTrue(self.summary()["pending"])
        self.assertIsNone(self.summary()["variance"])
        U.set_session_count(self.sid, 147.5, self.sup)
        s = self.summary()
        self.assertFalse(s["pending"])
        self.assertEqual((s["expected"], s["counted"], s["variance"]), (150, 147.5, -2.5))   # short
        U.set_session_count(self.sid, 150, self.mgr)
        self.assertEqual(self.summary()["variance"], 0)

    def test_over_is_positive(self):
        self.close()
        U.set_session_count(self.sid, 153, self.sup)
        self.assertEqual(self.summary()["variance"], 3)

    def test_supervisor_cannot_correct_a_saved_count_but_manager_can(self):
        self.close()
        U.set_session_count(self.sid, 140, self.sup)
        with self.assertRaises(PermissionError):
            U.set_session_count(self.sid, 150, self.sup)
        U.set_session_count(self.sid, 150, self.mgr)
        log = [l for l in U.get_cash_log(self.sid) if l["kind"] == "count"]
        self.assertEqual([(l["old_value"], l["new_value"]) for l in log], [(140.0, 150.0), (None, 140.0)])
        self.assertEqual(log[0]["changed_by_name"], U.get_user_by_id(self.mgr)["full_name"])

    def test_float_change_is_logged_and_locks_after_count(self):
        U.set_session_float(self.sid, 120, self.sup, "bigger float today")
        self.assertEqual(self.summary()["float"], 120)
        entry = U.get_cash_log(self.sid)[0]
        self.assertEqual((entry["kind"], entry["old_value"], entry["new_value"], entry["note"]),
                         ("float", 100.0, 120.0, "bigger float today"))
        self.close()
        U.set_session_count(self.sid, 170, self.sup)
        with self.assertRaises(ValueError):                           # locked once counted
            U.set_session_float(self.sid, 90, self.mgr)

    def test_float_can_still_change_after_close_until_counted(self):
        self.close()
        U.set_session_float(self.sid, 80, self.sup)
        self.assertEqual(self.summary()["float"], 80)

    def test_unchanged_value_writes_no_log_entry(self):
        before = len(U.get_cash_log(self.sid))
        U.set_session_float(self.sid, 100, self.sup)
        self.assertEqual(len(U.get_cash_log(self.sid)), before)

    def test_bad_amounts_rejected(self):
        self.close()
        for bad in (-1, "abc", None, float("nan"), 1e12):
            with self.assertRaises(ValueError):
                U.set_session_count(self.sid, bad, self.sup)

    def test_untracked_session_cannot_be_counted(self):
        C.set_many({"cash_drawer_enabled": "0"})
        sid = U.open_session(_user("cashier"))
        U.close_session(sid, 0, closed_by=self.sup)
        with self.assertRaises(ValueError):
            U.set_session_count(sid, 10, self.sup)


if __name__ == "__main__":
    unittest.main()
