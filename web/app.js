const $ = (sel) => document.querySelector(sel);

const state = {
  items: [],
  tasks: [],
  settings: null,
  deps: { ytdlp: "", ffmpeg: "" },
  parseBusy: false,
};

const STATUS_TEXT = {
  queued: "排队中",
  downloading: "下载中",
  processing: "合并中",
  done: "已完成",
  error: "失败",
  canceled: "已取消",
};

const PLATFORM_TEXT = { bilibili: "B站", douyin: "抖音" };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (ch) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[ch]));
}

function fmtDuration(seconds) {
  seconds = Math.max(0, Math.floor(seconds || 0));
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  const s = seconds % 60;
  const pad = (n) => String(n).padStart(2, "0");
  return h ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.textContent = message;
  $("#toasts").appendChild(el);
  setTimeout(() => {
    el.style.opacity = "0";
    el.style.transition = "opacity .25s";
    setTimeout(() => el.remove(), 260);
  }, 3200);
}

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  let data = null;
  try {
    data = await res.json();
  } catch (_) {
    /* ignore non-json */
  }
  if (!res.ok || (data && data.ok === false)) {
    throw new Error((data && data.error) || `请求失败 (${res.status})`);
  }
  return data;
}

/* ---------------------------------------------------------------- state */
async function refreshState() {
  try {
    const data = await api("/api/state");
    state.settings = data.settings;
    state.deps = data.deps;
    renderDeps();
    renderTasks(data.tasks);
  } catch (err) {
    console.warn(err);
  }
}

function renderDeps() {
  const pill = $("#dep-status");
  const ready = state.deps.ytdlp && state.deps.ffmpeg;
  pill.className = `pill ${ready ? "pill-ok" : "pill-warn"}`;
  pill.textContent = ready ? "引擎就绪" : "缺少依赖";
  pill.title = `yt-dlp: ${state.deps.ytdlp || "未找到"}\nffmpeg: ${state.deps.ffmpeg || "未找到"}`;

  $("#dep-box").innerHTML = [
    `yt-dlp：${state.deps.ytdlp ? esc(state.deps.ytdlp) : "未找到（B站下载必需）"}`,
    `ffmpeg：${state.deps.ffmpeg ? esc(state.deps.ffmpeg) : "未找到（B站高清合并必需）"}`,
  ]
    .map((line) => `<div>${line}</div>`)
    .join("");
}

/* ----------------------------------------------------------------- parse */
function renderErrors(errors) {
  const box = $("#errors");
  if (!errors || !errors.length) {
    box.classList.add("hidden");
    box.innerHTML = "";
    return;
  }
  box.classList.remove("hidden");
  box.innerHTML = errors
    .map((e) => `<div><strong>${esc(e.url)}</strong><br/>${esc(e.message)}</div>`)
    .join("");
}

function renderResults(items) {
  const root = $("#results");
  root.innerHTML = "";
  if (!items.length) return;

  items.forEach((item, index) => {
    const card = document.createElement("article");
    card.className = "video-card";
    const qualities = item.qualities || [{ id: "best", label: "最高画质" }];
    const options = qualities
      .map((q) => `<option value="${esc(q.id)}">${esc(q.label)}</option>`)
      .join("");
    card.innerHTML = `
      <div class="cover-wrap">
        <img class="cover" loading="lazy" referrerpolicy="no-referrer" alt=""
             src="${item.cover ? esc(item.cover) : ""}" />
        <span class="duration-badge">${fmtDuration(item.duration)}</span>
      </div>
      <div class="video-body">
        <h3 class="video-title" title="${esc(item.title)}">${esc(item.title)}</h3>
        <div class="video-meta">
          <span class="badge badge-${esc(item.platform)}">${PLATFORM_TEXT[item.platform] || item.platform}</span>
          <span>${esc(item.author || "未知作者")}</span>
        </div>
        <div class="video-actions">
          <select data-quality="${index}">${options}</select>
          <button class="primary" data-download="${index}">下载</button>
        </div>
      </div>`;
    root.appendChild(card);
  });
}

async function handleParse() {
  if (state.parseBusy) return;
  const text = $("#links").value.trim();
  if (!text) {
    toast("请先粘贴链接", "error");
    return;
  }
  state.parseBusy = true;
  $("#btn-parse").disabled = true;
  $("#parse-spinner").classList.remove("hidden");
  $("#parse-label").textContent = "解析中…";
  try {
    const data = await api("/api/parse", { method: "POST", body: JSON.stringify({ text }) });
    state.items = data.items || [];
    renderResults(state.items);
    renderErrors(data.errors || []);
    if (state.items.length) {
      toast(`解析成功 ${state.items.length} 个视频`, "ok");
      $("#results").scrollIntoView({ behavior: "smooth", block: "start" });
    } else {
      toast("没有解析到可下载的视频", "error");
    }
  } catch (err) {
    toast(err.message, "error");
  } finally {
    state.parseBusy = false;
    $("#btn-parse").disabled = false;
    $("#parse-spinner").classList.add("hidden");
    $("#parse-label").textContent = "解析链接";
  }
}

async function handleDownload(index, button) {
  const item = state.items[index];
  if (!item) return;
  const select = document.querySelector(`select[data-quality="${index}"]`);
  const quality = select ? select.value : "best";
  button.disabled = true;
  button.textContent = "添加中…";
  try {
    await api("/api/download", {
      method: "POST",
      body: JSON.stringify({ item, quality }),
    });
    toast("已加入下载队列", "ok");
    refreshState();
    $(".tasks-section").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    toast(err.message, "error");
  } finally {
    button.disabled = false;
    button.textContent = "下载";
  }
}

/* ----------------------------------------------------------------- tasks */
const taskEls = new Map();

function taskSubText(task) {
  if (task.status === "error") return task.error || "下载失败";
  if (task.status === "done") return task.filepath ? `保存到 ${task.filepath}` : "已完成";
  const parts = [STATUS_TEXT[task.status] || task.status];
  if (task.size_text) parts.push(task.size_text);
  if (task.speed_text && task.status === "downloading") parts.push(task.speed_text);
  if (task.eta && task.status === "downloading") parts.push(`剩余 ${fmtDuration(task.eta)}`);
  return parts.join(" · ");
}

function renderTasks(tasks) {
  state.tasks = tasks || [];
  const root = $("#tasks");
  $("#task-count").textContent = state.tasks.length;

  const empty = $("#tasks-empty");
  if (!state.tasks.length) {
    empty.classList.remove("hidden");
  } else {
    empty.classList.add("hidden");
  }

  const seen = new Set();
  state.tasks.forEach((task) => {
    seen.add(task.id);
    let row = taskEls.get(task.id);
    if (!row) {
      row = document.createElement("div");
      row.className = "task";
      row.innerHTML = `
        <div class="task-main">
          <div class="task-title"><span class="badge"></span><span class="t-name"></span></div>
          <div class="progress"><i style="width:0%"></i></div>
          <div class="task-sub"></div>
        </div>
        <div class="task-actions"></div>`;
      root.appendChild(row);
      taskEls.set(task.id, row);
    }
    row.className = `task ${task.status}`;
    const badge = row.querySelector(".badge");
    badge.className = `badge badge-${task.platform}`;
    badge.textContent = PLATFORM_TEXT[task.platform] || task.platform;
    row.querySelector(".t-name").textContent = task.title;
    row.querySelector(".progress > i").style.width = `${Math.max(task.status === "done" ? 100 : 1, task.progress)}%`;
    row.querySelector(".task-sub").textContent = taskSubText(task);

    const actions = row.querySelector(".task-actions");
    const wanted = [];
    if (["queued", "downloading", "processing"].includes(task.status)) {
      wanted.push(["cancel", "✕", "取消"]);
    } else {
      if (task.status === "done") wanted.push(["open", "📂", "打开下载目录"]);
      wanted.push(["remove", "🗑", "从列表移除"]);
    }
    const signature = wanted.map((w) => w[0]).join(",");
    if (actions.dataset.sig !== signature) {
      actions.dataset.sig = signature;
      actions.innerHTML = wanted
        .map(([act, icon, title]) => `<button class="icon-btn" data-act="${act}" title="${title}">${icon}</button>`)
        .join("");
    }
  });

  [...taskEls.keys()].forEach((id) => {
    if (!seen.has(id)) {
      taskEls.get(id).remove();
      taskEls.delete(id);
    }
  });
}

async function handleTaskAction(event) {
  const button = event.target.closest("[data-act]");
  if (!button) return;
  const row = button.closest(".task");
  const entry = [...taskEls.entries()].find(([, el]) => el === row);
  if (!entry) return;
  const [id] = entry;
  const act = button.dataset.act;
  try {
    if (act === "cancel" || act === "remove") {
      await api(`/api/tasks/${id}`, { method: "DELETE" });
      if (act === "remove") {
        row.remove();
        taskEls.delete(id);
      }
      refreshState();
    } else if (act === "open") {
      await api("/api/open-folder", { method: "POST", body: "{}" });
    }
  } catch (err) {
    toast(err.message, "error");
  }
}

/* -------------------------------------------------------------- settings */
function openSettings() {
  if (!state.settings) return;
  $("#set-dir").value = state.settings.download_dir || "";
  $("#set-concurrency").value = state.settings.concurrency || 2;
  $("#set-cookie-browser").value = state.settings.cookie_browser || "";
  $("#set-cookie-file").value = state.settings.cookie_file || "";
  $("#set-bili").value = "";
  $("#set-dy").value = "";
  $("#set-bili").placeholder = state.settings.bilibili_cookie_set
    ? "已保存（留空则不修改）"
    : "SESSDATA=...; bili_jct=...;";
  $("#set-dy").placeholder = state.settings.douyin_cookie_set
    ? "已保存（留空则不修改）"
    : "可选：从浏览器开发者工具复制 Cookie";
  renderDeps();
  $("#settings-modal").classList.remove("hidden");
}

async function saveSettings() {
  const patch = {
    download_dir: $("#set-dir").value.trim(),
    concurrency: Number($("#set-concurrency").value) || 2,
    cookie_browser: $("#set-cookie-browser").value,
    cookie_file: $("#set-cookie-file").value.trim(),
  };
  const bili = $("#set-bili").value.trim();
  const dy = $("#set-dy").value.trim();
  if (bili) patch.bilibili_cookie = bili;
  if (dy) patch.douyin_cookie = dy;
  try {
    const data = await api("/api/settings", { method: "POST", body: JSON.stringify(patch) });
    state.settings = data.settings;
    $("#settings-modal").classList.add("hidden");
    toast("设置已保存", "ok");
  } catch (err) {
    toast(err.message, "error");
  }
}

/* ------------------------------------------------------------------ init */
function bind() {
  $("#btn-parse").addEventListener("click", handleParse);
  $("#btn-clear").addEventListener("click", () => {
    $("#links").value = "";
    state.items = [];
    renderResults([]);
    renderErrors([]);
  });
  $("#links").addEventListener("keydown", (event) => {
    if ((event.ctrlKey || event.metaKey) && event.key === "Enter") handleParse();
  });
  $("#results").addEventListener("click", (event) => {
    const button = event.target.closest("[data-download]");
    if (button) handleDownload(Number(button.dataset.download), button);
  });
  $("#tasks").addEventListener("click", handleTaskAction);
  $("#btn-settings").addEventListener("click", openSettings);
  $("#btn-save-settings").addEventListener("click", saveSettings);
  $("#btn-folder").addEventListener("click", () =>
    api("/api/open-folder", { method: "POST", body: "{}" }).catch((e) => toast(e.message, "error"))
  );
  $("#btn-clear-tasks").addEventListener("click", async () => {
    try {
      await api("/api/tasks/clear", { method: "POST", body: "{}" });
      taskEls.forEach((el) => el.remove());
      taskEls.clear();
      refreshState();
    } catch (err) {
      toast(err.message, "error");
    }
  });
  document.querySelectorAll("[data-close]").forEach((el) =>
    el.addEventListener("click", () => $("#settings-modal").classList.add("hidden"))
  );
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape") $("#settings-modal").classList.add("hidden");
  });
}

bind();
refreshState();
setInterval(() => {
  if (!document.hidden) refreshState();
}, 1200);
