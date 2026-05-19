from __future__ import annotations

import shutil
import subprocess
import tarfile
import time
import urllib.error
import urllib.request
from pathlib import Path

from .utils import AI_MGMT_HOME, GITHUB_BRANCH, GITHUB_REPO, MANAGED_DIRS, CLIError, ensure_dir, is_relative_to, log, info, remove_path


def safe_extract_tar(archive_path: Path, destination: Path) -> None:
    ensure_dir(destination)
    with tarfile.open(archive_path, "r:gz") as tar:
        destination_resolved = destination.resolve()
        for member in tar.getmembers():
            member_path = destination / member.name
            if not is_relative_to(member_path.resolve(), destination_resolved):
                raise CLIError("Unsafe tarball path detected")
        tar.extractall(destination)


def download_repo_tarball(output_path: Path) -> bool:
    ensure_dir(output_path.parent)
    api_path = f"repos/{GITHUB_REPO}/tarball/{GITHUB_BRANCH}"
    curl_url = f"https://github.com/{GITHUB_REPO}/archive/refs/heads/{GITHUB_BRANCH}.tar.gz"
    if shutil.which("gh"):
        result = subprocess.run(["gh", "api", api_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        if result.returncode == 0:
            output_path.write_bytes(result.stdout)
            return True
    try:
        with urllib.request.urlopen(curl_url) as response:
            output_path.write_bytes(response.read())
        return True
    except urllib.error.URLError:
        return False


def pull_from_github() -> None:
    if not GITHUB_REPO:
        raise CLIError("No repository configured for --pull. Set AI_MANAGEMENT_REPO.")
    print()
    print(f"\033[1m── Pulling from GitHub ({GITHUB_REPO}@{GITHUB_BRANCH}) ──\033[0m")
    scratch = AI_MGMT_HOME / f".pull-work-{int(time.time())}"
    archive_path = scratch / "repo.tar.gz"
    extract_root = scratch / "extracted"
    if scratch.exists():
        shutil.rmtree(scratch)
    ensure_dir(scratch)
    info("Downloading tarball…")
    if not download_repo_tarball(archive_path):
        shutil.rmtree(scratch, ignore_errors=True)
        raise CLIError(f"Failed to download from {GITHUB_REPO}. Ensure gh is authenticated or the repo is public.")
    safe_extract_tar(archive_path, extract_root)
    extracted_dirs = [child for child in extract_root.iterdir() if child.is_dir()]
    if not extracted_dirs:
        shutil.rmtree(scratch, ignore_errors=True)
        raise CLIError("Tarball extraction failed — no directory found")
    extracted = extracted_dirs[0]
    ensure_dir(AI_MGMT_HOME)
    for name in MANAGED_DIRS + ["defaults.conf"]:
        src = extracted / name
        dest = AI_MGMT_HOME / name
        if not src.exists():
            continue
        remove_path(dest)
        if src.is_dir():
            shutil.copytree(src, dest)
            count = sum(1 for child in dest.rglob("*") if child.is_file())
            log(f"Pulled {name}/ ({count} files)")
        else:
            ensure_dir(dest.parent)
            shutil.copy2(src, dest)
            log(f"Pulled {name}")
    shutil.rmtree(scratch, ignore_errors=True)
    print()
    log(f"Pull complete → {AI_MGMT_HOME}")
