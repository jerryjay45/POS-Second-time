"""
Paid-outs and the no-sale drawer-open log: who may do what, and how they change expected cash.

Run from the project folder:   python -m unittest tests.test_paid_outs -v
"""
import unittest

from tests.test_cash_drawer import _user, _sale, U, C, CD      # shared throwaway data folder + helpers


class PaidOuts(unittest.TestCase):
    def setUp(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        self.cashier, self.sup, self.mgr = _user("cashier"), _user("supervisor"), _user("manager")
        self.sid = U.open_session(self.cashier, opened_by=self.sup)

    def summary(self):
        return CD.session_cash_summary(U.get_session_by_id(self.sid))

    def test_paid_out_lowers_expected_cash(self):
        _sale(self.cashier, self.sid, 80, "cash")
        U.add_paid_out(self.sid, 15.50, "ice", self.sup)
        s = self.summary()
        self.assertEqual(s["paid_outs"], 15.5)
        self.assertEqual(s["expected"], 100 + 80 - 15.5)

    def test_variance_uses_paid_outs(self):
        U.add_paid_out(self.sid, 20, "delivery tip", self.sup)
        U.close_session(self.sid, 0)
        U.set_session_count(self.sid, 80, self.sup)
        self.assertEqual(self.summary()["variance"], 0)

    def test_reason_and_amount_are_required(self):
        with self.assertRaises(ValueError):
            U.add_paid_out(self.sid, 10, "   ", self.sup)
        for bad in (0, -5, "abc", float("nan")):
            with self.assertRaises(ValueError):
                U.add_paid_out(self.sid, bad, "ice", self.sup)

    def test_cashier_cannot_record_or_void(self):
        with self.assertRaises(PermissionError):
            U.add_paid_out(self.sid, 10, "ice", self.cashier)
        pid = U.add_paid_out(self.sid, 10, "ice", self.sup)
        with self.assertRaises(PermissionError):
            U.void_paid_out(pid, self.sup)               # supervisor can record but not void
        with self.assertRaises(PermissionError):
            U.void_paid_out(pid, self.cashier)

    def test_manager_void_restores_expected_and_keeps_the_row(self):
        pid = U.add_paid_out(self.sid, 25, "supplies", self.sup)
        self.assertEqual(self.summary()["expected"], 75)
        U.void_paid_out(pid, self.mgr)
        self.assertEqual(self.summary()["expected"], 100)
        rows = U.get_paid_outs(self.sid)
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]["voided_at"])
        self.assertEqual(rows[0]["voided_by_name"], U.get_user_by_id(self.mgr)["full_name"])
        self.assertEqual(U.get_paid_outs(self.sid, include_voided=False), [])
        U.void_paid_out(pid, self.mgr)                   # voiding twice is harmless

    def test_locked_once_counted(self):
        U.close_session(self.sid, 0)
        U.add_paid_out(self.sid, 5, "late entry", self.sup)       # closed but not counted: allowed
        U.set_session_count(self.sid, 95, self.sup)
        with self.assertRaises(ValueError):
            U.add_paid_out(self.sid, 5, "too late", self.sup)

    def test_session_without_float_has_no_paid_outs(self):
        C.set_many({"cash_drawer_enabled": "0"})
        sid = U.open_session(self.cashier)
        with self.assertRaises(ValueError):
            U.add_paid_out(sid, 5, "ice", self.sup)

    def test_only_this_sessions_paid_outs_count(self):
        other = U.open_session(_user("cashier"))
        U.add_paid_out(other, 40, "elsewhere", self.sup)
        self.assertEqual(self.summary()["expected"], 100)


class DrawerOpens(unittest.TestCase):
    def setUp(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "50"})
        self.cashier, self.sup = _user("cashier"), _user("supervisor")
        self.sid = U.open_session(self.cashier)

    def test_open_is_logged_with_who_authorised(self):
        U.log_drawer_open(self.sup, self.cashier, self.sid)
        U.log_drawer_open(self.sup, self.cashier, self.sid)
        self.assertEqual(U.count_drawer_opens(self.sid), 2)
        self.assertEqual(U.get_drawer_opens(self.sid)[0]["authorised_by_name"],
                         U.get_user_by_id(self.sup)["full_name"])
        self.assertEqual(CD.session_cash_summary(U.get_session_by_id(self.sid))["no_sale_opens"], 2)

    def test_open_without_a_session_is_kept_but_not_counted_anywhere(self):
        U.log_drawer_open(self.sup, None, None)           # supervisor/manager screens have no till session
        self.assertEqual(U.count_drawer_opens(self.sid), 0)

    def test_logging_never_raises(self):
        U.log_drawer_open(99999, 99999, 99999)            # bad ids: swallowed, drawer still opens


class OldDatabaseUpgrade(unittest.TestCase):
    def test_tables_exist_and_init_is_repeatable(self):
        U.init_db(); U.init_db()
        with U._conn() as con:
            names = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertTrue({"session_paid_outs", "drawer_opens"} <= names)


if __name__ == "__main__":
    unittest.main()


class SafeDrops(unittest.TestCase):
    def setUp(self):
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        self.cashier, self.sup, self.mgr = _user("cashier"), _user("supervisor"), _user("manager")
        self.sid = U.open_session(self.cashier, opened_by=self.sup)

    def summary(self):
        return CD.session_cash_summary(U.get_session_by_id(self.sid))

    def test_safe_drop_lowers_expected_and_is_its_own_line(self):
        _sale(self.cashier, self.sid, 300, "cash")
        U.add_paid_out(self.sid, 200, "", self.sup, kind="safe_drop")     # no reason needed
        U.add_paid_out(self.sid, 10, "ice", self.sup)
        s = self.summary()
        self.assertEqual((s["safe_drops"], s["paid_outs"]), (200, 10))
        self.assertEqual(s["expected"], 100 + 300 - 200 - 10)

    def test_safe_drop_without_reason_gets_a_default_but_paid_out_still_needs_one(self):
        U.add_paid_out(self.sid, 50, "  ", self.sup, kind="safe_drop")
        self.assertEqual(U.get_paid_outs(self.sid)[0]["reason"], "Safe drop")
        with self.assertRaises(ValueError):
            U.add_paid_out(self.sid, 50, "  ", self.sup)

    def test_same_rules_as_paid_outs(self):
        with self.assertRaises(PermissionError):
            U.add_paid_out(self.sid, 50, "", self.cashier, kind="safe_drop")
        pid = U.add_paid_out(self.sid, 50, "", self.sup, kind="safe_drop")
        with self.assertRaises(PermissionError):
            U.void_paid_out(pid, self.sup)
        U.void_paid_out(pid, self.mgr)
        self.assertEqual(self.summary()["expected"], 100)
        with self.assertRaises(ValueError):
            U.add_paid_out(self.sid, 5, "x", self.sup, kind="bogus")

    def test_variance_balances_after_drop(self):
        _sale(self.cashier, self.sid, 150, "cash")
        U.add_paid_out(self.sid, 200, "", self.sup, kind="safe_drop")
        U.close_session(self.sid, 150, closed_by=self.sup)
        U.set_session_count(self.sid, 50, self.sup)
        self.assertEqual(self.summary()["variance"], 0)

    def test_database_from_the_previous_patch_gets_the_kind_column(self):
        with U._conn() as con:
            con.execute("DROP TABLE session_paid_outs")
            con.execute("""CREATE TABLE session_paid_outs (
                id INTEGER PRIMARY KEY AUTOINCREMENT, session_id INTEGER NOT NULL,
                amount REAL NOT NULL, reason TEXT NOT NULL, recorded_by INTEGER,
                recorded_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
                voided_by INTEGER, voided_at TEXT)""")
            con.execute("INSERT INTO session_paid_outs (session_id, amount, reason) VALUES (?, 12, 'old row')",
                        (self.sid,))
            con.commit()
        U.init_db()
        with U._conn() as con:
            self.assertIn("kind", {r[1] for r in con.execute("PRAGMA table_info(session_paid_outs)")})
        self.assertEqual(U.get_paid_outs(self.sid)[0]["kind"], "paid_out")      # old rows stay paid-outs
        self.assertEqual(self.summary()["paid_outs"], 12)


class XReport(unittest.TestCase):
    def test_x_report_is_titled_and_includes_the_cash_section(self):
        from utils import receipt_formatter as F
        C.set_many({"cash_drawer_enabled": "1", "cash_drawer_float": "100"})
        cashier, sup = _user("cashier"), _user("supervisor")
        sid = U.open_session(cashier)
        U.add_paid_out(sid, 20, "", sup, kind="safe_drop")
        s = U.get_session_by_id(sid)
        from core.db_checkout import session_totals
        lines = F.format_session_lines(s, session_totals(sid), "Cashier", {}, report_type="x",
                                       cash=CD.session_cash_summary(s))
        text = "\n".join(t for t, _k in lines)
        self.assertIn("X-REPORT", text)
        self.assertIn("Safe drops:", text)
        self.assertIn("Expected so far:", text)
