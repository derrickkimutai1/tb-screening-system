"""
Entry point for the packaged desktop build.

Starts the application on this machine and opens it in the default browser.
Closing the console window stops it. Records, uploaded radiographs and the
database are kept under the user's local application data folder, so they
survive between runs and upgrades of the executable.
"""

import os
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path

APP_FOLDER = "TBScreening"


def data_directory():
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    directory = root / APP_FOLDER
    (directory / "media").mkdir(parents=True, exist_ok=True)
    return directory


def secret_key(directory):
    """Generate a key once per machine and reuse it on every later run."""
    key_file = directory / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50), encoding="utf-8")
    return key_file.read_text(encoding="utf-8").strip()


def free_port(preferred=8765):
    """Use the preferred port when available, otherwise any free one."""
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("No free local port available.")


def configure(directory):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["TB_PACKAGED"] = "1"
    os.environ["TB_DATA_DIR"] = str(directory)
    os.environ["DJANGO_DB"] = "sqlite"
    os.environ["DJANGO_DEBUG"] = "False"
    os.environ["DJANGO_SECRET_KEY"] = secret_key(directory)


def main():
    directory = data_directory()
    configure(directory)

    import django
    from django.core.management import call_command

    django.setup()
    call_command("migrate", interactive=False, verbosity=0)

    from waitress import serve

    from config.wsgi import application

    port = free_port()
    address = f"http://127.0.0.1:{port}/"

    print()
    print("  TB Screening Support")
    print("  Preliminary screening prototype. Not a diagnostic device.")
    print()
    print(f"  Running at  {address}")
    print(f"  Data folder {directory}")
    print()
    print("  Close this window to stop the application.")
    print()

    if not os.environ.get("TB_NO_BROWSER"):
        threading.Timer(1.2, webbrowser.open, args=(address,)).start()

    serve(application, host="127.0.0.1", port=port, threads=4, _quiet=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"\n  The application could not start: {error}\n")
        input("  Press Enter to close.")
        sys.exit(1)
