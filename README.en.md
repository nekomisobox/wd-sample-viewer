# WD Tag Sample Viewer

[日本語](README.md) | **English**

<img width="249" height="314" alt="image" src="https://github.com/user-attachments/assets/4d92e91c-3f74-48c7-82fc-fe9361f65e88" /><img width="950" height="420" alt="image" src="https://github.com/user-attachments/assets/109fd211-46e2-417f-8434-5d02cbde85a0" />

Extract WD14 tags from images or video (the current frame of an HTML5 `<video>`), optionally generate sample images from those tags, and collect results in **WD Tag Sample Viewer** (bridge / viewer).

**Note:** The bridge UI, Chrome extension menus, and in-page notifications are **Japanese only**. This document is English; behavior is the same.

## Overview

From Chrome’s context menu, capture the target image or the current video frame and send it to a local **bridge** (`bridge_host` / `bridge_port` in `config.txt`), then to Forge or ComfyUI.

- **Backends**
  - `forge`: Forge / ReForge txt2img API
  - `comfyui`: ComfyUI txt2img workflow
- **Tagging / captioning**: WD14 and optional Florence run **inside the bridge** (no WD14 node in the ComfyUI workflow)
- **Florence captions**: Optional on/off
- **Japanese translation**: Danbooru dictionary (`data/danbooru_translations_jp.csv`) plus unofficial translation for unknown tags (**no paid APIs**)

This tool does **not** use the source image as img2img input. Right-clicked images/video are used **only for tag extraction**.

## Changelog

### v1.1

- **Rating tags in generation prompts** — When WD14 returns a rating, one tag is prepended to the positive prompt for sample generation only (general→safe, sensitive→sensitive, questionable→nsfw, explicit→explicit). Not added to the tag list or translation. The **Rating:** line in the viewer is still WD14’s classification.
- **View assembled generation prompt** — For jobs with sample generation, open **生成プロンプト（結合後）** in the viewer to see the exact positive sent to Forge / ComfyUI (collapsed by default, copy button).

### v1.0

Initial public release.

## Setup

First-time setup: see [README.txt](README.txt) (Japanese). Main steps: edit `config.txt`, start Forge/ComfyUI with API enabled, run `start.bat`, load the Chrome extension.

## Configuration

Edit `config.txt` to set backend and API URL.

```ini
backend=forge          # forge or comfyui
http://127.0.0.1:7860  # generation API URL (may be the first non-comment line)

# bridge (WD Tag Sample Viewer) listen address (default 127.0.0.1:8777)
bridge_host=127.0.0.1
bridge_port=8777
# bridge_url=http://127.0.0.1:8777  # optional; overrides host/port

# --- ComfyUI examples ---
# workflow=workflows/txt2img_sample.json
# node_positive=CLIP Text Encode Positive
# node_negative=CLIP Text Encode Negative
# node_ksampler=KSampler
```

Resolution, steps, sampler, checkpoint, etc. are **not** set in `config.txt`. Use Forge’s txt2img UI or your ComfyUI workflow JSON.

### ComfyUI notes

> [!CAUTION]
> **ComfyUI users (required reading)**  
> The bundled **workflows/txt2img_sample.json** is a **sample**. **It will not work as-is.** Fix these **two** items:
>
> 1. **Checkpoint** — Set **ckpt_name** on **CheckpointLoaderSimple** to a real file under **models/checkpoints/** (e.g. **your_model.safetensors**). The default **model.safetensors** will **fail**.
> 2. **API-format workflow** — Custom workflows must be saved with ComfyUI **Save (API Format)**. Normal workflow exports **will not work**.
>
> Without these fixes, prompt submission fails even when ComfyUI is reachable.

- Set **backend=comfyui** and ComfyUI URL (e.g. **http://127.0.0.1:8188**) in **config.txt**.
- **Seed:** The bridge **overwrites** `KSampler` seed with a **random** value each run (values in the workflow JSON are not used). Resolution, steps, sampler, etc. stay as in the workflow JSON.
- **workflow** / **node_*** lines can stay commented if you use the bundled workflow (defaults match the code). Uncomment only for custom JSON or different node `_meta.title`.
- Workflow must be **txt2img only** (no Load Image / WD14 nodes). Use **Preview Image** as the terminal node.
- The bridge fetches via `/view?type=temp` and saves under `jobs/`.

### What the bridge sends at generation time

The bridge sends only the assembled **positive** prompt and **negative** prompt from `config.txt`. Everything else uses each backend’s usual settings.

| Item | Forge / ReForge | ComfyUI |
| --- | --- | --- |
| Positive | txt2img `prompt` | Positive CLIP node in workflow |
| Negative | `negative_prompt` | Negative CLIP node in workflow |
| Seed | Forge UI | Bridge injects **random** seed into `KSampler` |
| Size, steps, sampler, batch, model | **Forge txt2img tab** | **Workflow JSON** |

`prompt_prefix` / `prompt_suffix` wrap tags when building the positive prompt (quality tags are usually in `prompt_suffix`). They are not shown in the viewer tag list.

When WD14 returns a rating, one tag is prepended for sample generation only: general→safe, sensitive→sensitive, questionable→nsfw, explicit→explicit. Not added to the tag list or translation.

## Translation

- Dictionary: `data/danbooru_translations_jp.csv`
- Unknown tags / Florence text: unofficial translation (via Google)
- On API failure: dictionary only plus a Japanese notice that caption translation failed (no billing prompts)

## Storage

- **Input image:** `jobs/{id}/input.png`
- **Generated sample:** `jobs/{id}/output_001.png`

**Reducing duplicate saves on the backend:**

- **Forge:** The bridge requests `save_images=false` (whether Forge honors it depends on Forge settings).
- **ComfyUI:** Preview Image + temp fetch only.

## Viewer (WD Tag Sample Viewer)

Open the bridge URL (default **http://127.0.0.1:8777/** while `start.bat` is running).

After changing `bridge_host` / `bridge_port`, **restart `start.bat`** and **reload** the extension at `chrome://extensions/` (`chrome_extension/src/bridge_config.js` is regenerated).

- Drag-and-drop, clipboard paste, image URL
- Job list, tag copy, translation copy
- **生成プロンプト（結合後）** — Collapsible assembled positive sent to the backend (v1.1; UI label is Japanese)
- **Sample generation** on/off (stored in `preferences.json`)
- **Florence caption** on/off (stored in `preferences.json`; first enable loads the model)
- Florence needs **transformers >= 4.41.2, < 4.50** and **timm / einops** (`requirements-florence.txt`). On errors, delete `.venv\.florence-installed-v3` and rerun `start.bat`, or `pip install -r requirements-florence.txt`.
- **Backend connection status**

## Chrome extension

Context menu entries (Japanese labels):

1. **Images:** WD tags + sample generation
2. **Video (`<video>`):** WD tags + sample generation (current frame)

Sends to the bridge → WD14 tags → (if enabled) generation → results in the viewer. A small notification panel appears on the page.

Reload the extension at `chrome://extensions/` after updates.

## Video frame capture

Only **HTML5 `<video>`** on the page. One frame at right-click time is exported to PNG for tagging (not full video download or batch frames).

### When it works

- A `<video>` element exists at the click target
- Metadata loaded; `videoWidth` / `videoHeight` available
- Same-origin or CORS-safe for canvas `drawImage`

### Common failures

| Cause | Behavior |
| :--- | :--- |
| Cross-origin / CORS | SecurityError-style message (Japanese) |
| DRM / encrypted streams | Canvas draw fails |
| iframe / custom players | No menu or capture failure |
| Not loaded yet | Resolution unknown message |
| No video under cursor | Video element not found |

**Workaround:** Screenshot or copy the frame and drop/paste it into the bridge viewer.

## Troubleshooting (first-time `model.onnx` download)

On first tag run, the bridge downloads `models/wd14/model.onnx`. On Windows you may see:

`[WinError 32] The process cannot access the file because it is being used by another process.`

| Check | Action |
| :--- | :--- |
| Multiple `start.bat` | Close all bridge consoles; start **one** |
| Copy of the project also running | Stop the other bridge |
| `model.onnx` already present | If size is OK (~tens of MB), no re-download; delete stray `model.onnx.tmp` |
| Stuck download | Stop bridge → delete `model.onnx.tmp` → one bridge → send one image |

Antivirus scanning right after download can cause temporary locks; the bridge retries.

## License

MIT License — see [LICENSE](LICENSE).
