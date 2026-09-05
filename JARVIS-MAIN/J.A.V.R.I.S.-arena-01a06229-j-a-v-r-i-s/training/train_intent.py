"""Deterministic trainer for the tiny intent classifier (ADR-0015, ADR-0023).

Pure-stdlib training for a purpose-built, JARVIS-specific network: hashed
n-gram features (vectorizer imported from the runtime module — single source
of truth), one 48-unit ReLU hidden layer, softmax over the playbook ids plus
an explicit ``unknown`` class (the structural abstention).

Run from the repository root:

    python training/train_intent.py --out src/jarvis/intent/model.json

Deterministic: fixed seed, fixed op order → the committed model.json is
reproducible byte-for-byte. The vocabulary is DERIVED, not hand-listed:
``LABELS = sorted(PLAYBOOKS ids) + [unknown]`` (ADR-0023 D1 — the kernel
owns the vocabulary; a catalog change flows into the next training run and
the tests make staleness loud). Gates are enforced before any weights are
written, on the rounded shipped artifact: top-1 >= 0.88 and top-3 >= 0.97
on a stratified holdout, unknown-recall (abstention) >= 0.80 on an
out-of-distribution pool. The stratified split happens on UNIQUE texts
before any upsampling, so the holdout never sees a duplicate. The trainer
never runs at runtime and is not part of the wheel — inference is the only
shipped code.
"""

from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from jarvis.intent.classifier import (
    FEATURE_DIM,
    HIDDEN,
    MODEL_FORMAT,
    PROPOSE_THRESHOLD,
    UNKNOWN_LABEL,
    _features,
)
from jarvis.planner.playbooks import PLAYBOOKS

SEED = 20260904
EPOCHS = 12
LR = 0.35
LR_DECAY = 0.75
TARGET_PER_LABEL = 520
UNKNOWN_TARGET = 1600

# ADR-0023 D1: the kernel owns the vocabulary — sorted playbook ids + unknown.
# ADR-0026 D5: owner-taught playbooks (gui.app) have no static matcher surface
# (phrases live in receipt-pinned owner packs), so the classifier cannot
# template or suggest them — they are excluded from the label vocabulary.
OWNER_TAUGHT: frozenset[str] = frozenset({"gui.app"})
LABELS: list[str] = [
    *sorted({p.id for p in PLAYBOOKS} - OWNER_TAUGHT),
    UNKNOWN_LABEL,
]

_PACKAGES = [
    "htop",
    "curl",
    "vim",
    "git",
    "tmux",
    "jq",
    "tree",
    "wget",
    "ripgrep",
    "make",
    "openssl",
    "gzip",
    "bat",
    "fzf",
    "ncdu",
    "bmon",
    "strace",
    "lsof",
    "zip",
    "unrar",
]
_UNITS = [
    "nginx",
    "ssh",
    "docker",
    "cron",
    "bluetooth",
    "cups",
    "postgresql",
    "redis",
    "apache2",
    "tailscale",
    "ufw",
    "networkd",
]
_APPS = [
    "firefox",
    "code",
    "terminal",
    "files",
    "calculator",
    "gedit",
    "thunderbird",
    "vlc",
    "gimp",
    "chromium",
    "evolution",
    "nautilus",
]
_QUERIES = [
    "text editor",
    "web browser",
    "pdf reader",
    "music player",
    "terminal emulator",
    "markdown editor",
    "archive manager",
    "screenshot tool",
    "disk usage analyzer",
    "password manager",
    "video player",
    "note taking app",
]
_LINES = [
    "remember the milk",
    "deploy on friday",
    "server alpha details",
    "call the bank at 4",
    "rotate the logs weekly",
    "buy coffee beans",
]
_PATHS = [
    "~/notes.txt",
    "/tmp/TODO",
    "~/work/log.txt",
    "~/checklist.md",
    "~/ideas.txt",
    "/var/log/syslog",
    "~/documents/report.md",
    "/etc/hosts",
    "~/projects/main.py",
    "~/.bashrc",
    "~/documents/invoice.pdf",
    "/var/log/boot.log",
    "~/scratch/draft.txt",
    "~/work/notes.md",
    "/tmp/build/output.log",
    "~/recipes.txt",
    "~/work/timesheet.csv",
    "~/music/playlist.m3u",
]
_PATHS2 = [
    "/tmp/TODO",
    "~/archive/copy.txt",
    "~/documents/mirror.md",
    "/tmp/staging.txt",
    "~/backup/notes.txt",
    "~/documents/duplicate.pdf",
]
_DIRS = [
    "~/Documents",
    "~/Downloads",
    "~/projects",
    "/var/tmp",
    "~/music",
    "~/pictures",
    "/tmp",
    "~/work/archive",
    "~/code",
    "~/videos",
]
_NAMES = ["photos", "reports", "backups", "scratch", "invoices", "templates", "summary", "draft"]
_NAMES2 = ["final", "renamed", "archive-new", "v2", "old", "merged"]
_HOSTS = [
    "example.com",
    "router.local",
    "8.8.8.8",
    "archive.ubuntu.com",
    "myserver.home",
    "gateway",
    "wikipedia.org",
    "192.168.1.1",
]
_PROCS = ["chrome", "spotify", "code", "slack", "java", "python", "vlc", "gimp"]
_PIDS = ["1234", "2345", "8080", "4321", "9999", "5432", "7788", "3141"]
_TERMS = ["TODO", "ERROR", "deploy", "deadline", "meeting", "config", "port", "warning"]

_TEMPLATES: dict[str, list[str]] = {
    "pkg.install": [
        "install {p}",
        "install {p} and {q}",
        "please install {p}",
        "install the {p} package",
        "can you install {p}",
        "i need {p} installed",
        "add {p} to my machine",
        "get {p} on this box",
        "put {p} on my system",
        "set up {p} for me",
        "could you add the {p} package",
        "help me install {p}",
        "install both {p} and {q}",
        "i want {p} on here",
        "install {p} {q}",
        "get me {p}",
        "i need {p} on this machine",
        "need {p} on here",
        "i need the {p} package",
        "install {p} for me",
    ],
    "pkg.remove": [
        "remove {p}",
        "uninstall {p}",
        "please remove {p}",
        "get rid of {p}",
        "remove the {p} package",
        "delete {p} from my system",
        "i don't need {p} anymore",
        "uninstall {p} and {q}",
        "take {p} off this machine",
        "can you remove {p}",
        "remove {p} {q}",
        "uninstall the {p} package now",
    ],
    "pkg.search": [
        "search for a {query}",
        "search {query}",
        "find a {query}",
        "find me a {query}",
        "look for {query} packages",
        "search packages for a {query}",
        "is there a {query} available",
        "find {query}",
        "search for {query}",
        "any good {query} in the repos",
    ],
    "pkg.info": [
        "info {p}",
        "info about {p}",
        "details about {p}",
        "show {p}",
        "show info for {p}",
        "what is the {p} package",
        "tell me about the {p} package",
        "details for {p}",
        "show details about {p}",
        "info on the {p} package",
    ],
    "pkg.cache.refresh": [
        "update",
        "update the package cache",
        "update the package index",
        "refresh the package lists",
        "update package lists",
        "refresh repositories",
        "update the repos",
        "sync the package index",
        "update my package lists",
        "refresh the package index",
        "update the package lists now",
    ],
    "pkg.upgrade": [
        "upgrade the system",
        "upgrade my system",
        "update the whole system",
        "update everything",
        "upgrade all packages",
        "upgrade installed packages",
        "bring the system up to date",
        "full system upgrade",
        "update all",
        "do a system upgrade",
        "upgrade the whole machine",
        "update the system",
    ],
    "svc.status": [
        "status of {u}",
        "status of the {u} service",
        "is {u} running",
        "check {u} status",
        "show the status of {u}",
        "what's the status of {u}",
        "is the {u} service active",
        "state of the {u} unit",
        "is {u} active",
    ],
    "svc.start": [
        "start {u}",
        "start the {u} service",
        "start {u} now",
        "bring {u} up",
        "turn on the {u} service",
        "can you start {u}",
        "fire up {u}",
        "get {u} running",
        "start {u} service",
    ],
    "svc.enable": [
        "enable {u}",
        "enable the {u} service",
        "enable {u} at boot",
        "make {u} start on boot",
        "enable {u} on startup",
        "have {u} start automatically",
        "enable {u} to run at boot",
        "set {u} to start on boot",
    ],
    "sys.info": [
        "system info",
        "show system info",
        "system information",
        "what distro am i on",
        "give me system details",
        "hardware and os details",
        "about this machine",
        "machine fingerprint",
        "what hardware is this",
        "show os details",
        "system details please",
        "what os and hardware do i have",
        "system summary",
        "show machine info",
        "what distro is this",
        "machine info",
    ],
    "gui.launch": [
        "open {a}",
        "launch {a}",
        "run {a}",
        "start the {a} app",
        "open up {a}",
        "launch the {a} application",
        "can you open {a}",
        "fire up {a}",
        "open the {a} program",
        "run the {a} application for me",
    ],
    "file.append": [
        "append this line to {path}",
        "append {line} to {path}",
        "add the line {line} to {path}",
        "write {line} to the end of {path}",
        "append a line to {path}",
        "put {line} into {path}",
    ],
    # ---- fs family (ADR-0023 D3: phrasings mirror the real matchers) ----
    "fs.list": [
        "list the files in {dir}",
        "show {dir}",
        "what is in {dir}",
        "list {dir} contents",
        "show the contents of {dir}",
        "files in {dir}",
        "list files in {dir} long form",
        "detailed listing of {dir}",
        "list {dir} with details",
        "show me what is inside {dir}",
        "list everything in {dir}",
        "long listing for {dir}",
    ],
    "fs.read": [
        "show the contents of {path}",
        "read {path}",
        "print {path}",
        "display {path}",
        "what is inside {path}",
        "show me {path} contents",
        "print the contents of {path}",
        "read out {path}",
        "show the whole file {path}",
        "contents of {path} please",
        "read the file {path}",
        "print out {path}",
    ],
    "fs.head": [
        "show the first lines of {path}",
        "first 20 lines of {path}",
        "head of {path}",
        "show the top of {path}",
        "beginning of {path} please",
        "show first lines from {path}",
        "the first few lines of {path}",
        "peek at the start of {path}",
        "show the beginning of {path}",
        "first lines in {path}",
        "top lines of {path}",
        "head {path}",
    ],
    "fs.tail": [
        "show the last lines of {path}",
        "last 20 lines of {path}",
        "tail of {path}",
        "show the end of {path}",
        "final lines of {path}",
        "show the last few lines of {path}",
        "end of {path} please",
        "bottom of {path}",
        "last lines from {path}",
        "show tail of {path}",
        "the latest lines in {path}",
        "tail {path}",
    ],
    "fs.count": [
        "count lines in {path}",
        "how many lines in {path}",
        "word count for {path}",
        "count the words in {path}",
        "how many bytes is {path}",
        "line count of {path}",
        "count lines words and bytes in {path}",
        "size in lines of {path}",
        "how many lines does {path} have",
        "count everything in {path}",
        "lines words bytes for {path}",
        "count up {path}",
    ],
    "fs.stat": [
        "metadata for {path}",
        "show {path} metadata",
        "file info for {path}",
        "when was {path} last modified",
        "permissions of {path}",
        "exact size of {path}",
        "show stats for {path}",
        "details and times for {path}",
        "stat info on {path}",
        "ownership of {path}",
        "show file metadata for {path}",
        "stat {path}",
    ],
    "fs.file_type": [
        "what type of file is {path}",
        "file type of {path}",
        "identify {path}",
        "what kind of file is {path}",
        "is {path} text or binary",
        "tell me the type of {path}",
        "mime type of {path}",
        "what format is {path}",
        "identify the file {path}",
        "type of the file {path}",
        "what is the file type for {path}",
        "classify the file {path}",
    ],
    "fs.which": [
        "where is {p} installed",
        "which {p}",
        "locate {p} on path",
        "find the {p} binary",
        "where does {p} live",
        "which {p} binary runs",
        "path to {p}",
        "resolve {p} on my path",
        "is {p} on my path",
        "where is the {p} program",
        "which directory holds {p}",
        "locate the {p} executable",
    ],
    "fs.disk_usage": [
        "how much space does {dir} use",
        "disk usage of {dir}",
        "size of {dir} on disk",
        "how big is {dir}",
        "space used by {dir}",
        "disk usage for {dir} human readable",
        "show the size of {dir}",
        "how much storage does {dir} take",
        "total size of {dir}",
        "measure {dir} size",
        "space taken by {dir}",
        "disk usage summary for {dir}",
    ],
    "fs.disk_free": [
        "disk free",
        "how much disk space is free",
        "free space on my disks",
        "show filesystem usage",
        "disk usage per filesystem",
        "how full are my disks",
        "storage left on this machine",
        "free space per mount",
        "show free disk space",
        "how much space is left",
        "free space on the filesystems",
        "disk space report",
    ],
    "sys.checksum": [
        "md5 of {path}",
        "checksum of {path}",
        "compute the md5 checksum for {path}",
        "hash of {path}",
        "what is the md5 for {path}",
        "verify {path} with md5",
        "md5 digest of {path}",
        "give me the checksum for {path}",
        "calculate md5 for {path}",
        "fingerprint {path} with md5",
        "checksum the file {path}",
        "md5 sum of {path}",
    ],
    "sys.memory": [
        "memory usage",
        "show memory usage",
        "how much ram is free",
        "ram and swap usage",
        "how is memory doing",
        "free memory on this machine",
        "show ram usage",
        "memory and swap",
        "how much memory is used",
        "is swap in use",
        "memory stats please",
        "show me memory and swap usage",
    ],
    "sys.processes": [
        "list running processes",
        "show processes",
        "what processes are running",
        "process list",
        "show all processes",
        "running processes full format",
        "list every process",
        "show me the processes on this machine",
        "what is running right now",
        "all running processes please",
        "process table",
        "show the running processes",
    ],
    "sys.uptime": [
        "uptime",
        "how long has this machine been up",
        "show uptime",
        "system uptime and load",
        "load averages",
        "how long since last boot",
        "uptime and load averages please",
        "show uptime and load",
        "time since boot",
        "load average now",
        "uptime stats",
        "how long has the system been running",
    ],
    "sys.date": [
        "date and time",
        "what time is it",
        "current date and time",
        "show the date",
        "what is today",
        "system date",
        "what day is it",
        "show date and time now",
        "tell me the time",
        "current time please",
        "what is the date today",
        "clock check",
    ],
    "sys.hostname": [
        "hostname",
        "what is my hostname",
        "show the machine name",
        "name of this computer",
        "what is this machine called",
        "hostname of this system",
        "show hostname",
        "machine name please",
        "what hostname am i on",
        "the computer name",
        "name of this machine",
        "show the hostname",
    ],
    "sys.cpus": [
        "cpu info",
        "show cpu information",
        "what cpu do i have",
        "processor details",
        "cpu model and cores",
        "how many cores does this machine have",
        "show processor info",
        "what processor is in this machine",
        "cpu details",
        "information about the cpu",
        "cores and clock speed",
        "cpu information please",
    ],
    "sys.pci": [
        "list pci devices",
        "pci devices",
        "show pci hardware",
        "what pci hardware is installed",
        "list the pci bus",
        "pci hardware listing",
        "show devices on the pci bus",
        "what hardware is on the pci bus",
        "pci inventory",
        "show my pci cards",
        "pci device list",
        "enumerate pci hardware",
    ],
    "sys.usb": [
        "list usb devices",
        "usb devices",
        "show usb hardware",
        "what is plugged into usb",
        "usb device list",
        "show connected usb devices",
        "what usb hardware is attached",
        "list the usb bus",
        "usb inventory",
        "show my usb peripherals",
        "enumerate usb hardware",
        "usb devices on this machine",
    ],
    "sys.blocks": [
        "list block devices",
        "show disks and partitions",
        "block devices",
        "what disks do i have",
        "list drives and partitions",
        "show the disk layout",
        "storage devices on this machine",
        "disks and partitions listing",
        "show my block devices",
        "what storage is attached",
        "block device overview",
        "list disks and partitions",
    ],
    "sys.sockets": [
        "listening sockets",
        "list listening ports",
        "show sockets",
        "what ports are listening",
        "list tcp and udp listeners",
        "show listening services ports",
        "open listening sockets",
        "which ports are open",
        "listening ports on this machine",
        "sockets numeric listing",
        "show the listening sockets",
        "listening port table",
    ],
    "sys.network": [
        "network interfaces",
        "show network interfaces",
        "ip addresses of this machine",
        "show my ip",
        "network configuration",
        "list interfaces and addresses",
        "what is my ip address",
        "show nic information",
        "network setup of this machine",
        "interfaces and ips",
        "show my network adapters",
        "network interface report",
    ],
    "sys.routes": [
        "routing table",
        "show the routing table",
        "network routes",
        "show routes",
        "how are packets routed",
        "list the kernel routes",
        "show ip routing table",
        "default route",
        "routing info",
        "show the kernel routing table",
        "route listing",
        "network routing table",
    ],
    "sys.journal": [
        "show the journal",
        "last journal entries",
        "systemd journal tail",
        "recent system logs",
        "show the last 50 journal entries",
        "show recent systemd logs",
        "service logs recent",
        "last 50 log lines from the journal",
        "system journal please",
        "recent boot logs",
        "show me the systemd journal",
        "journal recent entries",
    ],
    "sys.kernel_log": [
        "kernel log",
        "show the kernel ring buffer",
        "kernel messages",
        "show dmesg output",
        "ring buffer contents",
        "recent kernel messages",
        "kernel log output",
        "what did the kernel log",
        "show low level kernel messages",
        "hardware messages from the kernel",
        "kernel ring buffer please",
        "read the kernel log",
    ],
    "sys.users": [
        "who is logged in",
        "logged in users",
        "show users on this machine",
        "who is on this system",
        "list logged in users",
        "current sessions",
        "show active users",
        "who is logged on",
        "user sessions now",
        "logged on users please",
        "show who is here",
        "list the current users",
    ],
    "sys.login_history": [
        "last logins",
        "login history",
        "show recent logins",
        "who logged in recently",
        "last 20 logins",
        "login records",
        "recent login history",
        "show the last logins",
        "previous logins",
        "last sessions on this machine",
        "history of logins",
        "show recent session history",
    ],
    "sys.env": [
        "environment variables",
        "print environment",
        "show my env",
        "list environment variables",
        "show exported variables",
        "print all env vars",
        "what environment variables are set",
        "environment listing",
        "show the environment",
        "dump environment variables",
        "my env please",
        "env variable report",
    ],
    "sys.identity": [
        "my user and groups",
        "show my id",
        "current user and groups",
        "what user am i",
        "show uid and gid",
        "my identity on this machine",
        "which user and groups",
        "identity info",
        "show my user identity",
        "user and group listing",
        "id of the current user",
        "my uid and groups",
    ],
    "net.ping": [
        "ping {host}",
        "ping {host} four times",
        "can you ping {host}",
        "check if {host} is reachable",
        "ping the host {host}",
        "reachability check for {host}",
        "test connectivity to {host}",
        "is {host} reachable",
        "send four pings to {host}",
        "network check on {host}",
        "ping {host} ipv4",
        "try to reach {host}",
    ],
    "net.dns": [
        "resolve {host}",
        "dns lookup for {host}",
        "what ip does {host} resolve to",
        "resolve the name {host}",
        "look up {host} in dns",
        "ip address of {host}",
        "what is the address of {host}",
        "name resolution for {host}",
        "find the ip of {host}",
        "dns query for {host}",
        "what does {host} resolve to",
        "resolve {host} to an ip",
    ],
    "fs.find": [
        "find files named {name}",
        "find {name} under {dir}",
        "search for files called {name}",
        "locate the file {name} in {dir}",
        "find a file named {name}",
        "where is the file {name}",
        "find {name} recursively",
        "search {dir} for the file {name}",
        "file search for {name}",
        "find named {name} please",
        "hunt for {name} under {dir}",
        "look for a file called {name}",
    ],
    "fs.search": [
        "search {path} for {term}",
        "find the string {term} in {path}",
        "search for {term} under {dir}",
        "does {path} contain {term}",
        "look for {term} in {path}",
        "fixed string search for {term}",
        "search text {term} in {path}",
        "find lines with {term} in {path}",
        "is {term} in {path}",
        "search inside {path} for {term}",
        "grep the file {path} for {term}",
        "occurrences of {term} in {path}",
    ],
    "fs.mkdir": [
        "create a directory called {name} in {dir}",
        "make a new folder {name}",
        "create the folder {name}",
        "new directory {name} under {dir}",
        "make directory {name}",
        "i need a folder named {name}",
        "make me a directory {name}",
        "create a folder {name} here",
        "new dir {name}",
        "make a folder called {name} in {dir}",
        "create directory {name}",
        "set up a {name} folder",
    ],
    "fs.touch": [
        "create an empty file {name}",
        "make an empty file called {name}",
        "new file {name}",
        "create {name}",
        "touch the file {name}",
        "i need an empty file {name}",
        "make {name} if missing",
        "create a blank {name}",
        "empty file named {name}",
        "new blank file {name}",
        "create the file {name}",
        "make a file named {name}",
    ],
    "fs.copy": [
        "copy {path} to {path2}",
        "copy the file {path} to {path2}",
        "duplicate {path} as {path2}",
        "make a copy of {path} at {path2}",
        "copy {path} into {dir}",
        "backup copy of {path} to {path2}",
        "clone {path} to {path2}",
        "copy over {path} to {path2}",
        "put a duplicate of {path} in {dir}",
        "transfer a copy of {path} to {path2}",
        "copy the file at {path} to {path2} please",
        "save a copy of {path} in {dir}",
    ],
    "fs.move": [
        "move {path} to {dir}",
        "rename {path} to {name2}",
        "move the file {path} into {dir}",
        "relocate {path} to {dir}",
        "change {path} name to {name2}",
        "move {path} over to {dir}",
        "rename the file {path} as {name2}",
        "shift {path} into {dir}",
        "move {path} to {path2} please",
        "put {path} in {dir} instead",
        "transfer {path} to {dir}",
        "rename {path} as {name2}",
    ],
    "fs.remove": [
        "delete {path}",
        "remove the file {path}",
        "delete the file {path}",
        "get rid of the file {path}",
        "erase {path}",
        "please delete the file {path}",
        "remove {path} from disk",
        "delete this file: {path}",
        "trash the file {path}",
        "delete single file {path}",
        "remove the file at {path}",
        "delete the {path} file",
    ],
    "fs.link": [
        "symlink {path} to {path2}",
        "create a link to {path} named {path2}",
        "link {path} as {path2}",
        "make a symbolic link {path2} pointing to {path}",
        "soft link {path} to {path2}",
        "create symlink at {path2} for {path}",
        "symbolic link from {path} to {path2}",
        "link the file {path} to {path2}",
        "new symlink {path2} for {path}",
        "point {path2} at {path}",
        "make {path2} a link to {path}",
        "symlink the file {path} at {path2}",
    ],
    "svc.stop": [
        "stop {u}",
        "stop the {u} service",
        "stop {u} now",
        "shut down the {u} service",
        "halt {u}",
        "bring {u} down",
        "stop service {u}",
        "turn off the {u} service",
        "stop the {u} unit",
        "end the {u} service",
        "stop {u} for now",
        "shut the {u} unit down",
    ],
    "svc.restart": [
        "restart {u}",
        "restart the {u} service",
        "bounce {u}",
        "restart {u} now",
        "reload the {u} service",
        "restart service {u}",
        "cycle the {u} service",
        "restart the {u} unit",
        "give {u} a restart",
        "start {u} again",
        "restart {u} please",
        "do a restart of {u}",
    ],
    "svc.disable": [
        "disable {u}",
        "disable the {u} service",
        "keep {u} from starting at boot",
        "disable {u} at boot",
        "stop {u} from starting on startup",
        "turn off {u} autostart",
        "disable the {u} unit",
        "make sure {u} does not start at boot",
        "remove {u} from boot",
        "disable autostart for {u}",
        "no boot start for {u}",
        "disable the {u} daemon",
    ],
    "proc.kill": [
        "kill process {num}",
        "terminate pid {num}",
        "kill pid {num}",
        "end process {num}",
        "send sigterm to {num}",
        "stop process id {num}",
        "kill the process {num}",
        "terminate the process with pid {num}",
        "signal process {num} to stop",
        "gracefully stop pid {num}",
        "end pid {num}",
        "kill the process with id {num}",
    ],
    "proc.kill_name": [
        "kill the {proc} process",
        "stop all {proc} processes",
        "terminate {proc}",
        "end the {proc} process",
        "kill processes named {proc}",
        "stop {proc} by name",
        "shut down the {proc} process",
        "terminate every {proc} process",
        "kill {proc} exactly by name",
        "stop the process called {proc}",
        "end processes named {proc}",
        "kill that {proc} process",
    ],
    "sys.digest": [
        "system digest",
        "machine digest",
        "health check",
        "run a health check",
        "analyze my system",
        "analyze the system",
        "analyse my system",
        "digest the system",
        "system overview",
        "system health report",
        "give me a system digest",
        "synthesize the system state",
        "system synthesis",
        "machine health",
        "system report",
        "analyze this machine",
    ],
    UNKNOWN_LABEL: [
        "tell me a joke about {c}",
        "what's the weather in {c} tomorrow",
        "write me a poem about {a}",
        "order me a pizza",
        "play some jazz",
        "clean up my emails",
        "summarize this article about {t}",
        "translate hello to {lang}",
        "who won the match",
        "what is ostype",
        "explain systemd units to me",
        "how do i exit vim",
        "generate a password",
        "shutdown the machine",
        "reboot now",
        "set my volume to half",
        "change my wallpaper to {t}",
        "when is my next meeting",
        "book a flight to {c}",
        "remind me to call mom",
        "what's 2 plus 2",
        "draft an email to my boss",
        "fix my printer",
        "why is my computer slow",
        "backup my phone",
        "trim this video",
        "convert this pdf",
        "scrape that website",
        "train a model on my data",
        "scan that server for open ports",
        "delete my browsing history",
        "read me the news about {t}",
        "what time is it in {c}",
        "calculate my mortgage",
        "find my phone",
        "water the plants",
        "write a blog post about {t}",
    ],
}

_PREFIXES = ["", "please ", "can you ", "could you ", "hey jarvis ", "i want you to "]

_UNKNOWN_FILLERS = {
    "c": ["paris", "tokyo", "delhi", "london", "berlin", "lima"],
    "t": ["renewable energy", "ancient rome", "quantum computing", "street food", "jazz"],
    "lang": ["french", "japanese", "hindi", "swahili", "german"],
    "a": ["cats", "mountains", "rain", "summer", "the sea"],
}


def _label_target(label: str) -> int:
    return UNKNOWN_TARGET if label == UNKNOWN_LABEL else TARGET_PER_LABEL


def _unique_texts(rng: random.Random, label: str) -> list[str]:
    """Deterministically generate the unique phrasings for one label."""
    templates = _TEMPLATES[label]
    texts: set[str] = set()
    guard = 0
    target = _label_target(label)
    while len(texts) < target and guard < target * 40:
        guard += 1
        fillers = {
            "p": rng.choice(_PACKAGES),
            "q": rng.choice(_PACKAGES),
            "u": rng.choice(_UNITS),
            "a": rng.choice(_APPS),
            "query": rng.choice(_QUERIES),
            "line": rng.choice(_LINES),
            "path": rng.choice(_PATHS),
            "path2": rng.choice(_PATHS2),
            "dir": rng.choice(_DIRS),
            "name": rng.choice(_NAMES),
            "name2": rng.choice(_NAMES2),
            "host": rng.choice(_HOSTS),
            "proc": rng.choice(_PROCS),
            "num": rng.choice(_PIDS),
            "term": rng.choice(_TERMS),
        }
        if label == UNKNOWN_LABEL:
            for key, values in _UNKNOWN_FILLERS.items():
                fillers[key] = rng.choice(values)
        text = rng.choice(_PREFIXES) + rng.choice(templates).format(**fillers)
        texts.add(text)
    return sorted(texts)


def _corpus(rng: random.Random) -> list[tuple[str, int]]:
    """Unique (text, label-index) pairs per label, shuffled.

    The stratified holdout splits THIS list, before any upsampling, so the
    holdout measures unique phrasings only (ADR-0023 D3).
    """
    examples: list[tuple[str, int]] = []
    for label in LABELS:
        for text in _unique_texts(rng, label):
            examples.append((text, LABELS.index(label)))
    rng.shuffle(examples)
    return examples


def _upsample_train(train_set: list[tuple[str, int]], rng: random.Random) -> list[tuple[str, int]]:
    """Seeded bootstrap of the train split to a common per-label target."""
    by_label: dict[int, list[tuple[str, int]]] = {}
    for pair in train_set:
        by_label.setdefault(pair[1], []).append(pair)
    balanced: list[tuple[str, int]] = []
    for index, label in enumerate(LABELS):
        group = by_label.get(index, [])
        if not group:
            continue
        balanced.extend(group)
        target = _label_target(label)
        count = len(group)
        while count < target:
            balanced.append(group[rng.randrange(len(group))])
            count += 1
    rng.shuffle(balanced)
    return balanced


def _forward(
    model: dict[str, object], buckets: dict[int, float]
) -> tuple[list[float], list[float]]:
    w1: list[list[float]] = model["w1"]  # type: ignore[assignment]
    b1: list[float] = model["b1"]  # type: ignore[assignment]
    w2: list[list[float]] = model["w2"]  # type: ignore[assignment]
    b2: list[float] = model["b2"]  # type: ignore[assignment]
    acc = list(b1)
    for index, value in buckets.items():
        row = w1[index]
        for j in range(HIDDEN):
            acc[j] += value * row[j]
    hidden = [value if value > 0.0 else 0.0 for value in acc]
    n_classes = len(b2)
    logits = [b2[k] + sum(hidden[j] * w2[j][k] for j in range(HIDDEN)) for k in range(n_classes)]
    peak = max(logits)
    exps = [math.exp(value - peak) for value in logits]
    total = sum(exps)
    return hidden, [value / total for value in exps]


def train(examples: list[tuple[str, int]]) -> dict[str, object]:
    rng = random.Random(SEED)
    # Random init breaks the ReLU symmetry: at W1=W2=0 every hidden unit is
    # dead (relu(0)=0), dh = W2*d2 = 0 forever, and only b2 would ever learn.
    model: dict[str, object] = {
        "w1": [[rng.uniform(-0.14, 0.14) for _ in range(HIDDEN)] for _ in range(FEATURE_DIM)],
        "b1": [0.0] * HIDDEN,
        "w2": [[rng.uniform(-0.2, 0.2) for _ in range(len(LABELS))] for _ in range(HIDDEN)],
        "b2": [0.0] * len(LABELS),
    }
    dataset = [(text, label, _features(text)) for text, label in examples]
    lr = LR
    for epoch in range(EPOCHS):
        order = list(range(len(dataset)))
        rng.shuffle(order)
        loss = 0.0
        w1: list[list[float]] = model["w1"]  # type: ignore[assignment]
        b1: list[float] = model["b1"]  # type: ignore[assignment]
        w2: list[list[float]] = model["w2"]  # type: ignore[assignment]
        b2: list[float] = model["b2"]  # type: ignore[assignment]
        for position in order:
            _text, label, buckets = dataset[position]
            hidden, probs = _forward(model, buckets)
            loss += -math.log(max(probs[label], 1e-12))
            d2 = [probs[k] - (1.0 if k == label else 0.0) for k in range(len(LABELS))]
            for k, grad in enumerate(d2):
                b2[k] -= lr * grad
            # Backprop through the ReLU with PRE-update w2, then update both
            # layers. dL/dW1[bucket][j] = x[bucket] * dh[j] for active j.
            for j in range(HIDDEN):
                if hidden[j] <= 0.0:
                    continue
                w2row = w2[j]
                back = 0.0
                for k in range(len(LABELS)):
                    back += w2row[k] * d2[k]
                step = lr * back
                b1[j] -= step
                for index, value in buckets.items():
                    w1[index][j] -= step * value
                for k in range(len(LABELS)):
                    w2row[k] -= lr * d2[k] * hidden[j]
        if epoch % 3 == 2:
            print(f"  epoch {epoch + 1}/{EPOCHS}  loss/example={loss / len(dataset):.4f}")
        lr *= LR_DECAY
    return model


def evaluate(model: dict[str, object], examples: list[tuple[str, int]]) -> dict[str, float]:
    correct_top1 = correct_top3 = 0
    for text, label in examples:
        probs = _forward(model, _features(text))[1]
        order = sorted(range(len(probs)), key=lambda k: probs[k], reverse=True)
        if order[0] == label:
            correct_top1 += 1
        if label in order[:3]:
            correct_top3 += 1
    n = max(len(examples), 1)
    return {"top1": correct_top1 / n, "top3": correct_top3 / n}


def worst_confusions(
    model: dict[str, object], examples: list[tuple[str, int]], limit: int = 6
) -> list[str]:
    """Diagnostics for corpus tuning: the most-confused label pairs."""
    counts: dict[tuple[str, str], int] = {}
    for text, label in examples:
        probs = _forward(model, _features(text))[1]
        order = sorted(range(len(probs)), key=lambda k: probs[k], reverse=True)
        if order[0] != label:
            key = (LABELS[label], LABELS[order[0]])
            counts[key] = counts.get(key, 0) + 1
    ranked = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [f"{src} -> {dst}: {n}" for (src, dst), n in ranked[:limit]]


def unknown_recall(model: dict[str, object], ood: list[str]) -> float:
    """Abstention rate: argmax is unknown, OR no intent clears the threshold."""
    abstained = 0
    unknown_index = LABELS.index(UNKNOWN_LABEL)
    for text in ood:
        probs = _forward(model, _features(text))[1]
        order = sorted(range(len(probs)), key=lambda k: probs[k], reverse=True)
        if order[0] == unknown_index or probs[order[0]] < PROPOSE_THRESHOLD:
            abstained += 1
    return abstained / max(len(ood), 1)


def _stratified_holdout(
    examples: list[tuple[str, int]], rng: random.Random, fraction: float
) -> tuple[list[tuple[str, int]], list[tuple[str, int]]]:
    by_label: dict[int, list[tuple[str, int]]] = {}
    for pair in examples:
        by_label.setdefault(pair[1], []).append(pair)
    holdout: list[tuple[str, int]] = []
    train_set: list[tuple[str, int]] = []
    for _label, group in sorted(by_label.items()):
        rng.shuffle(group)
        cut = max(1, int(len(group) * fraction))
        holdout.extend(group[:cut])
        train_set.extend(group[cut:])
    rng.shuffle(train_set)
    return train_set, holdout


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="src/jarvis/intent/model.json")
    args = parser.parse_args()

    rng = random.Random(SEED)
    examples = _corpus(rng)
    train_set, holdout = _stratified_holdout(examples, rng, fraction=0.1)
    print(f"vocabulary: {len(LABELS)} classes ({len(LABELS) - 1} playbook ids + unknown)")
    print(
        f"corpus: {len(examples)} unique examples ({len(train_set)} train / {len(holdout)} holdout)"
    )
    train_set = _upsample_train(train_set, rng)
    print(f"balanced train split: {len(train_set)} examples")

    model = train(train_set)

    # Gate the EXACT shipped artifact: round in place first (same rounding as
    # serialization), then evaluate — the gates describe model.json, not a
    # fuller-precision sibling of it.
    for matrix in ("w1", "w2"):
        model[matrix] = [
            [round(value, 5) for value in row]
            for row in model[matrix]  # type: ignore[arg-type,index-item]
        ]
    for vector in ("b1", "b2"):
        model[vector] = [round(value, 5) for value in model[vector]]  # type: ignore[arg-type,index-item]

    metrics = evaluate(model, holdout)
    ood_pool = [
        text
        for text, label in _corpus(random.Random(SEED + 1))
        if label == LABELS.index(UNKNOWN_LABEL)
    ]
    recall = unknown_recall(model, ood_pool)
    print(f"holdout: top1={metrics['top1']:.3f} top3={metrics['top3']:.3f}")
    print(f"ood abstention (unknown recall): {recall:.3f}")
    for line in worst_confusions(model, holdout):
        print(f"  confusion: {line}")

    gates = metrics["top1"] >= 0.88 and metrics["top3"] >= 0.97 and recall >= 0.80
    if not gates:
        print("GATES FAILED — weights NOT written")
        return 1

    document = {
        "format": MODEL_FORMAT,
        "feature_dim": FEATURE_DIM,
        "hidden": HIDDEN,
        "seed": SEED,
        "labels": LABELS,
        "w1": model["w1"],  # type: ignore[dict-item]
        "b1": model["b1"],  # type: ignore[dict-item]
        "w2": model["w2"],  # type: ignore[dict-item]
        "b2": model["b2"],  # type: ignore[dict-item]
    }
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(document, separators=(",", ":")), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"wrote {out_path} ({size_kb:.0f} KB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
