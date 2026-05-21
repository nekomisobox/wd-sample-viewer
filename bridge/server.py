from __future__ import annotations

import base64
import csv
import gc
import io
import json
import math
import os
import subprocess
import sys
import time
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from comfy_client import generate_txt2img
from translate import translate_prompt

import numpy as np
import onnxruntime as ort
from PIL import Image, UnidentifiedImageError


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "config.txt"
PREFERENCES_PATH = ROOT / "preferences.json"
MODELS_DIR = ROOT / "models" / "wd14"
JOBS_DIR = ROOT / "jobs"
BRIDGE_CONFIG_JS_PATH = ROOT / "chrome_extension" / "src" / "bridge_config.js"
DEFAULT_BRIDGE_HOST = "127.0.0.1"
DEFAULT_BRIDGE_PORT = 8777
PREFERENCES_LOCK = threading.Lock()
MODEL_LOCK = threading.RLock()

MODEL_REPO_URL = "https://huggingface.co/SmilingWolf/wd-v1-4-convnext-tagger-v2/resolve/main"
MODEL_FILE = "model.onnx"
TAGS_FILE = "selected_tags.csv"


@dataclass
class Settings:
    backend: str = "forge"
    api_url: str = ""
    general_threshold: float = 0.35
    character_threshold: float = 0.85
    max_tags: int = 80
    florence_model: str = "thwri/CogFlorence-2.2-Large"
    florence_precision: str = "bf16"
    florence_attention: str = "sdpa"
    florence_task: str = "<MORE_DETAILED_CAPTION>"
    florence_max_new_tokens: int = 1024
    florence_num_beams: int = 5
    florence_do_sample: bool = False
    prompt_prefix: str = ""
    prompt_suffix: str = "masterpiece, best quality"
    negative_prompt: str = ""
    workflow: str = "workflows/txt2img_sample.json"
    node_positive: str = "CLIP Text Encode Positive"
    node_negative: str = "CLIP Text Encode Negative"
    node_ksampler: str = "KSampler"
    bridge_host: str = DEFAULT_BRIDGE_HOST
    bridge_port: int = DEFAULT_BRIDGE_PORT

    @property
    def webui_url(self) -> str:
        return self.api_url

    @property
    def bridge_base_url(self) -> str:
        return f"http://{self.bridge_host}:{self.bridge_port}".rstrip("/")


class Tagger:
    def __init__(self) -> None:
        self.session: ort.InferenceSession | None = None
        self.input_name = ""
        self.input_size = 448
        self.tags: list[dict[str, Any]] = []

    def ensure_loaded(self) -> None:
        with MODEL_LOCK:
            ensure_model_files()
            if self.session is None:
                providers = ["CPUExecutionProvider"]
                self.session = ort.InferenceSession(str(MODELS_DIR / MODEL_FILE), providers=providers)
                input_meta = self.session.get_inputs()[0]
                self.input_name = input_meta.name
                shape = input_meta.shape
                if len(shape) == 4 and isinstance(shape[1], int) and shape[1] > 0:
                    self.input_size = int(shape[1])
                elif len(shape) == 4 and isinstance(shape[2], int) and shape[2] > 0:
                    self.input_size = int(shape[2])
                self.tags = load_tags(MODELS_DIR / TAGS_FILE)

    def interrogate(self, image_bytes: bytes, settings: Settings) -> dict[str, Any]:
        self.ensure_loaded()
        assert self.session is not None

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        tensor = prepare_image(image, self.input_size)
        outputs = self.session.run(None, {self.input_name: tensor})
        scores = np.asarray(outputs[0])[0]

        general: list[tuple[str, float]] = []
        characters: list[tuple[str, float]] = []
        ratings: list[tuple[str, float]] = []

        for tag, score in zip(self.tags, scores, strict=False):
            name = str(tag.get("name") or "").strip()
            category = int(tag.get("category") or 0)
            if not name:
                continue
            value = float(score)
            clean_name = name.replace("_", " ")
            if category == 9:
                ratings.append((clean_name, value))
            elif category == 4:
                if value >= settings.character_threshold:
                    characters.append((clean_name, value))
            else:
                if value >= settings.general_threshold:
                    general.append((clean_name, value))

        general.sort(key=lambda item: item[1], reverse=True)
        characters.sort(key=lambda item: item[1], reverse=True)
        ratings.sort(key=lambda item: item[1], reverse=True)

        selected = characters + general
        selected = selected[: max(1, settings.max_tags)]
        return {
            "tags": [name for name, _score in selected],
            "tagScores": [{"name": name, "score": round(score, 4)} for name, score in selected],
            "rating": ratings[0][0] if ratings else "",
            "ratingScores": [{"name": name, "score": round(score, 4)} for name, score in ratings[:4]],
        }


TAGGER = Tagger()
JOB_LOCK = threading.Lock()


def _transformers_version_tuple(version: str) -> tuple[int, int, int]:
    parts: list[int] = []
    for piece in version.split(".")[:3]:
        digits = ""
        for char in piece:
            if char.isdigit():
                digits += char
            else:
                break
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[0], parts[1], parts[2]


def assert_florence_transformers_compatible() -> None:
    import transformers

    major, minor, patch = _transformers_version_tuple(transformers.__version__)
    if (major, minor, patch) >= (4, 50, 0):
        raise RuntimeError(
            f"transformers {transformers.__version__} は Florence と非互換です。"
            ' ".venv\\Scripts\\python.exe" -m pip install "transformers>=4.41.2,<4.50" を実行し、'
            " .venv\\.florence-installed-v3 が無い状態で start.bat を再実行してください。"
        )


def assert_florence_packages() -> None:
    missing: list[str] = []
    for name in ("timm", "einops"):
        try:
            __import__(name)
        except ImportError:
            missing.append(name)
    if missing:
        joined = ", ".join(missing)
        raise RuntimeError(
            f"Florence に必要なパッケージがありません: {joined}。"
            " .venv\\.florence-installed-v3 を削除して start.bat を再実行するか、"
            " .venv\\Scripts\\python.exe -m pip install -r requirements-florence.txt を実行してください。"
        )


class FlorenceCaptioner:
    def __init__(self) -> None:
        self.model_id = ""
        self.load_key = ""
        self.processor = None
        self.model = None
        self.torch = None
        self.device = "cpu"

    def ensure_loaded(self, settings: Settings) -> None:
        load_key = "|".join([settings.florence_model, settings.florence_precision, settings.florence_attention])
        if self.model is not None and self.load_key == load_key:
            return
        try:
            import torch
            from transformers import AutoModelForCausalLM, AutoProcessor

            assert_florence_transformers_compatible()
            assert_florence_packages()
        except ImportError as exc:
            raise RuntimeError(
                "Florence依存関係がありません。WD Tag Sample Viewer でFlorenceをONにしたあと、start.batを再起動してください。"
            ) from exc

        self.torch = torch
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        precision = settings.florence_precision.lower()
        if self.device == "cuda" and precision in {"bf16", "bfloat16"}:
            dtype = torch.bfloat16
        elif self.device == "cuda" and precision in {"fp16", "float16"}:
            dtype = torch.float16
        else:
            dtype = torch.float32

        model_kwargs: dict[str, Any] = {"torch_dtype": dtype, "trust_remote_code": True}
        if settings.florence_attention.strip():
            model_kwargs["attn_implementation"] = settings.florence_attention.strip()

        print(f"Loading Florence model: {settings.florence_model} ({self.device}, {precision})")
        try:
            self.processor = AutoProcessor.from_pretrained(settings.florence_model, trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                settings.florence_model,
                **model_kwargs,
            ).to(self.device)
        except Exception as exc:
            message = str(exc)
            if "timm" in message or "einops" in message:
                raise RuntimeError(
                    "Florence に timm / einops が必要です。"
                    " .venv\\.florence-installed-v3 を削除して start.bat を再実行するか、"
                    " pip install timm einops を実行してください。"
                ) from exc
            raise
        self.model_id = settings.florence_model
        self.load_key = load_key

    def caption(self, image_bytes: bytes, settings: Settings) -> str:
        self.ensure_loaded(settings)
        assert self.processor is not None
        assert self.model is not None
        assert self.torch is not None

        image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
        task = normalize_florence_task(settings.florence_task)
        inputs = self.processor(text=task, images=image, return_tensors="pt")
        inputs = {key: value.to(self.device) for key, value in inputs.items()}
        with self.torch.no_grad():
            generated_ids = self.model.generate(
                input_ids=inputs["input_ids"],
                pixel_values=inputs["pixel_values"],
                max_new_tokens=settings.florence_max_new_tokens,
                num_beams=settings.florence_num_beams,
                do_sample=settings.florence_do_sample,
            )
        generated_text = self.processor.batch_decode(generated_ids, skip_special_tokens=False)[0]
        parsed = self.processor.post_process_generation(
            generated_text,
            task=task,
            image_size=(image.width, image.height),
        )
        value = parsed.get(task) if isinstance(parsed, dict) else parsed
        if isinstance(value, dict):
            return " ".join(str(v).strip() for v in value.values() if str(v).strip())
        if isinstance(value, list):
            return " ".join(str(v).strip() for v in value if str(v).strip())
        return str(value or "").strip()

    def unload(self) -> None:
        self.model = None
        self.processor = None
        self.load_key = ""
        self.model_id = ""
        if self.torch is not None and getattr(self.torch, "cuda", None) and self.torch.cuda.is_available():
            self.torch.cuda.empty_cache()
        gc.collect()


FLORENCE = FlorenceCaptioner()


def ensure_model_files() -> None:
    with MODEL_LOCK:
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        for filename in (MODEL_FILE, TAGS_FILE):
            path = MODELS_DIR / filename
            if path.exists() and path.stat().st_size > 0:
                continue
            url = f"{MODEL_REPO_URL}/{filename}"
            print(f"Downloading {filename}...")
            download_file(url, path)


def _is_file_lock_error(exc: BaseException) -> bool:
    if isinstance(exc, PermissionError):
        return True
    if isinstance(exc, OSError) and getattr(exc, "winerror", None) == 32:
        return True
    return False


def atomic_replace(src: Path, dest: Path, *, attempts: int = 5, delay: float = 0.5) -> None:
    last_exc: BaseException | None = None
    for attempt in range(attempts):
        try:
            src.replace(dest)
            return
        except (PermissionError, OSError) as exc:
            if not _is_file_lock_error(exc):
                raise
            last_exc = exc
            if attempt + 1 < attempts:
                time.sleep(delay)
    model_dir = dest.parent
    raise RuntimeError(
        f"モデルファイルを {dest.name} に配置できませんでした（別プロセスがファイルを使用中です）。"
        " bridge（start.bat）を二重起動していないか確認してください。"
        f" 解決しない場合は bridge を終了し、{model_dir} の {dest.name}.tmp を削除してから"
        " bridge を1つだけ再起動してください。"
    ) from last_exc


def download_file(url: str, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=60) as response:
        total = int(response.headers.get("Content-Length") or 0)
        done = 0
        started = time.time()
        with tmp.open("wb") as fh:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                fh.write(chunk)
                done += len(chunk)
                if total:
                    pct = done / total * 100
                    elapsed = max(0.1, time.time() - started)
                    speed = done / 1024 / 1024 / elapsed
                    print(f"  {pct:5.1f}% {speed:4.1f} MB/s", end="\r")
    print()
    atomic_replace(tmp, path)


def safe_job_id() -> str:
    import uuid

    stamp = time.strftime("%Y%m%d_%H%M%S")
    return f"job_{stamp}_{uuid.uuid4().hex[:8]}"


def job_dir(job_id: str) -> Path:
    safe = "".join(ch for ch in job_id if ch.isalnum() or ch in {"_", "-"})
    if not safe:
        raise RuntimeError("invalid job id")
    path = (JOBS_DIR / safe).resolve()
    if not str(path).startswith(str(JOBS_DIR.resolve())):
        raise RuntimeError("invalid job path")
    return path


def job_meta_path(job_id: str) -> Path:
    return job_dir(job_id) / "job.json"


def open_job_folder(job_id: str) -> dict[str, Any]:
    directory = job_dir(job_id)
    if not directory.exists() or not directory.is_dir():
        raise RuntimeError("フォルダが見つかりません")
    if sys.platform == "win32":
        subprocess.Popen(["explorer.exe", str(directory)])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(directory)])
    else:
        subprocess.Popen(["xdg-open", str(directory)])
    return {"ok": True, "dir": str(directory)}


def read_job(job_id: str) -> dict[str, Any]:
    path = job_meta_path(job_id)
    if not path.exists():
        raise RuntimeError("job not found")
    return json.loads(path.read_text(encoding="utf-8"))


def write_job(job: dict[str, Any]) -> dict[str, Any]:
    with JOB_LOCK:
        jid = str(job["id"])
        directory = job_dir(jid)
        directory.mkdir(parents=True, exist_ok=True)
        job["updatedAt"] = time.time()
        job_meta_path(jid).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job


def update_job(job_id: str, **updates: Any) -> dict[str, Any]:
    with JOB_LOCK:
        job = read_job(job_id)
        job.update(updates)
        job["updatedAt"] = time.time()
        job_meta_path(job_id).write_text(json.dumps(job, ensure_ascii=False, indent=2), encoding="utf-8")
        return job


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    jid = str(job.get("id") or "")
    return {
        "id": jid,
        "state": job.get("state") or "unknown",
        "message": job.get("message") or "",
        "createdAt": job.get("createdAt") or 0,
        "updatedAt": job.get("updatedAt") or 0,
        "prompt": job.get("prompt") or "",
        "translatedPrompt": job.get("translatedPrompt") or "",
        "caption": job.get("caption") or "",
        "tags": job.get("tags") or [],
        "tagScores": job.get("tagScores") or [],
        "rating": job.get("rating") or "",
        "tagsOnly": bool(job.get("tagsOnly")),
        "input": f"/api/jobs/{jid}/files/input.png" if jid else "",
        "outputs": [f"/api/jobs/{jid}/files/{name}" for name in job.get("outputs") or []],
        "dir": str(job_dir(jid)) if jid else "",
        "webuiUrl": job.get("apiUrl") or job.get("webuiUrl") or "",
        "backend": job.get("backend") or "",
        "error": job.get("error") or "",
    }


def default_preferences() -> dict[str, Any]:
    return {"generateSample": True, "florenceEnabled": False}


def load_preferences() -> dict[str, Any]:
    defaults = default_preferences()
    if not PREFERENCES_PATH.exists():
        return dict(defaults)
    try:
        data = json.loads(PREFERENCES_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return dict(defaults)
    return {
        "generateSample": as_bool(str(data.get("generateSample")), defaults["generateSample"]),
        "florenceEnabled": as_bool(str(data.get("florenceEnabled")), defaults["florenceEnabled"]),
    }


def save_preferences(updates: dict[str, Any]) -> dict[str, Any]:
    with PREFERENCES_LOCK:
        current = load_preferences()
        if "generateSample" in updates:
            current["generateSample"] = as_bool(str(updates["generateSample"]), True)
        if "florenceEnabled" in updates:
            current["florenceEnabled"] = as_bool(str(updates["florenceEnabled"]), False)
            if not current["florenceEnabled"]:
                FLORENCE.unload()
        PREFERENCES_PATH.write_text(json.dumps(current, ensure_ascii=False, indent=2), encoding="utf-8")
        return current


def resolve_generate_sample(explicit: Any | None = None) -> bool:
    if explicit is not None:
        return as_bool(str(explicit), True)
    return load_preferences()["generateSample"]


def resolve_florence_enabled() -> bool:
    return load_preferences()["florenceEnabled"]


def list_jobs(limit: int = 100) -> list[dict[str, Any]]:
    JOBS_DIR.mkdir(parents=True, exist_ok=True)
    items: list[dict[str, Any]] = []
    for meta in JOBS_DIR.glob("*/job.json"):
        try:
            items.append(public_job(json.loads(meta.read_text(encoding="utf-8"))))
        except Exception:
            continue
    items.sort(key=lambda item: item.get("createdAt") or 0, reverse=True)
    return items[:limit]


def save_binary_outputs(job_id: str, images: list[bytes]) -> list[str]:
    names: list[str] = []
    directory = job_dir(job_id)
    for index, data in enumerate(images):
        name = f"output_{index + 1}.png"
        (directory / name).write_bytes(data)
        names.append(name)
    return names


def save_base64_outputs(job_id: str, images: list[str]) -> list[str]:
    names: list[str] = []
    directory = job_dir(job_id)
    for index, raw in enumerate(images):
        payload = str(raw)
        if "," in payload:
            payload = payload.split(",", 1)[1]
        data = base64.b64decode(payload)
        name = f"output_{index + 1}.png"
        (directory / name).write_bytes(data)
        names.append(name)
    return names


def process_job(job_id: str) -> None:
    try:
        job = update_job(job_id, state="running", message="WD14タグを抽出しています")
        settings = load_settings()
        tags_only = bool(job.get("tagsOnly"))
        input_path = job_dir(job_id) / "input.png"
        image_bytes = input_path.read_bytes()
        tag_result = TAGGER.interrogate(image_bytes, settings)
        caption = ""
        if resolve_florence_enabled() and not tags_only:
            update_job(job_id, message="Florence自然文を生成しています")
            caption = FLORENCE.caption(image_bytes, settings)
        translated_prompt = translate_prompt("", tag_result["tags"], caption=caption)
        update_job(
            job_id,
            tags=tag_result["tags"],
            tagScores=tag_result["tagScores"],
            rating=tag_result["rating"],
            ratingScores=tag_result["ratingScores"],
            caption=caption,
            translatedPrompt=translated_prompt,
            backend=settings.backend,
            apiUrl=settings.api_url,
        )
        if tags_only:
            update_job(job_id, state="done", message="タグ抽出完了")
            return
        generation_prompt = build_prompt(tag_result["tags"], caption, settings)
        if settings.backend == "comfyui":
            update_job(job_id, message="ComfyUIでサンプル生成中です")
            workflow_path = (ROOT / settings.workflow).resolve()
            if not workflow_path.exists():
                raise RuntimeError(f"workflow が見つかりません: {workflow_path}")
            images = generate_txt2img(
                settings.api_url,
                workflow_path,
                positive=generation_prompt,
                negative=settings.negative_prompt,
                seed=None,
                node_positive=settings.node_positive,
                node_negative=settings.node_negative,
                node_ksampler=settings.node_ksampler,
            )
            output_names = save_binary_outputs(job_id, images)
        else:
            update_job(job_id, message="txt2imgでサンプル生成中です")
            generated = call_webui_txt2img(settings, generation_prompt)
            output_names = save_base64_outputs(job_id, generated.get("images") or [])
        update_job(job_id, state="done", message="完了", outputs=output_names)
    except Exception as exc:
        update_job(job_id, state="error", message=str(exc), error=str(exc))


def create_job_from_image(
    image_bytes: bytes,
    source: str = "",
    generate_sample: bool | None = None,
) -> dict[str, Any]:
    if not image_bytes:
        raise RuntimeError("画像データが空です")
    image = Image.open(io.BytesIO(image_bytes)).convert("RGB")
    jid = safe_job_id()
    directory = job_dir(jid)
    directory.mkdir(parents=True, exist_ok=True)
    image.save(directory / "input.png")
    generate = resolve_generate_sample(generate_sample)
    job = {
        "id": jid,
        "state": "queued",
        "message": "待機中",
        "createdAt": time.time(),
        "updatedAt": time.time(),
        "source": source,
        "tagsOnly": not generate,
        "outputs": [],
    }
    write_job(job)
    threading.Thread(target=process_job, args=(jid,), daemon=True).start()
    return public_job(job)


def load_tags(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh)
        tags: list[dict[str, Any]] = []
        for row in reader:
            category_raw = row.get("category") or row.get("category_id") or 0
            try:
                category = int(category_raw)
            except ValueError:
                category = 0
            tags.append({"name": row.get("name") or "", "category": category})
        return tags


def prepare_image(image: Image.Image, size: int) -> np.ndarray:
    width, height = image.size
    side = max(width, height)
    canvas = Image.new("RGB", (side, side), (255, 255, 255))
    canvas.paste(image, ((side - width) // 2, (side - height) // 2))
    canvas = canvas.resize((size, size), Image.Resampling.LANCZOS)
    array = np.asarray(canvas, dtype=np.float32)
    array = array[:, :, ::-1]
    return np.expand_dims(array, axis=0)


def parse_bridge_endpoint(values: dict[str, str]) -> tuple[str, int]:
    bridge_url = (values.get("bridge_url") or "").strip().rstrip("/")
    if bridge_url:
        if not bridge_url.lower().startswith(("http://", "https://")):
            bridge_url = "http://" + bridge_url
        parsed = urllib.parse.urlparse(bridge_url)
        host = parsed.hostname or DEFAULT_BRIDGE_HOST
        if not parsed.port:
            port = 443 if parsed.scheme == "https" else 80
        else:
            port = parsed.port
        return host, clamp(port, 1, 65535)

    host = (values.get("bridge_host") or DEFAULT_BRIDGE_HOST).strip() or DEFAULT_BRIDGE_HOST
    port = clamp(as_int(values.get("bridge_port"), DEFAULT_BRIDGE_PORT), 1, 65535)
    return host, port


def sync_bridge_config(settings: Settings | None = None) -> str:
    settings = settings or load_settings()
    BRIDGE_CONFIG_JS_PATH.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "// Auto-generated from config.txt on bridge start. Do not edit.\n"
        f'const BRIDGE_BASE_URL = "{settings.bridge_base_url}";\n'
    )
    BRIDGE_CONFIG_JS_PATH.write_text(content, encoding="utf-8")
    return settings.bridge_base_url


def load_settings() -> Settings:
    if not CONFIG_PATH.exists():
        raise RuntimeError("config.txt が見つかりません")

    url = ""
    values: dict[str, str] = {}
    for raw_line in CONFIG_PATH.read_text(encoding="utf-8-sig").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        elif not url:
            url = line.rstrip("/")

    if values.get("api_url"):
        url = values.get("api_url")
    if not url:
        raise RuntimeError("config.txt に api_url を書いてください（1行目でも backend 行でも可）")
    if not url.lower().startswith(("http://", "https://")):
        url = "http://" + url

    backend = (values.get("backend") or "forge").strip().lower()
    if backend not in {"forge", "comfyui"}:
        raise RuntimeError("backend は forge または comfyui を指定してください")

    bridge_host, bridge_port = parse_bridge_endpoint(values)

    return Settings(
        backend=backend,
        api_url=url.rstrip("/"),
        bridge_host=bridge_host,
        bridge_port=bridge_port,
        general_threshold=as_float(values.get("general_threshold"), 0.35),
        character_threshold=as_float(values.get("character_threshold"), 0.85),
        max_tags=clamp(as_int(values.get("max_tags"), 80), 1, 200),
        florence_model=values.get("florence_model") or "thwri/CogFlorence-2.2-Large",
        florence_precision=values.get("florence_precision") or "bf16",
        florence_attention=values.get("florence_attention") or "sdpa",
        florence_task=values.get("florence_task") or "<MORE_DETAILED_CAPTION>",
        florence_max_new_tokens=clamp(as_int(values.get("florence_max_new_tokens"), 1024), 32, 4096),
        florence_num_beams=clamp(as_int(values.get("florence_num_beams"), 5), 1, 16),
        florence_do_sample=as_bool(values.get("florence_do_sample"), False),
        prompt_prefix=values.get("prompt_prefix") or "",
        prompt_suffix=values.get("prompt_suffix") or "",
        negative_prompt=values.get("negative_prompt") or "",
        workflow=values.get("workflow") or "workflows/txt2img_sample.json",
        node_positive=values.get("node_positive") or "CLIP Text Encode Positive",
        node_negative=values.get("node_negative") or "CLIP Text Encode Negative",
        node_ksampler=values.get("node_ksampler") or "KSampler",
    )


def as_int(value: str | None, default: int) -> int:
    try:
        return int(str(value or "").strip())
    except ValueError:
        return default


def as_float(value: str | None, default: float) -> float:
    try:
        return float(str(value or "").strip())
    except ValueError:
        return default


def as_bool(value: str | None, default: bool) -> bool:
    text = str(value or "").strip().lower()
    if text in {"1", "true", "yes", "on"}:
        return True
    if text in {"0", "false", "no", "off"}:
        return False
    return default


def clamp(value: int, lower: int, upper: int) -> int:
    return max(lower, min(upper, value))


def normalize_florence_task(value: str) -> str:
    task = str(value or "").strip()
    if not task:
        return "<MORE_DETAILED_CAPTION>"
    if task.startswith("<") and task.endswith(">"):
        return task
    return f"<{task.upper()}>"


def build_prompt(tags: list[str], caption: str, settings: Settings) -> str:
    parts = []
    if settings.prompt_prefix.strip():
        parts.append(settings.prompt_prefix.strip())
    parts.extend(tags)
    if caption.strip():
        parts.append(caption.strip())
    if settings.prompt_suffix.strip():
        parts.append(settings.prompt_suffix.strip())
    return ", ".join(part for part in parts if part)


def call_webui_txt2img(settings: Settings, prompt: str) -> dict[str, Any]:
    payload = {
        "prompt": prompt,
        "negative_prompt": settings.negative_prompt,
        "n_iter": 1,
        "save_images": False,
        "send_images": True,
    }
    return http_json(f"{settings.webui_url}/sdapi/v1/txt2img", "POST", payload, timeout=300)


def check_backend(settings: Settings) -> dict[str, Any]:
    if settings.backend == "comfyui":
        return http_json(f"{settings.api_url}/system_stats", "GET", None, timeout=10)
    return http_json(f"{settings.api_url}/sdapi/v1/options", "GET", None, timeout=10)


def check_webui(settings: Settings) -> dict[str, Any]:
    return check_backend(settings)


def http_json(url: str, method: str, payload: dict[str, Any] | None, timeout: int) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, method=method)
    request.add_header("Accept", "application/json")
    if body is not None:
        request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"Forge/ReForge API error {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Forge/ReForgeに接続できません: {exc.reason}") from exc

    try:
        return json.loads(data.decode("utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("Forge/ReForge API がJSONを返しませんでした") from exc


def parse_multipart(body: bytes, content_type: str) -> dict[str, tuple[str, bytes, str]]:
    header = f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
    message = BytesParser(policy=email_policy).parsebytes(header + body)
    fields: dict[str, tuple[str, bytes, str]] = {}
    if not message.is_multipart():
        return fields
    for part in message.iter_parts():
        name = part.get_param("name", header="content-disposition")
        filename = part.get_filename() or ""
        part_type = part.get_content_type() or "application/octet-stream"
        data = part.get_payload(decode=True) or b""
        if name:
            fields[name] = (filename, data, part_type)
    return fields


def json_response(handler: BaseHTTPRequestHandler, status: int, payload: dict[str, Any]) -> None:
    blob = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    handler.send_header("Access-Control-Allow-Headers", "Content-Type")
    handler.end_headers()
    handler.wfile.write(blob)


def bytes_response(handler: BaseHTTPRequestHandler, status: int, blob: bytes, content_type: str) -> None:
    handler.send_response(status)
    handler.send_header("Content-Type", content_type)
    handler.send_header("Content-Length", str(len(blob)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(blob)


APP_HTML = r"""<!doctype html>
<html lang="ja">
  <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>WD Tag Sample Viewer</title>
    <style>
      :root { color-scheme: dark; }
      body { margin: 0; background: #15191f; color: #e8eef7; font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
      header { align-items: center; border-bottom: 1px solid #2b3440; display: flex; gap: 16px; padding: 10px 16px; }
      .header-left { align-items: center; display: flex; flex: 1; gap: 16px; min-width: 0; }
      h1 { font-size: 22px; margin: 0; white-space: nowrap; }
      .status { color: #9db3ca; flex: 1; font-size: 13px; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
      .header-actions { align-items: center; display: flex; flex-shrink: 0; gap: 16px; margin-left: auto; }
      .backend-status { align-items: center; cursor: default; display: flex; gap: 8px; font-size: 13px; user-select: none; }
      .backend-dot { border-radius: 50%; flex-shrink: 0; height: 8px; width: 8px; }
      .backend-status.checking .backend-dot { animation: backend-pulse 1s ease-in-out infinite; background: #f8d27a; }
      .backend-status.connected .backend-dot { background: #5ee8c7; }
      .backend-status.disconnected .backend-dot { background: #ff9a9a; }
      .backend-label { color: #9db3ca; }
      .backend-state { font-weight: 600; }
      .backend-status.checking .backend-state { color: #f8d27a; }
      .backend-status.connected .backend-state { color: #5ee8c7; }
      .backend-status.disconnected .backend-state { color: #ff9a9a; }
      @keyframes backend-pulse { 0%, 100% { opacity: 1; } 50% { opacity: 0.35; } }
      button { background: #263140; border: 1px solid #3a4656; border-radius: 6px; color: #fff; cursor: pointer; font-size: 14px; padding: 8px 12px; }
      button:disabled { cursor: wait; opacity: 0.65; }
      button:hover { background: #334155; }
      .switch-row { align-items: center; display: flex; flex-shrink: 0; gap: 8px; }
      .switch-row label { color: #abc0d5; cursor: pointer; font-size: 13px; user-select: none; }
      .switch { appearance: none; background: #344252; border-radius: 999px; cursor: pointer; height: 22px; position: relative; transition: background 0.15s; width: 40px; }
      .switch::after { background: #fff; border-radius: 50%; content: ""; height: 16px; left: 3px; position: absolute; top: 3px; transition: transform 0.15s; width: 16px; }
      .switch:checked { background: #2f855a; }
      .switch:checked::after { transform: translateX(18px); }
      main { display: grid; gap: 12px; padding: 14px 16px 30px; }
      .drop { align-items: center; border: 1px dashed #344252; border-radius: 8px; display: grid; gap: 8px; grid-template-columns: 1fr minmax(260px, 1.4fr) auto; padding: 12px; }
      .drop.drag { background: #202936; border-color: #75b8ff; }
      .drop strong { display: block; font-size: 14px; }
      .drop span { color: #abc0d5; font-size: 12px; }
      input { background: #10141a; border: 1px solid #344252; border-radius: 6px; color: #e8eef7; font-size: 14px; padding: 9px 10px; }
      .jobs { display: grid; gap: 10px; }
      .job { background: #20252c; border: 1px solid #323b48; border-radius: 8px; display: grid; gap: 10px; padding: 12px; }
      .job-head { align-items: center; display: flex; gap: 12px; }
      .job-title { font-weight: 700; }
      .time { color: #9db3ca; font-size: 12px; }
      .pill { border-radius: 999px; font-size: 12px; margin-left: auto; padding: 5px 9px; }
      .queued { background: #3b2f14; color: #f8d27a; }
      .running { background: #14334d; color: #8ed1ff; }
      .done { background: #063b32; color: #5ee8c7; }
      .error { background: #4b1717; color: #ff9a9a; }
      .job-body { display: grid; gap: 10px; grid-template-columns: 300px 1fr; }
      .images-col { display: grid; gap: 6px; align-content: start; }
      .images { display: grid; gap: 8px; grid-template-columns: 140px 140px; align-content: start; }
      .images img { background: #0f1318; border: 1px solid #3a4656; border-radius: 6px; cursor: zoom-in; max-height: 220px; max-width: 100%; object-fit: contain; }
      .open-folder { font-size: 11px; justify-self: start; padding: 3px 8px; }
      .prompt { background: #0f1318; border: 1px solid #3a4656; border-radius: 6px; color: #f2f6fb; font-family: ui-monospace, SFMono-Regular, Consolas, monospace; font-size: 12px; line-height: 1.45; min-height: 120px; overflow: auto; padding: 10px; white-space: pre-wrap; word-break: break-word; }
      .prompt.translated { background: #12161b; color: #d8dee9; min-height: 80px; margin-top: 8px; }
      .tags-only { background: #0f1318; border: 1px solid #3a4656; border-radius: 6px; color: #d7e8ff; font-size: 13px; line-height: 1.55; min-height: 80px; overflow: auto; padding: 10px; white-space: pre-wrap; word-break: break-word; }
      .tag-meta { color: #9db3ca; font-size: 12px; margin-bottom: 6px; }
      .actions { display: flex; gap: 8px; justify-content: flex-end; }
      .empty { color: #9db3ca; padding: 24px; text-align: center; }
      .preview { align-items: center; background: rgba(0, 0, 0, 0.78); display: none; inset: 0; justify-content: center; padding: 24px; position: fixed; z-index: 20; }
      .preview.open { display: flex; }
      .preview img { background: #0f1318; border: 1px solid #4b5563; border-radius: 8px; box-shadow: 0 24px 80px rgba(0, 0, 0, 0.48); max-height: calc(100vh - 64px); max-width: calc(100vw - 64px); object-fit: contain; }
      .preview button { position: fixed; right: 20px; top: 18px; }
      @media (max-width: 820px) {
        .drop { grid-template-columns: 1fr; }
        .job-body { grid-template-columns: 1fr; }
        .images { grid-template-columns: repeat(2, minmax(120px, 1fr)); }
      }
    </style>
  </head>
  <body>
    <header>
      <div class="header-left">
        <h1>WD Tag Sample Viewer</h1>
        <div id="status" class="status">起動中</div>
      </div>
      <div class="header-actions">
        <div class="switch-row">
          <label for="generateSample">サンプル生成</label>
          <input id="generateSample" class="switch" type="checkbox" checked>
        </div>
        <div class="switch-row">
          <label for="florenceEnabled" title="初回のみモデル読込で遅くなります">Florence自然文</label>
          <input id="florenceEnabled" class="switch" type="checkbox">
        </div>
        <div id="backendStatus" class="backend-status checking" title="">
          <span class="backend-dot" aria-hidden="true"></span>
          <span class="backend-label">Backend</span>
          <span class="backend-state">接続中</span>
        </div>
        <button id="refresh" type="button">更新</button>
      </div>
    </header>
    <main>
      <section id="drop" class="drop">
        <div>
          <strong>Drop / Paste</strong>
          <span>画像ファイル、クリップボード画像、画像URL</span>
        </div>
        <input id="url" type="url" placeholder="画像URLを貼り付け">
        <button id="send" type="button">送信</button>
      </section>
      <section id="jobs" class="jobs"></section>
    </main>
    <div id="preview" class="preview" role="dialog" aria-label="画像プレビュー">
      <button id="previewClose" type="button">閉じる</button>
      <img id="previewImage" alt="preview">
    </div>
    <script>
      const jobsEl = document.getElementById("jobs");
      const statusEl = document.getElementById("status");
      const backendStatusEl = document.getElementById("backendStatus");
      const backendStateEl = backendStatusEl.querySelector(".backend-state");
      const refreshEl = document.getElementById("refresh");
      const dropEl = document.getElementById("drop");
      const urlEl = document.getElementById("url");
      const previewEl = document.getElementById("preview");
      const previewImageEl = document.getElementById("previewImage");
      const generateSampleEl = document.getElementById("generateSample");
      const florenceEnabledEl = document.getElementById("florenceEnabled");
      let isSelectingText = false;
      const JOBS_POLL_MS = 2500;
      const BACKEND_POLL_MS = 15000;
      let jobsTimer = null;
      let backendTimer = null;

      refreshEl.onclick = refreshAll;
      generateSampleEl.addEventListener("change", async () => {
        try {
          await fetchJson("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ generateSample: generateSampleEl.checked })
          });
        } catch (error) {
          statusEl.textContent = error.message;
        }
      });
      florenceEnabledEl.addEventListener("change", async () => {
        try {
          await fetchJson("/api/settings", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ florenceEnabled: florenceEnabledEl.checked })
          });
        } catch (error) {
          statusEl.textContent = error.message;
        }
      });
      document.getElementById("send").onclick = () => {
        const url = urlEl.value.trim();
        if (url) submitUrl(url);
      };

      dropEl.addEventListener("dragover", (event) => {
        event.preventDefault();
        dropEl.classList.add("drag");
      });
      dropEl.addEventListener("dragleave", () => dropEl.classList.remove("drag"));
      dropEl.addEventListener("drop", async (event) => {
        event.preventDefault();
        dropEl.classList.remove("drag");
        const file = [...event.dataTransfer.files].find((item) => item.type.startsWith("image/"));
        if (file) await submitFile(file);
      });
      document.addEventListener("paste", async (event) => {
        const file = [...event.clipboardData.files].find((item) => item.type.startsWith("image/"));
        if (file) {
          await submitFile(file);
          return;
        }
        const text = event.clipboardData.getData("text/plain").trim();
        if (/^https?:\/\//i.test(text)) {
          urlEl.value = text;
          await submitUrl(text);
        }
      });
      document.getElementById("previewClose").onclick = closePreview;
      previewEl.addEventListener("click", (event) => {
        if (event.target === previewEl) closePreview();
      });
      document.addEventListener("keydown", (event) => {
        if (event.key === "Escape") closePreview();
      });
      document.addEventListener("selectionchange", () => {
        const selection = window.getSelection();
        const anchor = selection && selection.anchorNode;
        const node = anchor && (anchor.nodeType === Node.TEXT_NODE ? anchor.parentElement : anchor);
        isSelectingText = !!selection && !selection.isCollapsed && !!node?.closest?.(".prompt, .tags-only, .translated");
      });

      async function submitFile(file) {
        const form = new FormData();
        form.append("image", file, file.name || "pasted.png");
        form.append("generateSample", generateSampleEl.checked ? "true" : "false");
        await fetchJson("/api/jobs", { method: "POST", body: form });
        await loadJobs();
      }

      async function submitUrl(url) {
        await fetchJson("/api/jobs", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ imageUrl: url, generateSample: generateSampleEl.checked })
        });
        urlEl.value = "";
        await loadJobs();
      }

      async function loadSettings() {
        try {
          const data = await fetchJson("/api/settings");
          generateSampleEl.checked = data.generateSample !== false;
          florenceEnabledEl.checked = data.florenceEnabled === true;
        } catch (_error) {
          generateSampleEl.checked = true;
          florenceEnabledEl.checked = false;
        }
      }

      async function refreshAll() {
        refreshEl.disabled = true;
        try {
          await Promise.all([loadBackendHealth(), loadJobs()]);
        } finally {
          refreshEl.disabled = false;
        }
      }

      async function loadBackendHealth(silent = false) {
        if (!silent) {
          setBackendStatus("checking", "接続中", "Forge / ComfyUI への接続を確認しています");
        }
        try {
          const data = await fetchJson("/api/health");
          const backendName = data.backend === "comfyui" ? "ComfyUI" : "Forge";
          const key = data.backend === "comfyui" ? "comfyui" : "webui";
          const info = data[key] || {};
          if (info.ok) {
            let detail = data.apiUrl || "";
            if (data.backend !== "comfyui" && info.sd_model_checkpoint) {
              detail = detail ? `${detail}\n${info.sd_model_checkpoint}` : info.sd_model_checkpoint;
            }
            setBackendStatus("connected", "接続済み", detail || `${backendName} に接続できました`);
            backendStatusEl.querySelector(".backend-label").textContent = backendName;
          } else {
            setBackendStatus("disconnected", "未接続", info.error || `${backendName} に接続できません`);
            backendStatusEl.querySelector(".backend-label").textContent = backendName;
          }
        } catch (error) {
          setBackendStatus("disconnected", "未接続", error.message || "接続確認に失敗しました");
          backendStatusEl.querySelector(".backend-label").textContent = "Backend";
        }
      }

      function setBackendStatus(state, text, title) {
        backendStatusEl.classList.remove("checking", "connected", "disconnected");
        backendStatusEl.classList.add(state);
        backendStateEl.textContent = text;
        backendStatusEl.title = title || "";
      }

      async function loadJobs() {
        try {
          const data = await fetchJson("/api/jobs");
          const items = data.items || [];
          updateTitle(items);
          statusEl.textContent = statusText(items);
          if (!isSelectingText) {
            renderJobs(items);
          }
        } catch (error) {
          statusEl.textContent = error.message;
        }
      }

      async function fetchJson(url, options) {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok || data.ok === false) throw new Error(data.error || response.statusText);
        return data;
      }

      function renderJobs(items) {
        if (!items.length) {
          jobsEl.innerHTML = '<div class="empty">まだジョブはありません</div>';
          return;
        }
        jobsEl.innerHTML = items.map(renderJob).join("");
        for (const button of jobsEl.querySelectorAll("[data-copy]")) {
          button.onclick = async () => {
            await navigator.clipboard.writeText(button.dataset.copy || "");
            const before = button.textContent;
            button.textContent = "コピーしました！";
            button.disabled = true;
            setTimeout(() => {
              button.textContent = before;
              button.disabled = false;
            }, 1200);
          };
        }
        for (const image of jobsEl.querySelectorAll("img[data-preview]")) {
          image.onclick = () => openPreview(image.currentSrc || image.src);
        }
        for (const button of jobsEl.querySelectorAll("[data-open-folder]")) {
          button.onclick = async () => {
            try {
              await fetchJson(`/api/jobs/${encodeURIComponent(button.dataset.openFolder)}/open-folder`, { method: "POST" });
            } catch (error) {
              statusEl.textContent = error.message || "フォルダを開けませんでした";
            }
          };
        }
      }

      function updateTitle(items) {
        const active = items.filter((item) => item.state === "queued" || item.state === "running").length;
        document.title = active > 0 ? `(${active}) WD Tag Sample Viewer` : "WD Tag Sample Viewer";
      }

      function statusText(items) {
        const queued = items.filter((item) => item.state === "queued").length;
        const running = items.filter((item) => item.state === "running").length;
        if (queued || running) {
          const parts = [];
          if (running) parts.push(`実行中 ${running}`);
          if (queued) parts.push(`待機 ${queued}`);
          return parts.join(" / ");
        }
        return "一覧を更新しました";
      }

      function renderJob(job) {
        const state = escapeHtml(job.state || "unknown");
        const tags = (job.tags || []).join(", ");
        const translated = job.translatedPrompt || "";
        const tagMeta = job.rating
          ? `Rating: ${escapeHtml(job.rating)}`
          : (job.tagsOnly ? "タグのみモード" : "");
        const outputs = (job.outputs || []).map((src) => `<img src="${escapeHtml(src)}" alt="output" data-preview="1">`).join("");
        const input = job.input ? `<img src="${escapeHtml(job.input)}" alt="input" data-preview="1">` : "";
        const mainContent = `
              ${tagMeta ? `<div class="tag-meta">${tagMeta}</div>` : ""}
              <div class="tags-only">${escapeHtml(tags || job.message || "タグ抽出中...")}</div>
              ${translated ? `<div class="prompt translated">${escapeHtml(translated)}</div>` : ""}
            `;
        const translationCopy = translated
          ? `<button data-copy="${escapeAttr(translated)}" type="button">翻訳をコピー</button>`
          : "";
        return `
          <article class="job" id="${escapeHtml(job.id)}">
            <div class="job-head">
              <div class="job-title">${escapeHtml(job.id)}</div>
              <div class="time">${formatTime(job.createdAt)}</div>
              <div class="pill ${state}">${state}</div>
            </div>
            <div class="job-body">
              <div class="images-col">
                <div class="images">${input}${outputs}</div>
                <button class="open-folder" data-open-folder="${escapeAttr(job.id)}" title="保存先のフォルダを開く" type="button">フォルダ</button>
              </div>
              <div>
                <div class="actions">
                  <button data-copy="${escapeAttr(tags)}" type="button">タグをコピー</button>
                  ${translationCopy}
                </div>
                ${mainContent}
              </div>
            </div>
          </article>
        `;
      }

      function formatTime(value) {
        if (!value) return "";
        return new Date(value * 1000).toLocaleString();
      }

      function openPreview(src) {
        previewImageEl.src = src;
        previewEl.classList.add("open");
      }

      function closePreview() {
        previewEl.classList.remove("open");
        previewImageEl.removeAttribute("src");
      }

      function escapeHtml(value) {
        return String(value).replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[char]));
      }

      function escapeAttr(value) {
        return escapeHtml(value).replace(/`/g, "&#96;");
      }

      function startPolling() {
        stopPolling();
        jobsTimer = setInterval(loadJobs, JOBS_POLL_MS);
        backendTimer = setInterval(() => loadBackendHealth(true), BACKEND_POLL_MS);
      }

      function stopPolling() {
        if (jobsTimer) clearInterval(jobsTimer);
        if (backendTimer) clearInterval(backendTimer);
        jobsTimer = null;
        backendTimer = null;
      }

      document.addEventListener("visibilitychange", () => {
        if (document.hidden) {
          stopPolling();
          return;
        }
        refreshAll();
        startPolling();
      });

      loadSettings();
      if (!document.hidden) {
        refreshAll();
        startPolling();
      }
    </script>
  </body>
</html>
"""


class Handler(BaseHTTPRequestHandler):
    server_version = "WDTagSampleBridge/0.2"

    def log_message(self, fmt: str, *args: Any) -> None:
        if self.command == "GET" and self.path.startswith("/api/jobs"):
            return
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def do_OPTIONS(self) -> None:
        json_response(self, 200, {"ok": True})

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/":
                bytes_response(self, 200, APP_HTML.encode("utf-8"), "text/html; charset=utf-8")
                return
            if parsed.path == "/api/jobs":
                json_response(self, 200, {"ok": True, "items": list_jobs()})
                return
            if parsed.path.startswith("/api/jobs/") and "/files/" in parsed.path:
                parts = parsed.path.split("/")
                job_id = parts[3] if len(parts) > 3 else ""
                filename = parts[5] if len(parts) > 5 else ""
                if filename not in {"input.png"} and not filename.startswith("output_"):
                    raise RuntimeError("invalid file")
                path = job_dir(job_id) / filename
                if not path.exists():
                    json_response(self, 404, {"ok": False, "error": "file not found"})
                    return
                bytes_response(self, 200, path.read_bytes(), "image/png")
                return
            if parsed.path == "/api/health":
                settings = load_settings()
                payload = {
                    "ok": True,
                    "bridge": "ready",
                    "backend": settings.backend,
                    "apiUrl": settings.api_url,
                    "bridgeUrl": settings.bridge_base_url,
                    "bridgeHost": settings.bridge_host,
                    "bridgePort": settings.bridge_port,
                    "backendConnected": False,
                }
                try:
                    backend_info = check_backend(settings)
                    payload["backendConnected"] = True
                    if settings.backend == "comfyui":
                        payload["comfyui"] = {"ok": True, "system": backend_info.get("system", {})}
                    else:
                        payload["webui"] = {
                            "ok": True,
                            "sd_model_checkpoint": backend_info.get("sd_model_checkpoint", ""),
                        }
                except Exception as exc:
                    key = "comfyui" if settings.backend == "comfyui" else "webui"
                    payload[key] = {"ok": False, "error": str(exc)}
                json_response(self, 200, payload)
                return
            if parsed.path == "/api/settings":
                prefs = load_preferences()
                settings = load_settings()
                json_response(
                    self,
                    200,
                    {
                        "ok": True,
                        **prefs,
                        "bridgeUrl": settings.bridge_base_url,
                        "bridgeHost": settings.bridge_host,
                        "bridgePort": settings.bridge_port,
                    },
                )
                return
            json_response(self, 404, {"ok": False, "error": "not found"})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})

    def do_POST(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path.rstrip("/") == "/api/settings":
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length)
                payload = json.loads(body.decode("utf-8")) if body else {}
                prefs = save_preferences(payload)
                json_response(self, 200, {"ok": True, **prefs})
                return
            if parsed.path.startswith("/api/jobs/") and parsed.path.rstrip("/").endswith("/open-folder"):
                parts = parsed.path.rstrip("/").split("/")
                if len(parts) >= 5 and parts[4] == "open-folder":
                    json_response(self, 200, open_job_folder(parts[3]))
                    return

            if parsed.path.rstrip("/") == "/api/jobs":
                length = int(self.headers.get("Content-Length") or 0)
                content_type = self.headers.get("Content-Type") or ""
                body = self.rfile.read(length)
                if "application/json" in content_type.lower():
                    payload = json.loads(body.decode("utf-8"))
                    image_url = str(payload.get("imageUrl") or "").strip()
                    if not image_url:
                        raise RuntimeError("imageUrl が空です")
                    generate_sample = payload.get("generateSample")
                    request = urllib.request.Request(image_url)
                    request.add_header("User-Agent", "Mozilla/5.0")
                    with urllib.request.urlopen(request, timeout=30) as response:
                        image_bytes = response.read()
                    job = create_job_from_image(image_bytes, image_url, generate_sample=generate_sample)
                else:
                    fields = parse_multipart(body, content_type)
                    image_item = fields.get("image")
                    if not image_item:
                        raise RuntimeError("image フィールドがありません")
                    filename, image_bytes, _mime = image_item
                    generate_field = fields.get("generateSample")
                    generate_sample = None
                    if generate_field:
                        generate_sample = generate_field[1].decode("utf-8", errors="replace")
                    job = create_job_from_image(image_bytes, filename, generate_sample=generate_sample)
                json_response(self, 200, {"ok": True, "job": job})
                return

            if parsed.path.rstrip("/") != "/api/analyze-generate":
                json_response(self, 404, {"ok": False, "error": "not found"})
                return

            length = int(self.headers.get("Content-Length") or 0)
            content_type = self.headers.get("Content-Type") or ""
            body = self.rfile.read(length)
            fields = parse_multipart(body, content_type)
            image_item = fields.get("image")
            if not image_item:
                raise RuntimeError("image フィールドがありません")
            _filename, image_bytes, _mime = image_item
            if not image_bytes:
                raise RuntimeError("画像データが空です")

            generate_field = fields.get("generateSample")
            generate_sample = None
            if generate_field:
                generate_sample = generate_field[1].decode("utf-8", errors="replace")
            job = create_job_from_image(image_bytes, "direct", generate_sample=generate_sample)
            json_response(self, 200, {"ok": True, "job": job})
        except UnidentifiedImageError:
            json_response(self, 400, {"ok": False, "error": "画像として読み込めませんでした"})
        except Exception as exc:
            json_response(self, 500, {"ok": False, "error": str(exc)})


def main() -> int:
    os.chdir(ROOT)
    print("WD Tag Sample Viewer")
    print(f"Folder: {ROOT}")
    settings = Settings()
    try:
        settings = load_settings()
        bridge_url = sync_bridge_config(settings)
        print(f"Bridge URL: {bridge_url}")
        print(f"Backend: {settings.backend}")
        print(f"API URL: {settings.api_url}")
        try:
            backend_info = check_backend(settings)
            if settings.backend == "comfyui":
                print("ComfyUI API: connected")
            else:
                checkpoint = backend_info.get("sd_model_checkpoint") or "(unknown checkpoint)"
                print("Forge/ReForge API: connected")
                print(f"Current checkpoint: {checkpoint}")
        except Exception as exc:
            label = "ComfyUI" if settings.backend == "comfyui" else "Forge/ReForge"
            print(f"{label} API: not connected")
            print(f"  {exc}")
            if settings.backend == "forge":
                print("  Forge/ReForgeが起動しているか、--apiが有効か、config.txtのURLを確認してください。")
            else:
                print("  ComfyUIが起動しているか、config.txtのURLを確認してください。")
    except Exception as exc:
        print(f"Config warning: {exc}")
        bridge_url = sync_bridge_config(settings)
        print(f"Bridge URL: {bridge_url} (defaults; fix config.txt)")
    print("Bridge ready. Keep this window open.")
    server = ThreadingHTTPServer((settings.bridge_host, settings.bridge_port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping...")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
