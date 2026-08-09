"""The "hosting-hop": Instagram, TikTok, and Facebook all fetch media by URL, not direct
upload -- rendered local files need a brief public URL before any of those publish calls
can happen. Per the plan: commit rendered output to a dedicated scratch branch (never
`main`, so the real repo history stays small and stable) and serve it via
raw.githubusercontent.com.

Simplification from the plan's "keep last 3 days" rolling window: each publish creates a
single fresh orphan commit and force-pushes it, discarding all prior scratch-branch history
outright rather than pruning by age. Simpler to implement correctly and satisfies the same
goal (bounded size) more robustly -- there's nothing to prune, there's just never more than
one commit's worth of files on the branch at a time.

Uses `git worktree` for the actual push so this never touches the caller's currently
checked-out branch/working directory -- important since this may run against the same repo
checkout that's mid-development, not just in an ephemeral CI runner.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

SCRATCH_BRANCH = "render-scratch"

# Platform URL-ownership verification files (e.g. TikTok's PULL_FROM_URL prefix check) must
# live at this exact scratch-branch URL prefix permanently -- but publish_to_scratch_branch
# wipes the branch on every push (single fresh orphan commit each time), so these get
# re-copied into every push rather than surviving on their own. Committed to `main` (under
# repo_root) as the durable source; add a new file to this directory for any future platform
# verification requirement, no code change needed. Relative to repo_root (not this module's
# own location) so tests using a fake repo never pick up the real repo's files.
VERIFICATION_FILES_SUBDIR = Path("assets") / "verification-files"


class HostingError(Exception):
    pass


def raw_url(github_owner: str, repo: str, branch: str, path_in_repo: str) -> str:
    return f"https://raw.githubusercontent.com/{github_owner}/{repo}/{branch}/{path_in_repo}"


def _run_git(args: list[str], cwd: Path) -> None:
    result = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        raise HostingError(f"git {' '.join(args)} failed:\n{result.stderr}")


def publish_to_scratch_branch(
    files: list[Path],
    repo_root: Path,
    github_owner: str,
    repo: str,
    branch: str = SCRATCH_BRANCH,
) -> list[str]:
    """Push `files` as a single fresh orphan commit on `branch`, force-pushed. Returns the
    raw.githubusercontent.com URL for each file, in the same order as `files`.
    """
    if not files:
        raise ValueError("no files to publish")

    with tempfile.TemporaryDirectory(prefix="the-network-scratch-") as tmp:
        worktree_dir = Path(tmp) / "worktree"
        _run_git(["worktree", "add", "--detach", str(worktree_dir)], cwd=repo_root)
        try:
            # a prior call's local branch ref can outlive its worktree -- clear it so
            # --orphan always starts clean instead of erroring on "branch already exists"
            existing_branches = subprocess.run(
                ["git", "branch", "--list", branch], cwd=repo_root, capture_output=True, text=True, check=True
            ).stdout
            if existing_branches.strip():
                _run_git(["branch", "-D", branch], cwd=repo_root)

            _run_git(["checkout", "--orphan", branch], cwd=worktree_dir)
            tracked = subprocess.run(
                ["git", "ls-files"], cwd=worktree_dir, capture_output=True, text=True, check=True
            ).stdout.strip()
            if tracked:
                _run_git(["rm", "-rf", "--cached", "."], cwd=worktree_dir)
            for item in worktree_dir.iterdir():
                if item.name == ".git":
                    continue
                if item.is_dir():
                    shutil.rmtree(item)
                else:
                    item.unlink()

            names = []
            for f in files:
                dest = worktree_dir / f.name
                shutil.copy2(f, dest)
                names.append(f.name)

            verification_files_dir = repo_root / VERIFICATION_FILES_SUBDIR
            if verification_files_dir.is_dir():
                for vf in verification_files_dir.iterdir():
                    if vf.is_file():
                        shutil.copy2(vf, worktree_dir / vf.name)

            _run_git(["add", "-A"], cwd=worktree_dir)
            _run_git(["-c", "user.email=the-network@local", "-c", "user.name=the-network", "commit", "-m", "scratch render output"], cwd=worktree_dir)
            _run_git(["push", "--force", "origin", f"HEAD:{branch}"], cwd=worktree_dir)
        finally:
            _run_git(["worktree", "remove", "--force", str(worktree_dir)], cwd=repo_root)

    return [raw_url(github_owner, repo, branch, name) for name in names]
