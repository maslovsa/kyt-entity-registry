import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import check_repo_size  # noqa: E402


def _repo(tmp_path: Path, files: dict[str, int]) -> Path:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    for rel, n in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x" * n)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return tmp_path


def test_tracked_sizes_counts_only_tracked_files(tmp_path):
    root = _repo(tmp_path, {"logos/a.png": 100, "logos/b.png": 50, "top.txt": 7})
    (root / "untracked.bin").write_bytes(b"y" * 9999)
    sizes = check_repo_size.tracked_sizes(root)
    assert sum(sizes.values()) == 157 and "untracked.bin" not in sizes


def test_breakdown_groups_by_directory(tmp_path):
    root = _repo(tmp_path, {"logos/defi/a.png": 300, "logos/dex/b.png": 100, "top.txt": 7})
    top = dict(check_repo_size.breakdown(check_repo_size.tracked_sizes(root)))
    assert top["logos/defi"] == 300 and top["(root files)"] == 7
