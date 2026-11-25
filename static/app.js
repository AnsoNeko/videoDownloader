const body = document.body;
const urlInput = document.getElementById("urlInput");
const cookiesInput = document.getElementById("cookiesInput");
const analyzeBtn = document.getElementById("analyzeBtn");
const downloadBtn = document.getElementById("downloadBtn");
const statusBox = document.getElementById("statusBox");
const resultCard = document.getElementById("resultCard");
const titleEl = document.getElementById("title");
const subtitleEl = document.getElementById("subtitle");
const thumbEl = document.getElementById("thumb");
const originLink = document.getElementById("originLink");
const formatSelect = document.getElementById("formatSelect");
const progressCard = document.getElementById("progressCard");
const progressBar = document.getElementById("progressBar");
const progressPercent = document.getElementById("progressPercent");
const progressStage = document.getElementById("progressStage");
const progressMeta = document.getElementById("progressMeta");
const downloadDirInput = document.getElementById("downloadDirInput");
const chooseDirBtn = document.getElementById("chooseDirBtn");
const saveDirBtn = document.getElementById("saveDirBtn");
const resetDirBtn = document.getElementById("resetDirBtn");
const directoryStatus = document.getElementById("directoryStatus");
const cookiePlatform = document.getElementById("cookiePlatform");
const useSavedCookies = document.getElementById("useSavedCookies");
const cookieFileInput = document.getElementById("cookieFileInput");
const importCookiesBtn = document.getElementById("importCookiesBtn");
const saveCookiesBtn = document.getElementById("saveCookiesBtn");
const clearCookiesBtn = document.getElementById("clearCookiesBtn");
const cookieStatus = document.getElementById("cookieStatus");
const cookieDrafts = new Map();
let activeCookiePlatform = cookiePlatform.value;
let manualCookiePlatform = false;
let cookieDetectionVersion = 0;
let cookieDetectionTimer = null;

let currentInfo = null;
let currentJobId = null;
let progressTimer = null;

function formatDuration(seconds) {
  if (!seconds) return "时长未知";
  const total = Number(seconds);
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = total % 60;
  return [h, m, s]
    .filter((value, index) => value > 0 || index > 0)
    .map((value) => String(value).padStart(2, "0"))
    .join(":");
}

function formatSize(bytes) {
  if (!bytes) return "";
  const units = ["B", "KB", "MB", "GB"];
  let size = Number(bytes);
  let unitIndex = 0;
  while (size >= 1024 && unitIndex < units.length - 1) {
    size /= 1024;
    unitIndex += 1;
  }
  return `${size.toFixed(size >= 100 ? 0 : 1)} ${units[unitIndex]}`;
}

function formatSpeed(bytesPerSecond) {
  if (!bytesPerSecond) return "";
  return `${formatSize(bytesPerSecond)}/s`;
}

function setStatus(text, type = "muted") {
  statusBox.className = `status status-${type}`;
  statusBox.innerHTML = text;
}

function setBusy(busy) {
  analyzeBtn.disabled = busy;
  downloadBtn.disabled = busy || !currentInfo;
  downloadDirInput.disabled = busy;
  saveDirBtn.disabled = busy;
  resetDirBtn.disabled = busy;
  if (chooseDirBtn) chooseDirBtn.disabled = busy;
  for (const control of [urlInput, cookiesInput, cookiePlatform, useSavedCookies,
    importCookiesBtn, saveCookiesBtn, clearCookiesBtn, cookieFileInput, formatSelect]) {
    control.disabled = busy;
  }
}

function invalidatePreview() {
  currentInfo = null;
  downloadBtn.disabled = true;
  resultCard.classList.add("hidden");
}

function showCookieState() {
  const option = cookiePlatform.selectedOptions[0];
  cookieStatus.textContent = option.value
    ? `${option.textContent}：${option.dataset.saved === "true" ? "本机已有保存的 Cookie" : "尚未保存 Cookie，可留空匿名尝试"}`
    : "粘贴或导入 Cookie 后自动识别所属平台，无需先填视频链接。";
  cookieStatus.classList.remove("error");
}

function updateCookieState(saved) {
  for (const option of cookiePlatform.options) {
    option.dataset.saved = saved[option.value] ? "true" : "false";
  }
  showCookieState();
}

function switchCookiePlatform(platform) {
  if (platform === activeCookiePlatform) return;
  cancelCookieDetection();
  if (!activeCookiePlatform && cookiesInput.value.trim()) {
    adoptCookiePlatform(platform, cookiesInput.value);
    invalidatePreview();
    showCookieState();
    return;
  }
  if (activeCookiePlatform) cookieDrafts.set(activeCookiePlatform, cookiesInput.value);
  cookiePlatform.value = platform;
  activeCookiePlatform = platform;
  cookiesInput.value = cookieDrafts.get(platform) || "";
  invalidatePreview();
  showCookieState();
}

function cancelCookieDetection() {
  cookieDetectionVersion += 1;
  clearTimeout(cookieDetectionTimer);
}

function adoptCookiePlatform(platform, text) {
  // The pasted text belongs to the detected platform. Moving the selection
  // must preserve that text instead of restoring a different platform's draft.
  cookiePlatform.value = platform;
  activeCookiePlatform = platform;
  cookiesInput.value = text;
  if (platform) cookieDrafts.set(platform, text);
}

async function detectPastedCookies() {
  const version = ++cookieDetectionVersion;
  const text = cookiesInput.value;
  try {
    const detected = await postJson("/api/cookies/detect", { cookies_text: text, url: urlInput.value.trim() });
    if (version !== cookieDetectionVersion || text !== cookiesInput.value) return;
    if (detected.platform) {
      manualCookiePlatform = false;
      adoptCookiePlatform(detected.platform, text);
      showCookieState();
      cookieStatus.textContent = `已根据${detected.source === "url" ? "视频链接" : "Cookie 内容"}识别为 ${cookiePlatform.selectedOptions[0].textContent}，可直接保存。`;
    } else if (!manualCookiePlatform || (detected.candidates.length && !detected.candidates.includes(cookiePlatform.value))) {
      adoptCookiePlatform("", text);
      showCookieState();
      if (text.trim()) {
        cookieStatus.textContent = detected.candidates.length
          ? "检测到多个平台的 Cookie，请选择本次要保存的平台。"
          : "此 Cookie 缺少可识别的平台信息，请选择所属平台，或先粘贴对应视频链接。";
      }
    }
  } catch (error) {
    if (version !== cookieDetectionVersion) return;
    cookieStatus.textContent = error.message;
    cookieStatus.classList.add("error");
  }
}

function scheduleCookieDetection() {
  cancelCookieDetection();
  cookieDetectionTimer = setTimeout(detectPastedCookies, 200);
}

function syncCookiePlatform() {
  const match = urlInput.value.match(/https?:\/\/[^\s<>，。！？；）】》」“”]+/i);
  if (!match) return;
  try {
    const host = new URL(match[0]).hostname.toLowerCase();
    for (const option of cookiePlatform.options) {
      if (!option.value) continue;
      if (option.dataset.domains.split(",").some(domain => host === domain || host.endsWith(`.${domain}`))) {
        switchCookiePlatform(option.value);
        return;
      }
    }
  } catch { /* The backend will explain invalid or unsupported URLs. */ }
}

function cookiePayload() {
  return {
    cookie_platform: cookiePlatform.value,
    cookies_text: getCookiesText(),
    use_saved_cookies: useSavedCookies.checked,
  };
}

urlInput.addEventListener("input", () => {
  invalidatePreview();
  syncCookiePlatform();
});
cookiesInput.addEventListener("input", () => {
  invalidatePreview();
  scheduleCookieDetection();
});
useSavedCookies.addEventListener("change", invalidatePreview);
cookiePlatform.addEventListener("change", () => {
  const platform = cookiePlatform.value;
  cancelCookieDetection();
  manualCookiePlatform = Boolean(platform);
  // Manual selection is the fallback for an unrecognized or combined file.
  // Keep the just-pasted contents available for saving in that case.
  if (!activeCookiePlatform && cookiesInput.value.trim()) {
    adoptCookiePlatform(platform, cookiesInput.value);
    invalidatePreview();
    showCookieState();
  } else {
    switchCookiePlatform(platform);
  }
});

importCookiesBtn.addEventListener("click", () => cookieFileInput.click());
cookieFileInput.addEventListener("change", async () => {
  const file = cookieFileInput.files[0];
  if (!file) return;
  const platform = cookiePlatform.value;
  const previousText = cookiesInput.value;
  try {
    if (file.size > 1024 * 1024) throw new Error("Cookie 文件过大，请导出目标网站的 cookies.txt（不超过 1 MB）。");
    const text = await file.text();
    // File reading can finish after the user has switched platforms.
    if (cookiePlatform.value === platform && cookiesInput.value === previousText) {
      cookiesInput.value = text;
      invalidatePreview();
      await detectPastedCookies();
    }
  } catch (error) {
    cookieStatus.textContent = error.message;
    cookieStatus.classList.add("error");
  } finally {
    cookieFileInput.value = "";
  }
});

saveCookiesBtn.addEventListener("click", async () => {
  cancelCookieDetection();
  setBusy(true);
  try {
    const text = getCookiesText();
    const data = await postJson("/api/cookies", { platform: manualCookiePlatform ? cookiePlatform.value : "", cookies_text: text, url: urlInput.value.trim() });
    adoptCookiePlatform(data.platform, text);
    updateCookieState(data.saved_cookies);
    useSavedCookies.checked = true;
    invalidatePreview();
    cookieStatus.textContent += "；已保存，下次留空即可自动使用。";
  } catch (error) {
    cookieStatus.textContent = error.message;
    cookieStatus.classList.add("error");
  } finally { setBusy(false); }
});

clearCookiesBtn.addEventListener("click", async () => {
  if (!cookiePlatform.value) {
    cancelCookieDetection();
    cookiesInput.value = "";
    invalidatePreview();
    showCookieState();
    return;
  }
  cancelCookieDetection();
  setBusy(true);
  try {
    const response = await fetch(`/api/cookies/${encodeURIComponent(cookiePlatform.value)}`, { method: "DELETE" });
    const data = await response.json();
    if (!response.ok || !data.ok) throw new Error(data.error || "清除失败");
    cookiesInput.value = "";
    cookieDrafts.delete(cookiePlatform.value);
    useSavedCookies.checked = false;
    updateCookieState(data.saved_cookies);
    invalidatePreview();
    cookieStatus.textContent = "已清除此平台的输入和保存文件，并关闭自动使用。程序目录 cookies.txt 保留，可重新勾选后使用。";
  } catch (error) {
    cookieStatus.textContent = error.message;
    cookieStatus.classList.add("error");
  } finally { setBusy(false); }
});

showCookieState();

function setDirectoryStatus(message, error = false) {
  directoryStatus.textContent = message;
  directoryStatus.classList.toggle("error", error);
}

async function saveDirectory(value) {
  const data = await postJson("/api/settings", { download_dir: value });
  downloadDirInput.value = data.download_dir;
  setDirectoryStatus(`已保存下载目录：${data.download_dir}`);
}

saveDirBtn.addEventListener("click", async () => {
  setBusy(true);
  try {
    await saveDirectory(downloadDirInput.value.trim());
  } catch (error) {
    setDirectoryStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

resetDirBtn.addEventListener("click", async () => {
  setBusy(true);
  try {
    await saveDirectory("");
  } catch (error) {
    setDirectoryStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

if (chooseDirBtn) chooseDirBtn.addEventListener("click", async () => {
  setBusy(true);
  setDirectoryStatus("请在弹出的窗口中选择下载文件夹…");
  try {
    const data = await postJson("/api/download-directory/choose", { download_dir: downloadDirInput.value.trim() });
    if (data.cancelled) {
      setDirectoryStatus("已取消选择，下载目录保持不变。");
    } else {
      downloadDirInput.value = data.download_dir;
      await saveDirectory(data.download_dir);
    }
  } catch (error) {
    setDirectoryStatus(error.message, true);
  } finally {
    setBusy(false);
  }
});

function escapeHtml(value) {
  const element = document.createElement("span");
  element.textContent = value;
  return element.innerHTML;
}

function getCookiesText() {
  return cookiesInput.value.replace(/^\uFEFF/, "").replace(/^[ \r\n]+|[ \r\n]+$/g, "");
}

function renderInfo(info) {
  currentInfo = info;
  titleEl.textContent = info.title || "未命名视频";
  subtitleEl.textContent = `${info.uploader || "未知作者"} | ${formatDuration(info.duration)}`;
  thumbEl.src = info.thumbnail || "";
  thumbEl.alt = info.title || "thumbnail";
  originLink.href = info.webpage_url || "#";
  originLink.textContent = info.webpage_url || "原视频链接";

  formatSelect.innerHTML = "";
  const bestOption = document.createElement("option");
  bestOption.value = "";
  bestOption.textContent = "最佳画质（自动合并，推荐）";
  formatSelect.appendChild(bestOption);

  for (const item of info.formats || []) {
    const option = document.createElement("option");
    option.value = item.format_id;
    const parts = [item.label, item.ext.toUpperCase()];
    if (item.video && item.audio) parts.push("含音频");
    if (item.video && !item.audio) parts.push("仅视频");
    if (!item.video && item.audio) parts.push("仅音频");
    if (item.filesize) parts.push(formatSize(item.filesize));
    option.textContent = parts.join(" | ");
    formatSelect.appendChild(option);
  }

  resultCard.classList.remove("hidden");
  downloadBtn.disabled = false;
}

function resetProgress() {
  progressBar.style.width = "0%";
  progressPercent.textContent = "0%";
  progressStage.textContent = "等待开始...";
  progressMeta.textContent = "";
}

function renderProgress(job) {
  const percent = Math.max(0, Math.min(100, Number(job.progress || 0)));
  progressCard.classList.remove("hidden");
  progressBar.style.width = `${percent}%`;
  progressPercent.textContent = `${percent.toFixed(1)}%`;
  progressStage.textContent = job.stage || "正在处理...";

  const meta = [];
  if (job.downloaded_bytes) meta.push(`已下载 ${formatSize(job.downloaded_bytes)}`);
  if (job.total_bytes) meta.push(`总大小 ${formatSize(job.total_bytes)}`);
  if (job.speed) meta.push(`速度 ${formatSpeed(job.speed)}`);
  if (job.eta || job.eta === 0) meta.push(`剩余 ${job.eta}s`);
  progressMeta.textContent = meta.join(" | ");
}

function stopProgressPolling() {
  if (progressTimer) {
    clearInterval(progressTimer);
    progressTimer = null;
  }
}

async function pollJob() {
  if (!currentJobId) return;
  try {
    const response = await fetch(`/api/download/${currentJobId}`);
    const data = await response.json();
    if (!response.ok || !data.ok) {
      throw new Error(data.error || "无法获取下载进度");
    }

    const job = data.job;
    renderProgress(job);

    if (job.status === "completed") {
      stopProgressPolling();
      setBusy(false);
      setStatus(`下载完成：${escapeHtml(job.file_name)}<br>保存位置：<code>${escapeHtml(job.download_dir)}</code>`, "success");
    } else if (job.status === "failed") {
      stopProgressPolling();
      setBusy(false);
      setStatus(escapeHtml(job.error || "下载失败"), "error");
    }
  } catch (error) {
    stopProgressPolling();
    setBusy(false);
    setStatus(escapeHtml(error.message || "获取进度失败"), "error");
  }
}

function startProgressPolling(jobId) {
  currentJobId = jobId;
  stopProgressPolling();
  resetProgress();
  progressCard.classList.remove("hidden");
  progressStage.textContent = "任务已创建，准备开始下载...";
  progressTimer = setInterval(pollJob, 1000);
  pollJob();
}

async function postJson(url, payload) {
  const response = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  const data = await response.json();
  if (!response.ok || !data.ok) {
    throw new Error(data.error || "请求失败");
  }
  return data;
}

analyzeBtn.addEventListener("click", async () => {
  syncCookiePlatform();
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("请先粘贴视频链接。", "error");
    return;
  }
  stopProgressPolling();
  currentJobId = null;
  progressCard.classList.add("hidden");
  setBusy(true);
  setStatus("正在解析视频链接...", "muted");
  try {
    const data = await postJson("/api/info", {
      url,
      use_browser_cookies: false,
      ...cookiePayload(),
    });
    renderInfo(data.info);
    setStatus("解析完成，现在可以下载。", "success");
  } catch (error) {
    currentInfo = null;
    downloadBtn.disabled = true;
    resultCard.classList.add("hidden");
    setStatus(escapeHtml(error.message), "error");
  } finally {
    setBusy(false);
  }
});

downloadBtn.addEventListener("click", async () => {
  const url = urlInput.value.trim();
  if (!url) {
    setStatus("请先粘贴视频链接。", "error");
    return;
  }
  setBusy(true);
  setStatus("已开始下载，正在获取进度...", "muted");
  try {
    const data = await postJson("/api/download", {
      url,
      format_id: formatSelect.value,
      download_dir: downloadDirInput.value.trim(),
      use_browser_cookies: false,
      ...cookiePayload(),
    });
    downloadDirInput.value = data.download_dir;
    setDirectoryStatus(`本次下载保存至：${data.download_dir}`);
    startProgressPolling(data.job_id);
  } catch (error) {
    setBusy(false);
    setStatus(escapeHtml(error.message), "error");
  }
});

if (body.dataset.hasYtdlp !== "true") {
  setStatus("未检测到 yt-dlp，请先执行 <code>python -m pip install -r requirements.txt --target vendor</code>。", "error");
} else if (body.dataset.hasYoutubeRuntime !== "true") {
  setStatus("YouTube 组件未就绪，请运行 update_dependencies.ps1，并安装 Deno ≥ 2.3 或 Node.js ≥ 22 后重启。", "error");
} else if (body.dataset.hasFfmpeg !== "true") {
  setStatus("已检测到 yt-dlp，但未找到 ffmpeg。基础下载可用，但部分高清视频流可能无法自动合并。", "muted");
} else if (body.dataset.hasCookieFile === "true") {
  setStatus("已检测到项目目录里的 <code>cookies.txt</code>，未粘贴文本时会自动使用它。", "success");
}
