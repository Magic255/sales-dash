import json
import threading
from urllib.parse import urlparse

import pytest
from werkzeug.serving import make_server

from app import create_app


@pytest.fixture()
def browser_server():
    app = create_app(
        {
            "TESTING": True,
            "SECRET_KEY": "browser-test-only-secret",
            "SQLALCHEMY_DATABASE_URI": "sqlite://",
            "WTF_CSRF_ENABLED": False,
            "RATELIMIT_ENABLED": False,
        }
    )
    server = make_server("127.0.0.1", 0, app, threaded=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        thread.join(timeout=5)


def test_sign_in_company_selection_and_dashboard_controls_work_in_browser(browser_server):
    from playwright.sync_api import sync_playwright

    state = {"signed_in": False, "analytics_requests": 0}

    def api_response(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method

        if path == "/api/auth/csrf":
            data = {"csrf_token": "browser-test-token"}
        elif path == "/api/auth/login" and method == "POST":
            state["signed_in"] = True
            data = {"authenticated": True}
        elif path == "/api/auth/me":
            if state["signed_in"]:
                data = {
                    "authenticated": True,
                    "user": {"id": "test-user-1", "email": "browser@example.test"},
                    "companies": [
                        {"id": "test-company-1", "name": "Browser Test Company", "role": "admin"}
                    ],
                    "selected_company": None,
                }
            else:
                data = {"authenticated": False}
        elif path == "/api/auth/mfa/status":
            data = {"enabled": False}
        elif path == "/api/auth/company" and method == "POST":
            data = {
                "selected_company": {
                    "id": "test-company-1",
                    "name": "Browser Test Company",
                    "role": "admin",
                }
            }
        elif path == "/api/dashboard/summary":
            data = {
                "customers": 0,
                "products": 0,
                "completed_sales": 0,
                "revenue_by_currency": [],
            }
        elif path in ("/api/customers", "/api/products", "/api/reports/sales"):
            data = {"items": []}
        elif path == "/api/sales-targets":
            data = {"company_targets": [], "salesperson_targets": [], "salespeople": []}
        elif path == "/api/dashboard/analytics":
            state["analytics_requests"] += 1
            data = {"totals_by_currency": [], "daily_revenue": []}
        elif path == "/api/dashboard/salespeople":
            data = {"salespeople": []}
        elif path == "/api/audit-logs":
            data = {"items": []}
        else:
            data = {}

        route.fulfill(status=200, content_type="application/json", body=json.dumps(data))

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/api/**", api_response)

        try:
            page.goto(browser_server, wait_until="networkidle")
            assert page.get_by_role("heading", name="Sign in to SALES DASH").is_visible()

            page.locator("#email").fill("browser@example.test")
            page.locator("#password").fill("a-browser-only-test-password")
            page.get_by_role("button", name="Sign in securely").click()

            company_select = page.locator("#company-select")
            company_select.wait_for(state="visible")
            company_select.select_option("test-company-1")

            assert page.locator("#selected-company-name").inner_text() == "Browser Test Company"
            page.locator("#sales-workspace").wait_for(state="visible")
            assert page.locator("#metric-customers").inner_text() == "0"

            initial_analytics_requests = state["analytics_requests"]
            with page.expect_response(
                lambda response: "/api/dashboard/analytics" in response.url
            ):
                page.get_by_role("button", name="Update trend").click()
            assert state["analytics_requests"] > initial_analytics_requests

            page.locator('[data-workspace-tab="customers"]').click()
            assert page.locator('[data-workspace-panel="customers"]').is_visible()
            assert not page_errors, "Browser JavaScript errors: " + "; ".join(page_errors)
        finally:
            browser.close()
