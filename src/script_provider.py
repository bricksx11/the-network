"""Adapter to the real script/CTA generator -- explicitly out of scope for this build (per
plan: "generate today's script + CTA copy" is treated as a black-box input). This is a
minimal stub returning one hardcoded example so the rest of the pipeline (research_gate,
image_selector, rendering) has something real to run against end-to-end locally. Replace
get_todays_script() with the real generator; keep the Script contract it returns unchanged
so nothing downstream needs to know the difference.
"""

from __future__ import annotations

from src.research_gate import Script

# TODO: replace with the real script/CTA generator. This single hardcoded example exists
# only to prove the rest of the pipeline (research_gate -> image_selector -> render) works
# end-to-end against a real, gate-passing script.
_STUB_SCRIPT = Script(
    shape="money_reveal",
    hook="6 figures in one month. As a barber.",
    beats=[
        "I stopped keeping low-paying clients just to stay busy. I started making room for "
        "the bigger-paying regulars instead.",
        "I stopped losing clients after one cut. I built a simple system that actually got "
        "them rebooking instead of disappearing.",
    ],
    reveal=(
        "Missed calls were costing me more than I realized. So I found an app that answers "
        "my calls and messages, books customers in, and handles my website bookings."
    ),
    cta="Comment 'CALLS' and I'll send you the app",
    platform_cta_overrides={"youtube": "Link in bio"},
)


def get_todays_script(niche: str) -> Script:
    return _STUB_SCRIPT
