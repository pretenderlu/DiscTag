from __future__ import annotations

import re
from dataclasses import dataclass

import requests


@dataclass(frozen=True)
class UpdateInfo:
    version: str
    url: str


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
    if version_key(tag) > version_key(current_version):
        return UpdateInfo(version=tag, url=url)
    return None
