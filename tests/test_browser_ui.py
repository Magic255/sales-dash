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
    from playwright.sync_api import expect, sync_playwright

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

            expect(page.locator("#selected-company-name")).to_have_text("Browser Test Company")
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



def sign_in_browser(page, base_url):
    page.goto(base_url, wait_until="networkidle")
    page.locator("#email").fill("browser@example.test")
    page.locator("#password").fill("a-browser-only-test-password")
    page.get_by_role("button", name="Sign in securely").click()
    company_select = page.locator("#company-select")
    company_select.wait_for(state="visible")
    company_select.select_option("test-company-1")
    page.locator("#sales-workspace").wait_for(state="visible")


def test_admin_sales_reporting_invitation_and_audit_flows_work_in_browser(browser_server):
    from playwright.sync_api import expect, sync_playwright

    state = {
        "signed_in": False,
        "customers": [],
        "products": [],
        "sales": [],
        "invitations": [],
        "audit_requests": 0,
        "report_queries": [],
        "csv_exports": 0,
        "company_name": "Browser Test Company",
        "members": [
            {
                "user_id": "test-user-1",
                "display_name": "Browser Admin",
                "email": "browser@example.test",
                "role": "admin",
                "status": "active",
            },
            {
                "user_id": "member-user-1",
                "display_name": "Browser Member",
                "email": "member@example.test",
                "role": "salesperson",
                "status": "active",
            },
        ],
    }

    def api_response(route):
        request = route.request
        path = urlparse(request.url).path
        method = request.method
        payload = json.loads(request.post_data or "{}")

        if path == "/api/reports/sales.csv":
            state["csv_exports"] += 1
            route.fulfill(
                status=200,
                content_type="text/csv",
                headers={"Content-Disposition": "attachment; filename=sales-report.csv"},
                body="sale_number,status\nSD-TEST-0001,completed\n",
            )
            return
        if path == "/api/auth/csrf":
            data = {"csrf_token": "browser-test-token"}
        elif path == "/api/auth/login" and method == "POST":
            state["signed_in"] = True
            data = {"authenticated": True}
        elif path == "/api/auth/me":
            data = {
                "authenticated": state["signed_in"],
                "user": {"id": "test-user-1", "email": "browser@example.test"},
                "companies": [
                    {"id": "test-company-1", "name": "Browser Test Company", "role": "admin"}
                ] if state["signed_in"] else [],
                "selected_company": None,
            }
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
                "customers": len(state["customers"]),
                "products": len(state["products"]),
                "completed_sales": sum(
                    sale["status"] == "completed" for sale in state["sales"]
                ),
                "revenue_by_currency": [],
            }
        elif path == "/api/customers" and method == "POST":
            customer = {
                "id": "customer-1",
                "name": payload["name"],
                "email": payload.get("email", ""),
                "phone": payload.get("phone", ""),
                "organization": payload.get("organization", ""),
                "is_active": True,
            }
            state["customers"].append(customer)
            data = {"item": customer}
        elif path == "/api/customers":
            data = {"items": state["customers"]}
        elif path == "/api/products" and method == "POST":
            product = {
                "id": "product-1",
                "sku": payload["sku"],
                "name": payload["name"],
                "unit_price": payload["unit_price"],
                "currency": payload["currency"],
                "is_active": True,
            }
            state["products"].append(product)
            data = {"item": product}
        elif path == "/api/products":
            data = {"items": state["products"]}
        elif path == "/api/sales" and method == "POST":
            customer = state["customers"][0]
            product = state["products"][0]
            sale = {
                "id": "sale-1",
                "sale_number": "SD-TEST-0001",
                "sale_date": payload["sale_date"],
                "customer_id": customer["id"],
                "customer_name": customer["name"],
                "salesperson_user_id": "test-user-1",
                "status": "draft",
                "currency": product["currency"],
                "total_amount": product["unit_price"],
                "discount_amount": payload["discount_amount"],
                "tax_amount": payload["tax_amount"],
                "notes": payload["notes"],
                "items": [{
                    "product_name": product["name"],
                    "quantity": payload["items"][0]["quantity"],
                    "discount_amount": payload["items"][0]["discount_amount"],
                }],
            }
            state["sales"].append(sale)
            data = {"item": sale}
        elif path.startswith("/api/sales/") and path.endswith("/complete") and method == "POST":
            state["sales"][0]["status"] = "completed"
            data = {"item": state["sales"][0]}
        elif path == "/api/reports/sales":
            state["report_queries"].append(request.url)
            data = {
                "items": state["sales"],
                "completed_totals_by_currency": [],
                "limited": False,
                "count": len(state["sales"]),
            }
        elif path == "/api/sales-targets":
            data = {"company_targets": [], "salesperson_targets": [], "salespeople": []}
        elif path == "/api/dashboard/analytics":
            data = {"totals_by_currency": [], "daily_revenue": []}
        elif path == "/api/dashboard/salespeople":
            data = {"salespeople": []}
        elif path == "/api/audit-logs":
            state["audit_requests"] += 1
            data = {"items": []}
        elif path == "/api/team/members" and method == "GET":
            data = {"items": state["members"]}
        elif path.startswith("/api/team/members/") and method == "PATCH":
            member_id = path.rsplit("/", 1)[-1]
            member = next(item for item in state["members"] if item["user_id"] == member_id)
            member.update(payload)
            data = {"item": member}
        elif path == "/api/company/settings" and method == "GET":
            data = {"item": {"name": state["company_name"], "slug": "browser-test-company"}}
        elif path == "/api/company/settings" and method == "PATCH":
            state["company_name"] = payload["name"]
            data = {"item": {"name": state["company_name"], "slug": "browser-test-company"}}
        elif path == "/api/team/invitations" and method == "POST":
            invitation = {
                "id": "invitation-1",
                "email": payload["email"],
                "role": payload["role"],
                "expires_at": "2026-11-26T12:00:00Z",
            }
            state["invitations"].append(invitation)
            data = {"message": "Invitation sent."}
        elif path == "/api/team/invitations":
            data = {"items": state["invitations"]}
        else:
            data = {}

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(data),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block", accept_downloads=True)
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/api/**", api_response)

        try:
            sign_in_browser(page, browser_server)
            expect(page.locator("#audit-rows")).to_contain_text(
                "No security activity recorded yet."
            )

            page.locator('[data-workspace-tab="customers"]').click()
            page.locator("#customer-form").wait_for(state="visible")
            page.locator("#customer-name").fill("Acme Browser Test")
            page.locator("#customer-email").fill("acme@example.test")
            page.get_by_role("button", name="Add customer").click()
            expect(page.locator("#customer-rows")).to_contain_text("Acme Browser Test")

            page.locator('[data-workspace-tab="products"]').click()
            page.locator("#product-sku").fill("BROWSER-001")
            page.locator("#product-name").fill("Browser Test Service")
            page.locator("#product-price").fill("12500")
            page.get_by_role("button", name="Add product").click()
            expect(page.locator("#product-rows")).to_contain_text("Browser Test Service")

            page.locator('[data-workspace-tab="sales"]').click()
            page.locator("#sale-customer").select_option("customer-1")
            page.locator("#sale-product").select_option("product-1")
            page.locator("#sale-quantity").fill("2")
            page.get_by_role("button", name="Save draft sale").click()
            expect(page.locator("#sales-rows")).to_contain_text("SD-TEST-0001")

            page.get_by_role("button", name="Complete").click()
            expect(page.locator("#sales-rows")).to_contain_text("completed")

            page.locator('[data-workspace-tab="reports"]').click()
            page.locator("#report-from").fill("2026-11-01")
            page.locator("#report-to").fill("2026-11-30")
            page.locator("#report-status").select_option("completed")
            page.get_by_role("button", name="Run report").click()
            expect(page.locator("#report-rows")).to_contain_text("SD-TEST-0001")
            assert any(
                "from=2026-11-01" in query
                and "to=2026-11-30" in query
                and "status=completed" in query
                for query in state["report_queries"]
            )

            with page.expect_download() as download_info:
                page.locator("#report-export").click()
            assert download_info.value.suggested_filename == "sales-report.csv"
            assert state["csv_exports"] == 1

            page.locator("#team-tab").click()
            page.locator("#invitation-email").fill("new-member@example.test")
            page.locator("#invitation-role").select_option("salesperson")
            page.get_by_role("button", name="Send invitation").click()
            expect(page.locator("#invitation-rows")).to_contain_text("new-member@example.test")
            expect(page.locator("#invitation-rows")).to_contain_text("salesperson")

            member_role = page.get_by_role("combobox", name="Role for member@example.test")
            member_role.select_option("manager")
            page.get_by_role("button", name="Save role").click()
            expect(
                page.get_by_role("combobox", name="Role for member@example.test")
            ).to_have_value("manager")
            assert state["members"][1]["role"] == "manager"

            page.get_by_role("button", name="Suspend").click()
            expect(page.locator("#team-member-rows")).to_contain_text("Suspended")
            page.get_by_role("button", name="Reactivate").click()
            assert state["members"][1]["status"] == "active"

            page.locator("#company-settings-tab").click()
            expect(page.locator("#company-settings-name")).to_have_value("Browser Test Company")
            page.locator("#company-settings-name").fill("Updated Browser Company")
            page.get_by_role("button", name="Save company name").click()
            expect(page.locator("#company-settings-message")).to_contain_text(
                "Company name updated."
            )
            assert state["company_name"] == "Updated Browser Company"

            with page.expect_response(lambda response: "/api/audit-logs" in response.url):
                page.locator("#audit-refresh").click()
            assert state["audit_requests"] >= 2
            assert not page_errors, "Browser JavaScript errors: " + "; ".join(page_errors)
        finally:
            browser.close()


def test_viewer_role_cannot_see_write_or_admin_controls_in_browser(browser_server):
    from playwright.sync_api import expect, sync_playwright

    state = {"signed_in": False}

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
            data = {
                "authenticated": state["signed_in"],
                "user": {"id": "viewer-user-1", "email": "viewer@example.test"},
                "companies": [
                    {"id": "test-company-1", "name": "Viewer Test Company", "role": "viewer"}
                ] if state["signed_in"] else [],
                "selected_company": None,
            }
        elif path == "/api/auth/mfa/status":
            data = {"enabled": False}
        elif path == "/api/auth/company" and method == "POST":
            data = {
                "selected_company": {
                    "id": "test-company-1",
                    "name": "Viewer Test Company",
                    "role": "viewer",
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
            data = {
                "items": [],
                "completed_totals_by_currency": [],
                "limited": False,
                "count": 0,
            }
        elif path == "/api/dashboard/analytics":
            data = {"totals_by_currency": [], "daily_revenue": []}
        elif path == "/api/dashboard/salespeople":
            data = {"salespeople": []}
        elif path == "/api/sales-targets":
            data = {"company_targets": [], "salesperson_targets": [], "salespeople": []}
        else:
            data = {}

        route.fulfill(
            status=200,
            content_type="application/json",
            body=json.dumps(data),
        )

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(service_workers="block")
        page = context.new_page()
        page_errors = []
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        page.route("**/api/**", api_response)

        try:
            sign_in_browser(page, browser_server)
            expect(page.locator("#customer-form")).to_be_hidden()
            expect(page.locator("#product-form")).to_be_hidden()
            expect(page.locator("#sale-form")).to_be_hidden()
            expect(page.locator("#team-tab")).to_be_hidden()
            expect(page.locator("#company-settings-tab")).to_be_hidden()
            expect(page.locator("#audit-panel")).to_be_hidden()
            assert not page_errors, "Browser JavaScript errors: " + "; ".join(page_errors)
        finally:
            browser.close()
