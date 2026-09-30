"""Fetch original dsh-pet assets at a pinned revision; verify Git blob hashes."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import time
import urllib.request

REVISION = "bd6c2bb67d9f88e1190c6884982c03c88205aa39"
REPO = "zhu1090093659/dsh-web"
PREFIX = "packages/dsh-pet/assets/"
PET_PREFIX = PREFIX + "whale-refined/"
ROOT = Path(__file__).resolve().parents[1] / "assets"


def request(url):
    for attempt in range(4):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except OSError:
            if attempt == 3:
                raise
            time.sleep(attempt + 1)


def blob_hash(data):
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def main():
    tree = json.loads(request(f"https://api.github.com/repos/{REPO}/git/trees/{REVISION}?recursive=1"))
    if tree.get("truncated"):
        raise RuntimeError("GitHub returned an incomplete asset listing")
    entries = [e for e in tree["tree"] if e["type"] == "blob" and (
        e["path"].startswith(PET_PREFIX) or e["path"] in ("LICENSE", "packages/dsh-pet/LICENSE"))]

    def fetch(entry):
        remote = entry["path"]
        relative = remote.removeprefix(PREFIX) if remote.startswith(PREFIX) else (
            "UPSTREAM-LICENSE" if remote == "LICENSE" else "DSH-PET-LICENSE")
        path = ROOT / relative
        if path.exists() and blob_hash(path.read_bytes()) == entry["sha"]:
            return
        data = request(f"https://raw.githubusercontent.com/{REPO}/{REVISION}/{remote}")
        if blob_hash(data) != entry["sha"]:
            raise RuntimeError(f"Hash mismatch: {remote}")
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_bytes(data)
        temporary.replace(path)

    print(f"Fetching/verifying {len(entries)} files ({sum(e['size'] for e in entries) / 1e6:.1f} MB)", flush=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool:
        for index, _ in enumerate(pool.map(fetch, entries), 1):
            if index % 100 == 0 or index == len(entries):
                print(f"{index}/{len(entries)}", flush=True)
    (ROOT / "source.json").write_text(json.dumps({
        "repository": f"https://github.com/{REPO}", "revision": REVISION,
        "files": [{"path": e["path"], "sha": e["sha"], "size": e["size"]} for e in entries],
    }, indent=2) + "\n")


if __name__ == "__main__":
    main()
