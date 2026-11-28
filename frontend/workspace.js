const workspace = document.querySelector("#sales-workspace");
let workspaceRole = "";
let workspaceUserId = "";
let customers = [];
let products = [];
let workspaceGeneration = 0;
let salespersonTargets = [];

function workspaceMessage(message) {
  document.querySelector("#workspace-message").textContent = message;
}

async function workspaceRequest(path, options = {}) {
  const method = (options.method || "GET").toUpperCase();
  const headers = new Headers(options.headers || {});
  if (options.body && !(options.body instanceof FormData)) headers.set("Content-Type", "application/json");
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
      product_compliance_verified: "Product compliance verified",
      product_compliance_rejected: "Product compliance rejected",
      product_compliance_recalled: "Product compliance recalled",
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

async function loadNotifications(generation = workspaceGeneration) {
  const body = document.querySelector("#notification-rows");
  const message = document.querySelector("#notifications-message");
  const tab = document.querySelector("#notifications-tab");
  if (!body || !message || !tab) return;
  message.textContent = "";
  try {
    const data = await workspaceRequest("/api/notifications");
    if (generation !== workspaceGeneration) return;
    tab.textContent = data.unread_count
      ? "Notifications (" + data.unread_count + ")"
      : "Notifications";
    body.replaceChildren();
    if (!data.items.length) {
      emptyRow(body, 5, "You have no notifications in this company.");
      return;
    }
    for (const item of data.items) {
      const row = document.createElement("tr");
      const created = new Date(item.created_at);
      textCell(row, Number.isNaN(created.getTime())
        ? item.created_at : created.toLocaleString());
      textCell(row, item.title);
      textCell(row, item.message);
      textCell(row, item.read_at ? "Read" : "Unread");
      const actions = document.createElement("td");
      if (!item.read_at) {
        const markRead = document.createElement("button");
        markRead.type = "button";
        markRead.className = "table-action";
        markRead.textContent = "Mark read";
        markRead.addEventListener("click", async () => {
          markRead.disabled = true;
          try {
            await workspaceRequest(
              "/api/notifications/" + encodeURIComponent(item.id) + "/read",
              {method: "POST", body: "{}"},
            );
            await loadNotifications(generation);
          } catch (error) {
            message.textContent = error.message;
            markRead.disabled = false;
          }
        });
        actions.append(markRead);
      } else {
        actions.textContent = "—";
      }
      row.append(actions);
      body.append(row);
    }
  } catch (error) {
    if (generation !== workspaceGeneration) return;
    emptyRow(body, 5, "Notifications could not be loaded.");
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
  document.querySelector("#weekly-discount-report").hidden = true;
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
            await loadNotifications();
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
  const trackInventory = window.prompt(
    "Track inventory? Enter yes or no", item.track_inventory ? "yes" : "no"
  );
  if (trackInventory === null) return;
  if (!["yes", "no"].includes(trackInventory.trim().toLowerCase())) {
    return workspaceMessage("Enter yes or no for inventory tracking.");
  }
  const lowStockThreshold = window.prompt(
    "Low-stock threshold", item.low_stock_threshold || "0.000"
  );
  if (lowStockThreshold === null) return;
  const categoryKey = window.prompt("Product category key", item.category_key || "general");
  if (categoryKey === null) return;
  const marketCountry = window.prompt("Market country (2-letter code, blank if not set)", item.market_country || "");
  if (marketCountry === null) return;
  const complianceRequired = window.prompt(
    "Require standards approval before sale? Enter yes or no",
    item.compliance_required ? "yes" : "no"
  );
  if (complianceRequired === null) return;
  if (!["yes", "no"].includes(complianceRequired.trim().toLowerCase())) {
    return workspaceMessage("Enter yes or no for standards approval.");
  }
  const currency = window.prompt("Currency (3-letter code)", item.currency);
  if (currency === null) return;
  try {
    await workspaceRequest("/api/products/" + encodeURIComponent(item.id), {
      method: "PATCH",
      body: JSON.stringify({
        sku, name, description, unit_price: unitPrice,
        cost_price: costPrice, minimum_selling_price: minimumSellingPrice,
        track_inventory: trackInventory.trim().toLowerCase() === "yes",
        compliance_required: complianceRequired.trim().toLowerCase() === "yes",
        category_key: categoryKey, market_country: marketCountry.trim().toUpperCase() || null,
        low_stock_threshold: lowStockThreshold, currency,
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
  if (!products.length) return emptyRow(body, 11, "No products yet. Add the first product above.");
  for (const item of products) {
    const row = document.createElement("tr");
    textCell(row, item.sku);
    textCell(row, item.name);
    textCell(row, item.category_key || "general");
    textCell(row, item.market_country || "—");
    textCell(row, amount(item.currency, item.unit_price));
    textCell(row, amount(item.currency, item.minimum_selling_price));
    textCell(row, item.currency);
    textCell(row, item.track_inventory ? "Tracked" : "Not tracked");
    textCell(row, item.compliance_required ? "Approval required" : "Not required");
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

const inventoryMovementLabels = {
  received: "Received",
  sold: "Sold",
  returned: "Returned",
  damaged: "Damaged",
  adjustment_increase: "Admin adjustment (+)",
  adjustment_decrease: "Admin adjustment (−)",
  reserved: "Reserved",
  released: "Reservation released",
};

async function loadInventoryHistory(productId, generation = workspaceGeneration) {
  const body = document.querySelector("#inventory-history-rows");
  body.replaceChildren();
  if (!productId) {
    emptyRow(body, 8, "Select a tracked product to view its movement history.");
    return;
  }
  const data = await workspaceRequest(
    "/api/products/" + encodeURIComponent(productId) + "/stock-movements"
  );
  if (generation !== workspaceGeneration) return;
  if (!data.items.length) {
    emptyRow(body, 8, "No stock movements have been recorded yet.");
    return;
  }
  for (const item of data.items) {
    const row = document.createElement("tr");
    const created = new Date(item.created_at);
    textCell(row, Number.isNaN(created.getTime())
      ? item.created_at : created.toLocaleString());
    const product = products.find((entry) => entry.id === item.product_id);
    textCell(row, product ? product.name : item.product_id);
    textCell(row, inventoryMovementLabels[item.movement_type] || item.movement_type);
    textCell(row, item.batch_code || "—");
    textCell(row, item.expiry_date || "—");
    textCell(row, item.quantity);
    textCell(row, item.reason);
    textCell(row, item.reference || "—");
    body.append(row);
  }
}

async function loadInventoryBatches(productId, generation = workspaceGeneration) {
  const body = document.querySelector("#inventory-batches-rows");
  body.replaceChildren();
  if (!productId) {
    emptyRow(body, 10, "Select a tracked product to view batches.");
    return;
  }
  const data = await workspaceRequest(
    "/api/products/" + encodeURIComponent(productId) + "/stock-batches"
  );
  if (generation !== workspaceGeneration) return;
  const batchProduct = products.find((entry) => entry.id === productId);
  if (!data.items.length) {
    emptyRow(body, 10, "No batches have been recorded for this product.");
    return;
  }
  for (const batch of data.items) {
    const row = document.createElement("tr");
    textCell(row, batch.batch_code);
    textCell(row, [batch.supplier_name, batch.supplier_invoice_reference || batch.delivery_note_reference]
      .filter(Boolean).join(" · ") || "Supplier details missing");
    textCell(row, [batch.manufacturer_name, batch.country_of_origin].filter(Boolean).join(" · ") || "Origin details missing");
    textCell(row, batch.expiry_date || "No expiry date");
    textCell(row, batch.stock_on_hand);
    textCell(row, batch.reserved_quantity);
    textCell(row, batch.available_quantity);
    textCell(row, batch.compliance_status.replaceAll("_", " "));
    textCell(row, batch.status.replaceAll("_", " "));
    const actions = document.createElement("td");
    if (batchProduct && batchProduct.market_country === "TZ") {
      const tbsLink = document.createElement("a");
      tbsLink.href = "https://tbs.go.tz/certified-product-companies";
      tbsLink.target = "_blank";
      tbsLink.rel = "noopener noreferrer";
      tbsLink.textContent = "TBS product register (where applicable)";
      tbsLink.className = "table-action";
      tbsLink.style.display = "block";
      actions.append(tbsLink);
      const sadcasLink = document.createElement("a");
      sadcasLink.href = "https://www.sadcas.org/accredited-organisations/product-certification-bodies";
      sadcasLink.target = "_blank";
      sadcasLink.rel = "noopener noreferrer";
      sadcasLink.textContent = "SADCAS accreditation scope";
      sadcasLink.className = "table-action";
      sadcasLink.style.display = "block";
      actions.append(sadcasLink);
      const tmdaLink = document.createElement("a");
      tmdaLink.href = "https://tmda.go.tz/pages/procedures-for-market-authorization";
      tmdaLink.target = "_blank";
      tmdaLink.rel = "noopener noreferrer";
      tmdaLink.textContent = "TMDA market authorisation (where applicable)";
      tmdaLink.className = "table-action";
      tmdaLink.style.display = "block";
      actions.append(tmdaLink);
      const tmdaImportLink = document.createElement("a");
      tmdaImportLink.href = "https://www.tmda.go.tz/pages/import-and-export-control";
      tmdaImportLink.target = "_blank";
      tmdaImportLink.rel = "noopener noreferrer";
      tmdaImportLink.textContent = "TMDA import/export control";
      tmdaImportLink.className = "table-action";
      tmdaImportLink.style.display = "block";
      actions.append(tmdaImportLink);
    }
    if (["pending_verification", "approved", "exception_approved", "verified_not_required"].includes(batch.compliance_status)) {
      const review = document.createElement("button");
      review.type = "button";
      review.className = "table-action";
      review.textContent = ["approved", "exception_approved", "verified_not_required"].includes(batch.compliance_status) ? "Recall" : "Review";
      review.addEventListener("click", async () => {
        const decision = ["approved", "exception_approved", "verified_not_required"].includes(batch.compliance_status)
          ? "recall" : window.prompt(
            "Evidence-based decision: approve, reject, release_not_required (only with a not-required category policy)" +
            (workspaceRole === "admin" ? ", or exception (never for legal requirements)" : "") +
            ". Missing or uncertain proof must remain quarantined.",
            "approve"
          );
        if (!decision) return;
        const normalized = decision.trim().toLowerCase();
        const allowedDecisions = workspaceRole === "admin"
          ? ["approve", "reject", "recall", "exception", "release_not_required"]
          : ["approve", "reject", "recall", "release_not_required"];
        if (!allowedDecisions.includes(normalized)) {
          return workspaceMessage("Choose one of the available compliance decisions.");
        }
        const payload = {decision: normalized};
        try {
          if (["approve", "exception", "release_not_required"].includes(normalized)) {
            let legacyProvenanceCompleted = false;
            if (!batch.supplier_name) {
              payload.supplier_name = window.prompt("Supplier name from invoice / delivery note", "");
              if (payload.supplier_name === null || !payload.supplier_name.trim()) return;
              legacyProvenanceCompleted = true;
            }
            if (!batch.supplier_invoice_reference && !batch.delivery_note_reference) {
              const invoiceReference = window.prompt(
                "Supplier invoice reference (leave blank if only a delivery note exists)",
                "",
              );
              if (invoiceReference === null) return;
              if (invoiceReference.trim()) {
                payload.supplier_invoice_reference = invoiceReference.trim();
              } else {
                payload.delivery_note_reference = window.prompt(
                  "Delivery note reference (required when no invoice exists)",
                  "",
                );
                if (
                  payload.delivery_note_reference === null
                  || !payload.delivery_note_reference.trim()
                ) return;
              }
              legacyProvenanceCompleted = true;
            }
            if (!batch.manufacturer_name) {
              payload.manufacturer_name = window.prompt("Manufacturer name", "");
              if (payload.manufacturer_name === null || !payload.manufacturer_name.trim()) return;
              legacyProvenanceCompleted = true;
            }
            if (!batch.country_of_origin) {
              payload.country_of_origin = window.prompt("Country of origin (2-letter code)", "");
              if (payload.country_of_origin === null || !payload.country_of_origin.trim()) return;
              legacyProvenanceCompleted = true;
            }
            if (legacyProvenanceCompleted && normalized === "approve") {
              payload.notes = window.prompt(
                "Reason for completing missing legacy supplier details",
                "",
              );
              if (payload.notes === null || !payload.notes.trim()) return;
            }
          }
          if (normalized === "approve") {
          payload.qr_code = window.prompt("QR / traceability value (required)", "");
          if (payload.qr_code === null) return;
          payload.authority_name = window.prompt("Issuing standards authority (for example TBS)", batch.authority_name || "");
          if (payload.authority_name === null) return;
          payload.authority_country = window.prompt("Issuing country code (2 letters)", "TZ");
          if (payload.authority_country === null) return;
          payload.certificate_reference = window.prompt("Certificate reference", "");
          if (payload.certificate_reference === null) return;
          payload.authority_role = window.prompt(
            "Issuer role: standards_body, regulator, certification_body, accreditation_body, testing_lab, inspection_body, other",
            /tbs|tanzania bureau/i.test(payload.authority_name) ? "standards_body" : "regulator",
          );
          if (payload.authority_role === null) return;
          payload.verification_method = window.prompt(
            "How did you check it? official_registry, accreditation_scope, issuer_confirmation, document_review",
            "official_registry",
          );
          if (payload.verification_method === null) return;
          const isTbs = /tbs|tanzania bureau/i.test(payload.authority_name);
          const defaultSource = payload.verification_method === "accreditation_scope" && isTbs
            ? "https://www.sadcas.org/accredited-organisations/product-certification-bodies"
            : isTbs ? "https://tbs.go.tz/certified-product-companies" : "";
          payload.verification_source_url = window.prompt(
            "HTTPS official registry / accreditation source URL (required for registry or scope checks)",
            defaultSource,
          ) || "";
          payload.verification_reference = window.prompt(
            "Registry licence, accreditation number, or issuer case reference",
            payload.certificate_reference,
          ) || "";
          payload.verified_product_identifier = window.prompt(
            "Exact product, brand, model or batch identity you matched",
            batchProduct ? batchProduct.name + (batchProduct.sku ? " / " + batchProduct.sku : "") : "",
          );
          if (payload.verified_product_identifier === null) return;
          payload.verified_scope = window.prompt(
            "Exact product category, standard and market scope confirmed",
            "",
          );
          if (payload.verified_scope === null) return;
          if (payload.verification_method === "accreditation_scope") {
            payload.accreditation_body_name = window.prompt(
              "Accreditation body whose scope you checked",
              isTbs ? "SADCAS" : "",
            );
            if (payload.accreditation_body_name === null) return;
          }
          payload.standard_reference = window.prompt("Standard / regulation reference (optional)", "") || "";
          const fileInput = document.createElement("input");
          fileInput.type = "file";
          fileInput.accept = ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp";
          fileInput.style.position = "fixed";
          fileInput.style.left = "-10000px";
          document.body.append(fileInput);
          const selectedFile = new Promise((resolve) => {
            fileInput.addEventListener("change", () => resolve(fileInput.files[0] || null), {once: true});
            fileInput.addEventListener("cancel", () => resolve(null), {once: true});
          });
          fileInput.click();
          const evidenceFile = await selectedFile;
          fileInput.remove();
          if (!evidenceFile) return;
          const evidenceForm = new FormData();
          evidenceForm.append("file", evidenceFile);
          const uploadedEvidence = await workspaceRequest(
            "/api/stock-batches/" + encodeURIComponent(batch.id) + "/evidence",
            {method: "POST", body: evidenceForm},
          );
          payload.evidence_file_id = uploadedEvidence.item.id;
        } else {
          payload.notes = window.prompt("Reason for " + normalized + " (required)", "");
          if (payload.notes === null || !payload.notes.trim()) return;
          if (normalized === "exception") {
            payload.qr_code = window.prompt("QR / batch traceability value (required for exception)", "");
            if (payload.qr_code === null || !payload.qr_code.trim()) return;
          }
          if (normalized === "release_not_required" || normalized === "exception") {
            const fileInput = document.createElement("input");
            fileInput.type = "file";
            fileInput.accept = ".pdf,.jpg,.jpeg,.png,.webp,application/pdf,image/jpeg,image/png,image/webp";
            fileInput.style.position = "fixed";
            fileInput.style.left = "-10000px";
            document.body.append(fileInput);
            const selectedFile = new Promise((resolve) => {
              fileInput.addEventListener("change", () => resolve(fileInput.files[0] || null), {once: true});
              fileInput.addEventListener("cancel", () => resolve(null), {once: true});
            });
            fileInput.click();
            const evidenceFile = await selectedFile;
            fileInput.remove();
            if (!evidenceFile) return;
            const evidenceForm = new FormData();
            evidenceForm.append("file", evidenceFile);
            const uploadedEvidence = await workspaceRequest(
              "/api/stock-batches/" + encodeURIComponent(batch.id) + "/evidence",
              {method: "POST", body: evidenceForm},
            );
            payload.evidence_file_id = uploadedEvidence.item.id;
          }
        }
        review.disabled = true;
          await workspaceRequest("/api/stock-batches/" + encodeURIComponent(batch.id) + "/compliance", {
            method: "POST", body: JSON.stringify(payload),
          });
          await loadInventory();
          workspaceMessage("Batch compliance decision recorded. The uploaded file is stored privately; QR values remain traceability inputs and do not prove official approval.");
        } catch (error) {
          workspaceMessage(error.message);
          review.disabled = false;
        }
      });
      actions.append(review);
    }
    if (batch.verification_method) {
      const verificationSummary = document.createElement("small");
      verificationSummary.textContent = [
        batch.authority_role || "issuer",
        batch.verification_method.replaceAll("_", " "),
        batch.verified_scope || "",
      ].filter(Boolean).join(" · ");
      verificationSummary.style.display = "block";
      verificationSummary.style.marginTop = "6px";
      actions.append(verificationSummary);
      if (batch.verification_source_url) {
        const sourceLink = document.createElement("a");
        sourceLink.href = batch.verification_source_url;
        sourceLink.target = "_blank";
        sourceLink.rel = "noopener noreferrer";
        sourceLink.textContent = "Open recorded verification source";
        sourceLink.className = "table-action";
        sourceLink.style.display = "block";
        actions.append(sourceLink);
      }
    }
    const evidenceButton = document.createElement("button");
    evidenceButton.type = "button";
    evidenceButton.className = "table-action";
    evidenceButton.textContent = "Evidence";
    evidenceButton.addEventListener("click", async () => {
      evidenceButton.disabled = true;
      try {
        const evidence = await workspaceRequest(
          "/api/stock-batches/" + encodeURIComponent(batch.id) + "/evidence"
        );
        const links = evidence.items || [];
        if (!links.length) {
          workspaceMessage("No private evidence has been uploaded for this batch yet.");
        } else {
          for (const item of links) {
            const link = document.createElement("a");
            link.href = item.download_url;
            link.textContent = "Download " + item.filename;
            link.className = "table-action";
            link.style.display = "block";
            link.style.marginTop = "4px";
            actions.append(link);
          }
          workspaceMessage(links.length + " private evidence file(s) available.");
        }
      } catch (error) {
        workspaceMessage(error.message);
      } finally {
        evidenceButton.disabled = false;
      }
    });
    actions.append(evidenceButton);
    if (!actions.childElementCount) actions.textContent = "—";
    row.append(actions);
    body.append(row);
  }
}

async function loadInventory(generation = workspaceGeneration) {
  if (!["admin", "manager"].includes(workspaceRole)) return;
  const body = document.querySelector("#inventory-rows");
  const select = document.querySelector("#inventory-product");
  const data = await workspaceRequest("/api/inventory");
  if (generation !== workspaceGeneration) return;
  const previousProductId = select.value;
  body.replaceChildren();
  select.replaceChildren();
  const placeholder = document.createElement("option");
  placeholder.value = "";
  placeholder.textContent = "Choose a tracked product";
  select.append(placeholder);
  const trackedProducts = products.filter((product) => product.track_inventory);
  for (const product of trackedProducts) {
    const option = document.createElement("option");
    option.value = product.id;
    option.textContent = product.sku + " — " + product.name;
    select.append(option);
  }
  for (const item of data.items) {
    const row = document.createElement("tr");
    textCell(row, item.sku);
    textCell(row, item.name);
    textCell(row, item.stock_on_hand);
    textCell(row, item.reserved_quantity);
    textCell(row, item.available_quantity);
    textCell(row, item.expired_quantity || "0.000");
    textCell(row, item.expiring_soon_quantity || "0.000");
    textCell(row, item.low_stock_threshold);
    textCell(row, item.status.replaceAll("_", " "));
    body.append(row);
  }
  if (!data.items.length) {
    emptyRow(body, 9, "No products currently have inventory tracking enabled.");
  }
  const current = trackedProducts.some((product) => product.id === previousProductId)
    ? previousProductId : (trackedProducts[0] ? trackedProducts[0].id : "");
  select.value = current;
  await Promise.all([
    loadInventoryHistory(current, generation),
    loadInventoryBatches(current, generation),
  ]);
}



async function loadCompliancePolicies(generation = workspaceGeneration) {
  const body = document.querySelector("#compliance-policy-rows");
  const message = document.querySelector("#compliance-policy-message");
  if (workspaceRole !== "admin") return;
  message.textContent = "";
  const data = await workspaceRequest("/api/compliance-policies");
  if (generation !== workspaceGeneration) return;
  body.replaceChildren();
  if (!data.items.length) {
    emptyRow(body, 6, "No category rules configured.");
    return;
  }
  for (const policy of data.items) {
    const row = document.createElement("tr");
    textCell(row, policy.category_key);
    textCell(row, policy.market_country);
    textCell(row, policy.approval_mode.replaceAll("_", " "));
    textCell(row, policy.legal_requirement ? "Yes — no Admin override" : "No");
    textCell(row, policy.accepted_authorities.join(", ") || "No authority allow-list");
    const basis = document.createElement("td");
    if (policy.requirement_source_url && policy.requirement_reference) {
      const basisLink = document.createElement("a");
      basisLink.href = policy.requirement_source_url;
      basisLink.target = "_blank";
      basisLink.rel = "noopener noreferrer";
      basisLink.textContent = policy.requirement_reference;
      basisLink.className = "table-action";
      basis.append(basisLink);
    } else {
      basis.textContent = "Source missing — update required";
    }
    row.append(basis);
    body.append(row);
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
    if (workspaceRole === "admin") await loadCompliancePolicies(generation);
    else emptyRow(document.querySelector("#compliance-policy-rows"), 6, "Category compliance rules are managed by company Admins.");
    await loadSales(generation);
    await loadNotifications(generation);
    await loadSalesTargets(generation);
    await loadDashboardAnalytics(generation);
    await loadDashboardSalespeople(generation);
    if (["admin", "manager"].includes(workspaceRole)) {
      await loadInventory(generation);
    }
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
  document.querySelector("#compliance-policy-form").hidden = workspaceRole !== "admin";
  document.querySelector("#sale-form").hidden = workspaceRole === "viewer";
  document.querySelector("#sale-floor-override").hidden = workspaceRole !== "admin";
  document.querySelector("#team-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#company-settings-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#discount-approvals-tab").hidden = workspaceRole !== "admin";
  document.querySelector("#inventory-tab").hidden =
    !["admin", "manager"].includes(workspaceRole);
  document.querySelector("#inventory-movement-form").hidden =
    !["admin", "manager"].includes(workspaceRole);
  document.querySelectorAll("[data-admin-only]").forEach((option) => {
    option.hidden = workspaceRole !== "admin";
    option.disabled = workspaceRole !== "admin";
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
  document.querySelector("#audit-panel").hidden = true;
  document.querySelector("#discount-approvals-tab").hidden = true;
  document.querySelector("#inventory-tab").hidden = true;
  document.querySelector("#inventory-message").textContent = "";
  document.querySelector("#inventory-rows").replaceChildren();
  document.querySelector("#inventory-history-rows").replaceChildren();
  document.querySelector("#inventory-batches-rows").replaceChildren();
  document.querySelector("#discount-approvals-message").textContent = "";
  document.querySelector("#notifications-message").textContent = "";
  document.querySelector("#notification-rows").replaceChildren();
  document.querySelector("#notifications-tab").textContent = "Notifications";
  document.querySelector("#audit-message").textContent = "";
  emptyRow(document.querySelector("#audit-rows"), 4, "Select a company to view activity.");
  workspace.hidden = true;
});

document.querySelectorAll("[data-workspace-tab]").forEach((button) => {
  button.addEventListener("click", () => {
    selectTab(button.dataset.workspaceTab);
    if (button.dataset.workspaceTab === "inventory") {
      loadInventory().catch((error) => {
        document.querySelector("#inventory-message").textContent = error.message;
      });
    }
  });
});

document.querySelector("#inventory-product").addEventListener("change", async (event) => {
  try {
    await Promise.all([
      loadInventoryHistory(event.currentTarget.value),
      loadInventoryBatches(event.currentTarget.value),
    ]);
  } catch (error) {
    document.querySelector("#inventory-message").textContent = error.message;
  }
});

function updateInventoryBatchRequirement() {
  const movement = document.querySelector("#inventory-movement-type").value;
  document.querySelector("#inventory-batch-code").required =
    ["received", "returned", "adjustment_increase"].includes(movement);
}

document.querySelector("#inventory-movement-type").addEventListener(
  "change", updateInventoryBatchRequirement
);
updateInventoryBatchRequirement();

document.querySelector("#inventory-movement-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const productId = document.querySelector("#inventory-product").value;
  if (!productId) {
    document.querySelector("#inventory-message").textContent =
      "Choose a product with inventory tracking enabled.";
    return;
  }
  button.disabled = true;
  try {
    await workspaceRequest(
      "/api/products/" + encodeURIComponent(productId) + "/stock-movements",
      {
        method: "POST",
        body: JSON.stringify({
          movement_type: document.querySelector("#inventory-movement-type").value,
          quantity: document.querySelector("#inventory-quantity").value,
          reason: document.querySelector("#inventory-reason").value,
          reference: document.querySelector("#inventory-reference").value,
          batch_code: document.querySelector("#inventory-batch-code").value,
          expiry_date: document.querySelector("#inventory-expiry-date").value || null,
        }),
      }
    );
    document.querySelector("#inventory-reason").value = "";
    document.querySelector("#inventory-reference").value = "";
    document.querySelector("#inventory-batch-code").value = "";
    document.querySelector("#inventory-expiry-date").value = "";
    document.querySelector("#inventory-quantity").value = "";
    document.querySelector("#inventory-message").textContent =
      "Stock movement recorded in the inventory ledger.";
    await loadInventory();
  } catch (error) {
    document.querySelector("#inventory-message").textContent = error.message;
  } finally {
    button.disabled = false;
  }
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


document.querySelector("#compliance-policy-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (workspaceRole !== "admin") return;
  const form = event.currentTarget;
  const button = form.querySelector("button");
  const message = document.querySelector("#compliance-policy-message");
  const authorities = document.querySelector("#policy-authorities").value
    .split("\n").map((value) => value.trim()).filter(Boolean);
  button.disabled = true;
  message.textContent = "";
  try {
    await workspaceRequest("/api/compliance-policies", {
      method: "POST",
      body: JSON.stringify({
        category_key: document.querySelector("#policy-category-key").value,
        market_country: document.querySelector("#policy-market-country").value.trim().toUpperCase(),
        approval_mode: document.querySelector("#policy-approval-mode").value,
        accepted_authorities: authorities,
      }),
    });
    message.textContent = "Category compliance rule saved.";
    await loadCompliancePolicies();
    await loadWorkspace();
  } catch (error) {
    message.textContent = error.message;
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
        compliance_required: document.querySelector("#product-compliance-required").checked,
        category_key: document.querySelector("#product-category-key").value,
        market_country: document.querySelector("#product-market-country").value.trim().toUpperCase() || null,
        low_stock_threshold: document.querySelector("#product-low-stock-threshold").value,
        currency: document.querySelector("#product-currency").value,
      }),
    });
    form.reset();
    document.querySelector("#product-currency").value = "TZS";
    document.querySelector("#product-low-stock-threshold").value = "0";
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
document.querySelector("#notifications-tab").addEventListener("click", loadNotifications);
document.querySelector("#notifications-refresh").addEventListener("click", loadNotifications);
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



let supplierRecords = [];
let purchaseOrderRecords = [];
function supplierCsv(value) { return value.split(",").map((part) => part.trim()).filter(Boolean); }
function fillSupplierSelect(select) {
  const previous=select.value; select.replaceChildren(new Option("Choose supplier",""));
  for (const item of supplierRecords) select.add(new Option(item.legal_name+" · "+item.status,item.id));
  if (supplierRecords.some((item)=>item.id===previous)) select.value=previous;
}
async function loadSuppliers() {
  const message=document.querySelector("#suppliers-message"), body=document.querySelector("#supplier-rows");
  if (!["admin","manager"].includes(workspaceRole)) return;
  message.textContent="";
  try {
    const data=await workspaceRequest("/api/suppliers"); supplierRecords=data.items; body.replaceChildren();
    if (!data.items.length) emptyRow(body,6,"No suppliers registered yet.");
    for (const item of data.items) {
      const row=document.createElement("tr");
      textCell(row,item.legal_name); textCell(row,item.country); textCell(row,item.licence_valid_until||"Not recorded");
      textCell(row,(item.authorised_categories||[]).join(", ")||"—"); textCell(row,item.status.replaceAll("_"," "));
      const actions=document.createElement("td");
      if (item.status==="pending_review" && item.submitted_by_user_id!==workspaceUserId) {
        for (const [label,decision] of [["Approve","approve"],["Restrict","restrict"],["Reject","reject"]]) {
          const b=document.createElement("button"); b.type="button"; b.className=decision==="approve"?"table-action":"table-action table-action-danger"; b.textContent=label;
          b.addEventListener("click",async()=>{
            let notes="";
            if(decision!=="approve"){notes=window.prompt("Reason for "+decision+"ing this supplier");if(notes===null)return;if(!notes.trim()){message.textContent="A reason is required.";return;}}
            b.disabled=true;
            try{await workspaceRequest("/api/suppliers/"+encodeURIComponent(item.id)+"/review",{method:"POST",body:JSON.stringify({decision,notes})});await loadSuppliers();}
            catch(error){message.textContent=error.message;b.disabled=false;}
          }); actions.append(b);
        }
      } else actions.textContent=item.submitted_by_user_id===workspaceUserId&&item.status==="pending_review"?"Independent reviewer required":(item.review_notes||"—");
      row.append(actions); body.append(row);
    }
    fillSupplierSelect(document.querySelector("#supplier-document-owner")); fillSupplierSelect(document.querySelector("#po-supplier"));
  } catch(error){message.textContent=error.message;emptyRow(body,6,"Supplier data could not be loaded.");}
}
async function loadSupplierDocuments(id) {
  const body=document.querySelector("#supplier-document-rows"); body.replaceChildren();
  if(!id)return emptyRow(body,4,"Choose a supplier to view evidence.");
  const data=await workspaceRequest("/api/suppliers/"+encodeURIComponent(id)+"/documents");
  if(!data.items.length)return emptyRow(body,4,"No evidence files uploaded.");
  for(const item of data.items){
    const row=document.createElement("tr");textCell(row,item.original_filename);textCell(row,item.scan_status);textCell(row,new Date(item.created_at).toLocaleString());
    const cell=document.createElement("td"),button=document.createElement("button");button.type="button";button.className="table-action";button.textContent="Download";
    button.addEventListener("click",async()=>{try{const response=await fetch("/api/suppliers/"+encodeURIComponent(id)+"/documents/"+encodeURIComponent(item.id),{credentials:"same-origin"});if(!response.ok){const data=await response.json().catch(()=>({}));throw new Error(data.error||"Download failed.");}const blob=await response.blob(),url=URL.createObjectURL(blob),link=document.createElement("a");link.href=url;link.download=item.original_filename;link.click();URL.revokeObjectURL(url);}catch(error){document.querySelector("#supplier-document-message").textContent=error.message;}});
    cell.append(button);row.append(cell);body.append(row);
  }
}
async function loadPurchaseOrders(){
  const body=document.querySelector("#purchase-order-rows"),message=document.querySelector("#purchase-orders-message");message.textContent="";
  try{
    const data=await workspaceRequest("/api/purchase-orders");purchaseOrderRecords=data.items;body.replaceChildren();
    if(!data.items.length)emptyRow(body,5,"No purchase orders created yet.");
    for(const order of data.items){const row=document.createElement("tr");textCell(row,order.order_number);const supplier=supplierRecords.find((item)=>item.id===order.supplier_id);textCell(row,supplier?supplier.legal_name:order.supplier_id);textCell(row,order.status.replaceAll("_"," "));textCell(row,order.currency);textCell(row,order.lines.map((line)=>line.received_quantity+" / "+line.ordered_quantity).join(", "));body.append(row);}
    const select=document.querySelector("#receipt-order");select.replaceChildren(new Option("Choose an open order",""));
    for(const order of data.items.filter((item)=>!["received","cancelled"].includes(item.status)))select.add(new Option(order.order_number,order.id));
    populateReceiptLines();
    const productSelect=document.querySelector("#po-product");productSelect.replaceChildren(new Option("Choose product",""));
    for(const product of products.filter((item)=>item.track_inventory&&item.is_active!==false))productSelect.add(new Option(product.name+" · "+product.sku,product.id));
  }catch(error){message.textContent=error.message;emptyRow(body,5,"Purchase orders could not be loaded.");}
}
function populateReceiptLines(){
  const order=purchaseOrderRecords.find((item)=>item.id===document.querySelector("#receipt-order").value),select=document.querySelector("#receipt-line");
  select.replaceChildren(new Option("Choose outstanding line",""));if(!order)return;
  for(const line of order.lines.filter((item)=>Number(item.remaining_quantity)>0)){const product=products.find((item)=>item.id===line.product_id);select.add(new Option((product?product.name:line.product_id)+" · remaining "+line.remaining_quantity,line.id));}
}
document.querySelector("#supplier-form").addEventListener("submit",async(event)=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("button");button.disabled=true;
  try{
    await workspaceRequest("/api/suppliers",{method:"POST",body:JSON.stringify({
      legal_name:document.querySelector("#supplier-legal-name").value,country:document.querySelector("#supplier-country").value,
      registration_number:document.querySelector("#supplier-registration").value,tax_identifier:document.querySelector("#supplier-tax").value,
      contact_name:document.querySelector("#supplier-contact-name").value,contact_email:document.querySelector("#supplier-contact-email").value,contact_phone:document.querySelector("#supplier-contact-phone").value,
      authorised_categories:supplierCsv(document.querySelector("#supplier-categories").value),authorised_territories:supplierCsv(document.querySelector("#supplier-territories").value),
      licence_number:document.querySelector("#supplier-licence-number").value,licence_issuer:document.querySelector("#supplier-licence-issuer").value,licence_source_url:document.querySelector("#supplier-licence-url").value,
      licence_valid_until:document.querySelector("#supplier-licence-expiry").value,next_review_date:document.querySelector("#supplier-review-date").value,
    })});
    form.reset();document.querySelector("#supplier-country").value="TZ";document.querySelector("#supplier-territories").value="TZ";await loadSuppliers();document.querySelector("#suppliers-message").textContent="Supplier submitted for independent review.";
  }catch(error){document.querySelector("#suppliers-message").textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector("#suppliers-refresh").addEventListener("click",loadSuppliers);
document.querySelector("#supplier-document-owner").addEventListener("change",(event)=>loadSupplierDocuments(event.currentTarget.value).catch((error)=>{document.querySelector("#supplier-document-message").textContent=error.message;}));
document.querySelector("#supplier-document-form").addEventListener("submit",async(event)=>{
  event.preventDefault();const id=document.querySelector("#supplier-document-owner").value,file=document.querySelector("#supplier-document-file").files[0];if(!id||!file)return;
  const button=event.currentTarget.querySelector("button");button.disabled=true;
  try{const body=new FormData();body.append("file",file);await workspaceRequest("/api/suppliers/"+encodeURIComponent(id)+"/documents",{method:"POST",body});document.querySelector("#supplier-document-file").value="";document.querySelector("#supplier-document-message").textContent="Document scanned and stored securely.";await loadSupplierDocuments(id);}
  catch(error){document.querySelector("#supplier-document-message").textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector("#po-product").addEventListener("change",(event)=>{const product=products.find((item)=>item.id===event.currentTarget.value);if(product)document.querySelector("#po-currency").value=product.currency;});
document.querySelector("#purchase-order-form").addEventListener("submit",async(event)=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("button");button.disabled=true;
  try{await workspaceRequest("/api/purchase-orders",{method:"POST",body:JSON.stringify({supplier_id:document.querySelector("#po-supplier").value,order_number:document.querySelector("#po-number").value,currency:document.querySelector("#po-currency").value,notes:document.querySelector("#po-notes").value,lines:[{product_id:document.querySelector("#po-product").value,ordered_quantity:document.querySelector("#po-quantity").value,unit_cost:document.querySelector("#po-unit-cost").value}]})});form.reset();document.querySelector("#po-currency").value="TZS";await loadPurchaseOrders();document.querySelector("#purchase-orders-message").textContent="Purchase order created.";}
  catch(error){document.querySelector("#purchase-orders-message").textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector("#purchase-orders-refresh").addEventListener("click",async()=>{await loadSuppliers();await loadPurchaseOrders();});
document.querySelector("#receipt-order").addEventListener("change",populateReceiptLines);
document.querySelector("#purchase-receipt-form").addEventListener("submit",async(event)=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("button"),id=document.querySelector("#receipt-order").value;button.disabled=true;
  try{await workspaceRequest("/api/purchase-orders/"+encodeURIComponent(id)+"/receipts",{method:"POST",body:JSON.stringify({delivery_note_reference:document.querySelector("#receipt-delivery-note").value,supplier_invoice_reference:document.querySelector("#receipt-invoice").value,lines:[{purchase_order_line_id:document.querySelector("#receipt-line").value,quantity:document.querySelector("#receipt-quantity").value,batch_code:document.querySelector("#receipt-batch").value,serial_reference:document.querySelector("#receipt-serial").value,certificate_reference:document.querySelector("#receipt-certificate").value,country_of_origin:document.querySelector("#receipt-origin").value,manufacturer_name:document.querySelector("#receipt-manufacturer").value,expiry_date:document.querySelector("#receipt-expiry").value}]})});form.reset();document.querySelector("#receipt-origin").value="TZ";await loadPurchaseOrders();document.querySelector("#receipt-message").textContent="Receipt recorded. Stock is quarantined pending verification.";}
  catch(error){document.querySelector("#receipt-message").textContent=error.message;}finally{button.disabled=false;}
});
document.querySelector("#suppliers-tab").addEventListener("click",loadSuppliers);
document.querySelector("#purchasing-tab").addEventListener("click",async()=>{await loadSuppliers();await loadPurchaseOrders();});
document.addEventListener("salesdash:company-selected",()=>{
  const allowed=["admin","manager"].includes(workspaceRole);document.querySelector("#suppliers-tab").hidden=!allowed;document.querySelector("#purchasing-tab").hidden=!allowed;document.querySelector("#expenses-tab").hidden=!allowed;
  supplierRecords=[];purchaseOrderRecords=[];
});

async function loadExpenses() {
  const body=document.querySelector("#expense-rows"),message=document.querySelector("#expenses-message");
  message.textContent="";
  try {
    const data=await workspaceRequest("/api/expenses");
    body.replaceChildren();
    if(!data.items.length) emptyRow(body,7,"No expenses recorded yet.");
    for(const item of data.items) {
      const row=document.createElement("tr");
      textCell(row,item.expense_date);textCell(row,item.description);textCell(row,item.category.replaceAll("_"," "));
      textCell(row,amount(item.currency,item.amount));textCell(row,item.payment_method);textCell(row,item.status);
      const actions=document.createElement("td");
      if(item.status==="recorded" && ["admin","manager"].includes(workspaceRole)) {
        addCatalogAction(actions,"Void",async()=>{
          const reason=window.prompt("Reason for voiding this expense");
          if(reason===null)return;
          if(!reason.trim()){message.textContent="A reason is required.";return;}
          try{await workspaceRequest("/api/expenses/"+encodeURIComponent(item.id)+"/void",{method:"POST",body:JSON.stringify({reason})});await loadExpenses();message.textContent="Expense voided; the original record remains in the ledger.";}
          catch(error){message.textContent=error.message;}
        },true);
      }
      if(!actions.childElementCount)actions.textContent="—";
      row.append(actions);body.append(row);
    }
    message.textContent="Showing "+data.items.length+" expense records (maximum 500).";
    const totals=(data.totals_by_currency||[]).map(item=>amount(item.currency,item.amount));
    document.querySelector("#expenses-totals").textContent="Recorded totals: "+(totals.length?totals.join(" · "):"—");
  } catch(error) {
    emptyRow(body,7,"Expenses could not be loaded.");message.textContent=error.message;
  }
}
document.querySelector("#expense-date").value=localDate();
document.querySelector("#expense-form").addEventListener("submit",async(event)=>{
  event.preventDefault();const form=event.currentTarget,button=form.querySelector("button");button.disabled=true;
  try{
    await workspaceRequest("/api/expenses",{method:"POST",body:JSON.stringify({
      description:document.querySelector("#expense-description").value,
      category:document.querySelector("#expense-category").value,
      amount:document.querySelector("#expense-amount").value,
      currency:document.querySelector("#expense-currency").value,
      expense_date:document.querySelector("#expense-date").value,
      payment_method:document.querySelector("#expense-payment-method").value,
      reference:document.querySelector("#expense-reference").value,
      notes:document.querySelector("#expense-notes").value
    })});
    form.reset();document.querySelector("#expense-currency").value="TZS";document.querySelector("#expense-date").value=localDate();
    await loadExpenses();document.querySelector("#expenses-message").textContent="Expense recorded.";
  }catch(error){document.querySelector("#expenses-message").textContent=error.message;}
  finally{button.disabled=false;}
});
document.querySelector("#expenses-refresh").addEventListener("click",loadExpenses);
document.querySelector("#expenses-tab").addEventListener("click",loadExpenses);
