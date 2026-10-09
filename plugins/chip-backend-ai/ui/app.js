const STATUS_LABELS = {
  pending: "待执行",
  running: "执行中",
  done: "已完成",
  done_on_disk: "产物已存在",
  failed: "失败",
  blocked: "阻塞",
  awaiting_human: "等待人工",
  skipped: "已跳过",
  inconsistent: "不一致",
};

const ACTION_LABELS = {
  not_started: "步级流程尚未启动",
  ready: "下一节点已就绪",
  running: "节点正在执行或曾被中断",
  await_human: "等待人工确认",
  blocked: "流程被失败节点阻塞",
  blocked_inputs: "等待必需输入",
  inconsistent: "状态与产物不一致",
  flow_complete: "流程节点全部完成",
};

const ROLE_LABELS = {
  user: "用户",
  assistant: "大模型",
  tool: "工具",
  system: "流程系统",
};

const INTERACTION_KIND_LABELS = {
  prompt: "请求",
  plan: "计划",
  decision: "决策",
  result: "结果",
  approval: "确认",
  note: "说明",
  error: "错误",
};

let snapshot = null;
let selectedStepId = null;
let refreshTimer = null;

const byId = (id) => document.getElementById(id);

function element(tag, className = "", text = null) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== null) node.textContent = text;
  return node;
}

function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat("zh-CN", {
    year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", second: "2-digit",
  }).format(date);
}

function formatBytes(value) {
  if (value === null || value === undefined) return "—";
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / 1024 / 1024).toFixed(1)} MB`;
}

function statusLabel(status) {
  return STATUS_LABELS[status] || status || "未知";
}

function allNodes() {
  return snapshot?.stages?.flatMap((stage) => stage.nodes || []) || [];
}

async function loadSnapshot({ quiet = false } = {}) {
  const button = byId("refresh-button");
  if (!quiet) {
    button.disabled = true;
    button.textContent = "读取中…";
  }
  try {
    const response = await fetch("/api/snapshot", { cache: "no-store" });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.error || `HTTP ${response.status}`);
    snapshot = payload;
    renderSnapshot(payload);
    hideError();
    if (selectedStepId) {
      const selected = allNodes().find((node) => node.id === selectedStepId);
      if (selected) renderDrawer(selected);
      else closeDrawer();
    }
  } catch (error) {
    showError(`无法读取项目状态：${error.message}`);
  } finally {
    if (!quiet) {
      button.disabled = false;
      button.textContent = "刷新状态";
    }
  }
}

function renderSnapshot(data) {
  const summary = data.summary;
  byId("project-name").textContent = data.project.name;
  byId("workspace-path").textContent = data.project.workspace;
  byId("workspace-path").title = data.project.workspace;
  byId("lifecycle-badge").textContent = summary.lifecycle;
  byId("status-description").textContent = ACTION_LABELS[summary.action] || summary.action;
  byId("progress-percent").textContent = `${summary.percent}%`;
  document.querySelector(".progress-orbit").style.setProperty("--progress", `${summary.percent}%`);
  byId("current-stage").textContent = summary.current_stage || "—";
  byId("current-step").textContent = summary.current_step_name || "当前没有活动节点";
  byId("step-progress").textContent = `${summary.done_steps} / ${summary.total_steps}`;
  byId("spec-version").textContent = summary.spec_version || "未记录";
  byId("flow-version").textContent = `流程版本 ${data.flow.version || "—"}`;
  byId("retry-budget").textContent = `${summary.retry_budget.used} / ${summary.retry_budget.max}`;
  byId("retry-remaining").textContent = `剩余 ${summary.retry_budget.remaining} 次`;
  byId("snapshot-time").textContent = `快照 ${formatTime(data.generated_at)}`;

  const blockerPanel = byId("blocker-panel");
  blockerPanel.hidden = !summary.blocker;
  byId("blocker-message").textContent = summary.blocker || "";

  const warningPanel = byId("warning-panel");
  const warningList = byId("warning-list");
  warningList.replaceChildren();
  warningPanel.hidden = !(data.warnings || []).length;
  (data.warnings || []).forEach((warning) => {
    warningList.append(element("li", "", warning.message));
  });

  renderBoard(data.stages || [], summary.current_step_id);
  renderDecisions(data.decisions || []);
  applySearch();
}

function renderBoard(stages, currentStepId) {
  const board = byId("flow-board");
  board.replaceChildren();
  stages.forEach((stage) => {
    const lane = element("article", "stage-lane");
    lane.dataset.search = `${stage.id} ${stage.name}`.toLowerCase();

    const header = element("header", "stage-header");
    const headingRow = element("div", "stage-heading-row");
    const titleWrap = element("div");
    const title = element("div");
    title.append(element("span", "stage-number", String(stage.index)), element("span", "stage-name", stage.id));
    titleWrap.append(title, element("span", "stage-subtitle", stage.name));
    headingRow.append(titleWrap, element("span", "stage-percent", `${stage.done_steps}/${stage.total_steps}`));
    const progress = element("div", "mini-progress");
    const fill = element("span");
    fill.style.width = `${stage.percent}%`;
    progress.append(fill);
    header.append(headingRow, progress);

    const stack = element("div", "node-stack");
    (stage.nodes || []).forEach((node) => {
      const card = element("button", `node-card status-${node.status}${node.id === currentStepId ? " is-current" : ""}`);
      card.type = "button";
      card.dataset.stepId = node.id;
      card.dataset.search = `${node.id} ${node.name} ${node.executor.type} ${node.executor.ref || ""}`.toLowerCase();
      card.setAttribute("aria-label", `${node.name}，${statusLabel(node.status)}`);

      const titleRow = element("div", "node-title-row");
      const copy = element("div");
      copy.append(element("span", "node-title", node.name), element("span", "node-id", node.id));
      titleRow.append(copy, element("span", "status-pill", statusLabel(node.status)));

      const meta = element("div", "node-meta");
      const executor = node.executor.ref || node.executor.type;
      const traceSummary = [];
      const logCount = existingCount(node.logs);
      if (logCount) traceSummary.push(`${logCount} LOG`);
      if (node.interactions?.length) traceSummary.push(`${node.interactions.length} AI`);
      const factSummary = `${existingCount(node.inputs)}/${node.inputs.length} IN · ${existingCount(node.outputs)}/${node.outputs.length} OUT`;
      meta.append(
        element("span", "", executor),
        element("span", node.gate ? "gate-mark" : "", traceSummary.join(" · ") || (node.gate ? "GATE" : factSummary)),
      );
      card.append(titleRow, meta);
      card.addEventListener("click", () => openDrawer(node.id));
      stack.append(card);
    });
    lane.append(header, stack);
    board.append(lane);
  });
}

function existingCount(files) {
  return (files || []).filter((file) => file.exists && file.is_file).length;
}

function renderDecisions(decisions) {
  const list = byId("decision-list");
  list.replaceChildren();
  if (!decisions.length) {
    list.append(element("div", "empty-state", "当前工作区还没有 decisions.jsonl 记录。"));
    return;
  }
  [...decisions].reverse().slice(0, 12).forEach((decision) => {
    const row = element("article", "decision-row");
    row.append(
      element("time", "", formatTime(decision.ts)),
      element("span", "decision-action", decision.action || "unknown"),
      element("span", "decision-reason", decision.reason || decision.invalid_record || "—"),
    );
    list.append(row);
  });
}

function openDrawer(stepId) {
  const node = allNodes().find((candidate) => candidate.id === stepId);
  if (!node) return;
  selectedStepId = stepId;
  renderDrawer(node);
  const drawer = byId("node-drawer");
  drawer.classList.add("open");
  drawer.setAttribute("aria-hidden", "false");
  byId("drawer-backdrop").hidden = false;
  byId("drawer-close").focus();
}

function renderDrawer(node) {
  byId("drawer-stage").textContent = `${node.stage.toUpperCase()} · ${node.id}`;
  byId("drawer-title").textContent = node.name;
  const body = byId("drawer-body");
  body.replaceChildren();

  const statusRow = element("div", "drawer-status-row");
  statusRow.append(
    element("span", `drawer-status status-${node.status}`, statusLabel(node.status)),
    element("span", "drawer-tag", node.gate ? "Quality Gate" : node.executor.type),
  );
  if (node.recorded_status !== node.status) {
    statusRow.append(element("span", "drawer-tag", `记录状态：${statusLabel(node.recorded_status)}`));
  }
  body.append(statusRow);

  const grid = element("div", "detail-grid");
  grid.append(
    detailCell("执行者", node.executor.ref || node.executor.type),
    detailCell("最近更新", formatTime(node.updated_at)),
    detailCell("输入事实", `${existingCount(node.inputs)} / ${node.inputs.length} 存在`),
    detailCell("输出事实", `${existingCount(node.outputs)} / ${node.outputs.length} 存在`),
    detailCell("运行日志", `${existingCount(node.logs)} 个可查看`),
    detailCell("模型交互", `${node.interactions?.length || 0} 条摘要`),
  );
  body.append(grid);

  if (node.instruction) {
    body.append(sectionWith("人工说明", element("p", "instruction-box", node.instruction.trim())));
  }
  if (node.note) {
    body.append(sectionWith("状态备注", element("p", "node-note", node.note)));
  }
  body.append(fileSection("运行日志", node.logs, "该节点尚未生成运行日志。"));
  body.append(interactionSection(node.interactions || []));
  body.append(fileSection("输入", node.inputs, "该节点没有声明输入。"));
  body.append(fileSection("输出与结果", node.outputs, "该节点没有声明输出。"));
  if ((node.related_files || []).length) {
    body.append(fileSection("关联决策 / 报告", node.related_files));
  }
  body.append(runSection(node.runs || []));
}

function interactionSection(interactions) {
  const list = element("div", "chat-list");
  if (!interactions.length) {
    const syncStatus = snapshot?.interaction_ledger?.sync_status;
    const syncHint = syncStatus?.last_sync_at
      ? `最近自动同步：${formatTime(syncStatus.last_sync_at)}。该节点在本次同步中没有可见聊天。`
      : "尚未检测到 Claude Code 自动同步；安装新插件并重启 Claude Code 后，每轮结束会自动记录。";
    list.append(element(
      "div",
      "empty-state",
      `该节点还没有显式交互记录。${syncHint}`,
    ));
  } else {
    interactions.slice(-100).forEach((interaction) => {
      const message = element("article", `chat-message role-${interaction.role || "system"}`);
      const header = element("header", "chat-header");
      const identity = element("div", "chat-identity");
      identity.append(
        element("span", "chat-role", ROLE_LABELS[interaction.role] || interaction.role || "记录"),
        element("span", "chat-kind", INTERACTION_KIND_LABELS[interaction.kind] || interaction.kind || "说明"),
      );
      header.append(identity, element("time", "", formatTime(interaction.ts)));
      message.append(header, element("p", "chat-content", interaction.content || "—"));

      const metadata = [];
      if (interaction.run_id) metadata.push(`run: ${interaction.run_id}`);
      if (interaction.model) metadata.push(`model: ${interaction.model}`);
      if (interaction.spec_version) metadata.push(`spec: ${interaction.spec_version}`);
      (interaction.references || []).forEach((reference) => metadata.push(`ref: ${reference}`));
      if (metadata.length) {
        const meta = element("div", "chat-meta");
        metadata.forEach((value) => meta.append(element("span", "", value)));
        message.append(meta);
      }
      list.append(message);
    });
  }
  return sectionWith("大模型交互记录（摘要）", list);
}

function detailCell(label, value) {
  const cell = element("div", "detail-cell");
  cell.append(element("span", "", label), element("strong", "", value || "—"));
  return cell;
}

function sectionWith(title, content) {
  const section = element("section", "drawer-section");
  section.append(element("h3", "", title), content);
  return section;
}

function fileSection(title, files, emptyMessage = "没有文件记录。") {
  const list = element("div", "file-list");
  if (!files?.length) {
    list.append(element("div", "empty-state", emptyMessage));
  } else {
    files.forEach((file) => list.append(fileRow(file)));
  }
  return sectionWith(title, list);
}

function fileRow(file) {
  const row = element("div", `file-row${file.exists && file.is_file ? " exists" : ""}`);
  const copy = element("div", "file-copy");
  copy.append(element("span", "file-name", `${file.name}${file.required ? " · 必需" : ""}`));
  copy.append(element("span", "file-path", file.path || "未声明路径"));
  const tail = element("div");
  if (file.exists && file.is_file) {
    const link = element("a", "file-action", "查看");
    link.href = `/api/file?path=${encodeURIComponent(file.path)}`;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = `${formatBytes(file.size)} · ${formatTime(file.modified_at)}`;
    tail.append(link);
  } else {
    tail.append(element("span", "file-meta", "不存在"));
  }
  row.append(element("span", "file-presence"), copy, tail);
  return row;
}

function runSection(runs) {
  const list = element("div", "run-list");
  if (!runs.length) {
    list.append(element("div", "empty-state", "该 stage 当前没有 run_NNN 历史。"));
  } else {
    runs.forEach((run) => {
      const row = element("div", "run-row");
      row.append(
        element("span", "run-id", run.run_id),
        element("span", "run-path", run.path),
        element("span", "file-meta", run.eval_overall || run.status || `${run.file_count} files`),
      );
      list.append(row);
    });
  }
  return sectionWith("Stage Run 历史", list);
}

function closeDrawer() {
  selectedStepId = null;
  const drawer = byId("node-drawer");
  drawer.classList.remove("open");
  drawer.setAttribute("aria-hidden", "true");
  byId("drawer-backdrop").hidden = true;
}

function locateCurrent() {
  const currentId = snapshot?.summary?.current_step_id;
  if (!currentId) return;
  const selector = `.node-card[data-step-id="${CSS.escape(currentId)}"]`;
  const card = document.querySelector(selector);
  if (card) {
    card.scrollIntoView({ behavior: "smooth", block: "center", inline: "center" });
    card.focus({ preventScroll: true });
  }
}

function applySearch() {
  const query = byId("node-search").value.trim().toLowerCase();
  document.querySelectorAll(".stage-lane").forEach((lane) => {
    let visibleCount = 0;
    lane.querySelectorAll(".node-card").forEach((card) => {
      const visible = !query || card.dataset.search.includes(query) || lane.dataset.search.includes(query);
      card.hidden = !visible;
      if (visible) visibleCount += 1;
    });
    lane.classList.toggle("is-empty", visibleCount === 0);
  });
}

function showError(message) {
  const toast = byId("error-toast");
  toast.textContent = message;
  toast.hidden = false;
}

function hideError() {
  byId("error-toast").hidden = true;
}

function configureAutoRefresh() {
  if (refreshTimer) window.clearInterval(refreshTimer);
  refreshTimer = null;
  if (byId("auto-refresh").checked) {
    refreshTimer = window.setInterval(() => loadSnapshot({ quiet: true }), 5000);
  }
}

byId("refresh-button").addEventListener("click", () => loadSnapshot());
byId("auto-refresh").addEventListener("change", configureAutoRefresh);
byId("node-search").addEventListener("input", applySearch);
byId("locate-current").addEventListener("click", locateCurrent);
byId("drawer-close").addEventListener("click", closeDrawer);
byId("drawer-backdrop").addEventListener("click", closeDrawer);
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && selectedStepId) closeDrawer();
});

configureAutoRefresh();
loadSnapshot();
