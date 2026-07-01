const allowedExtensions = [".mp4", ".mkv", ".mov", ".webm", ".mp3"];

const fileInput = document.querySelector("#fileInput");
const dropZone = document.querySelector("#dropZone");
const fileMeta = document.querySelector("#fileMeta");
const form = document.querySelector("#transcribeForm");
const modelSelect = document.querySelector("#modelSelect");
const languageSelect = document.querySelector("#languageSelect");
const manualLanguageField = document.querySelector("#manualLanguageField");
const manualLanguageInput = document.querySelector("#manualLanguageInput");
const outputSelect = document.querySelector("#outputSelect");
const startButton = document.querySelector("#startButton");
const resetButton = document.querySelector("#resetButton");
const healthBadge = document.querySelector("#healthBadge");
const progressTrack = document.querySelector(".progress-track");
const progressBar = document.querySelector("#progressBar");
const progressPercent = document.querySelector("#progressPercent");
const stageText = document.querySelector("#stageText");
const elapsedText = document.querySelector("#elapsedText");
const remainingText = document.querySelector("#remainingText");
const processedText = document.querySelector("#processedText");
const statusMessage = document.querySelector("#statusMessage");
const previewBox = document.querySelector("#previewBox");
const detectedLanguage = document.querySelector("#detectedLanguage");
const downloadSection = document.querySelector("#downloadSection");
const downloadTxtButton = document.querySelector("#downloadTxtButton");
const downloadTimestampedButton = document.querySelector("#downloadTimestampedButton");
const downloadSrtButton = document.querySelector("#downloadSrtButton");
const filesList = document.querySelector("#filesList");

let selectedFile = null;
let busy = false;
let pollTimer = null;
let resultPayload = null;

function extensionOf(filename) {
  const index = filename.lastIndexOf(".");
  return index === -1 ? "" : filename.slice(index).toLowerCase();
}

function formatBytes(bytes) {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB"];
  const exponent = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1);
  const value = bytes / 1024 ** exponent;
  return `${value.toFixed(value >= 10 || exponent === 0 ? 0 : 1)} ${units[exponent]}`;
}

function formatClock(seconds, includeHours = false) {
  if (seconds === null || seconds === undefined || Number.isNaN(seconds)) return "--:--";
  const total = Math.max(0, Math.round(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = total % 60;
  if (includeHours || hours > 0) {
    return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
  }
  return `${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")}`;
}

function setBusy(isBusy) {
  busy = isBusy;
  fileInput.disabled = isBusy;
  modelSelect.disabled = isBusy;
  languageSelect.disabled = isBusy;
  manualLanguageInput.disabled = isBusy;
  outputSelect.disabled = isBusy;
  startButton.disabled = isBusy || !selectedFile;
}

function setMessage(message, state = "") {
  statusMessage.textContent = message;
  statusMessage.className = `status-message ${state}`.trim();
}

function resetProgress() {
  progressTrack.classList.remove("indeterminate");
  progressBar.style.width = "0%";
  progressPercent.textContent = "0%";
  stageText.textContent = "Ready";
  elapsedText.textContent = "00:00";
  remainingText.textContent = "--:--";
  processedText.textContent = "00:00:00 / --:--";
}

function updateProgress(progress) {
  const percent = Math.max(0, Math.min(100, Number(progress.progress || 0)));
  const indeterminate = progress.status === "running" && percent === 0 && progress.stage === "loading_model";
  progressTrack.classList.toggle("indeterminate", indeterminate);
  if (!indeterminate) progressBar.style.width = `${percent}%`;
  progressPercent.textContent = `${Math.round(percent)}%`;
  stageText.textContent = stageLabel(progress.stage);
  elapsedText.textContent = formatClock(progress.elapsed_seconds);
  remainingText.textContent = progress.estimated_remaining_seconds === null ? "--:--" : formatClock(progress.estimated_remaining_seconds);
  processedText.textContent = progress.processed || "00:00:00 / --:--";
  setMessage(progress.message || stageLabel(progress.stage), progress.status === "error" ? "error" : "");
}

function stageLabel(stage) {
  const labels = {
    ready: "Ready",
    preparing: "Preparing file",
    loading_model: "Loading model",
    transcribing: "Transcribing",
    writing_files: "Writing files",
    complete: "Complete",
    error: "Error",
  };
  return labels[stage] || stage || "Ready";
}

function validateFile(file) {
  if (!file) return "No file selected.";
  if (!allowedExtensions.includes(extensionOf(file.name))) {
    return "Unsupported file type. Choose an MP4, MKV, MOV, WEBM, or MP3 file.";
  }
  if (file.size === 0) return "This file is empty.";
  return "";
}

function selectFile(file) {
  const error = validateFile(file);
  clearResult();
  if (error) {
    selectedFile = null;
    fileInput.value = "";
    fileMeta.textContent = "No file selected";
    startButton.disabled = true;
    stageText.textContent = "Error";
    setMessage(error, "error");
    return;
  }

  selectedFile = file;
  fileMeta.textContent = `${file.name} - ${formatBytes(file.size)} - Duration: unknown`;
  startButton.disabled = busy;
  stageText.textContent = "Ready";
  setMessage("File selected.");
}

function selectedLanguage() {
  if (languageSelect.value !== "manual") return languageSelect.value;
  return manualLanguageInput.value.trim().toLowerCase() || "auto";
}

function toggleManualLanguage() {
  const manual = languageSelect.value === "manual";
  manualLanguageField.hidden = !manual;
  if (manual) manualLanguageInput.focus();
}

function clearResult() {
  resultPayload = null;
  downloadSection.hidden = true;
  filesList.replaceChildren();
  previewBox.textContent = "Your transcript will appear here.";
  detectedLanguage.textContent = "Language: -";
  resetProgress();
}

async function checkHealth() {
  try {
    const response = await fetch("/api/health");
    const health = await response.json();
    if (health.ffmpeg_available && health.ffprobe_available) {
      healthBadge.textContent = health.cuda_available ? "CUDA" : "CPU";
      healthBadge.className = "badge ok";
    } else {
      healthBadge.textContent = "ffmpeg missing";
      healthBadge.className = "badge warn";
    }
  } catch {
    healthBadge.textContent = "Server unavailable";
    healthBadge.className = "badge warn";
  }
}

async function startTranscription(event) {
  event.preventDefault();
  const error = validateFile(selectedFile);
  if (error) {
    setMessage(error, "error");
    return;
  }

  setBusy(true);
  clearResult();
  stageText.textContent = "Preparing file";
  setMessage("Preparing file.");

  try {
    const formData = new FormData();
    formData.append("file", selectedFile);
    formData.append("model", modelSelect.value);
    formData.append("language", selectedLanguage());
    formData.append("output_format", outputSelect.value);

    const response = await fetch("/api/transcribe", { method: "POST", body: formData });
    const payload = await response.json();
    if (!response.ok) throw new Error(payload.detail || "Could not start transcription.");
    if (payload.duration) {
      fileMeta.textContent = `${selectedFile.name} - ${formatBytes(selectedFile.size)} - Duration: ${payload.duration}`;
    }
    pollProgress(payload.job_id);
  } catch (error) {
    setBusy(false);
    stageText.textContent = "Error";
    setMessage(error.message || "Something went wrong.", "error");
  }
}

function pollProgress(jobId) {
  if (pollTimer) clearInterval(pollTimer);

  const tick = async () => {
    try {
      const response = await fetch(`/api/progress/${jobId}`);
      const progress = await response.json();
      if (!response.ok) throw new Error(progress.detail || "Could not read progress.");
      updateProgress(progress);

      if (progress.status === "complete") {
        clearInterval(pollTimer);
        pollTimer = null;
        await loadResult(jobId);
      } else if (progress.status === "error") {
        clearInterval(pollTimer);
        pollTimer = null;
        setBusy(false);
        stageText.textContent = "Error";
        setMessage(progress.error || "Transcription failed.", "error");
      }
    } catch (error) {
      clearInterval(pollTimer);
      pollTimer = null;
      setBusy(false);
      stageText.textContent = "Error";
      setMessage(error.message || "Could not read progress.", "error");
    }
  };

  tick();
  pollTimer = setInterval(tick, 1000);
}

async function loadResult(jobId) {
  const response = await fetch(`/api/result/${jobId}`);
  const payload = await response.json();
  if (!response.ok) {
    setBusy(false);
    stageText.textContent = "Error";
    setMessage(payload.detail || "Could not load transcript result.", "error");
    return;
  }

  resultPayload = payload;
  progressTrack.classList.remove("indeterminate");
  progressBar.style.width = "100%";
  progressPercent.textContent = "100%";
  stageText.textContent = "Complete";
  remainingText.textContent = "00:00";
  setMessage("Complete.", "complete");
  previewBox.textContent = payload.preview || payload.transcript || "No speech was detected.";
  detectedLanguage.textContent = `Language: ${payload.detected_language || "unknown"}`;
  renderFiles(payload.generated_files || {});
  downloadSection.hidden = false;
  setBusy(false);
}

function renderFiles(files) {
  filesList.replaceChildren();
  for (const key of ["plain", "timestamped", "srt"]) {
    if (!files[key]) continue;
    const item = document.createElement("li");
    item.textContent = files[key];
    filesList.append(item);
  }
}

function download(url) {
  if (!url) return;
  window.location.href = url;
}

fileInput.addEventListener("change", () => selectFile(fileInput.files[0]));
languageSelect.addEventListener("change", toggleManualLanguage);
form.addEventListener("submit", startTranscription);

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!busy) dropZone.classList.add("dragging");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragging");
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragging");
  if (!busy) selectFile(event.dataTransfer.files[0]);
});

resetButton.addEventListener("click", () => {
  if (pollTimer) clearInterval(pollTimer);
  pollTimer = null;
  selectedFile = null;
  fileInput.value = "";
  manualLanguageInput.value = "";
  languageSelect.value = "auto";
  toggleManualLanguage();
  fileMeta.textContent = "No file selected";
  startButton.disabled = true;
  clearResult();
  setMessage("Select a media file to begin.");
});

downloadTxtButton.addEventListener("click", () => download(resultPayload?.files?.txt));
downloadTimestampedButton.addEventListener("click", () => download(resultPayload?.files?.timestamped));
downloadSrtButton.addEventListener("click", () => download(resultPayload?.files?.srt));

toggleManualLanguage();
resetProgress();
checkHealth();
