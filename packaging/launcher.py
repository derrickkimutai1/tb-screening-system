"""
Entry point for the packaged desktop build.

Starts the application on this machine and opens it in the default browser.
Closing the console window stops it.

Records, uploaded radiographs and the database are kept under the user's local
application data folder rather than beside the executable, because PyInstaller
unpacks the bundle to a temporary directory and deletes it on exit: anything
written inside it would be gone by the next run.
"""

import os
import secrets
import socket
import sys
import threading
import webbrowser
from pathlib import Path

APP_FOLDER = "TBScreening"

# Inside a bundle PyInstaller has already put the application on the path. Run
# directly from the project, as it is during development, this file lives in a
# subfolder and the project root is not importable without saying so.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def bundle_root():
    """Where the application's own files are.

    PyInstaller sets _MEIPASS to the directory it unpacked into. Outside a
    bundle this is the project folder, so the launcher can be run directly
    during development and behave the same way.
    """
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def data_directory():
    """Where this installation keeps what it has screened."""
    root = Path(os.environ.get("LOCALAPPDATA") or Path.home())
    directory = root / APP_FOLDER
    (directory / "media").mkdir(parents=True, exist_ok=True)
    return directory


def secret_key(directory):
    """Generate a key once per machine and reuse it on every later run.

    Per machine rather than compiled in, so that two installations do not
    share one, and so that a key cannot be read out of the executable.
    Regenerating it would sign everyone out, which is why it is kept.
    """
    key_file = directory / "secret.key"
    if not key_file.exists():
        key_file.write_text(secrets.token_urlsafe(50), encoding="utf-8")
        # Readable by this user only, as far as the platform allows.
        try:
            key_file.chmod(0o600)
        except OSError:
            pass
    return key_file.read_text(encoding="utf-8").strip()


def free_port(preferred=8765):
    """Use the preferred port when available, otherwise any free one.

    A fixed port is friendlier, because the address stays the same between
    runs, but it must not stop the application starting if something else has
    taken it.
    """
    for port in (preferred, 0):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError:
                continue
            return probe.getsockname()[1]
    raise RuntimeError("No free local port available.")


def configure(directory):
    """Set the environment the application reads its settings from.

    Everything the deployed system takes from a .env file is supplied here
    instead, because a packaged build has no .env and must not need one.
    """
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    os.environ["TB_PACKAGED"] = "1"
    os.environ["TB_DATA_DIR"] = str(directory)
    os.environ["DJANGO_DB"] = "sqlite"
    os.environ["DJANGO_DEBUG"] = "False"
    os.environ["DJANGO_ALLOWED_HOSTS"] = "127.0.0.1,localhost"
    os.environ["DJANGO_SECRET_KEY"] = secret_key(directory)

    # Served over plain HTTP on the loopback interface, where there is no
    # transport to secure. Insisting on secure cookies here would stop the
    # application working at all.
    os.environ["DJANGO_BEHIND_PROXY"] = "False"

    # No identity provider is reachable, so none is configured. The operator
    # is signed in by PackagedOperatorMiddleware instead.
    os.environ.pop("GOOGLE_OAUTH_CLIENT_ID", None)
    os.environ.pop("GOOGLE_OAUTH_CLIENT_SECRET", None)
    os.environ.pop("DATABASE_URL", None)

    # The bundle is read-only, so static files are served from where
    # PyInstaller unpacked them.
    os.environ["DJANGO_STATIC_ROOT"] = str(bundle_root() / "staticfiles")


def banner(address, directory):
    print()
    print("  TB Screening Support")
    print("  Preliminary screening prototype. Not a diagnostic device, and not")
    print("  clinically validated. Results need clinical review.")
    print()
    print(f"  Running at   {address}")
    print(f"  Data folder  {directory}")
    print()
    print("  Close this window to stop the application.")
    print()


def main():
    directory = data_directory()
    configure(directory)

    import django
    from django.core.management import call_command

    django.setup()

    # Brings a database created by an older version of this executable up to
    # date, which is what makes an upgrade a matter of replacing one file.
    print("  Preparing the database...", flush=True)
    call_command("migrate", interactive=False, verbosity=0)

    from waitress import serve

    from config.wsgi import application

    port = free_port()
    address = f"http://127.0.0.1:{port}/"
    banner(address, directory)

    if not os.environ.get("TB_NO_BROWSER"):
        # After a short delay, so the server is listening before the browser
        # asks for the page.
        threading.Timer(1.5, webbrowser.open, args=(address,)).start()

    # Few threads, because the model is held in this process and a second
    # concurrent screening would contend for it rather than go faster.
    serve(application, host="127.0.0.1", port=port, threads=4, _quiet=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n  Stopped.\n")
    except Exception as error:
        print(f"\n  The application could not start: {error}\n")
        import traceback

        traceback.print_exc()
        input("  Press Enter to close.")
        sys.exit(1)
