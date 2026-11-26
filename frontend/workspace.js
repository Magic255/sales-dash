const workspace = document.querySelector("#sales-workspace");
let workspaceRole = "";
let workspaceUserId = "";
let customers = [];
let products = [];
let inventorySummary = [];
let workspaceGeneration = 0;
let salespersonTargets = [];

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

async function loadAuditLogs(generation = workspaceGeneration) {
  const panel = document.querySelector("#audit-panel");
  const body = document.querySelector("#audit-rows");
  const message = document.querySelector("#audit-message");
  if (workspaceRole !== "admin") {
    panel.hidden = true;
    return;
  }

  message.textContent = "";
  emptyRow(body, 4, "Loading security activity…");
  try {
    const data = await workspaceRequest("/api/audit-logs?limit=50");
    if (generation !== workspaceGeneration || workspaceRole !== "admin") return;
    body.replaceChildren();
    if (!data.items.length) {
      emptyRow(body, 4, "No security activity recorded yet.");
      return;
    }

    const eventLabels = {
      product_created: "Product created",
      product_updated: "Product details or price changed",
      discount_limits_updated: "Discount limits updated",
      discount_approval_requested: "Discount approval requested",
      discount_approval_decided: "Discount approval decided",
      discount_applied: "Sale discount applied or changed",
      login_succeeded: "Signed in",
      password_changed: "Password changed",
      company_selected: "Company selected",
      logout: "Signed out",
      email_verified: "Email verified",
      password_reset: "Password reset",
      company_invitation_created: "Invitation created",
      company_invitation_accepted: "Invitation accepted",
      company_invitation_revoked: "Invitation revoked",
      mfa_enabled: "Two-step sign-in enabled",
      mfa_disabled: "Two-step sign-in disabled",
      mfa_recovery_code_used: "Recovery code used",
      company_settings_updated: "Company settings updated",
      team_member_role_changed: "Team role changed",
      team_member_suspended: "Team member suspended",
      team_member_reactivated: "Team member reactivated",
    };
    for (const item of data.items) {
      const row = document.createElement("tr");
      const occurredAt = new Date(item.occurred_at);
      textCell(
        row,
        Number.isNaN(occurredAt.getTime())
          ? item.occurred_at
          : occurredAt.toLocaleString(),
      );
      textCell(
        row,
        eventLabels[item.event_type] ||
          String(item.event_type || "Unknown event").replaceAll("_", " "),
      );
      textCell(
        row,
        item.actor_user_id ? "Account " + item.actor_user_id.slice(0, 8) : "System",
      );
      textCell(row, item.details ? JSON.stringify(item.details) : "—");
      body.append(row);
    }
    message.textContent = "Showing the " + data.items.length + " most recent events.";
  } catch (error) {
    if (generation !== workspaceGeneration) return;
    emptyRow(body, 4, "Security activity could not be loaded.");
    message.textContent = error.message;
  }
}

async function loadDiscountApprovals() {
  const generation = workspaceGeneration;
  const panel = document.querySelector('[data-workspace-panel="discount-approvals"]');
  const body = document.querySelector("#discount-approval-rows");
  const message = document.querySelector("#discount-approvals-message");
  if (workspaceRole !== "admin") {
    panel.hidden = true;
    document.querySelector("#discount-approvals-tab").hidden = true;
    return;
  }
  message.textContent = "";
  emptyRow(body, 6, "Loading approval requests…");
  try {
    const data = await workspaceRequest("/api/discount-approvals");
    if (generation !== workspaceGeneration || workspaceRole !== "admin") return;
    body.replaceChildren();
    if (!data.items.length) {
      emptyRow(body, 6, "No discount approvals are waiting.");
      return;
    }
    for (const item of data.items) {
      const row = document.createElement("tr");
      textCell(row, item.sale_number);
      textCell(row, item.requested_by);
      textCell(row, Number(item.requested_discount_percent).toFixed(2) + "%");
      textCell(row, item.reason);
      const requestedAt = new Date(item.created_at);
      textCell(row, Number.isNaN(requestedAt.getTime())
        ? item.created_at : requestedAt.toLocaleString());
      const actions = document.createElement("td");
      const approve = document.createElement("button");
      approve.type = "button";
      approve.className = "table-action";
      approve.textContent = "Approve";
      const reject = document.createElement("button");
      reject.type = "button";
      reject.className = "table-action table-action-danger";
      reject.textContent = "Reject";
      for (const [button, decision] of [[approve, "approve"], [reject, "reject"]]) {
        button.addEventListener("click", async () => {
          let reason;
          if (decision === "reject") {
            reason = window.prompt("Reason for rejecting this discount request");
            if (reason === null) return;
            if (!reason.trim()) {
              message.textContent = "A reason is required to reject a request.";
              return;
            }
          }
          button.disabled = true;
          try {
            await workspaceRequest(
              "/api/discount-approvals/" + encodeURIComponent(item.id) + "/decision",
              {method: "POST", body: JSON.stringify({decision, ...(reason ? {reason} : {})})},
            );
            message.textContent = decision === "approve"
              ? "Discount approved." : "Discount request rejected.";
            await loadDiscountApprovals();
          } catch (error) {
            message.textContent = error.message;
            button.disabled = false;
          }
        });
      }
      actions.append(approve, reject);
      row.append(actions);
      body.append(row);
    }
  } catch (error) {
    if (generation !== workspaceGeneration) return;
    emptyRow(body, 6, "Approval requests could not be loaded.");
    message.textContent = error.message;
  }
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

function canManageCatalog() {
  return ["admin", "manager"].includes(workspaceRole);
}

function canManageProducts() {
  return workspaceRole === "admin";
}

function addCatalogAction(cell, label, callback, danger = false) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = danger ? "table-action table-action-danger" : "table-action";
  button.textContent = label;
  button.addEventListener("click", callback);
  cell.append(button);
}

async function editCustomer(item) {
  const name = window.prompt("Customer name", item.name);
  if (name === null) return;
  const email = window.prompt("Email (optional)", item.email || "");
  if (email === null) return;
  const phone = window.prompt("Phone (optional)", item.phone || "");
  if (phone === null) return;
  const organization = window.prompt("Organization (optional)", item.organization || "");
  if (organization === null) return;
  try {
    await workspaceRequest("/api/customers/" + encodeURIComponent(item.id), {
      method: "PATCH",
      body: JSON.stringify({name, email, phone, organization}),
    });
    await loadWorkspace();
    workspaceMessage("Customer updated.");
  } catch (error) {
    workspaceMessage(error.message);
  }
}

async function setCustomerActive(item) {
  const next = !item.is_active;
  const action = next ? "restore" : "archive";
  if (!window.confirm("Are you sure you want to " + action + " this customer?")) return;
  try {
    await workspaceRequest("/api/customers/" + encodeURIComponent(item.id), {
      method: "PATCH", body: JSON.stringify({is_active: next}),
    });
    await loadWorkspace();
    workspaceMessage(next ? "Customer restored." : "Customer archived.");
  } catch (error) {
    workspaceMessage(error.message);
  }
}

async function editProduct(item) {
  const sku = window.prompt("Product code / SKU", item.sku);
  if (sku === null) return;
  const name = window.prompt("Product name", item.name);
  if (name === null) return;
  const description = window.prompt("Description (optional)", item.description || "");
  if (description === null) return;
  const unitPrice = window.prompt("Unit price", item.unit_price);
  if (unitPrice === null) return;
  const costPrice = window.prompt("Cost price", item.cost_price || "0.00");
  if (costPrice === null) return;
  const minimumSellingPrice = window.prompt(
    "Minimum selling price", item.minimum_selling_price || "0.00"
  );
  if (minimumSellingPrice === null) return;
  const trackInventoryAnswer = window.prompt(
    "Track stock and batches? Enter yes or no",
    item.track_inventory ? "yes" : "no"
  );
  if (trackInventoryAnswer === null) return;
  const trackInventory = trackInventoryAnswer.trim().toLowerCase();
  if (!["yes", "no"].includes(trackInventory)) {
    return workspaceMessage("Enter yes or no for inventory tracking.");
  }
  const reorderLevel = window.prompt(
    "Low-stock alert level", item.reorder_level || "0.000"
  );
  if (reorderLevel === null) return;
  const currency = window.prompt("Currency (3-letter code)", item.currency);
  if (currency === null) return;
  try {
    await workspaceRequest("/api/products/" + encodeURIComponent(item.id), {
      method: "PATCH",
      body: JSON.stringify({
        sku, name, description, unit_price: unitPrice,
        cost_price: costPrice, minimum_selling_price: minimumSellingPrice,
        track_inventory: trackInventory === "yes", reorder_level: reorderLevel, currency,
      }),
    });
    await loadWorkspace();
    workspaceMessage("Product updated. Existing sales retain their saved price snapshots.");
  } catch (error) {
    workspaceMessage(error.message);
  }
}

async function setProductActive(item) {
  const next = !item.is_active;
  const action = next ? "restore" : "archive";
  if (!window.confirm("Are you sure you want to " + action + " this product?")) return;
  try {
    await workspaceRequest("/api/products/" + encodeURIComponent(item.id), {
      method: "PATCH", body: JSON.stringify({is_active: next}),
    });
    await loadWorkspace();
    workspaceMessage(next ? "Product restored." : "Product archived.");
  } catch (error) {
    workspaceMessage(error.message);
  }
}

function renderCustomers() {
  const body = document.querySelector("#customer-rows");
  body.replaceChildren();
  if (!customers.length) return emptyRow(body, 5, "No customers yet. Add the first customer above.");
  for (const item of customers) {
    const row = document.createElement("tr");
    textCell(row, item.name);
    textCell(row, item.email);
    textCell(row, item.phone);
    textCell(row, item.is_active ? "Active" : "Archived");
    const actions = document.createElement("td");
    if (canManageCatalog()) {
      addCatalogAction(actions, "Edit", () => editCustomer(item));
      addCatalogAction(
        actions, item.is_active ? "Archive" : "Restore",
        () => setCustomerActive(item), item.is_active,
      );
    }
    if (!actions.childElementCount) actions.textContent = "—";
    row.append(actions);
    body.append(row);
  }
}

function renderProducts() {
  const body = document.querySelector("#product-rows");
  body.replaceChildren();
  if (!products.length) return emptyRow(body, 7, "No products yet. Add the first product above.");
  for (const item of products) {
    const row = document.createElement("tr");
    textCell(row, item.sku);
    textCell(row, item.name);
    textCell(row, amount(item.currency, item.unit_price));
    textCell(row, amount(item.currency, item.minimum_selling_price));
    textCell(row, item.currency);
    textCell(row, item.is_active ? "Active" : "Archived");
    const actions = document.createElement("td");
    if (canManageProducts()) {
      addCatalogAction(actions, "Edit", () => editProduct(item));
      addCatalogAction(
        actions, item.is_active ? "Archive" : "Restore",
        () => setProductActive(item), item.is_active,
      );
    }
    if (!actions.childElementCount) actions.textContent = "—";
    row.append(actions);
    body.append(row);
  }
}

function fillSaleChoices() {
  const customer = document.querySelector("#sale-customer");
  const product = document.querySelector("#sale-product");
  const activeCustomers = customers.filter((item) => item.is_active);
  const activeProducts = products.filter((item) => item.is_active);
  customer.replaceChildren(new Option(activeCustomers.length ? "Choose a customer" : "Add an active customer first", ""));
  product.replaceChildren(new Option(activeProducts.length ? "Choose a product" : "Add an active product first", ""));
  activeCustomers.forEach((item) => customer.add(new Option(item.name, item.id)));
  activeProducts.forEach((item) => product.add(new Option(
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
          const path = "/api/sales/" + encodeURIComponent(sale.id) + "/complete";
          try {
            await workspaceRequest(path, {method: "POST", body: "{}"});
          } catch (error) {
            if (
              workspaceRole !== "admin" ||
              !error.message.toLowerCase().includes("override requires a reason")
            ) throw error;
            const reason = window.prompt(
              "This draft is now below a product's minimum price. Enter the reason for the Admin override:"
            );
            if (reason === null || !reason.trim()) {
              workspaceMessage("Completion cancelled. An override reason is required.");
              complete.disabled = false;
              return;
            }
            await workspaceRequest(path, {
              method: "POST",
              body: JSON.stringify({price_floor_override_reason: reason.trim()}),
            });
          }
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
            batch_id: item.batch_id || null,
          })),
        };
        edit.disabled = true;
        try {
          const path = "/api/sales/" + encodeURIComponent(sale.id);
          try {
            await workspaceRequest(path, {
              method: "PATCH", body: JSON.stringify(payload),
            });
          } catch (error) {
            if (
              workspaceRole !== "admin" ||
              !error.message.toLowerCase().includes("override requires a reason")
            ) throw error;
            const reason = window.prompt(
              "This edit would take a product below its minimum price. Enter the reason for the Admin override:"
            );
            if (reason === null || !reason.trim()) {
              workspaceMessage("Edit cancelled. An override reason is required.");
              edit.disabled = false;
              return;
            }
            payload.price_floor_override_reason = reason.trim();
            await workspaceRequest(path, {
              method: "PATCH", body: JSON.stringify(payload),
            });
          }
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

function fillInventoryBatchOptions(select, productId, availableOnly = false) {
  select.replaceChildren(new Option("Choose a batch", ""));
  const product = inventorySummary.find((item) => item.product_id === productId);
  if (!product) return;
  for (const batch of product.batches) {
    const available = Number(batch.on_hand) - Number(batch.reserved);
    const expired = batch.expiry_date && batch.expiry_date < localDate();
    if (availableOnly && (available <= 0 || expired)) continue;
    const expiry = batch.expiry_date ? " · expires " + batch.expiry_date : "";
    select.add(new Option(
      batch.batch_code + " · available " + available.toFixed(3) + expiry,
      batch.id,
    ));
  }
}

function fillSaleBatchChoices() {
  const productId = document.querySelector("#sale-product").value;
  const product = products.find((item) => item.id === productId);
  const field = document.querySelector("#sale-batch-field");
  const select = document.querySelector("#sale-batch");
  field.hidden = !product || !product.track_inventory;
  select.required = Boolean(product && product.track_inventory);
  fillInventoryBatchOptions(select, productId, true);
}

async function loadInventory(generation = workspaceGeneration) {
  const data = await workspaceRequest("/api/inventory");
  if (generation !== workspaceGeneration) return;
  inventorySummary = data.items;
  const body = document.querySelector("#inventory-rows");
  body.replaceChildren();
  if (!inventorySummary.length) {
    emptyRow(body, 7, "No products are registered in this company.");
  } else {
    for (const item of inventorySummary) {
      const row = document.createElement("tr");
      textCell(row, item.sku);
      textCell(row, item.name);
      textCell(row, item.track_inventory ? item.on_hand : "—");
      textCell(row, item.track_inventory ? item.reserved : "—");
      textCell(row, item.track_inventory ? item.available : "—");
      textCell(row, item.track_inventory ? item.reorder_level : "—");
      textCell(row, item.status);
      body.append(row);
    }
  }
  const batchBody = document.querySelector("#inventory-batch-rows");
  batchBody.replaceChildren();
  const batchRows = inventorySummary.flatMap((product) =>
    product.batches.map((batch) => ({product, batch}))
  );
  if (!batchRows.length) {
    emptyRow(batchBody, 8, "No product batches have been created yet.");
  } else {
    for (const {product, batch} of batchRows) {
      const row = document.createElement("tr");
      const expired = batch.expiry_date && batch.expiry_date < localDate();
      const available = Math.max(
        0, Number(batch.on_hand) - Number(batch.reserved)
      );
      textCell(row, product.sku);
      textCell(row, product.name);
      textCell(row, batch.batch_code);
      textCell(row, batch.expiry_date || "No expiry date");
      textCell(row, batch.on_hand);
      textCell(row, batch.reserved);
      textCell(row, available.toFixed(3));
      textCell(
        row,
        expired ? "Expired" : available > 0 ? "Available"
          : Number(batch.reserved) > 0 ? "Reserved" : "Out of stock",
      );
      batchBody.append(row);
    }
  }
  const trackedProducts = products.filter((item) => item.track_inventory && item.is_active);
  for (const id of ["inventory-batch-product", "inventory-movement-product"]) {
    const select = document.querySelector("#" + id);
    const current = select.value;
    select.replaceChildren(new Option("Choose a tracked product", ""));
    trackedProducts.forEach((item) => select.add(new Option(item.name + " · " + item.sku, item.id)));
    if (trackedProducts.some((item) => item.id === current)) select.value = current;
  }
  fillInventoryBatchOptions(
    document.querySelector("#inventory-movement-batch"),
    document.querySelector("#inventory-movement-product").value,
  );
  fillSaleBatchChoices();

  const movementData = await workspaceRequest("/api/inventory/movements");
  if (generation !== workspaceGeneration) return;
  const movementBody = document.querySelector("#inventory-movement-rows");
  movementBody.replaceChildren();
  if (!movementData.items.length) {
    emptyRow(movementBody, 7, "No stock movements have been recorded yet.");
  } else {
    for (const movement of movementData.items) {
      const row = document.createElement("tr");
      textCell(row, new Date(movement.created_at).toLocaleString());
      textCell(row, movement.product_name + " · " + movement.sku);
      textCell(row, movement.batch_code);
      textCell(row, movement.movement_type);
      textCell(row, movement.quantity_delta !== "0.000"
        ? movement.quantity_delta
        : "Reserved " + movement.reserved_delta);
      textCell(row, movement.actor);
      textCell(row, movement.reason);
      movementBody.append(row);
    }
  }
}

async function loadWorkspace() {
  const generation = workspaceGeneration;
  workspaceMessage("Loading company data…");
  try {
    const [summary, customerData, productData] = await Promise.all([
      workspaceRequest("/api/dashboard/summary"),
      workspaceRequest("/api/customers" + (canManageCatalog() ? "?include_inactive=true" : "")),
      workspaceRequest("/api/products" + (canManageCatalog() ? "?include_inactive=true" : "")),
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
    await loadInventory(generation);
    await loadSales(generation);
    await loadSalesTargets(generation);
    await loadDashboardAnalytics(generation);
    await loadDashboardSalespeople(generation);
    if (generation === workspaceGeneration) {
      workspaceMessage("Company data is up to date.");
    }
  } catch (error) {
    if (generation === workspaceGeneration) workspaceMessage(error.message);
  }
}

async function loadDashboardSalespeople(generation = workspaceGeneration) {
  const panel = document.querySelector("#dashboard-salespeople-panel");
  const body = document.querySelector("#dashboard-salespeople-rows");
  if (!["admin", "manager"].includes(workspaceRole)) { panel.hidden = true; return; }
  panel.hidden = false;
  const params = new URLSearchParams({
    from: document.querySelector("#dashboard-analytics-from").value,
    to: document.querySelector("#dashboard-analytics-to").value,
  });
  const data = await workspaceRequest("/api/dashboard/salespeople?" + params.toString());
  if (generation !== workspaceGeneration) return;
  body.replaceChildren();
  if (!data.salespeople.length) {
    const row = document.createElement("tr"), cell = document.createElement("td");
    cell.colSpan = 6; cell.textContent = "No active salespeople in this company.";
    row.append(cell); body.append(row); return;
  }
  data.salespeople.forEach((person) => {
    const metricsByCurrency = new Map(
      person.by_currency.map((metric) => [metric.currency, metric])
    );
    salespersonTargets
      .filter((item) => item.user_id === person.user_id)
      .forEach((target) => {
        if (!metricsByCurrency.has(target.currency)) {
          metricsByCurrency.set(target.currency, {
            currency: target.currency,
            revenue: "0.00",
            completed_sales: 0,
            average_sale: "0.00",
          });
        }
      });
    const metrics = metricsByCurrency.size
      ? [...metricsByCurrency.values()]
      : [{currency: "—", revenue: "0.00", completed_sales: 0, average_sale: "0.00"}];
    metrics.forEach((metric) => {
      const target = salespersonTargets.find((item) =>
        item.user_id === person.user_id && item.currency === metric.currency
      );
      const targetText = target
        ? amount(target.currency, target.target_amount)
        : "No target";
      const attainmentText = target
        ? amount(target.currency, target.actual_amount) + " / " +
          amount(target.currency, target.target_amount) + " · " +
          target.progress_percent + "%"
        : "—";
      const row = document.createElement("tr");
      [
        person.name,
        metric.currency,
        metric.currency === "—" ? "—" : amount(metric.currency, metric.revenue),
        metric.completed_sales + " · avg " +
          (metric.currency === "—" ? "—" : amount(metric.currency, metric.average_sale)),
        targetText,
        attainmentText,
      ].forEach((value) => {
        const cell = document.createElement("td");
        cell.textContent = value;
        row.append(cell);
      });
      body.append(row);
    });
  });
}

async function loadDashboardAnalytics(generation = workspaceGeneration) {
  const fromInput = document.querySelector("#dashboard-analytics-from");
  const toInput = document.querySelector("#dashboard-analytics-to");
  if (!fromInput.value) fromInput.value = localDateDaysAgo(29);
  if (!toInput.value) toInput.value = localDate();
  const message = document.querySelector("#dashboard-analytics-message");
  message.textContent = "";
  const params = new URLSearchParams({from: fromInput.value, to: toInput.value});
  const data = await workspaceRequest("/api/dashboard/analytics?" + params.toString());
  if (generation !== workspaceGeneration) return;
  const totals = data.totals_by_currency.map((item) =>
    amount(item.currency, item.amount) + " · " + item.sales + " sales"
  );
  document.querySelector("#dashboard-analytics-totals").textContent =
    totals.length ? "Period totals: " + totals.join("  |  ") : "No completed sales in this date range.";
  const container = document.querySelector("#dashboard-revenue-trend");
  container.replaceChildren();
  if (!data.daily_revenue.length) {
    const empty = document.createElement("p");
    empty.className = "panel-copy";
    empty.textContent = "Complete a sale to start building your revenue trend.";
    container.append(empty);
    return;
  }
  const maximums = new Map();
  data.daily_revenue.forEach((item) => {
    maximums.set(item.currency, Math.max(maximums.get(item.currency) || 0, Number(item.amount)));
  });
  data.daily_revenue.forEach((item) => {
    const row = document.createElement("div");
    row.className = "revenue-trend-row";
    const label = document.createElement("span");
    label.className = "revenue-trend-label";
    label.textContent = item.date + " · " + item.currency;
    const track = document.createElement("div");
    track.className = "revenue-trend-track";
    const bar = document.createElement("div");
    bar.className = "revenue-trend-bar";
    bar.style.width = Math.max(2, Number(item.amount) / maximums.get(item.currency) * 100) + "%";
    bar.setAttribute("aria-label", amount(item.currency, item.amount));
    track.append(bar);
    const value = document.createElement("strong");
    value.className = "revenue-trend-value";
    value.textContent = amount(item.currency, item.amount) + " · " + item.sales;
    row.append(label, track, value);
    container.append(row);
  });
}

function targetProgress(container, item, label) {
  const wrapper = document.createElement("article");
  wrapper.className = "target-progress-item";
  const heading = document.createElement("div");
  heading.className = "target-progress-heading";
  const name = document.createElement("strong");
  name.textContent = label + " · " + item.currency;
  const percentage = document.createElement("span");
  percentage.textContent = item.progress_percent + "%";
  heading.append(name, percentage);
  const progress = document.createElement("progress");
  progress.max = 100;
  progress.value = Math.min(100, Math.max(0, Number(item.progress_percent) || 0));
  progress.setAttribute("aria-label", label + " progress");
  const detail = document.createElement("p");
  detail.className = "panel-copy";
  detail.textContent = amount(item.currency, item.actual_amount) + " of " + amount(item.currency, item.target_amount);
  wrapper.append(heading, progress, detail);
  container.append(wrapper);
}

async function loadSalesTargets(generation = workspaceGeneration) {
  const monthInput = document.querySelector("#sales-target-month");
  if (!monthInput.value) monthInput.value = localDate().slice(0, 7);
  const month = monthInput.value;
  const data = await workspaceRequest("/api/sales-targets?month=" + encodeURIComponent(month));
  if (generation !== workspaceGeneration) return;
  salespersonTargets = data.salesperson_targets;
  const company = document.querySelector("#company-target-progress");
  const sellers = document.querySelector("#salesperson-target-progress");
  company.replaceChildren();
  sellers.replaceChildren();
  if (!data.company_targets.length) {
    const empty = document.createElement("p");
    empty.className = "panel-copy";
    empty.textContent = "No company target has been set for this month yet.";
    company.append(empty);
  } else {
    data.company_targets.forEach((item) => targetProgress(company, item, "Company target"));
  }
  if (!data.salesperson_targets.length) {
    const empty = document.createElement("p");
    empty.className = "panel-copy";
    empty.textContent = workspaceRole === "salesperson"
      ? "No personal target has been set for you this month."
      : "No salesperson targets have been set for this month.";
    sellers.append(empty);
  } else {
    data.salesperson_targets.forEach((item) => targetProgress(sellers, item, item.name));
  }
  const management = document.querySelector("#sales-target-management");
  management.hidden = !["admin", "manager"].includes(workspaceRole);
  const choices = document.querySelector("#sales-target-salesperson");
  const selected = choices.value;
  choices.replaceChildren(new Option("Choose a salesperson", ""));
  data.salespeople.forEach((item) => choices.add(new Option(item.name, item.user_id)));
  if (data.salespeople.some((item) => item.user_id === selected)) choices.value = selected;
}

async function saveMonthlyTarget(payload) {
  const message = document.querySelector("#sales-target-message");
  try {
    await workspaceRequest("/api/sales-targets", {
      method: "PUT",
      body: JSON.stringify(payload),
    });
    message.textContent = "Monthly target saved.";
    await loadSalesTargets();
    await loadDashboardSalespeople();
  } catch (error) {
    message.textContent = error.message;
  }
}

function localDate() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

function localDateDaysAgo(days) {
  const value = new Date();
  value.setDate(value.getDate() - days);
  return new Date(value.getTime() - value.getTimezoneOffset() * 60000).toISOString().slice(0, 10);
}

document.addEventListener("salesdash:company-selected", (event) => {
  workspaceGeneration += 1;
  workspaceRole = event.detail.role;
  workspaceUserId = event.detail.userId;
  customers = [];
  products = [];
  inventorySummary = [];
  salespersonTargets = [];
  renderCustomers();
  renderProducts();
  fillSaleChoices();
  emptyRow(document.querySelector("#sales-rows"), 6, "Loading sales…");
  document.querySelector("#metric-customers").textContent = "—";
  document.querySelector("#metric-products").textContent = "—";
  document.querySelector("#metric-sales").textContent = "—";
  document.querySelector("#metric-revenue").textContent = "—";
  document.querySelector("#sales-target-month").value = localDate().slice(0, 7);
  document.querySelector("#dashboard-analytics-from").value = localDateDaysAgo(29);
  document.querySelector("#dashboard-analytics-to").value = localDate();
  document.querySelector("#sales-target-message").textContent = "";
  workspace.hidden = false;
  document.querySelector("#customer-form").hidden = workspaceRole === "viewer";
  document.querySelector("#product-form").hidden = !canManageProducts();
  document.querySelector("#sale-form").hidden = workspaceRole === "viewer";
  document.querySelector("#sale-floor-override").hidden = workspaceRole !== "admin";
  document.querySelector("#team-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#company-settings-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#discount-approvals-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#inventory-tab").hidden =
    !["admin", "manager"].includes(workspaceRole);
  document.querySelectorAll("[data-admin-only]").forEach((option) => {
    option.hidden = workspaceRole !== "admin";
  });
  document.querySelector("#weekly-discount-report").hidden =
    !["admin", "manager"].includes(workspaceRole);
  const auditPanel = document.querySelector("#audit-panel");
  auditPanel.hidden = workspaceRole !== "admin";
  if (workspaceRole === "admin") {
    loadAuditLogs(workspaceGeneration);
    loadDiscountApprovals();
  } else {
    emptyRow(document.querySelector("#audit-rows"), 4, "Security activity is available to company admins only.");
  }
  if (workspaceRole !== "admin") selectTab("overview");
  loadWorkspace();
});

document.addEventListener("salesdash:signed-out", () => {
  workspaceGeneration += 1;
  customers = [];
  products = [];
  inventorySummary = [];
  document.querySelector("#audit-panel").hidden = true;
  document.querySelector("#discount-approvals-tab").hidden = true;
  document.querySelector("#inventory-tab").hidden = true;
  document.querySelector("#weekly-discount-report").hidden = true;
  document.querySelector("#discount-approvals-message").textContent = "";
  document.querySelector("#audit-message").textContent = "";
  emptyRow(document.querySelector("#audit-rows"), 4, "Select a company to view activity.");
  workspace.hidden = true;
});

document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
  button.addEventListener("click", () => selectTab(button.dataset.workspaceTab));
});

document.querySelector("#workspace-refresh").addEventListener("click", loadWorkspace);

document.querySelector("#audit-refresh").addEventListener("click", async (event) => {
  const button = event.currentTarget;
  button.disabled = true;
  try {
    await loadAuditLogs();
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#sales-target-month").addEventListener("change", async () => {
  try {
    await loadSalesTargets();
    await loadDashboardSalespeople();
  } catch (error) {
    document.querySelector("#sales-target-message").textContent = error.message;
  }
});

document.querySelector("#company-target-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveMonthlyTarget({
    month: document.querySelector("#sales-target-month").value,
    target_type: "company",
    currency: document.querySelector("#company-target-currency").value,
    target_amount: document.querySelector("#company-target-amount").value,
  });
});

document.querySelector("#salesperson-target-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  await saveMonthlyTarget({
    month: document.querySelector("#sales-target-month").value,
    target_type: "salesperson",
    salesperson_user_id: document.querySelector("#sales-target-salesperson").value,
    currency: document.querySelector("#salesperson-target-currency").value,
    target_amount: document.querySelector("#salesperson-target-amount").value,
  });
});



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

document.querySelector("#inventory-tab").addEventListener("click", async () => {
  try {
    await loadInventory();
  } catch (error) {
    workspaceMessage(error.message);
  }
});

document.querySelector("#inventory-movement-product").addEventListener("change", (event) => {
  fillInventoryBatchOptions(
    document.querySelector("#inventory-movement-batch"), event.currentTarget.value
  );
});

document.querySelector("#sale-product").addEventListener("change", fillSaleBatchChoices);

document.querySelector("#inventory-movement-type").addEventListener("change", (event) => {
  const adjusted = event.currentTarget.value === "adjusted";
  document.querySelector("#inventory-quantity-label").textContent =
    adjusted ? "Quantity delta (+ or -)" : "Quantity";
  const input = document.querySelector("#inventory-movement-quantity");
  input.min = adjusted ? "-999999999" : "0.001";
});

document.querySelector("#inventory-batch-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  button.disabled = true;
  try {
    await workspaceRequest("/api/inventory/batches", {
      method: "POST",
      body: JSON.stringify({
        product_id: document.querySelector("#inventory-batch-product").value,
        batch_code: document.querySelector("#inventory-batch-code").value,
        expiry_date: document.querySelector("#inventory-batch-expiry").value || null,
      }),
    });
    form.reset();
    await loadWorkspace();
    workspaceMessage("Product batch created.");
  } catch (error) {
    workspaceMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#inventory-movement-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const movementType = document.querySelector("#inventory-movement-type").value;
  const quantity = document.querySelector("#inventory-movement-quantity").value;
  const payload = {
    product_id: document.querySelector("#inventory-movement-product").value,
    batch_id: document.querySelector("#inventory-movement-batch").value,
    movement_type: movementType,
    reason: document.querySelector("#inventory-movement-reason").value,
  };
  if (movementType === "adjusted") payload.quantity_delta = quantity;
  else payload.quantity = quantity;
  button.disabled = true;
  try {
    await workspaceRequest("/api/inventory/movements", {
      method: "POST", body: JSON.stringify(payload),
    });
    form.reset();
    await loadWorkspace();
    workspaceMessage("Stock movement recorded in the immutable ledger.");
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
        cost_price: document.querySelector("#product-cost").value,
        minimum_selling_price: document.querySelector("#product-minimum-price").value,
        track_inventory: document.querySelector("#product-track-inventory").checked,
        reorder_level: document.querySelector("#product-reorder-level").value,
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
        approval_reason: document.querySelector("#sale-approval-reason").value,
        price_floor_override_reason: document.querySelector("#sale-floor-override-reason").value,
        items: [{
          product_id: product.id,
          quantity: document.querySelector("#sale-quantity").value,
          discount_amount: document.querySelector("#sale-item-discount").value || "0",
          batch_id: document.querySelector("#sale-batch").value || null,
        }],
      }),
    });
    form.reset();
    document.querySelector("#sale-date").value = localDate();
    document.querySelector("#sale-quantity").value = "1";
    document.querySelector("#sale-item-discount").value = "0";
    document.querySelector("#sale-discount").value = "0";
    document.querySelector("#sale-tax").value = "0";
    document.querySelector("#sale-floor-override-reason").value = "";
    selectTab("sales");
    await loadWorkspace();
    workspaceMessage(saved.item.approval_status === "pending"
      ? "Draft saved. Your discount approval request is waiting for an Admin."
      : "Draft " + saved.item.sale_number + " saved.");
  } catch (error) {
    workspaceMessage(error.message);
  } finally {
    button.disabled = false;
  }
});

document.querySelector("#dashboard-analytics-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = event.currentTarget.querySelector("button");
  button.disabled = true;
  try {
    await loadDashboardAnalytics();
    await loadDashboardSalespeople();
  } catch (error) {
    document.querySelector("#dashboard-analytics-message").textContent = error.message;
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

async function loadWeeklyDiscountReport() {
  const weekStart = document.querySelector("#discount-week-start").value;
  const params = new URLSearchParams();
  if (weekStart) params.set("week_start", weekStart);
  const data = await workspaceRequest(
    "/api/reports/discounts/weekly?" + params.toString()
  );
  const body = document.querySelector("#weekly-discount-rows");
  body.replaceChildren();
  document.querySelector("#weekly-discount-note").textContent =
    "Week: " + data.week_start + " to " + data.week_end + ". " + data.note;
  const rows = data.salespeople.flatMap((seller) =>
    seller.by_currency.map((summary) => ({seller, summary}))
  );
  if (!rows.length) {
    emptyRow(body, 6, "No completed sales were recorded for this week.");
    return;
  }
  for (const {seller, summary} of rows) {
    const row = document.createElement("tr");
    textCell(row, seller.name);
    textCell(row, summary.currency);
    textCell(row, String(summary.completed_sales));
    textCell(row, amount(summary.currency, summary.discount_total));
    textCell(row, summary.discount_rate_percent + "%");
    textCell(row, amount(summary.currency, summary.net_sales_after_discount));
    body.append(row);
  }
}

document.querySelector("#weekly-discount-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await loadWeeklyDiscountReport();
  } catch (error) {
    workspaceMessage(error.message);
  }
});

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
      const statusCell = document.createElement("td");
      statusCell.textContent = item.status === "suspended" ? "Suspended" : "Active";
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
      row.append(roleCell, statusCell, actions);
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
    document.querySelector("#company-settings-salesperson-limit").value =
      data.item.discount_limits.salesperson_percent;
    document.querySelector("#company-settings-manager-limit").value =
      data.item.discount_limits.manager_percent;
    message.textContent = "";
  } catch (error) {
    message.textContent = error.message;
  }
}

document.querySelector("#company-settings-tab").addEventListener("click", loadCompanySettings);
document.querySelector("#discount-approvals-tab").addEventListener("click", loadDiscountApprovals);
document.querySelector("#discount-approvals-refresh").addEventListener(
  "click", loadDiscountApprovals,
);
document.querySelector("#company-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const message = document.querySelector("#company-settings-message");
  button.disabled = true;
  try {
    const data = await workspaceRequest("/api/company/settings", {
      method: "PATCH",
      body: JSON.stringify({
        name: document.querySelector("#company-settings-name").value,
        salesperson_discount_limit:
          document.querySelector("#company-settings-salesperson-limit").value,
        manager_discount_limit:
          document.querySelector("#company-settings-manager-limit").value,
      }),
    });
    document.querySelector("#company-settings-name").value = data.item.name;
    document.querySelector("#company-settings-salesperson-limit").value =
      data.item.discount_limits.salesperson_percent;
    document.querySelector("#company-settings-manager-limit").value =
      data.item.discount_limits.manager_percent;
    message.textContent = "Company settings updated.";
    workspaceMessage("Company settings saved.");
  } catch (error) {
    message.textContent = error.message;
  } finally {
    button.disabled = false;
  }
});
