"""The test runner, which keeps the suite out of the real media folder.

Tests that upload a radiograph write files. Django does not redirect that
anywhere by itself, so a test writes into whatever `MEDIA_ROOT` points at,
which in development is the folder holding real screenings.

Eleven test classes carried `@override_settings(MEDIA_ROOT=...)` to avoid it
and four did not, so every run of the suite left twenty-two files behind. Over
the project's life that accumulated 291 orphaned files and 166 MB, which only
came to light because `prunemedia` counts them. Nothing failed, which is what
made it last: a test that writes to the wrong directory still passes.

Redirecting per class cannot be relied on, because it depends on remembering a
decorator on every class anyone adds afterwards. Doing it here applies to the
whole run, including classes that have not been written yet, and the temporary
directory goes away with the test database.

`MediaIsolationTests` in the suite asserts this is actually in force, so the
protection is itself tested rather than assumed.
"""

import shutil
import tempfile
from pathlib import Path

from django.conf import settings
from django.test.runner import DiscoverRunner


class IsolatedMediaRunner(DiscoverRunner):
    """Runs the suite with uploads directed at a temporary directory."""

    def setup_test_environment(self, **kwargs):
        super().setup_test_environment(**kwargs)
        self._real_media = settings.MEDIA_ROOT
        self._scratch = tempfile.mkdtemp(prefix="tb-test-media-")
        settings.MEDIA_ROOT = self._scratch

    def teardown_test_environment(self, **kwargs):
        settings.MEDIA_ROOT = self._real_media
        # Best effort: a file still held open by a failed test should not turn
        # a reported failure into an unrelated error about deleting it.
        shutil.rmtree(self._scratch, ignore_errors=True)
        super().teardown_test_environment(**kwargs)

    @staticmethod
    def scratch_prefix():
        """The marker a test can look for to confirm the redirect is in force."""
        return Path(tempfile.gettempdir()).resolve()
