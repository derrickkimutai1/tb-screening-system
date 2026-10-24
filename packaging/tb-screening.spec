# PyInstaller build definition for the portable desktop build.
#
#   .venv/Scripts/python.exe -m PyInstaller packaging/tb-screening.spec --noconfirm
#
# Django finds most of what it needs by importing it, which PyInstaller follows.
# Three kinds of thing it cannot follow are listed here explicitly:
#
#   data files      templates, migrations, the collected static files and the
#                   trained model are read from disk at run time, so nothing
#                   imports them and nothing would otherwise be collected
#   hidden imports  modules named in settings as strings, which no import
#                   statement mentions
#   exclusions      packages that happen to be installed in the development
#                   environment and have no business in the executable
#
# The result is large, a few hundred megabytes, because TensorFlow is in it.
# That is the cost of being able to screen and to produce a heatmap offline.

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent

datas = [
    # Templates and migrations: read from disk, never imported.
    (str(ROOT / "screening" / "templates"), "screening/templates"),
    (str(ROOT / "screening" / "migrations"), "screening/migrations"),
    # Collected static files, served by WhiteNoise. Build them first with
    # manage.py collectstatic, or the interface arrives unstyled.
    (str(ROOT / "staticfiles"), "staticfiles"),
    # The trained model and the thresholds it was evaluated at. Fixed in the
    # bundle rather than fetched, so a prediction cannot depend on a download.
    (str(ROOT / "ml" / "models" / "tb_mobilenetv2_v1.keras"), "ml/models"),
    (str(ROOT / "ml" / "models" / "metadata.json"), "ml/models"),
    # Preprocessing is shared with the training scripts and imported by path.
    (str(ROOT / "ml" / "preprocessing.py"), "ml"),
]

# allauth keeps its own templates and locale data.
datas += collect_data_files("allauth")

hiddenimports = [
    # Named as strings in settings, so nothing imports them.
    "screening.apps",
    "screening.signals",
    "screening.middleware",
    "screening.context_processors",
    "screening.auth",
    "screening.templatetags.devmail",
    "django.contrib.staticfiles.apps",
    "whitenoise.storage",
    "waitress",
    # SQLite only; PostgreSQL is excluded below.
    "django.db.backends.sqlite3",
]

# allauth reaches its providers and internal flows dynamically.
hiddenimports += collect_submodules("allauth")

excludes = [
    # The packaged build runs on SQLite.
    "psycopg",
    "psycopg2",
    "psycopg_binary",
    # Training and evaluation tooling. Inference needs none of it.
    "matplotlib",
    "seaborn",
    "pandas",
    "sklearn",
    "scipy",
    "IPython",
    "ipykernel",
    "jupyter",
    "notebook",
    "pytest",
    "ruff",
    "pyinstaller",
    "tkinter",
]

analysis = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
    optimize=0,
)

pyz = PYZ(analysis.pure)

exe = EXE(
    pyz,
    analysis.scripts,
    [],
    exclude_binaries=True,
    name="TB Screening",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    # TensorFlow's libraries are already compressed and compress badly a second
    # time; UPX makes the build far slower for very little.
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,
)

# One folder rather than one file. A single file would unpack several hundred
# megabytes to a temporary directory on every launch, which takes long enough
# that the application looks broken before it opens.
collect = COLLECT(
    exe,
    analysis.binaries,
    analysis.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="TB Screening",
)
