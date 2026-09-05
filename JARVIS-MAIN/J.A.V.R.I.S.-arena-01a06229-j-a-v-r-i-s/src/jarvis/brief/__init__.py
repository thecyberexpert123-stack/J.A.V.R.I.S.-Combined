"""Scheduled briefings (ADR-0021): Level-2 proactivity, propose-only.

A briefing is computed from local state (journal, suggestions, unknown
requests, statvfs) — it never executes a command and never acts. A
deterministic policy decides notify-vs-silence per run, every decision is
ledgered, and feedback is recorded for a future (owner-gated) learned
interruption policy. Silence is a first-class outcome with a reason.
"""

from __future__ import annotations
