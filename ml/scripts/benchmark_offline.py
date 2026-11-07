"""What the packaged build costs on disk, and whether it reaches the network.

The proposal's low-resource claim rests on a system that runs where there is
no internet connection. That was asserted rather than measured, which is the
same position NFR-01 was in before anyone timed it.

Three things are measured here. How much disk the build occupies, how long it
takes from a cold start to answer its first request, and whether anything it
serves refers to a host outside itself.

The last of those is a static check rather than a packet capture. A page that
names no external host cannot fetch one, and the check reads every template,
stylesheet and script the build ships. It would not catch a request
constructed at runtime, and the note in the artefact says so.

    .venv/Scripts/python.exe ml/scripts/benchmark_offline.py
"""

import json
import os
import re
import socket
import subprocess
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BUILD = ROOT / "dist" / "TB Screening"
EXE = BUILD / "TB Screening.exe"

# Hosts the application is allowed to name: itself, and nothing else.
LOCAL = re.compile(r"^(localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0)(:\d+)?$")

# Only the places a browser would actually fetch from.
#
# The first version of this check looked for any http address anywhere in the
# file and reported 36 outside hosts, which was true and useless: every one of
# them was a bug-tracker link in a comment, a line of licence text, or the
# w3.org namespace that every SVG file declares and nobody requests. A number
# that counts those is not evidence about whether the build works offline, and
# publishing it would have been worse than publishing nothing.
#
# These patterns cover what causes a request on load: an element's src, a
# stylesheet link, a CSS url() or @import, a fetch, and a form's action. An
# anchor the user has to click is listed separately, because it is a link out
# rather than a dependency.
FETCHES = [
    re.compile(r"""\bsrc\s*=\s*["']\s*(https?://[^"'\s>]+)""", re.I),
    re.compile(r"""<link[^>]+href\s*=\s*["']\s*(https?://[^"'\s>]+)""", re.I),
    re.compile(r"""\burl\(\s*["']?\s*(https?://[^"')\s]+)""", re.I),
    re.compile(r"""@import\s+(?:url\()?\s*["']\s*(https?://[^"')\s]+)""", re.I),
    re.compile(r"""\bfetch\(\s*["'](https?://[^"'\s]+)""", re.I),
    re.compile(r"""<form[^>]+action\s*=\s*["']\s*(https?://[^"'\s>]+)""", re.I),
]
ANCHOR = re.compile(r"""<a\b[^>]+href\s*=\s*["']\s*(https?://[^"'\s>]+)""", re.I)
HOST = re.compile(r"^https?://([A-Za-z0-9.\-]+(?::\d+)?)")


def folder_size(path):
    total = 0
    for item in path.rglob("*"):
        if item.is_file():
            try:
                total += item.stat().st_size
            except OSError:
                pass
    return total


# Only what the application serves to a browser. The build also carries the
# whole of TensorFlow and every other dependency, and those packages name
# hundreds of hosts in their own documentation and metadata which no page ever
# fetches. Scanning them would answer a different question and answer it
# wrongly.
SERVED = ("_internal/screening/templates", "_internal/staticfiles", "_internal/templates")


def external_hosts(path):
    """Hosts the served files would fetch from, and ones they merely link to."""
    fetched, linked = {}, {}
    suffixes = {".html", ".css", ".js", ".svg"}
    roots = [path / part for part in SERVED if (path / part).exists()]
    for item in (f for root in roots for f in root.rglob("*")):
        if not item.is_file() or item.suffix.lower() not in suffixes:
            continue
        try:
            text = item.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        where = str(item.relative_to(path))
        for pattern, bucket in [(p, fetched) for p in FETCHES] + [(ANCHOR, linked)]:
            for url in pattern.findall(text):
                host = HOST.match(url)
                if host and not LOCAL.match(host.group(1)):
                    bucket.setdefault(host.group(1), []).append(where)
    return fetched, linked


def answers(port):
    with socket.socket() as s:
        s.settimeout(0.4)
        try:
            return s.connect_ex(("127.0.0.1", port)) == 0
        except OSError:
            return False


def cold_start(limit=180):
    """Launch the build and time how long until it accepts a connection.

    The port is found by asking the operating system which port this process
    is listening on, rather than by reading the address it prints.

    That is not a stylistic choice. The first two versions of this function
    read the banner from a pipe, and the build then sat at "Preparing the
    database" for ten minutes without ever answering, which looked exactly
    like a defect in the offline deliverable and was written up as one. It was
    not. Giving the frozen executable a pipe for its console blocks it.
    Started with its output going to a file instead, the same build answers in
    under three seconds. The lesson is worth the comment: an instrument that
    changes what it measures reports the instrument.
    """
    if not EXE.exists():
        return None, None, "no packaged build on this machine"
    try:
        import psutil
    except ImportError:
        return None, None, "psutil is needed to find the port the build listens on"

    env = dict(os.environ, TB_NO_BROWSER="1")
    with tempfile.TemporaryDirectory() as scratch:
        console = Path(scratch) / "console.log"
        started = time.perf_counter()
        with console.open("w", encoding="utf-8") as sink:
            process = subprocess.Popen(
                [str(EXE)], cwd=str(BUILD), env=env, stdout=sink, stderr=subprocess.STDOUT
            )
            watched = psutil.Process(process.pid)
            try:
                while time.perf_counter() - started < limit:
                    if process.poll() is not None:
                        return None, None, f"the build exited with status {process.returncode}"
                    try:
                        listening = [
                            c.laddr.port
                            for c in watched.net_connections(kind="tcp")
                            if c.status == psutil.CONN_LISTEN
                        ]
                    except (psutil.Error, OSError):
                        listening = []
                    if listening and answers(listening[0]):
                        return round(time.perf_counter() - started, 2), listening[0], None
                    time.sleep(0.2)
                return None, None, f"no answer within {limit}s"
            finally:
                process.terminate()
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    process.kill()


def main():
    if not BUILD.exists():
        raise SystemExit(f"no packaged build at {BUILD}")

    print("measuring the packaged build")
    size = folder_size(BUILD)
    model = next(BUILD.rglob("*.keras"), None)
    print(f"  on disk: {size / (1024**3):.2f} GB")

    hosts, links = external_hosts(BUILD)
    print(f"  outside hosts the served files would fetch from: {len(hosts)}")
    for host, where in sorted(hosts.items()):
        print(f"    {host}  ({len(where)} reference(s), e.g. {where[0]})")
    print(f"  outside hosts linked for a person to click: {len(links)}")
    for host in sorted(links):
        print(f"    {host}")

    print("  cold start...")
    seconds, port, problem = cold_start()
    print(f"    {seconds}s" if seconds else f"    not measured: {problem}")

    result = {
        "measures": (
            "the packaged Windows build: disk footprint, cold start, and "
            "whether it names any external host"
        ),
        "build_path": str(BUILD.relative_to(ROOT)),
        "disk_bytes": size,
        "disk_gb": round(size / (1024**3), 2),
        "model_file_mb": round(model.stat().st_size / (1024**2), 1) if model else None,
        "cold_start_seconds": seconds,
        "cold_start_problem": problem,
        "cold_start_port": port,
        "external_hosts_fetched": sorted(hosts),
        "external_host_count": len(hosts),
        "external_hosts_linked": sorted(links),
        "external_link_count": len(links),
        "files_scanned_for_hosts": [".html", ".css", ".js", ".svg"],
        "directories_scanned": list(SERVED),
        "note": (
            "The fetch count is a static read of every template, stylesheet, "
            "script and SVG the build serves to a browser, looking only where "
            "a request is actually caused: an element's src, a stylesheet "
            "link, a CSS url() or @import, a fetch call, and a form's action. "
            "An earlier version of this check counted any address anywhere in "
            "a file and reported 36 outside hosts, every one of them a bug "
            "tracker in a comment, a line of licence text, or the w3.org "
            "namespace that every SVG declares and nothing requests. Hosts "
            "behind an anchor are counted separately, because a link a person "
            "has to click is not something the page loads. The bundled "
            "third-party packages are not scanned; they are not served. This "
            "is a reading of the files rather than a capture of the traffic, "
            "so it is evidence and not proof: it would not catch an address "
            "assembled at runtime. Cold start is wall-clock from launching "
            "the executable to the port answering, which covers unpacking, "
            "Django startup and the migration check, but not the first "
            "prediction."
        ),
    }

    out = ROOT / "ml" / "artifacts" / "offline_benchmark.json"
    out.write_text(json.dumps(result, indent=2), encoding="utf-8", newline="")
    print(f"\n-> {out}")


if __name__ == "__main__":
    main()
