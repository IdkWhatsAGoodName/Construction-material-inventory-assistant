"use strict";

const panel = document.querySelector("#order-panel");
const form = document.querySelector("#order-evaluation-form");
const skuInput = document.querySelector("#order-sku");
const quantityInput = document.querySelector("#order-quantity");
const description = document.querySelector("#order-material-description");
const evaluateButton = document.querySelector("#order-evaluate");
const cancelButton = document.querySelector("#order-cancel");
const resultPanel = document.querySelector("#order-result");
const resultMessage = document.querySelector("#order-result-message");
const expiry = document.querySelector("#order-expiry");
const confirmButton = document.querySelector("#order-confirm");
const orderStatus = document.querySelector("#order-status");

let activeToken = null;
let initiatingButton = null;

document.querySelectorAll(".order-row-action").forEach((button) => {
  button.addEventListener("click", () => openOrderPanel(button));
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  setBusy(true);
  resetResult();
  orderStatus.textContent = "Evaluating order…";
  try {
    const response = await fetch("/api/orders/evaluate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        material_query: skuInput.value,
        quantity: Number(quantityInput.value),
      }),
    });
    const body = await response.json();
    if (!response.ok) {
      throw new Error(errorMessage(body, "The order could not be evaluated."));
    }
    showEvaluation(body);
    orderStatus.textContent = "Order evaluation complete.";
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

confirmButton.addEventListener("click", async () => {
  if (!activeToken) return;
  setBusy(true);
  orderStatus.textContent = "Confirming reservation…";
  try {
    const response = await fetch("/api/orders/confirm", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ confirmation_token: activeToken }),
    });
    const body = await response.json();
    if (!response.ok && response.status !== 409) {
      throw new Error(errorMessage(body, "The reservation could not be confirmed."));
    }
    activeToken = null;
    confirmButton.hidden = true;
    resultMessage.textContent = body.message;
    if (body.item) updateMaterialRow(body.item);
    await refreshInventoryAlerts();
    resultPanel.focus();
    orderStatus.textContent =
      body.outcome === "confirmed"
        ? "Reservation confirmed and inventory display refreshed."
        : "The evaluation became stale. Inventory display refreshed; evaluate again.";
  } catch (error) {
    showError(error);
  } finally {
    setBusy(false);
  }
});

cancelButton.addEventListener("click", () => {
  panel.hidden = true;
  resetResult();
  orderStatus.textContent = "";
  initiatingButton?.focus();
});

function openOrderPanel(button) {
  initiatingButton = button;
  skuInput.value = button.dataset.sku;
  description.textContent = button.dataset.description;
  quantityInput.value = "1";
  panel.hidden = false;
  resetResult();
  orderStatus.textContent = "";
  quantityInput.focus();
}

function showEvaluation(body) {
  activeToken = body.confirmation_token;
  resultMessage.textContent = body.message;
  resultPanel.hidden = false;
  if (body.expires_at) {
    const timestamp = new Date(body.expires_at).toLocaleString();
    expiry.textContent = `This unconfirmed quote expires at ${timestamp} (15 minutes after evaluation).`;
    expiry.hidden = false;
  }
  confirmButton.hidden = !activeToken;
  resultPanel.focus();
}

function resetResult() {
  activeToken = null;
  resultPanel.hidden = true;
  resultMessage.textContent = "";
  expiry.textContent = "";
  expiry.hidden = true;
  confirmButton.hidden = true;
}

function setBusy(busy) {
  evaluateButton.disabled = busy;
  confirmButton.disabled = busy;
  cancelButton.disabled = busy;
}

function showError(error) {
  resultPanel.hidden = false;
  resultMessage.textContent = error instanceof Error ? error.message : "Unexpected order error.";
  resultPanel.focus();
  orderStatus.textContent = "Order action failed.";
}

function errorMessage(body, fallback) {
  return body?.detail?.message || body?.message || fallback;
}

function updateMaterialRow(item) {
  const row = document.getElementById(`material-${item.sku}`);
  if (!row) return;
  setCell(row, "qty_on_hand", `${item.qty_on_hand} ${item.unit_of_measure}`);
  setCell(row, "qty_reserved", `${item.qty_reserved} ${item.unit_of_measure}`);
  setCell(row, "qty_available", `${item.qty_available} ${item.unit_of_measure}`);
  setCell(row, "qty_shippable", `${item.qty_shippable} ${item.unit_of_measure}`);

  const statusCell = row.querySelector('[data-field="status"]');
  statusCell.replaceChildren();
  const status = document.createElement("span");
  status.className = `status status-${item.status}`;
  status.textContent = titleCase(item.status);
  statusCell.append(status);
  item.conditions.forEach((condition) => {
    const label = document.createElement("span");
    label.className = "condition";
    label.textContent = condition.replaceAll("_", " ");
    statusCell.append(label);
  });
}

function setCell(row, field, value) {
  row.querySelector(`[data-field="${field}"]`).textContent = value;
}

async function refreshInventoryAlerts() {
  const response = await fetch("/api/inventory/alerts");
  if (!response.ok) throw new Error("Inventory warnings could not be refreshed.");
  const body = await response.json();
  const warning = document.querySelector("#inventory-warning");
  const title = document.querySelector("#inventory-warning-title");
  const summary = document.querySelector("#inventory-warning-summary");
  const list = document.querySelector("#inventory-warning-items");
  const alertStatus = document.querySelector("#inventory-alert-status");

  warning.hidden = body.count === 0;
  list.replaceChildren();
  if (body.count > 0) {
    title.textContent = "Inventory discrepancy requires attention";
    summary.textContent = `${body.count} ${body.count === 1 ? "material is" : "materials are"} over-allocated. Zero units can ship for each affected material until inventory is corrected. This demo has no correction workflow.`;
    body.items.forEach((item) => {
      const listItem = document.createElement("li");
      const link = document.createElement("a");
      link.href = `/?q=${encodeURIComponent(item.sku)}#material-${encodeURIComponent(item.sku)}`;
      link.textContent = item.sku;
      listItem.append(link, document.createTextNode(`: ${item.message}`));
      list.append(listItem);
    });
  } else {
    title.textContent = "";
    summary.textContent = "";
  }
  alertStatus.textContent =
    body.count === 0
      ? "Inventory warnings refreshed. No over-allocation discrepancies are present."
      : `Inventory warnings refreshed. ${body.count} ${body.count === 1 ? "over-allocation discrepancy is" : "over-allocation discrepancies are"} present.`;
}

function titleCase(value) {
  return value
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}
