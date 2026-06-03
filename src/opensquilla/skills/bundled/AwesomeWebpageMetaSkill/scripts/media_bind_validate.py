import html
import json
import os
import re
from pathlib import Path

project_root = Path(os.environ["PROJECT_ROOT"]).expanduser().resolve()
project_dir = project_root / "project"
index_path = project_dir / "index.html"
style_path = project_dir / "style.css"
script_path = project_dir / "script.js"

def requested(name):
    return os.environ.get(f"INCLUDE_{name.upper()}", "YES") == "YES"

def normalize_path(value):
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or raw.startswith("/") or ".." in Path(raw).parts:
        return None, None
    if raw.startswith("project/"):
        src = raw[len("project/"):]
        disk = project_root / raw
    else:
        src = raw
        disk = project_dir / raw
    if not raw.startswith(("assets/images/", "assets/audio/", "assets/video/")):
        if not src.startswith(("assets/images/", "assets/audio/", "assets/video/")):
            return None, None
    return src, disk

def collect_assets():
    ready_re = re.compile(r"^(IMAGE|AUDIO|VIDEO)_READY:\s*(\{.*\})\s*$", re.M)
    fail_re = re.compile(r"^(IMAGE|AUDIO|VIDEO)_(CONFIG_NEEDED|GENERATION_FAILED|MODEL_UNSUPPORTED):\s*(\{.*\})\s*$", re.M)
    sources = {
        "image_download": os.environ.get("IMAGE_DOWNLOAD", ""),
        "image_aigc": os.environ.get("IMAGE_AIGC", ""),
        "audio_aigc": os.environ.get("AUDIO_AIGC", ""),
        "video_aigc": os.environ.get("VIDEO_AIGC", ""),
    }
    assets = []
    generation_failures = []
    seen = set()
    for source, text in sources.items():
        for match in ready_re.finditer(text):
            kind = match.group(1).lower()
            try:
                payload = json.loads(match.group(2))
            except json.JSONDecodeError:
                continue
            if not isinstance(payload, dict):
                continue
            src, disk = normalize_path(payload.get("local_path"))
            if src is None or disk is None or not disk.is_file() or disk.stat().st_size <= 0:
                continue
            key = (kind, src)
            if key in seen:
                continue
            seen.add(key)
            assets.append({
                "kind": kind,
                "src": src,
                "bytes": disk.stat().st_size,
                "subject": str(payload.get("subject") or payload.get("slot_id") or payload.get("prompt_preview") or payload.get("script_preview") or src),
            })
        for match in fail_re.finditer(text):
            try:
                payload = json.loads(match.group(3))
            except json.JSONDecodeError:
                payload = {}
            generation_failures.append({
                "kind": match.group(1).lower(),
                "label": f"{match.group(1)}_{match.group(2)}",
                "source_step": source,
                "reason": payload.get("reason") or payload.get("status") or payload.get("phase"),
            })
    return assets, generation_failures

failures = []
for path, label in [
    (index_path, "project/index.html"),
    (style_path, "project/style.css"),
    (script_path, "project/script.js"),
]:
    if not path.is_file():
        failures.append({"kind": "page", "reason": "missing_authored_file", "path": label})
if failures:
    print(json.dumps({"status": "MEDIA_BIND_FAILED", "failures": failures}, ensure_ascii=True, separators=(",", ":")))
    raise SystemExit("MEDIA_BIND_FAILED")

assets, generation_failures = collect_assets()
index_html = index_path.read_text(encoding="utf-8")
style_css = style_path.read_text(encoding="utf-8")
script_js = script_path.read_text(encoding="utf-8")
combined = "\n".join([index_html, style_css, script_js])
lower_html = index_html.lower()

repair_map = {}
for asset in assets:
    if asset["src"] not in combined:
        repair_map[(asset["kind"], asset["src"])] = asset
audio_assets = [asset for asset in assets if asset["kind"] == "audio"]
video_assets = [asset for asset in assets if asset["kind"] == "video"]
if audio_assets and ("<audio" not in lower_html or not any(asset["src"] in index_html for asset in audio_assets)):
    for asset in audio_assets:
        repair_map[(asset["kind"], asset["src"])] = asset
if video_assets and ("<video" not in lower_html or not any(asset["src"] in index_html for asset in video_assets)):
    for asset in video_assets:
        repair_map[(asset["kind"], asset["src"])] = asset

if repair_map:
    repair_assets = list(repair_map.values())
    images = [asset for asset in repair_assets if asset["kind"] == "image"]
    audio = [asset for asset in repair_assets if asset["kind"] == "audio"]
    video = [asset for asset in repair_assets if asset["kind"] == "video"]
    blocks = [
        '<section id="generated-media-assets" class="generated-media-assets" aria-labelledby="generated-media-title">',
        '  <div class="generated-media-assets__inner">',
        '    <p class="generated-media-assets__eyebrow">Generated media</p>',
        '    <h2 id="generated-media-title">本地生成媒体</h2>',
        '    <p class="generated-media-assets__intro">以下素材已生成并绑定到页面，可直接播放或替换同名文件。</p>',
    ]
    for asset in audio:
        label = html.escape(asset["subject"][:120])
        src = html.escape(asset["src"], quote=True)
        blocks.extend([
            '    <article class="generated-media-card generated-media-card--audio">',
            '      <div><h3>音频导览</h3>',
            f'      <p>{label}</p></div>',
            f'      <audio controls preload="metadata" src="{src}"></audio>',
            '    </article>',
        ])
    for asset in video:
        label = html.escape(asset["subject"][:120])
        src = html.escape(asset["src"], quote=True)
        blocks.extend([
            '    <article class="generated-media-card generated-media-card--video">',
            '      <div><h3>视频片段</h3>',
            f'      <p>{label}</p></div>',
            f'      <video controls playsinline preload="metadata" src="{src}"></video>',
            '    </article>',
        ])
    if images:
        blocks.append('    <div class="generated-media-gallery" aria-label="生成图片素材">')
        for asset in images:
            label = html.escape(asset["subject"][:120])
            src = html.escape(asset["src"], quote=True)
            blocks.extend([
                '      <figure>',
                f'        <img loading="lazy" src="{src}" alt="{label}">',
                f'        <figcaption>{label}</figcaption>',
                '      </figure>',
            ])
        blocks.append('    </div>')
    blocks.extend(['  </div>', '</section>'])
    repair_html = "\n".join(blocks)
    insert_idx = lower_html.rfind("</main>")
    if insert_idx < 0:
        insert_idx = lower_html.rfind("</body>")
    if insert_idx >= 0:
        index_html = index_html[:insert_idx] + repair_html + "\n" + index_html[insert_idx:]
    else:
        index_html += "\n" + repair_html + "\n"
    if ".generated-media-assets" not in style_css:
        style_css += """

.generated-media-assets {
  background: #f5f7fb;
  color: #15202b;
  padding: clamp(2rem, 6vw, 5rem) clamp(1rem, 4vw, 3rem);
}
.generated-media-assets__inner {
  max-width: 1120px;
  margin: 0 auto;
}
.generated-media-assets__eyebrow {
  margin: 0 0 .5rem;
  color: #0f766e;
  font-size: .78rem;
  font-weight: 700;
  text-transform: uppercase;
}
.generated-media-assets h2 {
  margin: 0 0 1rem;
  font-size: clamp(1.75rem, 4vw, 3.25rem);
  line-height: 1.08;
}
.generated-media-assets__intro {
  max-width: 64ch;
  margin: 0 0 2rem;
  color: #475569;
  line-height: 1.75;
}
.generated-media-card {
  display: grid;
  grid-template-columns: minmax(0, 1fr) minmax(280px, 460px);
  gap: 1.5rem;
  align-items: center;
  padding: clamp(1rem, 3vw, 2rem);
  margin-bottom: 1.5rem;
  border: 1px solid rgba(15, 23, 42, .12);
  border-radius: 8px;
  background: #fff;
}
.generated-media-card audio,
.generated-media-card video {
  width: 100%;
}
.generated-media-gallery {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 1rem;
}
.generated-media-gallery figure {
  margin: 0;
  overflow: hidden;
  border-radius: 8px;
  background: #fff;
}
.generated-media-gallery img {
  display: block;
  width: 100%;
  aspect-ratio: 4 / 3;
  object-fit: cover;
}
.generated-media-gallery figcaption {
  padding: .85rem 1rem 1rem;
  color: #475569;
  line-height: 1.55;
}
@media (max-width: 760px) {
  .generated-media-card {
    grid-template-columns: 1fr;
  }
}
"""
    index_path.write_text(index_html, encoding="utf-8")
    style_path.write_text(style_css, encoding="utf-8")

index_html = index_path.read_text(encoding="utf-8")
style_css = style_path.read_text(encoding="utf-8")
script_js = script_path.read_text(encoding="utf-8")
combined = "\n".join([index_html, style_css, script_js])
lower_html = index_html.lower()
assets_by_kind = {"image": [], "audio": [], "video": []}
for asset in assets:
    assets_by_kind[asset["kind"]].append(asset)

required = {"image": requested("image"), "audio": requested("audio"), "video": requested("video")}
for kind, is_required in required.items():
    if not is_required:
        continue
    if not assets_by_kind[kind]:
        failures.append({"kind": kind, "reason": "requested_modality_has_no_ready_asset"})
        continue
    for asset in assets_by_kind[kind]:
        if asset["src"] not in combined:
            failures.append({"kind": kind, "reason": "asset_not_referenced_by_page", "src": asset["src"]})
    if kind == "audio" and ("<audio" not in lower_html or not any(a["src"] in index_html for a in assets_by_kind[kind])):
        failures.append({"kind": kind, "reason": "audio_control_missing_or_unbound"})
    if kind == "video" and ("<video" not in lower_html or not any(a["src"] in index_html for a in assets_by_kind[kind])):
        failures.append({"kind": kind, "reason": "video_control_missing_or_unbound"})

report = {
    "status": "MEDIA_BIND_OK" if not failures else "MEDIA_BIND_FAILED",
    "requested": required,
    "ready_counts": {kind: len(items) for kind, items in assets_by_kind.items()},
    "referenced": {
        kind: [asset["src"] for asset in items if asset["src"] in combined]
        for kind, items in assets_by_kind.items()
    },
    "patched_assets": [asset["src"] for asset in repair_map.values()],
    "generation_failures": generation_failures,
    "failures": failures,
}
print(json.dumps(report, ensure_ascii=True, separators=(",", ":")))
if failures:
    raise SystemExit("MEDIA_BIND_FAILED")
