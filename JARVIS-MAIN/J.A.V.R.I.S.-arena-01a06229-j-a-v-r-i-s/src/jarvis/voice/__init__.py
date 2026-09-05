"""Voice front-end (ADR-0019): record → transcribe → the existing kernel → speak.

Voice is presentation, never authority: the transcribed text enters the same
match → plan → approve → execute → verify path as typed requests, and T2 is
not voice-consentable in this release (misrecognition must never manufacture
consent). All audio work is delegated to standard external binaries through
fixed argv (no shell, no new Python dependencies — ADR-0005/0006); a missing
binary is an honestly-reported absence, never a silent degrade.
"""

from __future__ import annotations
