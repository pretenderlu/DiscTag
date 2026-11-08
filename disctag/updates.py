from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import requests


class UpdateError(RuntimeError):
    pass


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str
    download_url: str = ""
    installer_name: str = ""
    size: int = 0
    sha256: str = ""


def version_key(value: str) -> tuple[int, ...]:
    parts = value.strip().lstrip("vV").split("-", 1)[0].split(".")
    numbers = []
    for part in parts:
        match = re.match(r"\d+", part)
        if not match:
            break
        numbers.append(int(match.group(0)))
    while len(numbers) < 4:
        numbers.append(0)
    return tuple(numbers)


def check_for_updates(current_version: str, repository: str = "pretenderlu/DiscTag", timeout: float = 10) -> UpdateInfo | None:
    response = requests.get(
        f"https://api.github.com/repos/{repository}/releases/latest",
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"DiscTag/{current_version}",
        },
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if payload.get("draft") or payload.get("prerelease"):
        return None
    tag = str(payload.get("tag_name", ""))
    url = str(payload.get("html_url", ""))
    if not tag or not url.startswith("https://github.com/"):
        return None
    if version_key(tag) <= version_key(current_version):
        return None
    assets = payload.get("assets") or []
    installer = next(
        (
            asset
            for asset in assets
            if str(asset.get("name", "")).startswith("DiscTagSetup-")
            and str(asset.get("name", "")).endswith(".exe")
        ),
        {},
    )
    digest = str(installer.get("digest", "") or "")
    if not re.fullmatch(r"sha256:[0-9a-fA-F]{64}", digest):
        installer = {}
    return UpdateInfo(
        version=tag,
        url=url,
        download_url=installer.get("browser_download_url", ""),
        installer_name=installer.get("name", ""),
        size=int(installer.get("size", 0) or 0),
        sha256=digest.removeprefix("sha256:").lower() if installer else "",
    )


def download_update(
    info: UpdateInfo,
    destination: Path,
    progress: Callable[[int, int], None] | None = None,
) -> Path:
    if not info.download_url:
        raise UpdateError("该版本没有可自动安装的 Windows 安装包。")
    if not info.sha256:
        raise UpdateError("该版本缺少安装包校验信息，请前往发布页手动下载。")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".download")
    digest = hashlib.sha256()
    downloaded = 0
    try:
        with requests.get(info.download_url, stream=True, timeout=30) as response:
            response.raise_for_status()
            total = info.size or int(response.headers.get("Content-Length", 0))
            with temporary.open("wb") as output:
                for chunk in response.iter_content(1024 * 1024):
                    if not chunk:
                        continue
                    output.write(chunk)
                    digest.update(chunk)
                    downloaded += len(chunk)
                    if progress:
                        progress(downloaded, total)
        if info.size and downloaded != info.size:
            raise UpdateError("更新包下载不完整，请重试。")
        if digest.hexdigest() != info.sha256.lower():
            raise UpdateError("更新包校验失败，已阻止安装。")
        os.replace(temporary, destination)
        return destination
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
