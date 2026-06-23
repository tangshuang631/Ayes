async function requestJson(url, options = {}) {
  const response = await fetch(url, options);
  return await response.json();
}

let selectedTarget = null;
let statusPollHandle = null;
let sessionHeartbeatHandle = null;
let cachedVisionModels = [];
let editableRegions = [];
let roiPreviewSource = null;
let roiDraftState = null;
let lastAppliedSpecSignature = "";
const frontendSessionId = `web_${Date.now()}_${Math.random().toString(36).slice(2, 10)}`;

function getTaskId() {
  return document.getElementById("taskIdInput").value.trim();
}

function getMinutes() {
  return document.getElementById("memoryMinutes").value || "5";
}

function buildScopedUrl(basePath, extra = {}) {
  const params = new URLSearchParams();
  const taskId = getTaskId();
  const minutes = getMinutes();
  if (taskId) {
    params.set("task_id", taskId);
  }
  if (minutes && !("minutes" in extra && extra.minutes === null)) {
    params.set("minutes", minutes);
  }
  Object.entries(extra).forEach(([key, value]) => {
    if (value === null || value === undefined || value === "") {
      return;
    }
    params.set(key, value);
  });
  const query = params.toString();
  return query ? `${basePath}?${query}` : basePath;
}

function setText(id, payload) {
  document.getElementById(id).textContent =
    typeof payload === "string" ? payload : JSON.stringify(payload, null, 2);
}

function formatTimestamp(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(Number(value) * 1000);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

function buildRegionMeta(item) {
  const region = item.region || {};
  if (!region.region_id && !region.name) {
    return "全目标";
  }
  const label = region.name || region.region_id || "区域";
  return `${label} | ${region.coordinate_space || "target"} | x=${region.x ?? 0}, y=${region.y ?? 0}, w=${region.w ?? 0}, h=${region.h ?? 0}`;
}

function buildEventDetailLines(item) {
  const lines = [];
  lines.push(`${formatTimestamp(item.timestamp)} | ${item.source || "-"} | ${item.priority || "-"}`);
  lines.push(buildRegionMeta(item));
  if (item.visual?.summary) {
    lines.push(`视觉: ${item.visual.summary}`);
  }
  if (item.text?.ocr_text) {
    lines.push(`OCR: ${item.text.ocr_text}`);
  }
  if ((item.text?.blocks || []).length) {
    const blockPreview = item.text.blocks
      .slice(0, 3)
      .map((block) => `${block.text} [${(block.bbox || []).join(", ")}]`)
      .join("\n");
    lines.push(`块:\n${blockPreview}`);
  }
  if ((item.tags || []).length) {
    lines.push(`标签: ${item.tags.join(", ")}`);
  }
  if ((item.evidence_refs || []).length) {
    lines.push(`证据: ${item.evidence_refs.join(", ")}`);
  }
  return lines.join("\n");
}

function buildEvidenceLinks(refs) {
  if (!refs || !refs.length) {
    return "暂无";
  }
  return refs
    .map((ref) => {
      const href = ref.startsWith("/") ? ref : `/${ref}`;
      return `<a href="${href}" target="_blank" rel="noreferrer">${ref}</a>`;
    })
    .join("<br />");
}

function buildEvidencePreviewHtmlFromRefs(refs) {
  if (!refs || !refs.length) {
    return "";
  }
  return `
    <div class="evidence-preview-grid">
      ${refs
        .map((ref) => {
          const href = ref.startsWith("/") ? ref : `/${ref}`;
          return `
            <a class="evidence-preview-item" href="${href}" target="_blank" rel="noreferrer">
              <img src="${href}" alt="${ref}" loading="lazy" />
              <span>${ref.split("/").pop() || ref}</span>
            </a>
          `;
        })
        .join("")}
    </div>
  `;
}

function buildEvidencePreviewHtml(items) {
  if (!items || !items.length) {
    return "";
  }
  return `
    <div class="evidence-preview-grid">
      ${items
        .map((item) => `
          <a class="evidence-preview-item" href="${item.src}" target="_blank" rel="noreferrer">
            <img src="${item.src}" alt="${item.label || item.ref || "evidence"}" loading="lazy" />
            <span>${item.label || item.ref || item.src}</span>
          </a>
        `)
        .join("")}
    </div>
  `;
}

function buildTimelineEventHtml(item) {
  return `
    <div class="timeline-title">${item.event_type}</div>
    <div class="timeline-meta">${item.summary || ""}\n${buildEventDetailLines(item)}</div>
    ${buildEvidencePreviewHtmlFromRefs(item.evidence_refs || [])}
  `;
}

function nextRegionId() {
  return `roi_${Date.now()}_${Math.random().toString(36).slice(2, 6)}`;
}

function syncRegionsTextarea() {
  document.getElementById("regionsJsonInput").value = JSON.stringify(editableRegions, null, 2);
}

function loadRegionsFromTextValue(raw) {
  if (!raw.trim()) {
    editableRegions = [];
    renderRegionList();
    renderRegionOverlay();
    return;
  }
  try {
    const parsed = JSON.parse(raw);
    editableRegions = Array.isArray(parsed) ? parsed : [];
  } catch (_) {
    return;
  }
  renderRegionList();
  renderRegionOverlay();
}

function renderRegionList() {
  const container = document.getElementById("roiRegionList");
  container.innerHTML = "";
  if (!editableRegions.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前还没有已选区域";
    container.appendChild(empty);
    return;
  }
  editableRegions.forEach((region) => {
    const item = document.createElement("div");
    item.className = "roi-region-item";
    const info = document.createElement("div");
    const title = document.createElement("input");
    title.value = region.name || "";
    title.placeholder = "区域名称";
    title.onchange = (event) => {
      region.name = event.target.value.trim() || region.region_id;
      syncRegionsTextarea();
      renderRegionOverlay();
    };
    const meta = document.createElement("div");
    meta.className = "roi-region-meta";
    meta.textContent = `${region.region_id} | x=${region.x}, y=${region.y}, w=${region.w}, h=${region.h}`;
    info.appendChild(title);
    info.appendChild(meta);
    const actions = document.createElement("div");
    actions.className = "roi-region-actions";
    const enabled = document.createElement("label");
    enabled.className = "check-row";
    enabled.innerHTML = `<input type="checkbox" ${region.enabled === false ? "" : "checked"} />启用`;
    enabled.querySelector("input").onchange = (event) => {
      region.enabled = event.target.checked;
      syncRegionsTextarea();
      renderRegionOverlay();
    };
    const remove = document.createElement("button");
    remove.className = "text-button";
    remove.textContent = "删除";
    remove.onclick = () => {
      editableRegions = editableRegions.filter((item) => item.region_id !== region.region_id);
      syncRegionsTextarea();
      renderRegionList();
      renderRegionOverlay();
    };
    actions.appendChild(enabled);
    actions.appendChild(remove);
    item.appendChild(info);
    item.appendChild(actions);
    container.appendChild(item);
  });
}

function renderRegionOverlay() {
  const overlay = document.getElementById("roiOverlay");
  const image = document.getElementById("roiEditorImage");
  overlay.innerHTML = "";
  if (!image.naturalWidth || !image.clientWidth) {
    return;
  }
  const scaleX = image.clientWidth / image.naturalWidth;
  const scaleY = image.clientHeight / image.naturalHeight;
  editableRegions.forEach((region) => {
    const box = document.createElement("div");
    box.className = "roi-box";
    box.style.left = `${region.x * scaleX}px`;
    box.style.top = `${region.y * scaleY}px`;
    box.style.width = `${region.w * scaleX}px`;
    box.style.height = `${region.h * scaleY}px`;
    const label = document.createElement("div");
    label.className = "roi-label";
    label.textContent = region.name || region.region_id;
    box.appendChild(label);
    overlay.appendChild(box);
  });
}

function openRoiEditorWithSource(source) {
  roiPreviewSource = source;
  const empty = document.getElementById("roiEditorEmpty");
  const shell = document.getElementById("roiEditorShell");
  const image = document.getElementById("roiEditorImage");
  empty.classList.add("hidden");
  shell.classList.remove("hidden");
  image.onload = () => {
    renderRegionOverlay();
  };
  image.src = `${source}?t=${Date.now()}`;
}

function getSelectedTargetPreviewPath() {
  if (!selectedTarget) {
    return null;
  }
  if (selectedTarget.preview_path) {
    return selectedTarget.preview_path;
  }
  return null;
}

function renderVisionModels(items) {
  cachedVisionModels = items || [];
  const select = document.getElementById("visionModelSelect");
  select.innerHTML = '<option value="">使用手动模型名</option>';
  cachedVisionModels.forEach((item) => {
    const option = document.createElement("option");
    option.value = item.name;
    option.textContent = `${item.name}${item.size ? ` / ${item.size}` : ""}`;
    select.appendChild(option);
  });
}

async function notifyFrontendSessionOpen() {
  try {
    await requestJson("/api/app/session-open", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: frontendSessionId }),
    });
  } catch (_) {
  }
}

async function notifyFrontendSessionClose() {
  try {
    await requestJson("/api/app/session-close", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: frontendSessionId }),
      keepalive: true,
    });
  } catch (_) {
  }
}

async function notifyFrontendSessionHeartbeat() {
  try {
    await requestJson("/api/app/session-heartbeat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ session_id: frontendSessionId }),
    });
  } catch (_) {
  }
}

function setSelectedTarget(target) {
  selectedTarget = target;
  const summary = document.getElementById("selectedTargetSummary");
  if (!target) {
    summary.textContent = "未选择监控目标";
    return;
  }
  if (target.type === "screen") {
    summary.textContent = `已选目标: 主屏幕 / screen_id=${target.screen_id}`;
    document.getElementById("targetModeSelect").value = "selected_screen";
    return;
  }
  if (target.type === "process") {
    summary.textContent = `已选目标: ${target.process_name || "未知进程"} / process`;
    document.getElementById("targetModeSelect").value = "selected_process";
    return;
  }
  summary.textContent = `已选目标: ${target.process_name || "未知进程"}${target.title ? ` / ${target.title}` : ""} / window_id=${target.window_id}`;
  document.getElementById("targetModeSelect").value = target.type === "process" ? "selected_process" : "selected_window";
}

function applySpecToForm(spec) {
  if (!spec) {
    return;
  }
  lastAppliedSpecSignature = JSON.stringify(spec);
  document.getElementById("modeSelect").value = spec.mode || "observe";
  document.getElementById("screenshotIntervalInput").value = spec.sampling?.screenshot_interval_ms || 1000;
  document.getElementById("ocrIntervalInput").value = spec.sampling?.ocr_interval_ms || 1000;
  document.getElementById("skipOcrInput").checked = Boolean(spec.sampling?.skip_ocr_when_no_change);
  document.getElementById("alertEnabledInput").checked = Boolean(spec.alert?.enabled);
  document.getElementById("queryInput").value = (spec.watch_intent?.queries || [])[0] || "";
  document.getElementById("visionEnabledInput").checked = Boolean(spec.vision?.enabled);
  document.getElementById("visionModelInput").value = spec.vision?.model || "Molmo-7B-D-0924";
  const modelSelect = document.getElementById("visionModelSelect");
  if ((cachedVisionModels || []).some((item) => item.name === (spec.vision?.model || ""))) {
    modelSelect.value = spec.vision?.model || "";
  } else {
    modelSelect.value = "";
  }
  document.getElementById("visionTriggerSparseInput").checked = Boolean(spec.vision?.trigger_when_ocr_sparse ?? true);
  document.getElementById("visionSparseCharsInput").value = spec.vision?.ocr_sparse_min_chars ?? 12;
  editableRegions = Array.isArray(spec.target?.regions) ? [...spec.target.regions] : [];
  syncRegionsTextarea();
  renderRegionList();
  renderRegionOverlay();
  const refreshClick = spec.actions?.refresh_click || {};
  document.getElementById("refreshClickEnabledInput").checked = Boolean(refreshClick.enabled);
  document.getElementById("refreshCoordinateSpaceSelect").value = refreshClick.coordinate_space || "window";
  document.getElementById("refreshPointXInput").value = refreshClick.point?.x ?? 100;
  document.getElementById("refreshPointYInput").value = refreshClick.point?.y ?? 200;
  document.getElementById("refreshIntervalInput").value = refreshClick.interval_sec ?? 30;
  document.getElementById("refreshCooldownInput").value = refreshClick.cooldown_sec ?? 30;
}

function renderScreens(items) {
  const container = document.getElementById("screenList");
  container.innerHTML = "";
  items.forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = "window-item";
    const button = document.createElement("button");
    button.className = "candidate-button";
    button.innerHTML = `
      ${item.preview_path ? `<img class="candidate-preview" src="${item.preview_path}?t=${Date.now()}" alt="屏幕预览" />` : ""}
      <div class="window-title">${item.name}</div>
      <div class="window-meta">${item.observability.label} | ${item.bounds.width}x${item.bounds.height}</div>
    `;
    button.onclick = () => {
      setSelectedTarget({ type: "screen", screen_id: item.screen_id, preview_path: item.preview_path });
    };
    wrapper.appendChild(button);
    container.appendChild(wrapper);
  });
}

function renderTargetItems(containerId, items, type) {
  const container = document.getElementById(containerId);
  container.innerHTML = "";
  if (!items.length) {
    const empty = document.createElement("div");
    empty.className = "empty-state";
    empty.textContent = "当前没有可展示候选";
    container.appendChild(empty);
    return;
  }
  items.slice(0, 20).forEach((item) => {
    const wrapper = document.createElement("div");
    wrapper.className = "window-item";
    const button = document.createElement("button");
    button.className = "candidate-button";
    button.innerHTML = `
      ${item.preview_path ? `<img class="candidate-preview" src="${item.preview_path}?t=${Date.now()}" alt="候选预览" />` : ""}
      <div class="window-title">${item.process_name || "未知进程"} ${item.title ? " / " + item.title : ""}</div>
      <div class="window-meta">${item.is_business_candidate ? "推荐" : "候选"} | window_id=${item.window_id} | ${item.observability.label} | ${item.bounds.width}x${item.bounds.height}</div>
      <div class="candidate-tags">${item.preview_path ? "有快照" : "无快照"}${item.is_collapsed_default ? " | 默认折叠" : ""}</div>
    `;
    button.onclick = () => {
      if (type === "process") {
        setSelectedTarget({
          type: "process",
          process_name: item.process_name,
          title: item.title,
          window_id: item.window_id,
          preview_path: item.preview_path,
        });
      } else {
        setSelectedTarget({
          type: "window",
          window_id: item.window_id,
          process_name: item.process_name,
          title: item.title,
          preview_path: item.preview_path,
        });
      }
    };
    wrapper.appendChild(button);
    container.appendChild(wrapper);
  });
}

function renderWindows(items) {
  renderTargetItems("windowList", items, "window");
}

function renderCollapsedWindows(items) {
  renderTargetItems("collapsedWindowList", items, "window");
  const section = document.getElementById("collapsedWindowSection");
  section.open = false;
  section.style.display = items.length ? "block" : "none";
}

function renderProcesses(items) {
  renderTargetItems("processList", items, "process");
}

function renderCollapsedProcesses(items) {
  renderTargetItems("collapsedProcessList", items, "process");
  const section = document.getElementById("collapsedProcessSection");
  section.open = false;
  section.style.display = items.length ? "block" : "none";
}

function renderEvents(items) {
  const container = document.getElementById("eventList");
  container.innerHTML = "";
  items.slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = buildTimelineEventHtml(item);
    container.appendChild(node);
  });
}

function renderSnippets(items) {
  const container = document.getElementById("snippetList");
  container.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = `
      <div class="timeline-title">${item.preview || "无可用文本"}</div>
      <div class="timeline-meta">${item.summary || ""}\n${item.ocr_text || ""}\n${formatTimestamp(item.timestamp)}</div>
    `;
    container.appendChild(node);
  });
}

function renderActionEvents(items) {
  const container = document.getElementById("actionList");
  container.innerHTML = "";
  items.slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = buildTimelineEventHtml(item);
    container.appendChild(node);
  });
}

function renderSimpleTimeline(id, items) {
  const container = document.getElementById(id);
  container.innerHTML = "";
  items.slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = buildTimelineEventHtml(item);
    container.appendChild(node);
  });
}

function renderMemoryResult(payload) {
  setText("memoryView", payload.answer || "暂无回答");
  const meta = document.getElementById("memoryMeta");
  meta.textContent = `任务: ${payload.task_id || "-"} | 时间范围: 最近 ${payload.minutes || "-"} 分钟 | 记忆层: ${(payload.memory_layers_used || []).join(", ") || "-"}`;
  const summary = document.getElementById("memorySummary");
  const timeRange = payload.time_range || {};
  summary.textContent = `结论: ${payload.answer || "暂无回答"} | 置信度: ${payload.confidence ?? "-"} | 证据事件: ${(payload.matched_events || []).length} | 实际命中时间: ${timeRange.from ? Math.floor(timeRange.from) : "-"} -> ${timeRange.to ? Math.floor(timeRange.to) : "-"} | 时间范围约束: ${payload.time_scope_respected ? "已遵守" : "未标记"}`;
  const refs = document.getElementById("memoryRefs");
  refs.innerHTML = `证据引用:<br />${buildEvidenceLinks(payload.evidence_refs || [])}${buildEvidencePreviewHtml(payload.evidence_previews || [])}`;
  const evidence = document.getElementById("memoryEvidence");
  evidence.innerHTML = "";
  (payload.matched_events || []).slice().reverse().forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = buildTimelineEventHtml(item);
    evidence.appendChild(node);
  });
}

function renderLongTerm(items) {
  const container = document.getElementById("longTermList");
  container.innerHTML = "";
  items.forEach((item) => {
    const node = document.createElement("div");
    node.className = "timeline-item";
    node.innerHTML = `
      <div class="timeline-title">${item.summary}</div>
      <div class="timeline-meta">事件数: ${item.event_count} | task_id=${item.task_id} | ${formatTimestamp(item.window_start)} -> ${formatTimestamp(item.window_end)}</div>
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
    const metadata = item.metadata && Object.keys(item.metadata).length ? `\n${JSON.stringify(item.metadata, null, 2)}` : "";
    node.innerHTML = `
      <div class="log-title">${item.category} / ${item.level}</div>
      <div class="log-meta">${formatTimestamp(item.timestamp)}\n${item.message}${metadata}</div>
    `;
    container.appendChild(node);
  });
}

async function refreshStatus() {
  const status = await requestJson("/api/status");
  setText("statusView", status);
  const runtimeMeta = document.getElementById("runtimeMeta");
  runtimeMeta.textContent = `任务已装载: ${status.has_runner ? "是" : "否"} | 持续监控: ${status.is_running ? "运行中" : "未运行"} | 动作计数: ${status.action_count ?? 0} | 命中计数: ${status.match_count ?? 0} | 告警计数: ${status.alert_count ?? 0} | 最近执行: ${status.last_run_at ? Math.floor(status.last_run_at) : "-"} | 最近事件: ${status.last_event_at ? Math.floor(status.last_event_at) : "-"} | 最近命中: ${status.last_match_at ? Math.floor(status.last_match_at) : "-"} | 最近错误: ${status.last_error || "-"}`;
  const summary = document.getElementById("statusSummary");
  summary.innerHTML = `
    <div class="status-chip"><div class="status-chip-label">当前任务</div><div class="status-chip-value">${status.task_id || status.last_task_id || "-"}</div></div>
    <div class="status-chip"><div class="status-chip-label">运行状态</div><div class="status-chip-value">${status.is_running ? "持续监控中" : status.has_runner ? "已装载未运行" : "未装载"}</div></div>
    <div class="status-chip"><div class="status-chip-label">最近命中 / 告警</div><div class="status-chip-value">${status.match_count ?? 0} / ${status.alert_count ?? 0}</div></div>
    <div class="status-chip"><div class="status-chip-label">前端连接 / 后台策略</div><div class="status-chip-value">${status.connected_frontends ?? 0} / ${status.can_shutdown_service ? "可退出" : "保持运行"}</div></div>
  `;
  const taskInput = document.getElementById("taskIdInput");
  if (status.task_id) {
    taskInput.value = status.task_id;
  } else if (!taskInput.value && status.last_task_id) {
    taskInput.value = status.last_task_id;
  }
  if (status.spec) {
    const signature = JSON.stringify(status.spec);
    if (signature !== lastAppliedSpecSignature) {
      applySpecToForm(status.spec);
    }
  }
}

async function refreshWindows() {
  const data = await requestJson("/api/targets");
  renderScreens(data.screens || []);
  renderWindows(data.windows || []);
  renderCollapsedWindows(data.collapsed_windows || []);
  renderProcesses(data.processes || []);
  renderCollapsedProcesses(data.collapsed_processes || []);
  const collapseRule = data.collapse_rule || {};
  document.getElementById("targetCollapseRule").textContent = `默认折叠: ${collapseRule.max_width || "-"}x${collapseRule.max_height || "-"} 及以下，或无快照候选`;
}

async function refreshEvents() {
  const data = await requestJson(buildScopedUrl("/api/timeline/recent", { limit: "20" }));
  renderEvents(data.items || []);
}

async function refreshActionEvents() {
  const data = await requestJson(buildScopedUrl("/api/events", { source: "action" }));
  renderActionEvents(data.items || []);
}

async function refreshSnippets() {
  const data = await requestJson(buildScopedUrl("/api/ocr/snippets", { limit: "20" }));
  renderSnippets(data.items || []);
}

async function refreshMatchEvents() {
  const data = await requestJson(buildScopedUrl("/api/events", { source: "semantic_match" }));
  renderSimpleTimeline("matchList", data.items || []);
}

async function refreshAlertEvents() {
  const data = await requestJson(buildScopedUrl("/api/events", { source: "alert" }));
  renderSimpleTimeline("alertList", data.items || []);
}

async function refreshLongTerm() {
  const data = await requestJson(buildScopedUrl("/api/timeline/long-term", { limit: "20", minutes: null }));
  renderLongTerm(data.items || []);
}

async function refreshLogs() {
  const category = document.getElementById("logCategorySelect").value;
  const data = await requestJson(buildScopedUrl("/api/logs", { category }));
  renderLogs(data.items || []);
}

async function refreshVisionModels() {
  const data = await requestJson("/api/vision/models");
  renderVisionModels(data.items || []);
}

async function queryMemory() {
  const keyword = document.getElementById("memoryKeyword").value;
  const data = await requestJson(buildScopedUrl("/api/ask", { question: keyword || "最近发生了什么" }));
  renderMemoryResult(data);
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

async function applyConfiguredWatch() {
  if (!selectedTarget) {
    setSelectedTarget(null);
    return;
  }
  const targetMode = document.getElementById("targetModeSelect").value;
  const mode = document.getElementById("modeSelect").value;
  const query = document.getElementById("queryInput").value.trim();
  const screenshotInterval = Number(document.getElementById("screenshotIntervalInput").value || 1000);
  const ocrInterval = Number(document.getElementById("ocrIntervalInput").value || 1000);
  const alertEnabled = document.getElementById("alertEnabledInput").checked;
  const skipOcr = document.getElementById("skipOcrInput").checked;
  const visionEnabled = document.getElementById("visionEnabledInput").checked;
  const selectedVisionModel = document.getElementById("visionModelSelect").value.trim();
  const visionModel = selectedVisionModel || document.getElementById("visionModelInput").value.trim() || "Molmo-7B-D-0924";
  const visionTriggerSparse = document.getElementById("visionTriggerSparseInput").checked;
  const visionSparseChars = Number(document.getElementById("visionSparseCharsInput").value || 12);
  const refreshClickEnabled = document.getElementById("refreshClickEnabledInput").checked;
  const refreshCoordinateSpace = document.getElementById("refreshCoordinateSpaceSelect").value;
  const refreshPointX = Number(document.getElementById("refreshPointXInput").value || 0);
  const refreshPointY = Number(document.getElementById("refreshPointYInput").value || 0);
  const refreshInterval = Number(document.getElementById("refreshIntervalInput").value || 30);
  const refreshCooldown = Number(document.getElementById("refreshCooldownInput").value || 30);
  const regionsJson = document.getElementById("regionsJsonInput").value.trim();
  const taskId = getTaskId() || "task_web";
  let regions = [];
  if (regionsJson) {
    try {
      const parsed = JSON.parse(regionsJson);
      if (Array.isArray(parsed)) {
        regions = parsed;
      }
    } catch (_) {
    }
  }
  editableRegions = regions;
  let targetPayload;
  if (targetMode === "selected_screen") {
    targetPayload = { type: "screen", screen_id: selectedTarget.screen_id || 1, regions };
  } else if (targetMode === "selected_process") {
    targetPayload = { type: "process", process_name: selectedTarget.process_name, regions };
  } else {
    targetPayload = { type: "window", window_id: selectedTarget.window_id, regions };
  }
  const payload = {
    task_id: taskId,
    mode,
    target: targetPayload,
    sampling: {
      screenshot_interval_ms: screenshotInterval,
      ocr_interval_ms: ocrInterval,
      change_detection_interval_ms: screenshotInterval,
      max_fps: 2,
      skip_ocr_when_no_change: skipOcr,
    },
    vision: {
      enabled: visionEnabled,
      provider: "ollama",
      model: visionModel,
      trigger_when_ocr_sparse: visionTriggerSparse,
      ocr_sparse_min_chars: visionSparseChars,
      trigger_on_visual_regions: true,
      trigger_on_watch_intent: true,
      trigger_on_question_semantics: true,
      max_calls_per_minute: 6,
    },
    watch_intent: mode === "triggered"
      ? {
          enabled: true,
          summary: query || "命中条件时提醒我",
          queries: query ? [query] : ["状态变化"],
        }
      : {
          enabled: false,
        },
    alert: {
      enabled: alertEnabled,
    },
    actions: {
      refresh_click: {
        enabled: refreshClickEnabled,
        point: { x: refreshPointX, y: refreshPointY },
        coordinate_space: refreshCoordinateSpace,
        interval_sec: refreshInterval,
        cooldown_sec: refreshCooldown,
      },
    },
  };
  const result = await requestJson("/api/watch/load-configured", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (result.target?.type === "process") {
    setSelectedTarget({
      type: "process",
      process_name: result.target.process_name,
    });
  }
  await refreshStatus();
  await refreshLogs();
}

async function startBackgroundWatch() {
  const result = await requestJson("/api/watch/start", { method: "POST" });
  if (result.error) {
    return;
  }
  await refreshStatus();
  await refreshLogs();
}

function ensureStatusPolling() {
  if (statusPollHandle !== null) {
    return;
  }
  statusPollHandle = window.setInterval(async () => {
    await refreshStatus();
    await refreshEvents();
    await refreshSnippets();
    await refreshActionEvents();
    await refreshMatchEvents();
    await refreshAlertEvents();
    await refreshLogs();
  }, 2000);
}

function ensureSessionHeartbeat() {
  if (sessionHeartbeatHandle !== null) {
    return;
  }
  sessionHeartbeatHandle = window.setInterval(() => {
    notifyFrontendSessionHeartbeat();
  }, 10000);
}

document.getElementById("refreshTargetsBtn").onclick = refreshWindows;
document.getElementById("startWatchBtn").onclick = startBackgroundWatch;
document.getElementById("runOnceBtn").onclick = async () => {
  await requestJson("/api/watch/run-once", { method: "POST" });
  await refreshStatus();
  await refreshEvents();
  await refreshSnippets();
  await refreshActionEvents();
  await refreshMatchEvents();
  await refreshAlertEvents();
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
document.getElementById("refreshSnippetsBtn").onclick = refreshSnippets;
document.getElementById("refreshActionsBtn").onclick = refreshActionEvents;
document.getElementById("refreshMatchesBtn").onclick = refreshMatchEvents;
document.getElementById("refreshAlertsBtn").onclick = refreshAlertEvents;
document.getElementById("askBtn").onclick = queryMemory;
document.getElementById("refreshLogsBtn").onclick = refreshLogs;
document.getElementById("refreshScreenshotBtn").onclick = refreshScreenshot;
document.getElementById("refreshTimelineBtn").onclick = async () => {
  await refreshEvents();
  await refreshLongTerm();
};
document.getElementById("refreshLongTermBtn").onclick = refreshLongTerm;
document.getElementById("applyConfigBtn").onclick = applyConfiguredWatch;
document.getElementById("applyTaskScopeBtn").onclick = async () => {
  await refreshStatus();
  await refreshEvents();
  await refreshSnippets();
  await refreshLongTerm();
  await refreshLogs();
  await queryMemory();
};
document.getElementById("logCategorySelect").onchange = refreshLogs;
document.getElementById("refreshVisionModelsBtn").onclick = refreshVisionModels;
document.getElementById("resetRegionsBtn").onclick = () => {
  editableRegions = [];
  syncRegionsTextarea();
  renderRegionList();
  renderRegionOverlay();
};
document.getElementById("loadSelectedPreviewBtn").onclick = () => {
  const previewPath = getSelectedTargetPreviewPath();
  if (!previewPath) {
    return;
  }
  openRoiEditorWithSource(previewPath);
};
document.getElementById("visionModelSelect").onchange = (event) => {
  const value = event.target.value;
  if (value) {
    document.getElementById("visionModelInput").value = value;
  }
};
document.getElementById("regionsJsonInput").addEventListener("change", (event) => {
  loadRegionsFromTextValue(event.target.value);
});

const roiStage = document.getElementById("roiEditorStage");
const roiImage = document.getElementById("roiEditorImage");
const roiDraft = document.getElementById("roiDraft");

function pointerToImagePoint(event) {
  if (!roiImage.naturalWidth || !roiImage.clientWidth) {
    return null;
  }
  const rect = roiStage.getBoundingClientRect();
  const x = Math.max(0, Math.min(event.clientX - rect.left, roiImage.clientWidth));
  const y = Math.max(0, Math.min(event.clientY - rect.top, roiImage.clientHeight));
  return {
    x,
    y,
    imageX: Math.round((x / roiImage.clientWidth) * roiImage.naturalWidth),
    imageY: Math.round((y / roiImage.clientHeight) * roiImage.naturalHeight),
  };
}

function drawDraftBox(start, current) {
  const left = Math.min(start.x, current.x);
  const top = Math.min(start.y, current.y);
  const width = Math.abs(current.x - start.x);
  const height = Math.abs(current.y - start.y);
  roiDraft.innerHTML = `<div class="roi-draft-box" style="left:${left}px;top:${top}px;width:${width}px;height:${height}px;"></div>`;
  roiDraft.classList.remove("hidden");
}

roiStage.addEventListener("pointerdown", (event) => {
  if (!roiImage.src || event.target.closest(".roi-label")) {
    return;
  }
  const point = pointerToImagePoint(event);
  if (!point) {
    return;
  }
  roiDraftState = { start: point, current: point };
  drawDraftBox(point, point);
});

roiStage.addEventListener("pointermove", (event) => {
  if (!roiDraftState) {
    return;
  }
  const point = pointerToImagePoint(event);
  if (!point) {
    return;
  }
  roiDraftState.current = point;
  drawDraftBox(roiDraftState.start, point);
});

window.addEventListener("pointerup", () => {
  if (!roiDraftState) {
    return;
  }
  const { start, current } = roiDraftState;
  roiDraftState = null;
  roiDraft.classList.add("hidden");
  roiDraft.innerHTML = "";
  const x = Math.min(start.imageX, current.imageX);
  const y = Math.min(start.imageY, current.imageY);
  const w = Math.abs(current.imageX - start.imageX);
  const h = Math.abs(current.imageY - start.imageY);
  if (w < 8 || h < 8) {
    return;
  }
  const regionId = nextRegionId();
  editableRegions.push({
    region_id: regionId,
    name: `区域 ${editableRegions.length + 1}`,
    x,
    y,
    w,
    h,
    coordinate_space: "target",
    enabled: true,
  });
  syncRegionsTextarea();
  renderRegionList();
  renderRegionOverlay();
});

window.addEventListener("beforeunload", () => {
  notifyFrontendSessionClose();
});

notifyFrontendSessionOpen().finally(() => {
  refreshStatus();
  refreshWindows();
  refreshEvents();
  refreshSnippets();
  refreshActionEvents();
  refreshMatchEvents();
  refreshAlertEvents();
  refreshLongTerm();
  refreshLogs();
  refreshScreenshot();
  refreshVisionModels();
  ensureStatusPolling();
  ensureSessionHeartbeat();
});
