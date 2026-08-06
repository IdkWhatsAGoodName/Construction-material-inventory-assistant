"use strict";

const chatForm = document.querySelector("#chat-form");
const chatMessage = document.querySelector("#chat-message");
const chatSubmit = document.querySelector("#chat-submit");
const chatTranscript = document.querySelector("#chat-transcript");
const chatStatus = document.querySelector("#chat-status");
const pendingPanel = document.querySelector("#pending-orders");
const pendingList = document.querySelector("#pending-orders-list");

chatForm?.addEventListener("submit", async (event) => {
  event.preventDefault();
  const message = chatMessage.value.trim();
  if (!message) return;
  document.querySelector("#chat-empty")?.remove();
  appendBubble("User", message, "user");
  chatMessage.value = "";
  setChatBusy(true);
  chatStatus.textContent = "Gemini is selecting tools and the application is verifying results…";
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message }),
    });
    const body = await response.json();
    if (!response.ok) throw new Error(errorMessage(body, "The chat request could not be completed."));
    body.verified_results.forEach(appendVerifiedResult);
    if (body.commentary) {
      appendBubble("Gemini commentary (non-authoritative)", body.commentary, "gemini");
    } else if (body.commentary_status === "omitted_unsafe") {
      appendNote("Gemini commentary was omitted because it did not pass factual-token validation.");
    } else if (body.commentary_status === "unavailable") {
      appendNote("Gemini commentary was unavailable; the verified results remain authoritative.");
    }
    renderPendingOrders(body.pending_orders);
    await refreshChangedInventory(body.verified_results);
    chatStatus.textContent = body.orchestration_status === "complete"
      ? "Chat turn complete. Verified results are shown separately from Gemini commentary."
      : "Chat orchestration stopped early. Review the verified results that completed.";
  } catch (error) {
    appendNote(error instanceof Error ? error.message : "Unexpected chat error.");
    chatStatus.textContent = "Chat request failed. Deterministic catalogue and order controls remain available.";
  } finally {
    setChatBusy(false);
    chatMessage.focus();
  }
});

function appendVerifiedResult(result) {
  const article = document.createElement("article");
  article.className = `verified-result verified-result-${result.status}`;
  const label = document.createElement("p");
  label.className = "verified-label";
  label.textContent = "Verified application result";
  const title = document.createElement("h3");
  title.textContent = result.title;
  const message = document.createElement("p");
  message.textContent = result.message;
  article.append(label, title, message);
  chatTranscript.append(article);
}

function appendBubble(titleText, messageText, role) {
  const article = document.createElement("article");
  article.className = `chat-bubble chat-bubble-${role}`;
  const title = document.createElement("h3");
  title.textContent = titleText;
  const message = document.createElement("p");
  message.textContent = messageText;
  article.append(title, message);
  chatTranscript.append(article);
}

function appendNote(messageText) {
  const note = document.createElement("p");
  note.className = "chat-note";
  note.textContent = messageText;
  chatTranscript.append(note);
}

function renderPendingOrders(orders) {
  pendingList.replaceChildren();
  pendingPanel.hidden = orders.length === 0;
  orders.forEach((order) => {
    const item = document.createElement("li");
    const reference = document.createElement("strong");
    reference.textContent = order.reference;
    const expires = new Date(order.expires_at).toLocaleString();
    item.append(reference, document.createTextNode(`: ${order.summary} Expires ${expires}.`));
    pendingList.append(item);
  });
}

async function refreshChangedInventory(results) {
  const skus = new Set(results.flatMap((result) => result.affected_skus));
  for (const sku of skus) {
    const response = await fetch(`/api/inventory/${encodeURIComponent(sku)}`);
    if (response.ok && window.updateMaterialRow) window.updateMaterialRow(await response.json());
  }
  if (skus.size > 0 && window.refreshInventoryAlerts) await window.refreshInventoryAlerts();
}

function setChatBusy(busy) {
  chatSubmit.disabled = busy;
  chatMessage.disabled = busy;
}
