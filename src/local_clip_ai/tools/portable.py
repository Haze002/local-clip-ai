from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from local_clip_ai.paths import AppPaths

GITHUB_API_ROOT = "https://api.github.com/repos"
USER_AGENT = "Local-Clip-AI/0.1 (+https://github.com/Haze002/local-clip-ai)"
FFMPEG_REPOSITORY = "BtbN/FFmpeg-Builds"
FFMPEG_ASSET = "ffmpeg-n8.1-latest-win64-lgpl-shared-8.1.zip"
YT_DLP_REPOSITORY = "yt-dlp/yt-dlp"
YT_DLP_ASSET = "yt-dlp.exe"


@dataclass(frozen=True, slots=True)
class PortableToolInstall:
    name: str
    release: str
    asset: str
    sha256: str
    executables: tuple[str, ...]
    installed_at: str


def _request_json(url: str) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)


def _release_asset(repository: str, asset_name: str) -> tuple[str, dict[str, Any]]:
    release = _request_json(f"{GITHUB_API_ROOT}/{repository}/releases/latest")
    for asset in release.get("assets", []):
        if asset.get("name") == asset_name:
            return str(release["tag_name"]), asset
    raise RuntimeError(f"{asset_name!r} is not present in the latest {repository} release")


def _expected_sha256(asset: dict[str, Any]) -> str:
    digest = str(asset.get("digest") or "")
    algorithm, separator, value = digest.partition(":")
    if separator and algorithm.lower() == "sha256" and len(value) == 64:
        return value.lower()
    raise RuntimeError(f"GitHub did not provide a SHA-256 digest for {asset.get('name')}")


def _download_verified(url: str, destination: Path, expected_sha256: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(destination.suffix + ".part")
    digest = hashlib.sha256()
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=60) as response, partial.open("wb") as output:
            while block := response.read(1024 * 1024):
                output.write(block)
                digest.update(block)
        actual_sha256 = digest.hexdigest()
        if actual_sha256 != expected_sha256:
            raise RuntimeError(
                f"SHA-256 mismatch for {destination.name}: "
                f"expected {expected_sha256}, received {actual_sha256}"
            )
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


def _safe_extract(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    destination_root = destination.resolve()
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            member_path = (destination / member.filename).resolve()
            if os.path.commonpath((destination_root, member_path)) != str(destination_root):
                raise RuntimeError(f"Unsafe path in {archive.name}: {member.filename}")
        bundle.extractall(destination)


def _write_receipt(root: Path, install: PortableToolInstall) -> None:
    (root / "install.json").write_text(
        json.dumps(asdict(install), indent=2) + "\n",
        encoding="utf-8",
    )


def _installed_at() -> str:
    return datetime.now(UTC).isoformat()


def _install_ffmpeg(paths: AppPaths, force: bool) -> PortableToolInstall:
    install_root = paths.tools / "ffmpeg"
    existing_ffmpeg, existing_ffprobe = find_ffmpeg(
        paths,
        include_path=False,
        include_bundled=False,
    )
    receipt = install_root / "install.json"
    if not force and existing_ffmpeg and existing_ffprobe and receipt.is_file():
        values = json.loads(receipt.read_text(encoding="utf-8"))
        values["executables"] = tuple(values["executables"])
        return PortableToolInstall(**values)

    release, asset = _release_asset(FFMPEG_REPOSITORY, FFMPEG_ASSET)
    expected_sha256 = _expected_sha256(asset)
    archive = paths.temporary / FFMPEG_ASSET
    _download_verified(str(asset["browser_download_url"]), archive, expected_sha256)

    with tempfile.TemporaryDirectory(prefix="ffmpeg-install-", dir=paths.temporary) as temp:
        extracted = Path(temp)
        _safe_extract(archive, extracted)
        ffmpeg = next(extracted.rglob("ffmpeg.exe"), None)
        ffprobe = next(extracted.rglob("ffprobe.exe"), None)
        if not ffmpeg or not ffprobe or ffmpeg.parent != ffprobe.parent:
            raise RuntimeError("The FFmpeg archive did not contain the expected executables")
        staged_root = ffmpeg.parent.parent
        if install_root.exists():
            shutil.rmtree(install_root)
        shutil.move(str(staged_root), install_root)
    archive.unlink(missing_ok=True)

    installed_ffmpeg = next(install_root.rglob("ffmpeg.exe"))
    installed_ffprobe = next(install_root.rglob("ffprobe.exe"))
    install = PortableToolInstall(
        name="ffmpeg",
        release=release,
        asset=FFMPEG_ASSET,
        sha256=expected_sha256,
        executables=(
            str(installed_ffmpeg.relative_to(paths.root)),
            str(installed_ffprobe.relative_to(paths.root)),
        ),
        installed_at=_installed_at(),
    )
    _write_receipt(install_root, install)
    return install


def _install_yt_dlp(paths: AppPaths, force: bool) -> PortableToolInstall:
    install_root = paths.tools / "yt-dlp"
    executable = install_root / YT_DLP_ASSET
    receipt = install_root / "install.json"
    if not force and executable.is_file() and receipt.is_file():
        values = json.loads(receipt.read_text(encoding="utf-8"))
        values["executables"] = tuple(values["executables"])
        return PortableToolInstall(**values)

    release, asset = _release_asset(YT_DLP_REPOSITORY, YT_DLP_ASSET)
    expected_sha256 = _expected_sha256(asset)
    install_root.mkdir(parents=True, exist_ok=True)
    _download_verified(str(asset["browser_download_url"]), executable, expected_sha256)
    install = PortableToolInstall(
        name="yt-dlp",
        release=release,
        asset=YT_DLP_ASSET,
        sha256=expected_sha256,
        executables=(str(executable.relative_to(paths.root)),),
        installed_at=_installed_at(),
    )
    _write_receipt(install_root, install)
    return install


def install_portable_tools(
    paths: AppPaths,
    *,
    force: bool = False,
) -> tuple[PortableToolInstall, ...]:
    paths.ensure_directories()
    return (
        _install_ffmpeg(paths, force),
        _install_yt_dlp(paths, force),
    )


def find_ffmpeg(
    paths: AppPaths,
    *,
    include_path: bool = True,
    include_bundled: bool = True,
) -> tuple[Path | None, Path | None]:
    ffmpeg = next(paths.tools.glob("ffmpeg/**/ffmpeg.exe"), None)
    ffprobe = next(paths.tools.glob("ffmpeg/**/ffprobe.exe"), None)
    if include_bundled and (bundled_tools := _bundled_tools_directory()):
        ffmpeg = ffmpeg or next(bundled_tools.glob("ffmpeg/**/ffmpeg.exe"), None)
        ffprobe = ffprobe or next(bundled_tools.glob("ffmpeg/**/ffprobe.exe"), None)
    if include_path:
        ffmpeg = ffmpeg or _which_path("ffmpeg")
        ffprobe = ffprobe or _which_path("ffprobe")
    return ffmpeg, ffprobe


def find_yt_dlp(
    paths: AppPaths,
    *,
    include_path: bool = True,
    include_bundled: bool = True,
) -> Path | None:
    portable = paths.tools / "yt-dlp" / YT_DLP_ASSET
    if portable.is_file():
        return portable
    if include_bundled and (bundled_tools := _bundled_tools_directory()):
        bundled = bundled_tools / "yt-dlp" / YT_DLP_ASSET
        if bundled.is_file():
            return bundled
    return _which_path("yt-dlp") if include_path else None


def _bundled_tools_directory() -> Path | None:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if not frozen_root:
        return None
    bundled_tools = Path(frozen_root) / "bundled_tools"
    return bundled_tools if bundled_tools.is_dir() else None


def _which_path(name: str) -> Path | None:
    executable = shutil.which(name)
    return Path(executable) if executable else None
