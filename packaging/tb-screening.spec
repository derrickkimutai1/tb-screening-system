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
    # The measurements behind the model performance page. Small JSON files,
    # read at request time, so without them that page has nothing to show in
    # the desktop build and says so rather than breaking.
    (str(ROOT / "ml" / "artifacts" / "metrics.json"), "ml/artifacts"),
    (str(ROOT / "ml" / "artifacts" / "calibration.json"), "ml/artifacts"),
    (str(ROOT / "ml" / "artifacts" / "cross_dataset.json"), "ml/artifacts"),
    (str(ROOT / "ml" / "artifacts" / "response_times.json"), "ml/artifacts"),
    # The architecture comparison is read out of the experiments log rather
    # than from a file of its own, so the log travels with the build.
    (str(ROOT / "ml" / "artifacts" / "experiments.csv"), "ml/artifacts"),
    (
        str(ROOT / "ml" / "artifacts" / "explanation_comparison-all.json"),
        "ml/artifacts",
    ),
    (
        str(ROOT / "ml" / "artifacts" / "occlusion-p32s16-all-tb_evaluation.json"),
        "ml/artifacts",
    ),
    (
        str(
            ROOT
            / "ml"
            / "artifacts"
            / "gradcam-block_13_expand_relu-all-tb_evaluation.json"
        ),
        "ml/artifacts",
    ),
    # Preprocessing is shared with the training scripts. image_processing.py
    # puts ML_DIR on sys.path and imports it by name, so it travels as a file
    # rather than as a module and must land where ML_DIR points: beside the
    # unpacked bundle, which is what BASE_DIR resolves to there.
    (str(ROOT / "ml" / "preprocessing.py"), "ml"),
]

# allauth keeps its own templates and locale data.
datas += collect_data_files("allauth")

# This project's own modules. Django reaches almost all of them by name from a
# string in settings rather than by importing them, so PyInstaller's analysis
# follows nothing into them and the first build shipped without the settings
# module at all.
#
# Listed one by one rather than collected, because collecting imports each in
# turn and these cannot be imported without Django already configured, which
# it is not while the bundle is being analysed.
hiddenimports = [
    "config",
    "config.settings",
    "config.urls",
    "config.wsgi",
    "screening",
    "screening.admin",
    "screening.apps",
    "screening.auth",
    "screening.context_processors",
    "screening.forms",
    "screening.middleware",
    "screening.models",
    "screening.signals",
    "screening.urls",
    "screening.views",
    "screening.services",
    "screening.services.devmail",
    "screening.services.gradcam",
    "screening.services.image_processing",
    "screening.services.occlusion",
    "screening.services.overlays",
    "screening.services.scorecam",
    "screening.services.predict",
    "screening.services.quality",
    "screening.services.sanitise",
    "screening.services.triage",
    "screening.templatetags",
    "screening.templatetags.devmail",
    "waitress",
    # SQLite only; PostgreSQL is excluded below.
    "django.db.backends.sqlite3",
    "django.db.backends.sqlite3.base",
]

# Everything Django reaches by a dotted string in settings: middleware,
# authentication backends, context processors, storage and mail backends, the
# allauth adapters and forms, and every installed app.
#
# This list was produced from the settings themselves rather than written out,
# and regenerating it is the way to extend it. Finding these one failed launch
# at a time is how the first two builds went: the bundle starts, Django reads a
# name out of settings, and the module behind it was never collected because
# nothing imports it.
hiddenimports += [
    "allauth",
    "allauth.account",
    "allauth.account.auth_backends",
    "allauth.account.middleware",
    "allauth.socialaccount",
    "allauth.socialaccount.providers.google",
    "allauth.socialaccount.providers.microsoft",
    "django.contrib.admin",
    "django.contrib.admin.apps",
    "django.contrib.auth",
    "django.contrib.auth.backends",
    "django.contrib.auth.context_processors",
    "django.contrib.auth.middleware",
    "django.contrib.contenttypes",
    "django.contrib.messages",
    "django.contrib.messages.context_processors",
    "django.contrib.messages.middleware",
    "django.contrib.sessions",
    "django.contrib.sessions.middleware",
    "django.contrib.sites",
    "django.contrib.staticfiles",
    "django.contrib.staticfiles.apps",
    "django.core.files.storage",
    "django.core.mail.backends.console",
    "django.core.mail.backends.smtp",
    "django.middleware.clickjacking",
    "django.middleware.common",
    "django.middleware.csrf",
    "django.middleware.security",
    "django.template.context_processors",
    "whitenoise.middleware",
    "whitenoise.storage",
]

# WhiteNoise and the session and messages backends each reach further modules
# by name again, so the whole of the small ones travels rather than guessing.
hiddenimports += collect_submodules("whitenoise")
hiddenimports += collect_submodules("django.contrib.sessions")
hiddenimports += collect_submodules("django.contrib.messages")

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
