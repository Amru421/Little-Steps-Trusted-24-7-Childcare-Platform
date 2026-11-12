import http.cookiejar
import json
import os
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from pathlib import Path

import server as app


class NestcareAPITests(unittest.TestCase):
    def test_production_bootstrap_creates_only_configured_admin(self):
        original_db_path = app.DB_PATH
        previous = {
            key: os.environ.get(key)
            for key in ("NESTCARE_DEMO_DATA", "NESTCARE_ADMIN_EMAIL", "NESTCARE_ADMIN_PASSWORD")
        }
        with tempfile.TemporaryDirectory() as directory:
            app.DB_PATH = Path(directory) / "production.sqlite3"
            os.environ["NESTCARE_DEMO_DATA"] = "false"
            os.environ["NESTCARE_ADMIN_EMAIL"] = "deployment-admin@example.test"
            os.environ["NESTCARE_ADMIN_PASSWORD"] = "UniqueProductionAdminPass123!"
            try:
                app.initialize()
                with app.database() as db:
                    users = db.execute("SELECT email,role FROM users").fetchall()
                    center_count = db.execute("SELECT COUNT(*) FROM centers").fetchone()[0]
                self.assertEqual([(row["email"], row["role"]) for row in users],
                                 [("deployment-admin@example.test", "admin")])
                self.assertEqual(center_count, 0)
            finally:
                app.DB_PATH = original_db_path
                for key, value in previous.items():
                    if value is None:
                        os.environ.pop(key, None)
                    else:
                        os.environ[key] = value

    @classmethod
    def setUpClass(cls):
        cls.temp_dir = tempfile.TemporaryDirectory()
        cls.original_db_path = app.DB_PATH
        app.DB_PATH = Path(cls.temp_dir.name) / "test.sqlite3"
        app.initialize()
        cls.httpd = app.ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        cls.thread = threading.Thread(target=cls.httpd.serve_forever, daemon=True)
        cls.thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.httpd.server_port}"
        cls.admin = cls.opener()
        cls.admin_user = cls.request_json(
            cls.admin, "POST", "/api/login",
            {"email": "admin@nestcare.local", "password": "NestcareAdmin123!"},
        )["user"]
        cls.provider = cls.opener()
        cls.provider_user = cls.request_json(
            cls.provider, "POST", "/api/login",
            {"email": "provider@nestcare.local", "password": "NestcareProvider123!"},
        )["user"]
        cls.parent = cls.opener()
        cls.parent_user = cls.request_json(
            cls.parent, "POST", "/api/register",
            {"name": "Test Parent", "email": "parent-test@example.local", "password": "ParentPass123!", "role": "parent"},
        )["user"]
        admin_data = cls.request_json(cls.admin, "GET", "/api/admin/overview")
        parent_record = next(user for user in admin_data["users"] if user["email"] == "parent-test@example.local")
        cls.request_json(cls.admin, "PATCH", f"/api/admin/users/{parent_record['id']}", {"status": "active"})
        cls.center_id = cls.request_json(cls.parent, "GET", "/api/centers?city=Bengaluru")["centers"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.thread.join(timeout=3)
        app.DB_PATH = cls.original_db_path
        cls.temp_dir.cleanup()

    @classmethod
    def opener(cls):
        return urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))

    @classmethod
    def request_json(cls, opener, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        request = urllib.request.Request(
            cls.base_url + path, data=data, method=method,
            headers={"Content-Type": "application/json"} if body is not None else {},
        )
        try:
            with opener.open(request, timeout=5) as response:
                return json.loads(response.read())
        except urllib.error.HTTPError as error:
            status, body = error.code, error.read()
            error.close()
            return {"_status": status, **json.loads(body)}

    def booking_request(self):
        return self.request_json(
            self.parent, "POST", "/api/bookings",
            {"centerId": self.center_id, "childName": "Mira", "childAge": "Toddler",
             "date": (date.today() + timedelta(days=3)).isoformat(), "plan": "daily", "notes": "Test booking"},
        )

    def test_search_filters_verified_centers(self):
        result = self.request_json(self.parent, "GET", "/api/centers?city=Bengaluru&age=Infant&hours=24")
        self.assertGreaterEqual(len(result["centers"]), 1)
        self.assertTrue(all(center["verified"] for center in result["centers"]))
        self.assertTrue(all("Infant" in center["age_groups"] for center in result["centers"]))

    def test_availability_checks_date_and_hourly_time_ranges(self):
        target_date = (date.today() + timedelta(days=4)).isoformat()
        daily = self.request_json(
            self.parent, "GET",
            f"/api/availability?centerId={self.center_id}&date={target_date}&plan=daily",
        )
        self.assertTrue(daily["available"])
        hourly = self.request_json(
            self.parent, "GET",
            f"/api/availability?centerId={self.center_id}&date={target_date}&plan=hourly&startTime=09%3A00&endTime=11%3A00",
        )
        self.assertEqual(hourly["availableSlots"], daily["availableSlots"])

    def test_capacity_is_rechecked_when_booking_is_submitted(self):
        target_date = (date.today() + timedelta(days=6)).isoformat()
        with app.database() as db:
            db.execute("UPDATE centers SET capacity=1 WHERE id=?", (self.center_id,))
        first = self.request_json(
            self.parent, "POST", "/api/bookings",
            {"centerId": self.center_id, "childName": "Mira", "childAge": "Toddler",
             "date": target_date, "plan": "daily"},
        )
        self.assertIn("bookingId", first)
        availability = self.request_json(
            self.parent, "GET",
            f"/api/availability?centerId={self.center_id}&date={target_date}&plan=daily",
        )
        self.assertFalse(availability["available"])
        second = self.request_json(
            self.parent, "POST", "/api/bookings",
            {"centerId": self.center_id, "childName": "Noah", "childAge": "Toddler",
             "date": target_date, "plan": "daily"},
        )
        self.assertEqual(second["_status"], 409)
        with app.database() as db:
            db.execute("UPDATE centers SET capacity=18 WHERE id=?", (self.center_id,))

    def test_parent_can_request_booking_and_provider_can_confirm(self):
        result = self.booking_request()
        self.assertIn("bookingId", result)
        provider_bookings = self.request_json(self.provider, "GET", "/api/bookings")["bookings"]
        self.assertTrue(any(item["id"] == result["bookingId"] for item in provider_bookings))
        update = self.request_json(
            self.provider, "PATCH", f"/api/bookings/{result['bookingId']}", {"status": "confirmed"}
        )
        self.assertIn("message", update)
        parent_bookings = self.request_json(self.parent, "GET", "/api/bookings")["bookings"]
        self.assertEqual(next(x for x in parent_bookings if x["id"] == result["bookingId"])["status"], "confirmed")
        cancelled = self.request_json(
            self.parent, "PATCH", f"/api/bookings/{result['bookingId']}", {"status": "cancelled"}
        )
        self.assertIn("message", cancelled)
        parent_bookings = self.request_json(self.parent, "GET", "/api/bookings")["bookings"]
        self.assertEqual(next(x for x in parent_bookings if x["id"] == result["bookingId"])["status"], "cancelled")

    def test_parent_can_request_monthly_care(self):
        result = self.request_json(
            self.parent, "POST", "/api/subscriptions",
            {"centerId": self.center_id, "childName": "Mira", "childAge": "Toddler",
             "startDate": (date.today() + timedelta(days=10)).isoformat()},
        )
        self.assertIn("subscriptionId", result)
        rows = self.request_json(self.provider, "GET", "/api/subscriptions")["subscriptions"]
        self.assertTrue(any(row["id"] == result["subscriptionId"] for row in rows))

    def test_provider_registration_requires_admin_review(self):
        application = self.request_json(
            self.parent, "POST", "/api/register",
            {"name": "New Provider", "email": "new-provider@example.local", "password": "ProviderPass123!",
             "role": "provider", "centerName": "Sunshine Center", "city": "Pune", "address": "Koregaon Park",
             "capacity": 8, "ageGroups": ["Infant", "Toddler"], "certifications": ["First aid"]},
        )
        self.assertEqual(application["user"]["status"], "pending")
        self.assertEqual(application["user"]["role"], "provider")
        admin_data = self.request_json(self.admin, "GET", "/api/admin/overview")
        target = next(user for user in admin_data["users"] if user["email"] == "new-provider@example.local")
        approved = self.request_json(
            self.admin, "PATCH", f"/api/admin/users/{target['id']}", {"status": "active"}
        )
        self.assertIn("message", approved)
        self.assertEqual(self.request_json(self.admin, "GET", "/api/admin/overview")["stats"]["providers"], 2)
        center = next(
            item for item in self.request_json(self.admin, "GET", "/api/admin/overview")["centers"]
            if item["name"] == "Sunshine Center"
        )
        self.assertEqual(self.request_json(self.admin, "GET", "/api/centers?city=Pune")["centers"], [])
        self.request_json(self.admin, "PATCH", f"/api/admin/centers/{center['id']}", {"verified": True})
        self.assertEqual(len(self.request_json(self.admin, "GET", "/api/centers?city=Pune")["centers"]), 1)

    def test_parent_account_requires_admin_approval(self):
        account = self.request_json(
            self.parent, "POST", "/api/register",
            {"name": "Pending Parent", "email": "pending-parent@example.local",
             "password": "PendingPass123!", "role": "parent"},
        )
        self.assertEqual(account["user"]["status"], "pending")
        blocked = self.request_json(self.parent, "GET", "/api/bookings")
        self.assertEqual(blocked["_status"], 403)
        overview = self.request_json(self.admin, "GET", "/api/admin/overview")
        user = next(x for x in overview["users"] if x["email"] == "pending-parent@example.local")
        self.request_json(self.admin, "PATCH", f"/api/admin/users/{user['id']}", {"status": "active"})
        self.assertEqual(self.request_json(self.parent, "GET", "/api/bookings")["bookings"], [])

    def test_provider_can_update_capacity_pricing_and_caregivers(self):
        result = self.request_json(
            self.provider, "PATCH", "/api/provider/center",
            {"hours": "Open 24 hours", "capacity": 20, "description": "Family-run childcare.",
             "ageGroups": ["Infant", "Toddler", "Preschool"], "certifications": ["First aid"],
             "plans": {"hourly": 190, "daily": 980, "monthly": 14600},
             "caregivers": [{"name": "Meera", "role": "Lead caregiver", "experience": "8 years"}]},
        )
        self.assertIn("message", result)
        center = self.request_json(self.provider, "GET", "/api/provider/center")["center"]
        self.assertEqual(center["capacity"], 20)
        self.assertEqual(center["caregivers"][0]["name"], "Meera")

    def test_roles_cannot_access_admin_overview(self):
        response = self.request_json(self.parent, "GET", "/api/admin/overview")
        self.assertEqual(response["_status"], 403)

    def test_public_feedback_is_validated_and_visible_only_to_admins(self):
        response = self.request_json(
            self.parent, "POST", "/api/feedback",
            {"rating": 5, "category": "search", "message": "The center search was clear and easy to use."},
        )
        self.assertIn("feedbackId", response)
        overview = self.request_json(self.admin, "GET", "/api/admin/overview")
        feedback = next(item for item in overview["feedback"] if item["id"] == response["feedbackId"])
        self.assertEqual(feedback["rating"], 5)
        self.assertEqual(feedback["category"], "search")
        self.assertEqual(feedback["message"], "The center search was clear and easy to use.")

        invalid = self.request_json(
            self.parent, "POST", "/api/feedback",
            {"rating": 6, "category": "search", "message": "This rating should be rejected."},
        )
        self.assertEqual(invalid["_status"], 400)
        invalid_topic = self.request_json(
            self.parent, "POST", "/api/feedback",
            {"rating": 4, "category": "unknown", "message": "This topic should be rejected."},
        )
        self.assertEqual(invalid_topic["_status"], 400)

    def test_explainer_page_works_without_a_video_asset(self):
        with self.parent.open(self.base_url + "/explainer.html", timeout=5) as response:
            page = response.read().decode("utf-8")
        self.assertIn("Explore Nestcare.", page)
        self.assertIn("What you’ll see", page)
        self.assertNotIn(".webm", page)

    def test_family_concern_is_visible_and_resolvable_by_admin(self):
        booking = self.booking_request()
        report = self.request_json(
            self.parent, "POST", "/api/disputes",
            {"bookingId": booking["bookingId"], "message": "Test concern"},
        )
        self.assertIn("message", report)
        overview = self.request_json(self.admin, "GET", "/api/admin/overview")
        dispute = next(item for item in overview["disputes"] if item["message"] == "Test concern")
        result = self.request_json(
            self.admin, "PATCH", f"/api/admin/disputes/{dispute['id']}", {"status": "resolved"}
        )
        self.assertIn("message", result)


if __name__ == "__main__":
    unittest.main()
