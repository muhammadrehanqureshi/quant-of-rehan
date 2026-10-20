"""The APK is built in the cloud, and built from the manifest that ships.

Owner order 2026-10-20: the phone is where the console changes are seen, and
the order of 2026-10-19 keeps the owner's PC out of it. The repository has no
Gradle project, so the build is the aapt2/javac/D8/zipalign/apksigner chain
android/README.md documents, and the only place it may run is a runner.

These are source assertions, not a build: the workflow itself is executed by
GitHub on the pull request and on master, and a failing step there is the real
evidence. What is pinned here is the part a passing run would not otherwise
protect, that the artifact is the version the manifest declares and that no
signing material is ever written into the repository.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "android-apk.yml"
README = ROOT / "android" / "README.md"
MANIFEST = ROOT / "android" / "app" / "src" / "main" / "AndroidManifest.xml"


class BuildWorkflowTest(unittest.TestCase):
    def setUp(self):
        self.workflow = WORKFLOW.read_text(encoding="utf-8")
        self.manifest = MANIFEST.read_text(encoding="utf-8")

    def test_it_is_a_cloud_build_the_owner_can_start(self):
        self.assertIn("workflow_dispatch:", self.workflow)
        self.assertIn("runs-on: ubuntu-latest", self.workflow)
        self.assertIn("timeout-minutes:", self.workflow)
        # A merge that changes the app rebuilds it, so master's artifact is
        # the commit that shipped.
        self.assertIn("branches: [master]", self.workflow)
        self.assertIn("android/app/src/**", self.workflow)

    def test_it_runs_the_documented_chain_and_nothing_local(self):
        for tool in ("aapt2", "javac", "d8", "zipalign", "apksigner"):
            with self.subTest(tool=tool):
                self.assertIn(tool, self.workflow)
        self.assertIn("--manifest android/app/src/main/AndroidManifest.xml",
                      self.workflow)
        # The README's flags: Java 8 sources against the platform jar.
        self.assertIn("-source 8 -target 8 -classpath \"$ANDROID_JAR\"",
                      self.workflow)
        # D8 writes into an existing directory, and the dex is injected after
        # the link step, exactly as the hand build does.
        self.assertIn('mkdir -p "$B/dex"', self.workflow)
        self.assertIn('z.write(f"{B}/dex/classes.dex", "classes.dex")',
                      self.workflow)
        # No shell that starts anything on the owner's machine.
        for forbidden in ("schtasks", "Start-Process", "Register-ScheduledTask"):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.workflow)

    def test_the_artifact_is_the_version_the_manifest_declares(self):
        version = re.search(r'android:versionName="([^"]+)"', self.manifest)
        code = re.search(r'android:versionCode="([^"]+)"', self.manifest)
        self.assertIsNotNone(version)
        self.assertIsNotNone(code)
        # The workflow reads both back from the built APK and refuses to ship
        # a file whose badging disagrees with the manifest.
        self.assertIn("aapt2", self.workflow)
        self.assertIn("dump badging", self.workflow)
        self.assertIn("versionName='$VERSION'", self.workflow)
        self.assertIn("versionCode='$CODE'", self.workflow)
        self.assertIn("if-no-files-found: error", self.workflow)

    def test_signing_material_comes_from_secrets_only(self):
        self.assertIn("secrets.ANDROID_KEYSTORE_BASE64", self.workflow)
        # A generated key is the documented fallback, never a stored one.
        self.assertIn("keytool -genkeypair", self.workflow)
        # No keystore, password or key is written into the tree.
        for pattern in (r"[A-Za-z0-9+/]{80,}={0,2}", r"-----BEGIN [A-Z ]+-----"):
            with self.subTest(pattern=pattern):
                self.assertIsNone(re.search(pattern, self.workflow))
        self.assertFalse(
            list((ROOT / "android").rglob("*.jks")),
            "a keystore must never be committed")
        self.assertFalse(list((ROOT / "android").rglob("*.keystore")))


class ReadmeTest(unittest.TestCase):
    def test_the_hand_build_names_the_cloud_build(self):
        readme = README.read_text(encoding="utf-8")
        self.assertIn("android-apk.yml", readme)
        self.assertIn("ANDROID_KEYSTORE_BASE64", readme)


if __name__ == "__main__":
    unittest.main()
