import subprocess
from pathlib import Path

import pytest

from src.publish.hosting import HostingError, publish_to_scratch_branch, raw_url


def test_raw_url_construction():
    assert raw_url("bricksx11", "the-network", "render-scratch", "slide-1.png") == (
        "https://raw.githubusercontent.com/bricksx11/the-network/render-scratch/slide-1.png"
    )


def _run(args: list[str], cwd: Path) -> str:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, check=True)
    return result.stdout.strip()


@pytest.fixture
def local_repo_with_remote(tmp_path):
    """A real local git repo with a real (local, bare) 'origin' remote -- lets us exercise
    the actual worktree/orphan-commit/force-push mechanics without needing real GitHub.
    """
    bare_remote = tmp_path / "remote.git"
    bare_remote.mkdir()
    _run(["init", "--bare", "-b", "main"], cwd=bare_remote)

    local = tmp_path / "local"
    local.mkdir()
    _run(["init", "-b", "main"], cwd=local)
    _run(["-c", "user.email=t@local", "-c", "user.name=t", "commit", "--allow-empty", "-m", "initial"], cwd=local)
    _run(["remote", "add", "origin", str(bare_remote)], cwd=local)
    _run(["push", "-u", "origin", "main"], cwd=local)

    return local, bare_remote


def test_publish_to_scratch_branch_pushes_files_and_returns_urls(local_repo_with_remote, tmp_path):
    local_repo, bare_remote = local_repo_with_remote

    file_a = tmp_path / "a.png"
    file_a.write_bytes(b"fake image a")
    file_b = tmp_path / "b.png"
    file_b.write_bytes(b"fake image b")

    urls = publish_to_scratch_branch([file_a, file_b], local_repo, "someowner", "somerepo")

    assert urls == [
        "https://raw.githubusercontent.com/someowner/somerepo/render-scratch/a.png",
        "https://raw.githubusercontent.com/someowner/somerepo/render-scratch/b.png",
    ]

    # the branch actually exists on the "remote" with exactly those two files
    branches = _run(["branch", "-a"], cwd=bare_remote)
    assert "render-scratch" in branches

    ls = _run(["ls-tree", "-r", "--name-only", "render-scratch"], cwd=bare_remote)
    assert set(ls.splitlines()) == {"a.png", "b.png"}


def test_publish_to_scratch_branch_does_not_disturb_original_checkout(local_repo_with_remote, tmp_path):
    local_repo, _ = local_repo_with_remote
    branch_before = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local_repo)

    file_a = tmp_path / "a.png"
    file_a.write_bytes(b"fake image a")
    publish_to_scratch_branch([file_a], local_repo, "someowner", "somerepo")

    branch_after = _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=local_repo)
    assert branch_before == branch_after == "main"


def test_publish_to_scratch_branch_force_push_replaces_not_accumulates(local_repo_with_remote, tmp_path):
    local_repo, bare_remote = local_repo_with_remote

    day1_file = tmp_path / "day1.png"
    day1_file.write_bytes(b"day 1")
    publish_to_scratch_branch([day1_file], local_repo, "owner", "repo")

    day2_file = tmp_path / "day2.png"
    day2_file.write_bytes(b"day 2")
    publish_to_scratch_branch([day2_file], local_repo, "owner", "repo")

    ls = _run(["ls-tree", "-r", "--name-only", "render-scratch"], cwd=bare_remote)
    # day1's file must be gone -- force-push replaced it, not accumulated alongside it
    assert set(ls.splitlines()) == {"day2.png"}

    log = _run(["log", "--oneline", "render-scratch"], cwd=bare_remote)
    assert len(log.splitlines()) == 1  # always a single fresh orphan commit, no history growth


def test_publish_to_scratch_branch_always_includes_verification_files(local_repo_with_remote, tmp_path):
    """Platform URL-ownership verification files (e.g. TikTok's) must survive every wipe --
    they live under repo_root/assets/verification-files/ and get copied into every push
    automatically, not just when explicitly passed in `files`.
    """
    local_repo, bare_remote = local_repo_with_remote
    verification_dir = local_repo / "assets" / "verification-files"
    verification_dir.mkdir(parents=True)
    (verification_dir / "tiktok-verify.txt").write_text("tiktok-developers-site-verification=fake123")

    file_a = tmp_path / "a.png"
    file_a.write_bytes(b"fake image a")
    publish_to_scratch_branch([file_a], local_repo, "owner", "repo")

    ls = _run(["ls-tree", "-r", "--name-only", "render-scratch"], cwd=bare_remote)
    assert set(ls.splitlines()) == {"a.png", "tiktok-verify.txt"}


def test_publish_to_scratch_branch_raises_on_empty_file_list(local_repo_with_remote):
    local_repo, _ = local_repo_with_remote
    with pytest.raises(ValueError, match="no files"):
        publish_to_scratch_branch([], local_repo, "owner", "repo")
