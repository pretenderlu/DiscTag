"""Downloads the pinned minimal FFmpeg binary into vendor/."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
from pathlib import Path

import requests

REPOSITORY = "pretenderlu/DiscTag"
PLATFORM_KEYS = {
    ("Windows", "AMD64"): "windows-x64",
    ("Darwin", "arm64"): "macos-AppleSilicon",
    ("Darwin", "x86_64"): "macos-Intel",
}


def platform_key() -> str:
    key = PLATFORM_KEYS.get((platform.system(), platform.machine()))
    if key is None:
        raise SystemExit(f"不支持的平台：{platform.system()} {platform.machine()}")
    return key


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--platform", choices=("windows-x64", "macos-AppleSilicon", "macos-Intel"))
    args = parser.parse_args()
    project = Path(__file__).resolve().parent.parent
    manifest = json.loads((project / "scripts" / "ffmpeg.json").read_text(encoding="utf-8"))
    key = args.platform or platform_key()
    asset = manifest["assets"][key]
    sha256 = asset["sha256"]
    filename = "ffmpeg.exe" if key == "windows-x64" else "ffmpeg"
    target = project / "vendor" / filename
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == sha256:
        print(f"{target} 已是指定版本（{sha256[:12]}…），无需下载。")
        return
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    release = requests.get(
        f"https://api.github.com/repos/{REPOSITORY}/releases/tags/{manifest['tag']}",
        headers=headers,
        timeout=30,
    )
    release.raise_for_status()
    asset_url = next(
        entry["url"] for entry in release.json().get("assets", []) if entry.get("name") == asset["name"]
    )
    print(f"下载 {asset['name']}（{manifest['tag']}）")
    response = requests.get(
        asset_url,
        headers={"Accept": "application/octet-stream", **({"Authorization": f"Bearer {token}"} if token else {})},
        timeout=120,
    )
    response.raise_for_status()
    data = response.content
    digest = hashlib.sha256(data).hexdigest()
    if digest != sha256:
        raise SystemExit(f"SHA-256 校验失败：期望 {sha256}，实际 {digest}；未写入 {target}。")
    target.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=target.parent, delete=False) as temporary:
        temporary.write(data)
        temp_path = Path(temporary.name)
    temp_path.replace(target)
    if filename == "ffmpeg":
        target.chmod(0o755)
    print(f"{target}（{len(data)} 字节，sha256 {digest}）")


if __name__ == "__main__":
    main()
