# ADR-0019: Voice front-end — an I/O adapter into the existing kernel, not a new brain

- **Status:** Accepted and implemented (2026-09-04; owner-directed "continue the Major Milestone"
  — roadmap item R1 from `docs/RESEARCH-jarvis-agent-linux-2026.md`).
- **Context:** The research milestone identified voice as the highest-delight charter-compliant
  step toward the MCU target (film capabilities F1/F10: short spoken commands, calibrated
  responses). The local voice stack is mature (openWakeWord → whisper-class STT → Piper TTS), but
  those are heavyweight third-party models. ADR-0005 (stdlib-only Python runtime) and ADR-0006
  (argv-only, no shell) therefore shape the design: JARVIS ships **no new Python dependencies**
  and **no shell anywhere** — voice I/O is delegated to standard external binaries through fixed
  argv, exactly like every playbook the kernel already runs.

## Decision

**D1 — Voice is presentation, the kernel stays the only authority.** The voice module
(`src/jarvis/voice/`) owns three adapters — record → transcribe → speak — and feeds the
transcribed text into the **same** `Orchestrator.run_intent` path as typed requests. Match → plan
→ approve → execute → verify is byte-identical for a spoken request. No playbook is added for
audio; the adapters are I/O plumbing (fixed argv, validated paths, no shell), the same standing
GUI control has.

**D2 — External-binary adapters, probed honestly.** Detection mirrors `gui/detect.py`
(read-only, side-effect free, headless is a normal state):

- Recorder (probe order): `arecord` (`-r 16000 -f S16_LE -c 1 -d <1..15> <wav>`), `pw-record`.
- STT (probe order): `whisper-cli`, `whisper.cpp`, `whisper` with model path from
  `$JARVIS_STT_MODEL` (must exist; passed as one validated argv token).
- TTS: `piper` with `$JARVIS_TTS_MODEL`, response text piped via the Runner's `stdin_text`
  (argv frozen; the text is JARVIS's own response, never user argv).
- Player (probe order): `paplay`, `aplay -q`, `ffplay -nodisp -autoexit`.

A missing piece is an honestly-reported absence (`jarvis voice doctor`), never a silent
degrade: without TTS, responses print; without STT, `ask` accepts an explicit `--wav` file;
without a recorder, that is the only mode.

**D3 — Consent parity: T2 is not voice-consentable in this release.** Voice requests run under
the non-consenting policy (same construction as the MCP surface without `allow`): T0/T1 proceed
exactly as on a non-TTY CLI; **T2 refuses with the spoken preview hint** — the owner confirms
such actions by typing them with `--yes`, where the consent record lands in the journal. Rationale
(2026 security literature): speech misrecognition must never be able to manufacture per-call
consent for system-level actions. T3 is refused as always. Hands-free wake-word listening is
**parked**: an in-process wake-word engine would require new Python dependencies (an ADR-0005
exception needing owner sign-off), so this release is push-to-talk / one-shot by design.

**D4 — Boundaries.** Recorded audio and synthesized WAVs live under the state dir
(`voice/`), are never logged, and are overwritten per turn (no retained audio by default);
transcripts are printed and journaled as task params follow the existing journal rules; the
voice module never executes anything outside its three adapters.

## Consequences

- A Raspberry-Pi-class or GPU box with `whisper-cli` + `piper` + ALSA gets full spoken
  interaction with sub-2 s target latency (sentence-level streaming is deferred — one-shot
  responses only this release).
- The sandbox/CI (no audio hardware) exercises everything except real audio: detection honesty,
  argv templates, pipeline plumbing with stub binaries, kernel parity, and the T2 refusal —
  the same "honest skip" discipline as the live-test suites.
- If the owner later approves an `[voice]` extra (openwakeword, faster-whisper), only the
  detection table and this ADR change; the pipeline and consent model stand.
