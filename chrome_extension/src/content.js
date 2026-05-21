let lastContext = { x: 24, y: 24 };
let lastVideo = null;

document.addEventListener(
  "contextmenu",
  (event) => {
    lastContext = { x: event.clientX, y: event.clientY };
    const path = typeof event.composedPath === "function" ? event.composedPath() : [];
    lastVideo = null;
    for (const node of path) {
      if (node instanceof HTMLVideoElement) {
        lastVideo = node;
        break;
      }
    }
    if (!lastVideo) {
      lastVideo = event.target?.closest?.("video") || null;
    }
  },
  true
);

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (message?.type === "WD_SAMPLE_CAPTURE_VIDEO_FRAME") {
    queueMicrotask(() => {
      try {
        const video = lastVideo;
        if (!video) {
          sendResponse({ ok: false, error: "動画要素が見つかりませんでした" });
          return;
        }
        if (!video.videoWidth || !video.videoHeight) {
          sendResponse({ ok: false, error: "動画の解像度を取得できませんでした" });
          return;
        }
        const canvas = document.createElement("canvas");
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext("2d");
        if (!ctx) {
          sendResponse({ ok: false, error: "Canvasを作成できませんでした" });
          return;
        }
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        sendResponse({ ok: true, dataUrl: canvas.toDataURL("image/png") });
      } catch (error) {
        const msg =
          error?.name === "SecurityError" || String(error?.message || "").includes("tainted")
            ? "この動画はサイト側の制限によりフレームを取得できません"
            : error?.message || String(error);
        sendResponse({ ok: false, error: msg });
      }
    });
    return true;
  }

  if (message?.type === "WD_SAMPLE_STARTED") {
    showPanel({ state: "loading", message: message.message || "処理中..." });
  }
  if (message?.type === "WD_SAMPLE_ERROR") {
    showPanel({ state: "error", message: message.message || "エラーが発生しました" });
  }
  if (message?.type === "WD_SAMPLE_DONE") {
    showPanel({
      state: "done",
      message: message.message || "Chrome取込に送りました",
      autoCloseMs: 1800
    });
  }
  return undefined;
});

function showPanel({ state, message, prompt = "", caption = "", tags = [], images = [], autoCloseMs = 0 }) {
  document.getElementById("wd-forge-panel")?.remove();

  const host = document.createElement("div");
  host.id = "wd-forge-panel";
  host.style.left = `${Math.max(10, Math.min(lastContext.x, window.innerWidth - 440))}px`;
  host.style.top = `${Math.max(10, Math.min(lastContext.y, window.innerHeight - 320))}px`;
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
    <style>
      :host {
        position: fixed;
        z-index: 2147483647;
        width: min(430px, calc(100vw - 20px));
        color: #18181b;
        font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      }
      .panel {
        background: #ffffff;
        border: 1px solid rgba(24, 24, 27, 0.16);
        border-radius: 8px;
        box-shadow: 0 18px 52px rgba(0, 0, 0, 0.24);
        overflow: hidden;
      }
      .bar {
        align-items: center;
        background: #f4f4f5;
        border-bottom: 1px solid rgba(24, 24, 27, 0.1);
        cursor: move;
        display: flex;
        gap: 8px;
        min-height: 40px;
        padding: 0 8px 0 12px;
        user-select: none;
      }
      .title {
        flex: 1;
        font-size: 13px;
        font-weight: 700;
      }
      button {
        background: transparent;
        border: 0;
        border-radius: 6px;
        cursor: pointer;
        height: 30px;
        width: 30px;
      }
      button:hover {
        background: #e4e4e7;
      }
      .body {
        display: grid;
        gap: 10px;
        max-height: min(680px, calc(100vh - 70px));
        overflow: auto;
        padding: 12px;
      }
      .status {
        color: ${state === "error" ? "#b42318" : "#166534"};
        font-size: 13px;
        font-weight: 700;
        line-height: 1.45;
      }
      .prompt, .caption, .tags {
        background: #fafafa;
        border: 1px solid #e4e4e7;
        border-radius: 6px;
        font-size: 12px;
        line-height: 1.45;
        max-height: 130px;
        overflow: auto;
        padding: 8px;
        white-space: pre-wrap;
        word-break: break-word;
      }
      .images {
        display: grid;
        gap: 8px;
      }
      .images img {
        background: #f4f4f5;
        border: 1px solid #e4e4e7;
        border-radius: 6px;
        display: block;
        height: auto;
        max-width: 100%;
      }
    </style>
    <section class="panel" role="dialog" aria-label="WD Tag Sample">
      <div class="bar">
        <div class="title">WD Tag Sample</div>
        <button id="close" title="閉じる" aria-label="閉じる">x</button>
      </div>
      <div class="body">
        <div class="status">${escapeHtml(message)}</div>
        ${prompt ? `<div class="prompt">${escapeHtml(prompt)}</div>` : ""}
        ${caption ? `<div class="caption">${escapeHtml(caption)}</div>` : ""}
        ${tags.length ? `<div class="tags">${escapeHtml(tags.join(", "))}</div>` : ""}
        ${images.length ? `<div class="images">${images.map((src) => `<img src="${escapeHtml(src)}" alt="Generated sample">`).join("")}</div>` : ""}
      </div>
    </section>
  `;

  root.getElementById("close").addEventListener("click", () => host.remove());
  enableDrag(host, root.querySelector(".bar"));
  document.documentElement.append(host);

  if (autoCloseMs > 0) {
    let timer = setTimeout(() => host.remove(), autoCloseMs);
    host.addEventListener("pointerenter", () => clearTimeout(timer));
    host.addEventListener("pointerleave", () => {
      clearTimeout(timer);
      timer = setTimeout(() => host.remove(), 900);
    });
  }
}

function enableDrag(host, bar) {
  let drag = null;
  bar.addEventListener("pointerdown", (event) => {
    if (event.target.closest("button")) return;
    drag = {
      pointerId: event.pointerId,
      x: event.clientX,
      y: event.clientY,
      left: Number.parseFloat(host.style.left) || 0,
      top: Number.parseFloat(host.style.top) || 0
    };
    bar.setPointerCapture(event.pointerId);
  });
  bar.addEventListener("pointermove", (event) => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    const width = host.getBoundingClientRect().width;
    const height = host.getBoundingClientRect().height;
    const left = drag.left + event.clientX - drag.x;
    const top = drag.top + event.clientY - drag.y;
    host.style.left = `${clamp(left, 8, Math.max(8, window.innerWidth - width - 8))}px`;
    host.style.top = `${clamp(top, 8, Math.max(8, window.innerHeight - height - 8))}px`;
  });
  bar.addEventListener("pointerup", (event) => {
    if (!drag || drag.pointerId !== event.pointerId) return;
    bar.releasePointerCapture(event.pointerId);
    drag = null;
  });
  bar.addEventListener("pointercancel", () => {
    drag = null;
  });
}

function clamp(value, min, max) {
  return Math.min(Math.max(value, min), max);
}

function escapeHtml(value) {
  return String(value).replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char]));
}
