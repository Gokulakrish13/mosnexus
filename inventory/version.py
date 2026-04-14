"""
NexusOps Application Version Configuration
============================================
Single source of truth for application versioning.
Follows Semantic Versioning (SemVer): https://semver.org/

    MAJOR.MINOR.PATCH[-PRERELEASE][+BUILD]

    MAJOR  — Incompatible API / schema changes (breaking)
    MINOR  — New features, backward-compatible
    PATCH  — Bug fixes, backward-compatible
    PRE    — Pre-release tag (alpha, beta, rc)
    BUILD  — Build metadata (git SHA, build number)

Usage:
    from inventory.version import get_version, get_full_version, VERSION_INFO
"""

import subprocess
from datetime import datetime
from pathlib import Path

# ─── VERSION DEFINITION ─────────────────────────────────────────────────────
VERSION_INFO = {
    "major": 1,
    "minor": 0,
    "patch": 0,
    "pre_release": "",  # e.g. 'alpha.1', 'beta.2', 'rc.1', or '' for stable
    "build": "prod",  # e.g. 'prod', 'staging', or '' for auto-detect
}

# ─── RELEASE METADATA ───────────────────────────────────────────────────────
RELEASE_CODENAME = "NexusOps Enterprise"
RELEASE_DATE = "2026-02-28"
MIN_PYTHON_VERSION = "3.10"
MIN_DJANGO_VERSION = "5.1"

# ─── ENVIRONMENT TAGS ───────────────────────────────────────────────────────
ENVIRONMENTS = {
    "dev": "Development",
    "staging": "Staging",
    "prod": "Production",
    "test": "Testing",
}


def get_version() -> str:
    """
    Return the short version string, e.g. '1.0.0' or '1.1.0-beta.1'
    """
    version_string = f"{VERSION_INFO['major']}.{VERSION_INFO['minor']}.{VERSION_INFO['patch']}"
    if VERSION_INFO.get("pre_release"):
        version_string += f"-{VERSION_INFO['pre_release']}"
    return version_string


def get_full_version() -> str:
    """
    Return the full version string with build metadata,
    e.g. '1.0.0+prod' or '1.1.0-rc.1+build.1234'
    """
    version_string = get_version()
    build = VERSION_INFO.get("build", "")
    if build:
        version_string += f"+{build}"
    return version_string


def get_git_sha(short: bool = True) -> str:
    """Return the current Git commit SHA."""
    try:
        cmd = ["git", "rev-parse"]
        if short:
            cmd.append("--short")
        cmd.append("HEAD")
        return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def get_git_branch() -> str:
    """Return the current Git branch name."""
    try:
        return (
            subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def get_git_tag() -> str:
    """Return the latest Git tag (if any)."""
    try:
        return (
            subprocess.check_output(["git", "describe", "--tags", "--abbrev=0"], stderr=subprocess.DEVNULL)
            .decode()
            .strip()
        )
    except (OSError, subprocess.SubprocessError):
        return ""


def get_build_info() -> dict:
    """
    Return a comprehensive build information dictionary.
    Useful for health-check endpoints and admin panels.
    """
    return {
        "version": get_version(),
        "full_version": get_full_version(),
        "codename": RELEASE_CODENAME,
        "release_date": RELEASE_DATE,
        "git_sha": get_git_sha(),
        "git_sha_full": get_git_sha(short=False),
        "git_branch": get_git_branch(),
        "git_tag": get_git_tag(),
        "build_timestamp": datetime.utcnow().isoformat() + "Z",
        "environment": VERSION_INFO.get("build", "unknown"),
        "python_min": MIN_PYTHON_VERSION,
        "django_min": MIN_DJANGO_VERSION,
    }


def write_version_file():
    """Write the VERSION file to disk (used during CI/CD builds)."""
    version_file = Path(__file__).resolve().parent.parent / "VERSION"
    version_file.write_text(get_version())


# Expose as module-level constants for convenience
__version__ = get_version()
__full_version__ = get_full_version()
