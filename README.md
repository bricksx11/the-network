# the-network

Automated multi-platform content pipeline for Bizyr's marketing (barber, dog groomer, car detailer, etc.
avatar accounts). Generates a carousel + a short vertical video per niche per day from a local image
library, and publishes/drafts them across Instagram, Facebook, TikTok, and YouTube.

Full architecture and rationale: see the plan this repo was built from —
`~/.claude/plans/wondrous-growing-marshmallow.md` on the machine that generated it, or ask Claude to
recap it.

## Status

Early build. Rendering pipeline (image selection, text overlay, video compile) is being built and
verified locally first, before any platform API integration. See `logs/` for nothing yet — that's
where per-run audit logs land once the orchestrator exists.

## Requirements

- Python 3.11+
- `ffmpeg` on PATH (already present via GitHub's `ubuntu-latest` runner image; install locally to test)
- See `requirements.txt` once dependencies are pinned

## Local dev

```
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest tests/
```
