"""Thin re-export so orchestrator.py's `from src.script_provider import get_todays_script`
import site doesn't need to change. The real generation logic lives in
src/script_generator.py (see that module's docstring for the full story) -- this used to be
a hardcoded stub returning the same barber-flavored example regardless of niche, which was
the entire cause of the repetition problem. Kept as a separate, differently-named module
(script_generator.py) since "provider" undersold what it actually does now.
"""

from __future__ import annotations

from src.script_generator import generate_script as get_todays_script

__all__ = ["get_todays_script"]
