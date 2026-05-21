importScripts("bridge_config.js");

const MENU_IMAGE = "wdtag-sample-image";
const MENU_VIDEO = "wdtag-sample-video";
const JOBS_URL = `${BRIDGE_BASE_URL}/api/jobs`;

let menuChain = Promise.resolve();

function registerMenus() {
  menuChain = menuChain.then(async () => {
    await chrome.contextMenus.removeAll();
    await chrome.contextMenus.create({
      id: MENU_IMAGE,
      title: "WDタグ+サンプル生成",
      contexts: ["image"]
    });
    await chrome.contextMenus.create({
      id: MENU_VIDEO,
      title: "WDタグ+サンプル生成（動画フレーム）",
      contexts: ["video"]
    });
  }).catch((error) => console.error("menu register failed", error));
  return menuChain;
}

chrome.runtime.onInstalled.addListener(registerMenus);
chrome.runtime.onStartup.addListener(registerMenus);
registerMenus();

chrome.contextMenus.onClicked.addListener(async (info, tab) => {
  if (!tab?.id) return;
  const frameId = typeof info.frameId === "number" ? info.frameId : 0;

  await notify(tab.id, frameId, {
    type: "WD_SAMPLE_STARTED",
    message: (await fetchGenerateSamplePreference())
      ? "タグ抽出とサンプル生成を開始しました..."
      : "タグ抽出を開始しました..."
  });

  try {
    let blob;
    let filename;
    if (info.menuItemId === MENU_IMAGE) {
      if (!info.srcUrl) throw new Error("画像URLが取得できませんでした");
      blob = await fetchImageBlob(info.srcUrl);
      filename = makeFilename(info.srcUrl, blob.type);
    } else if (info.menuItemId === MENU_VIDEO) {
      const capture = await chrome.tabs.sendMessage(
        tab.id,
        { type: "WD_SAMPLE_CAPTURE_VIDEO_FRAME" },
        { frameId }
      );
      if (!capture?.ok) throw new Error(capture?.error || "動画フレームを取得できませんでした");
      blob = dataUrlToBlob(capture.dataUrl);
      filename = `video_frame_${stamp()}.png`;
    } else {
      return;
    }

    const result = await postToBridge(blob, filename);
    await openInboxIfNeeded(result.job?.id || "");
    await notify(tab.id, frameId, {
      type: "WD_SAMPLE_DONE",
      message: "WD Tag Sample Viewer に送りました"
    });
  } catch (error) {
    await notify(tab.id, frameId, {
      type: "WD_SAMPLE_ERROR",
      message: readableError(error)
    });
  }
});

async function postToBridge(blob, filename) {
  const generateSample = await fetchGenerateSamplePreference();
  const form = new FormData();
  form.append("image", new File([blob], filename, { type: blob.type || "image/png" }));
  form.append("generateSample", generateSample ? "true" : "false");
  const response = await fetch(JOBS_URL, { method: "POST", body: form });
  let json;
  try {
    json = await response.json();
  } catch {
    throw new Error(`ブリッジがJSONを返しませんでした (${response.status})`);
  }
  if (!response.ok || json.ok === false) {
    throw new Error(json.error || `ブリッジエラー ${response.status}`);
  }
  return json;
}

async function fetchGenerateSamplePreference() {
  try {
    const response = await fetch(`${BRIDGE_BASE_URL}/api/settings`);
    const json = await response.json();
    if (!response.ok || json.ok === false) return true;
    return json.generateSample !== false;
  } catch {
    return true;
  }
}

async function openInboxIfNeeded(jobId) {
  const tabs = await chrome.tabs.query({});
  const inboxTab = tabs.find((tab) => {
    const url = tab.url || "";
    return url === `${BRIDGE_BASE_URL}/` || url.startsWith(`${BRIDGE_BASE_URL}/`);
  });
  if (inboxTab) {
    return;
  }
  const hash = jobId ? `#${encodeURIComponent(jobId)}` : "";
  await chrome.tabs.create({ url: `${BRIDGE_BASE_URL}/${hash}`, active: true });
}

async function fetchImageBlob(url) {
  const response = await fetch(url, { credentials: "include", cache: "force-cache" });
  if (!response.ok) throw new Error(`画像を取得できませんでした (${response.status})`);
  return await response.blob();
}

async function notify(tabId, frameId, message) {
  const options = { frameId };
  const target = frameId === 0 ? { tabId } : { tabId, frameIds: [frameId] };
  try {
    await chrome.tabs.sendMessage(tabId, message, options);
  } catch (_error) {
    await chrome.scripting.executeScript({ target, files: ["src/content.js"] });
    await chrome.tabs.sendMessage(tabId, message, options);
  }
}

function dataUrlToBlob(dataUrl) {
  const [header, payload] = String(dataUrl).split(",", 2);
  if (!payload) throw new Error("動画フレームのデータが空です");
  const mime = header.match(/^data:([^;]+)/)?.[1] || "image/png";
  const binary = atob(payload);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return new Blob([bytes], { type: mime });
}

function makeFilename(sourceUrl, mimeType) {
  const ext = extensionFromMime(mimeType) || extensionFromUrl(sourceUrl) || "png";
  return `wd_source_${stamp()}.${ext}`;
}

function extensionFromMime(mimeType) {
  return {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/gif": "gif"
  }[mimeType] || "";
}

function extensionFromUrl(url) {
  try {
    return new URL(url).pathname.match(/\.([a-z0-9]{3,5})$/i)?.[1]?.toLowerCase() || "";
  } catch {
    return "";
  }
}

function stamp() {
  return new Date().toISOString().replace(/[-:.TZ]/g, "").slice(0, 14);
}

function readableError(error) {
  const message = error?.message || String(error);
  if (message.includes("Failed to fetch")) {
    return "ローカルブリッジに接続できません。start.batが起動しているか確認してください。";
  }
  return message;
}
