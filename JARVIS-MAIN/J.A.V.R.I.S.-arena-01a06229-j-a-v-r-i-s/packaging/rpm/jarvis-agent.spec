Name:           jarvis-agent
Version:        1.10.2
Release:        1%{?dist}
Summary:        JARVIS (Just A Rather Very Intelligent System) — verified automation agent for Linux
License:        LicenseRef-Proprietary-Until-Owner-Decides
URL:            https://github.com/thecyberexpert123-stack/J.A.V.R.I.S.
Source0:        %{name}-%{version}-py3-none-any.whl
BuildArch:      noarch
Requires:       python3 >= 3.10

%description
Safety-kernelled task engine with LLM planning behind deterministic guards,
cited knowledge (cite-or-abstain), capability-matrix GUI control, journaling
and undo. Self-contained: ships its own library copy; requires only python3.

%prep
# nothing to prep: the wheel is the source

%build
# nothing to build: pure-Python wheel

%install
mkdir -p %{buildroot}/usr/share/jarvis/lib %{buildroot}/usr/bin
unzip -q %{SOURCE0} -d %{buildroot}/usr/share/jarvis/lib
cat > %{buildroot}/usr/bin/jarvis <<'SH'
#!/bin/sh
exec env PYTHONPATH="/usr/share/jarvis/lib${PYTHONPATH:+:$PYTHONPATH}" \
    python3 -m jarvis "$@"
SH
chmod 755 %{buildroot}/usr/bin/jarvis

%files
/usr/share/jarvis/lib
/usr/bin/jarvis

%changelog
* Tue Sep 02 2026 JARVIS owners <thecyberexpert123-stack@users.noreply.github.com> - 1.0.0-1
- v1.0.0: full milestone series (engine, planner, safety kernel, knowledge, GUI)
