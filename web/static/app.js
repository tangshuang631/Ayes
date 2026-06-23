async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  return await response.json();
}

function setText(id, payload) {
  document.getElementById(id).textContent =
    typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}

function renderWindows(items) {
  const container = document.getElementById("windowList");
  container.innerHTML = "";
  items.slice(0, 20).forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = "window-item";
    const button = document.createElement("button");
    button.innerHTML = `
      <div class="window-title">${item.process_name || "未知进程"} ${item.title ? " / " + item.title : ""}</div>
      <div class="window-meta">window_id=${item.window_id} | ${item.observability.label} | ${item.bounds.width}x${item.bounds.height}</div>
    `;
    button.onclick = async () => {
      await requestJson(`/api/watch/load-window/${item.window_id}`, { method: "POST" });
      await refreshStatus();
      await refreshLogs();
    };
    wrapper.appendChild(button);
    container.appendChild(wrapper);
  });
}

function renderEvents(items) {
  const container = document.getElementById("eventList");
  container.innerHTML = "";
  items.slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = `
      <div class="timeline-title">${item.event_type}</div>
      <div class="timeline-meta">${item.summary || ""}\n${item.text?.ocr_text || ""}</div>
    `;
    container.appendChild(node);
  });
}

function renderLogs(items) {
  const container = document.getElementById("logList");
  container.innerHTML = "";
  items.slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "log-item";
    node.innerHTML = `
      <div class="log-title">${item.category} / ${item.level}</div>
      <div class="log-meta">${item.message}</div>
    `;
    container.appendChild(node);
  });
}

async function refreshStatus() {
  const status = await requestJson("/api/status");
  setText("statusView", status);
}

async function refreshWindows() {
  const data = await requestJson("/api/windows");
  renderWindows(data.items || []);
}

async function refreshEvents() {
  const data = await requestJson("/api/events");
  renderEvents(data.items || []);
}

async function refreshLogs() {
  const data = await requestJson("/api/logs");
  renderLogs(data.items || []);
}

async function queryMemory() {
  const keyword = document.getElementById("memoryKeyword").value;
  const minutes = document.getElementById("memoryMinutes").value || "5";
  const data = await requestJson(`/api/ask?minutes=${encodeURIComponent(minutes)}&question=${encodeURIComponent(keyword || "最近发生了什么")}`);
  setText("memoryView", data);
}

async function refreshScreenshot() {
  const data = await requestJson("/api/screenshot");
  const image = document.getElementById("screenshotPreview");
  if (data.path) {
    image.src = `/${data.path}?t=${Date.now()}`;
  } else {
    image.removeAttribute("src");
  }
}

document.getElementById("refreshWindowsBtn").onclick = refreshWindows;
document.getElementById("loadScreenBtn").onclick = async () => {
  await requestJson("/api/watch/load-screen", { method: "POST" });
  await refreshStatus();
  await refreshLogs();
};
document.getElementById("runOnceBtn").onclick = async () => {
  await requestJson("/api/watch/run-once", { method: "POST" });
  await refreshStatus();
  await refreshEvents();
  await refreshLogs();
  await queryMemory();
  await refreshScreenshot();
};
document.getElementById("stopWatchBtn").onclick = async () => {
  await requestJson("/api/watch/stop", { method: "POST" });
  await refreshStatus();
  await refreshLogs();
};
document.getElementById("refreshEventsBtn").onclick = refreshEvents;
document.getElementById("askBtn").onclick = queryMemory;
document.getElementById("refreshLogsBtn").onclick = refreshLogs;
document.getElementById("refreshScreenshotBtn").onclick = refreshScreenshot;

refreshStatus();
refreshWindows();
refreshEvents();
refreshLogs();
refreshScreenshot();
