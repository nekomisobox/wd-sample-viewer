from __future__ import annotations

import copy
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


def find_nodes_by_title(workflow: dict[str, Any], *titles: str) -> list[tuple[str, dict[str, Any]]]:
    wanted = {title.strip().lower() for title in titles if title and title.strip()}
    found: list[tuple[str, dict[str, Any]]] = []
    for node_id, node in workflow.items():
        if not isinstance(node, dict):
            continue
        class_type = str(node.get("class_type") or "").strip()
        meta_title = str((node.get("_meta") or {}).get("title") or "").strip()
        candidates = {class_type.lower(), meta_title.lower()}
        if wanted.intersection(candidates):
            found.append((str(node_id), node))
    return found


def load_workflow(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise RuntimeError("workflow JSON must be an object")
    return data


def patch_txt2img_workflow(
    workflow: dict[str, Any],
    *,
    positive: str,
    negative: str,
    width: int,
    height: int,
    seed: int | None,
    node_positive: str,
    node_negative: str,
    node_ksampler: str,
    node_empty_latent: str,
) -> dict[str, Any]:
    wf = copy.deepcopy(workflow)
    pos_nodes = find_nodes_by_title(wf, node_positive)
    neg_nodes = find_nodes_by_title(wf, node_negative)
    sampler_nodes = find_nodes_by_title(wf, node_ksampler)
    latent_nodes = find_nodes_by_title(wf, node_empty_latent)
    if not pos_nodes:
        raise RuntimeError(f"positive node not found: {node_positive}")
    if not neg_nodes:
        raise RuntimeError(f"negative node not found: {node_negative}")
    if not sampler_nodes:
        raise RuntimeError(f"sampler node not found: {node_ksampler}")
    if not latent_nodes:
        raise RuntimeError(f"latent node not found: {node_empty_latent}")
    pos_nodes[0][1].setdefault("inputs", {})["text"] = positive
    neg_nodes[0][1].setdefault("inputs", {})["text"] = negative
    sampler_nodes[0][1].setdefault("inputs", {})["seed"] = seed if seed is not None else random.randint(0, 2**32 - 1)
    latent_nodes[0][1].setdefault("inputs", {})["width"] = int(width)
    latent_nodes[0][1].setdefault("inputs", {})["height"] = int(height)
    return wf


def http_json(url: str, method: str = "GET", payload: dict[str, Any] | None = None, timeout: int = 60) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=body, method=method)
    req.add_header("Accept", "application/json")
    if body is not None:
        req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"ComfyUI API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"ComfyUIに接続できません: {exc.reason}") from exc


def http_bytes(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def queue_prompt(comfy_url: str, workflow: dict[str, Any]) -> str:
    payload = {"prompt": workflow}
    result = http_json(f"{comfy_url.rstrip('/')}/prompt", "POST", payload, timeout=60)
    prompt_id = str(result.get("prompt_id") or "").strip()
    if not prompt_id:
        raise RuntimeError("ComfyUI prompt_id が空です")
    return prompt_id


def _history_entry(comfy_url: str, prompt_id: str) -> dict[str, Any] | None:
    all_history = http_json(f"{comfy_url.rstrip('/')}/history/{prompt_id}", timeout=30)
    entry = all_history.get(prompt_id)
    return entry if isinstance(entry, dict) else None


def wait_for_outputs(comfy_url: str, prompt_id: str, timeout: int = 900) -> dict[str, Any]:
    started = time.time()
    while time.time() - started < timeout:
        entry = _history_entry(comfy_url, prompt_id)
        if entry and entry.get("outputs"):
            status = entry.get("status") or {}
            if status.get("status_str") == "error":
                messages = status.get("messages") or []
                raise RuntimeError(str(messages[-1] if messages else "ComfyUI execution failed"))
            return entry
        time.sleep(1.0)
    raise RuntimeError("ComfyUI generation timed out")


def collect_preview_images(comfy_url: str, history: dict[str, Any]) -> list[bytes]:
    images: list[bytes] = []
    for output in (history.get("outputs") or {}).values():
        if not isinstance(output, dict):
            continue
        for image in output.get("images") or []:
            if not isinstance(image, dict):
                continue
            filename = str(image.get("filename") or "").strip()
            if not filename:
                continue
            query = urllib.parse.urlencode(
                {
                    "filename": filename,
                    "subfolder": image.get("subfolder", ""),
                    "type": image.get("type", "temp"),
                }
            )
            images.append(http_bytes(f"{comfy_url.rstrip('/')}/view?{query}", timeout=60))
    if not images:
        raise RuntimeError("ComfyUI history has no preview images")
    return images


def generate_txt2img(
    comfy_url: str,
    workflow_path: Path,
    *,
    positive: str,
    negative: str,
    width: int,
    height: int,
    seed: int | None,
    node_positive: str,
    node_negative: str,
    node_ksampler: str,
    node_empty_latent: str,
    timeout: int = 900,
) -> list[bytes]:
    workflow = patch_txt2img_workflow(
        load_workflow(workflow_path),
        positive=positive,
        negative=negative,
        width=width,
        height=height,
        seed=seed,
        node_positive=node_positive,
        node_negative=node_negative,
        node_ksampler=node_ksampler,
        node_empty_latent=node_empty_latent,
    )
    prompt_id = queue_prompt(comfy_url, workflow)
    history = wait_for_outputs(comfy_url, prompt_id, timeout=timeout)
    return collect_preview_images(comfy_url, history)
