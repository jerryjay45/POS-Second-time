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
