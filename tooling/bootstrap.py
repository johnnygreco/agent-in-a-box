#!/usr/bin/env python3
"""Install the pinned Cedar toolchain into .toolchain/ (stdlib only).

    python3 tooling/bootstrap.py            # cvc5 + the Cedar bridge
    python3 tooling/bootstrap.py --with-cli # also the official cedar CLI (test oracle)

Everything goes under the repository's .toolchain/ directory. Nothing is
installed system-wide and no trust store is touched. Downloads are verified
against tooling/toolchain.lock.json before use; a mismatch stops the install.
Requires cargo (rustup, user-local) for the bridge and the CLI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOCK = json.loads((ROOT / "tooling" / "toolchain.lock.json").read_text())
DEST = Path(os.environ.get("AGENT_IN_A_BOX_TOOLCHAIN", ROOT / ".toolchain"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def platform_key() -> str:
    system, machine = platform.system(), platform.machine().lower()
    if system == "Linux" and machine in ("x86_64", "amd64"):
        return "linux-x86_64"
    if system == "Darwin" and machine in ("arm64", "aarch64"):
        return "macos-arm64"
    raise SystemExit(f"unsupported platform for the pinned toolchain: {system} {machine}")


def install_cvc5(key: str) -> Path:
    asset = LOCK["cvc5"]["assets"][key]
    archive = DEST / "downloads" / Path(asset["url"]).name
    archive.parent.mkdir(parents=True, exist_ok=True)
    if not archive.exists() or sha256(archive) != asset["sha256"]:
        print(f"downloading {asset['url']}")
        urllib.request.urlretrieve(asset["url"], archive)
    if sha256(archive) != asset["sha256"]:
        raise SystemExit(f"checksum mismatch for {archive}; refusing to install")
    target = DEST / "bin" / "cvc5"
    target.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive) as zf, zf.open(asset["member"]) as src, target.open("wb") as out:
        shutil.copyfileobj(src, out)
    target.chmod(0o755)
    expected = asset.get("binary_sha256")
    if expected and sha256(target) != expected:
        raise SystemExit(f"cvc5 binary checksum mismatch; refusing to install {target}")
    return target


def cargo() -> str:
    found = shutil.which("cargo") or str(Path.home() / ".cargo" / "bin" / "cargo")
    if not Path(found).exists():
        raise SystemExit("cargo not found; install Rust with rustup (user-local) first")
    return found


def build_bridge() -> Path:
    manifest = ROOT / LOCK["bridge"]["source"] / "Cargo.toml"
    subprocess.run(
        [cargo(), "build", "--release", "--locked", "--manifest-path", str(manifest)], check=True
    )
    built = manifest.parent / "target" / "release" / LOCK["bridge"]["name"]
    target = DEST / "bin" / LOCK["bridge"]["name"]
    shutil.copy2(built, target)
    return target


def install_cli() -> Path:
    cli = LOCK["cedar_cli"]
    spec = f"{cli['crate']}@{cli['version']}"
    subprocess.run(
        [cargo(), "install", spec, "--locked", "--features", ",".join(cli["features"]),
         "--root", str(DEST / "cedar-cli")],
        check=True,
    )
    return DEST / "cedar-cli" / "bin" / "cedar"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--with-cli", action="store_true", help="also install the cedar CLI")
    args = parser.parse_args()
    key = platform_key()
    installed = {"platform": key, "binaries": {}}
    for name, path in (("cvc5", install_cvc5(key)), ("bridge", build_bridge())):
        installed["binaries"][name] = {"path": str(path), "sha256": sha256(path)}
    if args.with_cli:
        path = install_cli()
        installed["binaries"]["cedar_cli"] = {"path": str(path), "sha256": sha256(path)}
    bridge_lock = ROOT / LOCK["bridge"]["source"] / "Cargo.lock"
    installed["bridge_cargo_lock_sha256"] = sha256(bridge_lock)
    (DEST / "installed.json").write_text(json.dumps(installed, indent=2) + "\n")
    print(json.dumps(installed, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
