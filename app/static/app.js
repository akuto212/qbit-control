"use strict";

const el = (id) => document.getElementById(id);
const button = el("limit-button");
let status = null;
let applying = false;
let statusRequest = null;
let timer = null;

function notice(message = "") {
  el("notice").textContent = message;
  el("notice").hidden = !message;
}

function metric(id, formatted) {
  const [amount, unit] = formatted.split(" ");
  const suffix = document.createElement("span");
  suffix.className = "unit";
  suffix.textContent = ` ${unit || ""}`;
  el(id).replaceChildren(document.createTextNode(amount), suffix);
}

function render() {
  const online = status?.online === true;
  const limited = online && status.speed_limit_enabled;
  el("control").dataset.state = online ? (limited ? "limited" : "unlimited") : "offline";
  el("connection").textContent = online ? "Connected" : "Offline";
  el("connection").dataset.online = String(online);
  el("mode").textContent = online ? (limited ? "Limited" : "Unlimited") : "Offline";
  metric("download", online ? status.download_speed_formatted : "— MiB/s");
  metric("upload", online ? status.upload_speed_formatted : "— MiB/s");
  el("explanation").textContent = online
    ? (limited ? "Keeping some bandwidth free for everything else." : "Alternative limits are off. Normal qBittorrent limits apply.")
    : "qBittorrent unavailable";
  const hasLimits = online && typeof status.alt_download_limit_formatted === "string"
    && typeof status.alt_upload_limit_formatted === "string";
  el("limits").hidden = !hasLimits;
  if (hasLimits) {
    el("download-limit").textContent = `↓ ${status.alt_download_limit_formatted}`;
    el("upload-limit").textContent = `↑ ${status.alt_upload_limit_formatted}`;
  }
  button.disabled = applying || !online;
  button.setAttribute("aria-busy", String(applying));
  el("button-label").textContent = applying ? "Applying..."
    : online ? (limited ? "Disable speed limit" : "Enable speed limit") : "Waiting for connection";
  el("update-status").textContent = online ? "Updated just now" : "Reconnecting automatically";
}

async function request(path, method = "GET") {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), 10000);
  try {
    const response = await fetch(path, {
      method,
      credentials: "same-origin",
      cache: "no-store",
      redirect: "error",
      headers: method === "POST" ? { "X-QBT-Control": "1" } : {},
      signal: controller.signal,
    });
    if (response.status === 401 || response.status === 403) {
      throw new Error("Access denied. Reload this page to sign in again.");
    }
    if (!response.headers.get("content-type")?.includes("application/json")) {
      throw new Error("Session unavailable. Reload this page to sign in again.");
    }
    const data = await response.json();
    if (!response.ok) {
      throw new Error(response.status === 503
        ? "qBittorrent unavailable" : "Request failed. Please try again.");
    }
    return data;
  } catch (error) {
    if (error instanceof TypeError || error.name === "AbortError") {
      throw new Error("Connection lost. Retrying automatically; reload if sign-in is needed.");
    }
    throw error;
  } finally {
    clearTimeout(timeout);
  }
}

function refresh() {
  if (statusRequest) return statusRequest;
  statusRequest = (async () => {
    try {
      const data = await request("/api/status");
      if (data.online !== true || typeof data.speed_limit_enabled !== "boolean"
        || typeof data.download_speed_formatted !== "string"
        || typeof data.upload_speed_formatted !== "string") {
        throw new Error("Unexpected status response. Please reload the page.");
      }
      status = data;
      if (!applying) notice();
    } catch (error) {
      status = null;
      notice(error.message);
    }
    render();
  })().finally(() => { statusRequest = null; });
  return statusRequest;
}

function schedule() {
  clearTimeout(timer);
  if (!document.hidden && !applying) {
    timer = setTimeout(async () => { await refresh(); schedule(); }, 3000);
  }
}

button.addEventListener("click", async () => {
  if (applying || !status?.online) return;
  // Capture the explicit desired state before waiting for any in-flight status read.
  const enabled = !status.speed_limit_enabled;
  applying = true;
  clearTimeout(timer);
  notice();
  render();
  let failure = "";
  try {
    if (statusRequest) await statusRequest;
    await request(enabled ? "/api/limit/on" : "/api/limit/off", "POST");
  } catch (error) {
    failure = `Could not confirm the change. ${error.message}`;
  } finally {
    // Refresh even after a timeout: qBittorrent may already have applied the request.
    await refresh();
    if (!failure && status?.online && status.speed_limit_enabled !== enabled) {
      failure = "The mode changed again. Check the qBittorrent schedule or another controller.";
    }
    applying = false;
    render();
    if (failure) notice(failure);
    schedule();
  }
});

document.addEventListener("visibilitychange", async () => {
  clearTimeout(timer);
  if (!document.hidden && !applying) { await refresh(); schedule(); }
});

refresh().then(schedule);
