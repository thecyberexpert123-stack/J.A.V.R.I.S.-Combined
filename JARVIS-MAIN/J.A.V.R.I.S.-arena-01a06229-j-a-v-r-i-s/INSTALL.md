# Installing JARVIS

JARVIS is a pure-Python package with **zero runtime dependencies** (stdlib only,
Python ≥ 3.10). Every artifact below contains the same code — pick the one that
fits your workflow. Import package: `jarvis` · distribution name: `jarvis-agent` ·
console command: `jarvis`.

## Recommended: pipx (any distro)

```sh
pipx install jarvis-agent        # from PyPI once published (owner-gated)
# or from a release artifact:
pipx install ./jarvis_agent-<version>-py3-none-any.whl
jarvis --version
```

## Debian / Ubuntu (.deb)

```sh
sudo apt-get install ./jarvis-agent_<version>_all.deb
jarvis --version
```

The deb is self-contained: it installs its own library copy to
`/usr/share/jarvis/lib` and a `/usr/bin/jarvis` shim. It depends only on
`python3 (>= 3.10)` — nothing is fetched at install time.

## Fedora / RHEL (.rpm)

```sh
sudo dnf install ./jarvis-agent-<version>-1.noarch.rpm
jarvis --version
```

Same self-contained layout as the deb (`/usr/share/jarvis/lib` + shim).

## Arch / AUR

Use `packaging/arch/PKGBUILD` (in-repo; AUR publication is pending the owner's
LICENSE decision):

```sh
makepkg -f            # builds jarvis-agent-<version>-1-any.pkg.tar.zst
sudo pacman -U ./jarvis-agent-<version>-1-any.pkg.tar.zst
```

## Alpine / minimal images (wheel)

```sh
apk add python3 py3-pip
PIP_BREAK_SYSTEM_PACKAGES=1 pip install jarvis_agent-<version>-py3-none-any.whl
```

## From source

```sh
git clone https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.
cd J.A.V.R.I.S.
pip install .
```

## Teaching JARVIS a new app (app packs, ADR-0026)

No playbook for your app yet? Teach it in minutes — a small JSON pack, no code:

```sh
jarvis app-skill wizard --file my-app.json   # validate-by-construction + receipt
jarvis app-skill list                        # what JARVIS knows
jarvis do "<one of your phrases>"            # consented run, plan displayed
```

See the README's "Unknown apps & owner-taught packs" section for the pack format and the
walls that apply to every step.

## AI models (optional but recommended)

The deterministic engine works with zero AI. For open-ended planning, JARVIS
is local-first (ADR-0003/0025) and dual-path with disclosed failover:

```sh
# local (recommended): Ollama + a small agentic-class model
ollama pull llama3.2              # 3B class: small machines
# or: ollama pull llama3.1        # 8B class: strongest local tool-calling
# or: ollama pull qwen2.5:7b      # 9B-class alternative if you have 8 GB VRAM
export JARVIS_LOCAL_MODEL=llama3.2   # optional override

# remote (opt-in): any OpenAI-compatible endpoint
export JARVIS_OPENAI_API_KEY=...  # env only, never logged
# export JARVIS_OPENAI_BASE_URL=https://api.openai.com/v1
# export JARVIS_OPENAI_MODEL=gpt-4o-mini
# export JARVIS_REMOTE_LLM=0      # hard-disable the remote path

jarvis ai status                  # both paths: liveness, models, breakers
```

If local fails, a configured remote is tried and **the serving backend is
always disclosed** in the output. `--no-ai` (or `JARVIS_NO_AI=1`) disables
every AI path in one switch.

## First run

```sh
jarvis status                      # fingerprint this machine + what JARVIS found
jarvis explain "what is ostype"    # cited knowledge, verified on this machine
jarvis do "install htop"           # engine playbook (T1) — watch the guards
jarvis gui status                  # what your desktop can do (honest matrix)
```

Nothing destructive runs without your explicit consent (T2 asks, T3 is refused
by policy), every action is journalled (`jarvis tasks`, `jarvis undo`), and the
knowledge layer cites sources or refuses to answer.

## Telemetry

**There is none.** No analytics, no phone-home, no crash reporting. Whether an
opt-in mechanism ever exists is an explicit owner decision.
