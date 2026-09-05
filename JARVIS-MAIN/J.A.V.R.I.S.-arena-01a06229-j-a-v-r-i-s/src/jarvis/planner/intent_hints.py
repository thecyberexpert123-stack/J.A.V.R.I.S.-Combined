"""Canonical intent hints for the LLM planner (ADR-0025 D1).

One engine-legal example phrase per playbook id. The planner's system prompt
is BUILT from this table + the live catalog at call time — never a hand-list
in a string literal. Two tests keep it honest: every hint must pass the real
``match_intent`` (a phrase the engine would refuse can never teach the
model), and the table must cover exactly the live catalog (staleness is a
CI failure — the ADR-0023 discipline applied to the planner).
"""

from __future__ import annotations

INTENT_HINTS: dict[str, str] = {
    "pkg.install": "install htop",
    "pkg.remove": "remove curl",
    "pkg.search": "search text editor",
    "pkg.info": "info git",
    "pkg.cache.refresh": "update the package cache",
    "pkg.upgrade": "upgrade the system",
    "svc.status": "status of nginx",
    "svc.start": "start nginx",
    "svc.enable": "enable redis",
    "svc.stop": "stop nginx",
    "svc.restart": "restart nginx",
    "svc.disable": "disable redis",
    "proc.kill": "kill process 1234",
    "proc.kill_name": "stop processes named spotify",
    "sys.info": "system info",
    "sys.digest": "system digest",
    "fs.list": "list the files in ~/Documents",
    "fs.read": "show the contents of ~/notes.txt",
    "fs.head": "show the first 20 lines of ~/notes.txt",
    "fs.tail": "show the last 20 lines of /var/log/syslog",
    "fs.count": "count lines in ~/notes.txt",
    "fs.stat": "stat ~/notes.txt",
    "fs.file_type": "what type of file is /etc/hosts",
    "fs.which": "which git",
    "fs.disk_usage": "how much space does ~/projects use",
    "fs.disk_free": "disk free",
    "sys.checksum": "md5 of ~/notes.txt",
    "sys.memory": "memory usage",
    "sys.processes": "process list",
    "sys.uptime": "uptime",
    "sys.date": "date and time",
    "sys.hostname": "hostname",
    "sys.cpus": "cpu info",
    "sys.pci": "pci devices",
    "sys.usb": "usb devices",
    "sys.blocks": "block devices",
    "sys.sockets": "listening sockets",
    "sys.network": "network interfaces",
    "sys.routes": "routing table",
    "sys.journal": "show the journal",
    "sys.kernel_log": "kernel log",
    "sys.users": "who is logged in",
    "sys.login_history": "last logins",
    "sys.env": "environment variables",
    "sys.identity": "id",
    "net.ping": "ping example.com",
    "net.dns": "resolve example.com",
    "fs.find": "find files named report",
    "fs.search": "look for TODO in ~/notes.txt",
    "fs.mkdir": "make a new folder photos",
    "fs.touch": "create an empty file notes",
    "fs.copy": "copy ~/notes.txt to /tmp/TODO",
    "fs.move": "move ~/notes.txt to ~/projects",
    "fs.remove": "delete the file /tmp/TODO",
    "fs.link": "symlink ~/notes.txt to /tmp/TODO",
    "file.append": "append remember the milk to ~/notes.txt",
    "gui.launch": "open firefox",
}
