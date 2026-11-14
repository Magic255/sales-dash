const workspace = document.querySelector("#sales-workspace");
let workspaceRole = "";
let workspaceUserId = "";
let customers = [];
let products = [];
let workspaceGeneration = 0;

function workspaceMessage(message) {
  document.querySelector("#workspace-message").textContent = message;
}

async function workspaceRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body) headers.set("Content-Type", "application/json");
  if (!["GET", "HEAD", "OPTIONS"].includes(method)) {
    if (!csrfToken) await refreshCsrfToken();
    headers.set("X-CSRFToken", csrfToken);
  }
  const response = await fetch(path, {
    ...options, method, headers, credentials: "same-origin",
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || "Could not complete that action.");
  return data;
}

function textCell(row, value) {
  const cell = document.createElement("td");
  cell.textContent = value == null || value === "" ? "—" : String(value);
  row.append(cell);
}

function emptyRow(tbody, columns, message) {
  const row = document.createElement("tr");
  const cell = document.createElement("td");
  cell.colSpan = columns;
  cell.textContent = message;
  row.append(cell);
  tbody.replaceChildren(row);
}

function amount(currency, value) {
  return currency + " " + Number(value).toLocaleString(undefined, {
    minimumFractionDigits: 2, maximumFractionDigits: 2,
  });
}

function selectTab(name) {
  document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
    const active = button.dataset.workspaceTab === name;
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-current", active ? "page" : "false");
  });
  document.querySelectorAll("[data-workspace-panel]").forEach((panel) => {
    panel.hidden = panel.dataset.workspacePanel !== name;
  });
}

function renderCustomers() {
  const body = document.querySelector("#customer-rows");
  body.replaceChildren();
  if (!customers.length) return emptyRow(body, 3, "No customers yet. Add the first customer above.");
  for (const item of customers) {
    const row = document.createElement("tr");
    textCell(row, item.name);
    textCell(row, item.email);
    textCell(row, item.phone);
    body.append(row);
  }
}

function renderProducts() {
  const body = document.querySelector("#product-rows");
  body.replaceChildren();
  if (!products.length) return emptyRow(body, 4, "No products yet. Add the first product above.");
  for (const item of products) {
    const row = document.createElement("tr");
    textCell(row, item.sku);
    textCell(row, item.name);
    textCell(row, amount(item.currency, item.unit_price));
    textCell(row, item.currency);
    body.append(row);
  }
}

function fillSaleChoices() {
  const customer = document.querySelector("#sale-customer");
  const product = document.querySelector("#sale-product");
  customer.replaceChildren(new Option(customers.length ? "Choose a customer" : "Add a customer first", ""));
  product.replaceChildren(new Option(products.length ? "Choose a product" : "Add a product first", ""));
  customers.forEach((item) => customer.add(new Option(item.name, item.id)));
  products.forEach((item) => product.add(new Option(
    item.name + " · " + amount(item.currency, item.unit_price), item.id,
  )));
}

async function loadSales(generation) {
  const data = await workspaceRequest("/api/reports/sales");
  if (generation !== workspaceGeneration) return;
  const body = document.querySelector("#sales-rows");
  body.replaceChildren();
  if (!data.items.length) return emptyRow(body, 6, "No sales recorded yet.");
  for (const sale of data.items) {
    const row = document.createElement("tr");
    textCell(row, sale.sale_number);
    textCell(row, sale.sale_date);
    textCell(row, sale.customer_name);
    textCell(row, sale.status);
    textCell(row, amount(sale.currency, sale.total_amount));
    const actions = document.createElement("td");
    const canComplete = sale.status === "draft" && (
      ["admin", "manager"].includes(workspaceRole) ||
      sale.salesperson_user_id === workspaceUserId
    );
    if (canComplete) {
      const complete = document.createElement("button");
      complete.type = "button";
      complete.className = "table-action";
      complete.textContent = "Complete";
      complete.addEventListener("click", async () => {
        complete.disabled = true;
        try {
          await workspaceRequest("/api/sales/" + encodeURIComponent(sale.id) + "/complete", {
            method: "POST", body: "{}",
          });
          await loadWorkspace();
        } catch (error) {
          workspaceMessage(error.message);
          complete.disabled = false;
        }
      });
      actions.append(complete);
    }
    if (sale.status === "draft" && ["admin", "manager"].includes(workspaceRole)) {
      const edit = document.createElement("button");
      edit.type = "button";
      edit.className = "table-action";
      edit.textContent = "Edit";
      edit.addEventListener("click", async () => {
        const first = sale.items[0];
        if (!first) return workspaceMessage("This sale has no editable items.");
        const quantity = window.prompt("Quantity for " + first.product_name + ":", first.quantity);
        if (quantity === null) return;
        const lineDiscounts = sale.items.reduce((sum, item) => sum + Number(item.discount_amount), 0);
        const orderDiscount = Math.max(0, Number(sale.discount_amount) - lineDiscounts);
        const payload = {
          customer_id: sale.customer_id, currency: sale.currency, sale_date: sale.sale_date,
          discount_amount: orderDiscount.toFixed(2), tax_amount: sale.tax_amount,
          notes: sale.notes || "",
          items: sale.items.map((item, index) => ({
            product_id: item.product_id,
            quantity: index === 0 ? quantity : item.quantity,
            discount_amount: item.discount_amount,
          })),
        };
        edit.disabled = true;
        try {
          await workspaceRequest("/api/sales/" + encodeURIComponent(sale.id), {
            method: "PATCH", body: JSON.stringify(payload),
          });
          await loadWorkspace();
          workspaceMessage("Draft sale updated.");
        } catch (error) {
          workspaceMessage(error.message);
          edit.disabled = false;
        }
      });
      actions.append(edit);
    }
    if (sale.status !== "void" && workspaceRole === "admin") {
      const voidButton = document.createElement("button");
      voidButton.type = "button";
      voidButton.className = "table-action table-action-danger";
      voidButton.textContent = "Void";
      voidButton.addEventListener("click", async () => {
        if (!window.confirm("Void this sale? This cannot be undone.")) return;
        voidButton.disabled = true;
        try {
          await workspaceRequest("/api/sales/" + encodeURIComponent(sale.id) + "/void", {
            method: "POST", body: "{}",
          });
          await loadWorkspace();
        } catch (error) {
          workspaceMessage(error.message);
          voidButton.disabled = false;
        }
      });
      actions.append(voidButton);
    }
    if (!actions.childElementCount) actions.textContent = "—";
    row.append(actions);
    body.append(row);
  }
}

async function loadWorkspace() {
  const generation = workspaceGeneration;
  workspaceMessage("Loading company data…");
  try {
    const [summary, customerData, productData] = await Promise.all([
      workspaceRequest("/api/dashboard/summary"),
      workspaceRequest("/api/customers"),
      workspaceRequest("/api/products"),
    ]);
    if (generation !== workspaceGeneration) return;
    customers = customerData.items;
    products = productData.items;
    document.querySelector("#metric-customers").textContent = summary.customers;
    document.querySelector("#metric-products").textContent = summary.products;
    document.querySelector("#metric-sales").textContent = summary.completed_sales;
    document.querySelector("#metric-revenue").textContent = summary.revenue_by_currency.length
      ? summary.revenue_by_currency.map((item) => amount(item.currency, item.amount)).join(" · ")
      : "—";
    renderCustomers();
    renderProducts();
    fillSaleChoices();
    await loadSales(generation);
    if (generation === workspaceGeneration) {
      workspaceMessage("Company data is up to date.");
    }
  } catch (error) {
    if (generation === workspaceGeneration) workspaceMessage(error.message);
  }
}

function localDate() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

document.addEventListener("salesdash:company-selected", (event) => {
  workspaceGeneration += 1;
  workspaceRole = event.detail.role;
  workspaceUserId = event.detail.userId;
  customers = [];
  products = [];
  renderCustomers();
  renderProducts();
  fillSaleChoices();
  emptyRow(document.querySelector("#sales-rows"), 6, "Loading sales…");
  document.querySelector("#metric-customers").textContent = "—";
  document.querySelector("#metric-products").textContent = "—";
  document.querySelector("#metric-sales").textContent = "—";
  document.querySelector("#metric-revenue").textContent = "—";
  workspace.hidden = false;
  document.querySelector("#customer-form").hidden = workspaceRole === "viewer";
  document.querySelector("#product-form").hidden = !["admin", "manager"].includes(workspaceRole);
  document.querySelector("#sale-form").hidden = workspaceRole === "viewer";
  document.querySelector("#team-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#company-settings-tab").hidden = workspaceRole !== "admin";
  if (workspaceRole !== "admin") selectTab("overview");
  loadWorkspace();
});

document.addEventListener("salesdash:signed-out", () => {
  workspaceGeneration += 1;
  customers = [];
  products = [];
  workspace.hidden = true;
});

document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
  button.addEventListener("click", () => selectTab(button.dataset.workspaceTab));
});

document.querySelector("#workspace-refresh").addEventListener("click", loadWorkspace);

document.querySelector("#customer-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await workspaceRequest("/api/customers", {
      method: "POST",
      body: JSON.stringify({
        name: document.querySelector("#customer-name").value,
        email: document.querySelector("#customer-email").value,
        phone: document.querySelector("#customer-phone").value,
        organization: document.querySelector("#customer-organization").value,
      }),
    });
    form.reset();
    selectTab("customers");
    await loadWorkspace();
  } catch (error) {
    workspaceMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#product-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await workspaceRequest("/api/products", {
      method: "POST",
      body: JSON.stringify({
        sku: document.querySelector("#product-sku").value,
        name: document.querySelector("#product-name").value,
        unit_price: document.querySelector("#product-price").value,
        currency: document.querySelector("#product-currency").value,
      }),
    });
    form.reset();
    document.querySelector("#product-currency").value = "TZS";
    selectTab("products");
    await loadWorkspace();
  } catch (error) {
    workspaceMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#sale-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const product = products.find((item) => item.id === document.querySelector("#sale-product").value);
  if (!product) return workspaceMessage("Choose a product first.");
  button.disabled = true;
  try {
    const saved = await workspaceRequest("/api/sales", {
      method: "POST",
      body: JSON.stringify({
        customer_id: document.querySelector("#sale-customer").value,
        currency: product.currency,
        sale_date: document.querySelector("#sale-date").value,
        discount_amount: document.querySelector("#sale-discount").value || "0",
        tax_amount: document.querySelector("#sale-tax").value || "0",
        notes: document.querySelector("#sale-notes").value,
        items: [{
          product_id: product.id,
          quantity: document.querySelector("#sale-quantity").value,
          discount_amount: document.querySelector("#sale-item-discount").value || "0",
        }],
      }),
    });
    form.reset();
    document.querySelector("#sale-date").value = localDate();
    document.querySelector("#sale-quantity").value = "1";
    document.querySelector("#sale-item-discount").value = "0";
    document.querySelector("#sale-discount").value = "0";
    document.querySelector("#sale-tax").value = "0";
    selectTab("sales");
    workspaceMessage("Draft " + saved.item.sale_number + " saved.");
    await loadWorkspace();
  } catch (error) {
    workspaceMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#sale-date").value = localDate();
selectTab("overview");



async function loadSalesReport() {
  const params = new URLSearchParams();
  const from = document.querySelector("#report-from").value;
  const to = document.querySelector("#report-to").value;
  const status = document.querySelector("#report-status").value;
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  if (status) params.set("status", status);
  const data = await workspaceRequest("/api/reports/sales?" + params.toString());
  const body = document.querySelector("#report-rows");
  body.replaceChildren();
  if (!data.items.length) return emptyRow(body, 6, "No sales match these filters.");
  for (const sale of data.items) {
    const row = document.createElement("tr");
    textCell(row, sale.sale_number);
    textCell(row, sale.sale_date);
    textCell(row, sale.customer_name);
    textCell(row, sale.status);
    textCell(row, amount(sale.currency, sale.total_amount));
    textCell(row, sale.items.map((item) => item.product_name + " × " + item.quantity).join(", "));
    body.append(row);
  }
  const totals = data.completed_totals_by_currency.map((item) => amount(item.currency, item.amount)).join(" · ");
  document.querySelector("#report-totals").textContent = "Completed revenue: " + (totals || "—");
  document.querySelector("#report-limit").textContent = data.limited
    ? "Showing the first 500 matching sales. Narrow the date range for a complete view."
    : data.count + " matching sales.";
}

document.querySelector("#report-filter-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadSalesReport();
  } catch (error) {
    workspaceMessage(error.message);
  }
});

document.querySelector("#report-export").addEventListener("click", async () => {
  const params = new URLSearchParams();
  const from = document.querySelector("#report-from").value;
  const to = document.querySelector("#report-to").value;
  const status = document.querySelector("#report-status").value;
  if (from) params.set("from", from);
  if (to) params.set("to", to);
  if (status) params.set("status", status);
  try {
    const response = await fetch("/api/reports/sales.csv?" + params.toString(), {
      credentials: "same-origin",
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "Could not export this report.");
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = "sales-report.csv";
    link.click();
    URL.revokeObjectURL(url);
  } catch (error) {
    workspaceMessage(error.message);
  }
});


async function loadCompanyInvitations() {
  const body = document.querySelector("#invitation-rows");
  if (!body || workspaceRole !== "admin") return;
  try {
    const data = await workspaceRequest("/api/team/invitations");
    body.replaceChildren();
    if (!data.items.length) return emptyRow(body, 4, "No pending invitations.");
    for (const item of data.items) {
      const row = document.createElement("tr");
      textCell(row, item.email);
      textCell(row, item.role);
      const expiry = new Date(item.expires_at);
      textCell(row, Number.isNaN(expiry.getTime()) ? item.expires_at : expiry.toLocaleString());
      const actions = document.createElement("td");
      const revoke = document.createElement("button");
      revoke.type = "button";
      revoke.className = "table-action table-action-danger";
      revoke.textContent = "Revoke";
      revoke.addEventListener("click", async () => {
        revoke.disabled = true;
        try {
          await workspaceRequest("/api/team/invitations/" + encodeURIComponent(item.id), {
            method: "DELETE",
          });
          await loadCompanyInvitations();
          workspaceMessage("Invitation revoked.");
        } catch (error) {
          workspaceMessage(error.message);
          revoke.disabled = false;
        }
      });
      actions.append(revoke);
      row.append(actions);
      body.append(row);
    }
  } catch (error) {
    workspaceMessage(error.message);
  }
}

document.querySelector("#invitation-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    const result = await workspaceRequest("/api/team/invitations", {
      method: "POST",
      body: JSON.stringify({
        email: document.querySelector("#invitation-email").value,
        role: document.querySelector("#invitation-role").value,
      }),
    });
    form.reset();
    workspaceMessage(result.message);
    await loadCompanyInvitations();
  } catch (error) {
    workspaceMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

async function loadTeamMembers() {
  const body = document.querySelector("#team-member-rows");
  if (!body || workspaceRole !== "admin") return;
  try {
    const data = await workspaceRequest("/api/team/members");
    body.replaceChildren();
    if (!data.items.length) return emptyRow(body, 5, "No company members found.");
    for (const item of data.items) {
      const row = document.createElement("tr");
      textCell(row, item.display_name || item.email);
      textCell(row, item.email);

      const roleCell = document.createElement("td");
      const actions = document.createElement("td");
      if (item.role === "admin") {
        roleCell.textContent = "Admin";
      } else {
        const roleSelect = document.createElement("select");
        roleSelect.setAttribute("aria-label", "Role for " + item.email);
        for (const [value, label] of [
          ["manager", "Manager"], ["salesperson", "Salesperson"], ["viewer", "Viewer"],
        ]) {
          roleSelect.add(new Option(label, value));
        }
        roleSelect.value = item.role;
        roleCell.append(roleSelect);

        const saveRole = document.createElement("button");
        saveRole.type = "button";
        saveRole.className = "table-action";
        saveRole.textContent = "Save role";
        saveRole.addEventListener("click", async () => {
          saveRole.disabled = true;
          try {
            await workspaceRequest("/api/team/members/" + encodeURIComponent(item.user_id), {
              method: "PATCH", body: JSON.stringify({role: roleSelect.value}),
            });
            workspaceMessage("Team role updated.");
            await loadTeamMembers();
          } catch (error) {
            workspaceMessage(error.message);
            saveRole.disabled = false;
          }
        });
        actions.append(saveRole);
      }
      textCell(row, item.status === "suspended" ? "Suspended" : "Active");
      if (item.role !== "admin" && item.user_id !== workspaceUserId) {
        const toggle = document.createElement("button");
        toggle.type = "button";
        toggle.className = item.status === "suspended"
          ? "table-action" : "table-action table-action-danger";
        toggle.textContent = item.status === "suspended" ? "Reactivate" : "Suspend";
        toggle.addEventListener("click", async () => {
          toggle.disabled = true;
          try {
            const status = item.status === "suspended" ? "active" : "suspended";
            await workspaceRequest("/api/team/members/" + encodeURIComponent(item.user_id), {
              method: "PATCH", body: JSON.stringify({status}),
            });
            workspaceMessage(status === "active" ? "Member access restored." : "Member suspended.");
            await loadTeamMembers();
          } catch (error) {
            workspaceMessage(error.message);
            toggle.disabled = false;
          }
        });
        actions.append(toggle);
      }
      if (!actions.childElementCount) actions.textContent = "—";
      row.append(roleCell, actions);
      body.append(row);
    }
  } catch (error) {
    workspaceMessage(error.message);
  }
}

document.querySelector("#team-tab").addEventListener("click", () => {
  loadTeamMembers();
  loadCompanyInvitations();
});

async function loadCompanySettings() {
  if (workspaceRole !== "admin") return;
  const message = document.querySelector("#company-settings-message");
  try {
    const data = await workspaceRequest("/api/company/settings");
    document.querySelector("#company-settings-name").value = data.item.name;
    message.textContent = "";
  } catch (error) {
    message.textContent = error.message;
  }
}

document.querySelector("#company-settings-tab").addEventListener("click", loadCompanySettings);
document.querySelector("#company-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const message = document.querySelector("#company-settings-message");
  button.disabled = true;
  try {
    const data = await workspaceRequest("/api/company/settings", {
      method: "PATCH",
      body: JSON.stringify({name: document.querySelector("#company-settings-name").value}),
    });
    document.querySelector("#company-settings-name").value = data.item.name;
    message.textContent = "Company name updated.";
    workspaceMessage("Company settings saved.");
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
