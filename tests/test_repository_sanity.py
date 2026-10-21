from pathlib import Path
import re
import unittest

ROOT = Path(__file__).resolve().parents[1]


class RepositorySanityTests(unittest.TestCase):
    def read(self, name):
        return (ROOT / name).read_text(encoding="utf-8")

    def test_required_schema_features_exist(self):
        schema = self.read("schema.sql").lower()
        for fragment in (
            "create table if not exists users",
            "create table if not exists orders",
            "create table if not exists tickets",
            "create table if not exists ticket_types",
            "create table if not exists ticket_files",
            "delivery_started_at",
            "ticket_type_id",
            "is_checked_in",
            "create table if not exists user_menu",
            "create table if not exists support_tickets",
        ):
            with self.subTest(fragment=fragment):
                self.assertIn(fragment, schema)

    def test_only_tier_checkout_owns_buy_callback(self):
        payment = self.read("handlers_payment.py")
        user = self.read("handlers_user.py")
        self.assertEqual(payment.count('F.data == "menu:buy"'), 1)
        self.assertNotIn('F.data == "menu:buy"', user)

    def test_phonepe_fails_closed_until_configured(self):
        phonepe = self.read("services_phonepe.py")
        self.assertIn("raise PhonePeError", phonepe)
        self.assertIn("return False", phonepe)

    def test_polling_has_database_lock(self):
        main = self.read("main.py")
        self.assertIn("pg_try_advisory_lock", main)
        self.assertIn("run_single_poller(dp, bot)", main)

    def test_parameterized_sql_used_for_user_input(self):
        payment = self.read("handlers_payment.py")
        self.assertIn("WHERE id=$1", payment)
        self.assertIn("WHERE order_id=$1", payment)


if __name__ == "__main__":
    unittest.main()
