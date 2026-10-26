"""
Dependency hygiene checks for requirements.txt.

- Every pin must have a reason to exist: the project imports it, a setting
  names it, another pinned package needs it, or it's listed below in
  INDIRECT_RUNTIME_PINS with an explanation.
- Every third-party package the project imports must be installed by
  requirements.txt, so production never depends on a dev-only tool or on a
  package that happens to be in someone's local venv.
- Packages with past security advisories can't be pinned below the first
  patched release.

These read the metadata of the installed packages, so run them in an
environment built from requirements-dev.txt (CI does).
"""

import ast
import re
import sys
from importlib.metadata import PackageNotFoundError, distribution
from importlib.metadata import packages_distributions
from importlib.metadata import version as installed_version
from pathlib import Path

from django.test import SimpleTestCase
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name
from packaging.version import Version

REPO_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS_FILE = REPO_ROOT / "requirements.txt"
DEV_REQUIREMENTS_FILE = REPO_ROOT / "requirements-dev.txt"
FIRST_PARTY = {"core", "leagues", "dcstreethockey", "manage", "list_captain_urls"}
SKIP_DIRS = {"venv", ".venv", "node_modules", "staticfiles", "static", "media"}

# Pins nothing imports directly that production still needs. Keep the reason
# current: if it stops being true, remove the pin.
INDIRECT_RUNTIME_PINS = {
    "boto3": "django-storages' S3 media backend imports it lazily and doesn't "
    "declare it as a dependency",
    "psycopg": "PostgreSQL driver loaded by Django's postgresql database backend",
    "brotli": "WhiteNoise pre-compresses static files with it when installed",
    "uvicorn": "production web server, started by Procfile and render.yaml",
    "setuptools": "kept on a patched release for the build environment",
}

# First patched release for each GitHub security advisory raised against this
# repo. Lowering a pin below its floor would reintroduce a known vulnerability.
# A floor still applies if a removed package is ever added back.
PATCHED_DEPENDENCY_FLOORS = {
    # GHSA-ffc3-869f-jxw9 (critical), GHSA-w2cx-738m-mc7w, GHSA-r6x4-923q-g947,
    # GHSA-gvp8-978c-rx2q all affect PyJWT <= 2.13.0.
    "pyjwt": "2.14.0",
    "django": "5.2.17",
    "urllib3": "2.8.0",
    # 24 advisories fixed in 13.0.0 (CVE-2026-112390 through -112901): crafted
    # images crash or hang decoders, plus Ghostscript argument injection.
    "pillow": "13.0.0",
    # PYSEC-2026-4320: bundle trusted the compromised emSign ECC Root CA - G3.
    "certifi": "2026.10.19",
    "sqlparse": "0.6.0",
    "djangorestframework": "3.17.2",
    "idna": "3.15",
    "oauthlib": "4.0.0",
    # GHSA-xmj3-9gf7-h52w: a crafted wheel's namespace_packages.txt could
    # create a file outside the install directory (Windows only).
    "setuptools": "84.1.0",
    # PYSEC-2026-4322 / GHSA-9v8h-qqgm-4m35: out-of-bounds write in the Brotli
    # decoder, reachable from any Brotli-compressed response or request body.
    "brotli": "1.2.1",
}


def read_pins(path):
    """Return {canonical name: (version, extras)} for each ``name==version``."""
    pins = {}
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        requirement = Requirement(line)
        version = str(requirement.specifier).removeprefix("==")
        pins[canonicalize_name(requirement.name)] = (version, requirement.extras)
    return pins


def project_python_files():
    for path in REPO_ROOT.rglob("*.py"):
        if not SKIP_DIRS.intersection(path.relative_to(REPO_ROOT).parts):
            yield path


def referenced_modules():
    """Top-level module names the project imports or names in settings."""
    modules = set()
    for path in project_python_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        in_settings = "settings" in path.parts
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                modules.add(node.module.split(".")[0])
            elif (
                in_settings
                and isinstance(node, ast.Constant)
                and isinstance(node.value, str)
                and re.fullmatch(r"[a-z_][a-z0-9_]*(\.[A-Za-z0-9_]+)*", node.value)
            ):
                # INSTALLED_APPS, MIDDLEWARE, STORAGES backends, and so on.
                modules.add(node.value.split(".")[0])
    return modules - FIRST_PARTY - set(sys.stdlib_module_names)


def requirements_of(name, extras=()):
    """Canonical names a distribution needs, honoring requested extras."""
    try:
        requires = distribution(name).requires or []
    except PackageNotFoundError:
        return set()
    needed = set()
    for line in requires:
        requirement = Requirement(line)
        marker = requirement.marker
        if marker is None or any(
            marker.evaluate({"extra": extra}) for extra in ("", *extras)
        ):
            needed.add(canonicalize_name(requirement.name))
    return needed


def closure(roots, pins):
    """Every package reachable from ``roots`` through declared requirements."""
    seen, stack = set(), list(roots)
    while stack:
        name = stack.pop()
        if name in seen:
            continue
        seen.add(name)
        extras = pins.get(name, (None, set()))[1]
        stack.extend(requirements_of(name, extras) - seen)
    return seen


class RequirementsHygieneTest(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.pins = read_pins(REQUIREMENTS_FILE)
        cls.module_owners = {
            module: {canonicalize_name(d) for d in dists}
            for module, dists in packages_distributions().items()
        }
        cls.imported_packages = set()
        for module in referenced_modules():
            cls.imported_packages |= cls.module_owners.get(module, set())

    def test_every_pin_is_installed(self):
        missing = []
        for name, (version, _) in self.pins.items():
            try:
                if installed_version(name) != version:
                    missing.append(
                        f"{name}=={version} (installed {installed_version(name)})"
                    )
            except PackageNotFoundError:
                missing.append(f"{name}=={version} (not installed)")
        self.assertEqual(missing, [], "Run: pip install -r requirements-dev.txt")

    def test_every_pin_is_needed(self):
        roots = (self.imported_packages | set(INDIRECT_RUNTIME_PINS)) & set(self.pins)
        needed = closure(roots, self.pins)
        unneeded = sorted(set(self.pins) - needed)
        self.assertEqual(
            unneeded,
            [],
            "Nothing imports these and no other pinned package requires them. "
            "Remove them from requirements.txt, or add them to "
            "INDIRECT_RUNTIME_PINS with the reason production needs them.",
        )

    def test_every_imported_package_is_installed_by_requirements(self):
        provided = closure(set(self.pins), self.pins)
        dev_only = set(read_pins(DEV_REQUIREMENTS_FILE)) - set(self.pins)
        missing = sorted(self.imported_packages - provided)
        self.assertEqual(
            missing,
            [],
            "The project imports these but requirements.txt doesn't install "
            f"them. Dev-only packages: {sorted(dev_only)}",
        )

    def test_indirect_pins_are_still_pinned(self):
        for name in INDIRECT_RUNTIME_PINS:
            with self.subTest(package=name):
                self.assertIn(name, self.pins)


class PatchedDependencyFloorTest(SimpleTestCase):
    """Regression guard for Dependabot security advisories."""

    def test_pins_are_at_or_above_patched_versions(self):
        pins = read_pins(REQUIREMENTS_FILE)
        for package, floor in PATCHED_DEPENDENCY_FLOORS.items():
            if package not in pins:
                continue  # removed entirely, which is also safe
            with self.subTest(package=package):
                self.assertGreaterEqual(Version(pins[package][0]), Version(floor))

    def test_installed_versions_are_at_or_above_patched_versions(self):
        for package, floor in PATCHED_DEPENDENCY_FLOORS.items():
            try:
                version = installed_version(package)
            except PackageNotFoundError:
                continue
            with self.subTest(package=package):
                self.assertGreaterEqual(Version(version), Version(floor))
