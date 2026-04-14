"""
Release Management Command
============================
Corporate-grade release automation for NexusOps.

Usage:
    python manage.py release --bump patch          # 1.0.0 → 1.0.1
    python manage.py release --bump minor          # 1.0.0 → 1.1.0
    python manage.py release --bump major          # 1.0.0 → 2.0.0
    python manage.py release --bump patch --tag    # Bump + git tag
    python manage.py release --show                # Show current version
    python manage.py release --tag-only            # Tag current version in git
"""

# pylint: disable=import-outside-toplevel,missing-class-docstring,too-complex,too-many-branches,unused-argument

import re
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Manage application versioning: bump versions, create git tags, and show release info."

    def add_arguments(self, parser):
        parser.add_argument(
            "--bump",
            type=str,
            choices=["major", "minor", "patch"],
            help="Bump the version (major, minor, or patch)",
        )
        parser.add_argument(
            "--pre",
            type=str,
            default="",
            help="Set pre-release tag (e.g. alpha.1, beta.2, rc.1). Use empty string to clear.",
        )
        parser.add_argument(
            "--build",
            type=str,
            default=None,
            help="Set build metadata (e.g. prod, staging).",
        )
        parser.add_argument(
            "--tag",
            action="store_true",
            help="Create a git tag after bumping.",
        )
        parser.add_argument(
            "--tag-only",
            action="store_true",
            help="Create a git tag for the current version without bumping.",
        )
        parser.add_argument(
            "--show",
            action="store_true",
            help="Display current version information.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Show what would happen without making changes.",
        )

    def handle(self, *args, **options):
        version_file = Path(__file__).resolve().parent.parent.parent.parent / "inventory" / "version.py"
        root_version_file = Path(__file__).resolve().parent.parent.parent.parent / "VERSION"

        if not version_file.exists():
            raise CommandError(f"Version file not found: {version_file}")

        content = version_file.read_text()

        current = self._parse_version(content)

        if options["show"]:
            self._show_version(current)
            return

        if options["tag_only"]:
            tag = f"v{current['major']}.{current['minor']}.{current['patch']}"
            if current.get("pre_release"):
                tag += f"-{current['pre_release']}"
            self._create_git_tag(tag, options["dry_run"])
            return

        if not options["bump"]:
            self.stdout.write(self.style.WARNING("No action specified. Use --bump, --show, --tag-only, or --help."))
            return

        new = dict(current)
        bump = options["bump"]

        if bump == "major":
            new["major"] += 1
            new["minor"] = 0
            new["patch"] = 0
        elif bump == "minor":
            new["minor"] += 1
            new["patch"] = 0
        elif bump == "patch":
            new["patch"] += 1

        if options["pre"] is not None and options["pre"] != "":
            new["pre_release"] = options["pre"]
        elif options["bump"]:
            new["pre_release"] = ""  # Clear pre-release on bump

        if options["build"] is not None:
            new["build"] = options["build"]

        old_ver = f"{current['major']}.{current['minor']}.{current['patch']}"
        new_ver = f"{new['major']}.{new['minor']}.{new['patch']}"
        if new.get("pre_release"):
            new_ver += f"-{new['pre_release']}"

        self.stdout.write(f"\n  Version bump: {self.style.WARNING(old_ver)} → {self.style.SUCCESS(new_ver)}\n")

        if options["dry_run"]:
            self.stdout.write(self.style.NOTICE("  [DRY RUN] No files modified.\n"))
            return

        content = self._update_version_file(content, new)
        version_file.write_text(content)
        self.stdout.write(f"  ✓ Updated {version_file.name}")

        root_version_file.write_text(new_ver.split("-", maxsplit=1)[0])  # VERSION file is clean semver
        self.stdout.write("  ✓ Updated VERSION file")

        if options["tag"]:
            tag = f"v{new_ver}"
            self._create_git_tag(tag, dry_run=False)

        self.stdout.write(self.style.SUCCESS(f"\n  Release {new_ver} prepared successfully!\n"))

        self.stdout.write(self.style.WARNING("  Remember to update CHANGELOG.md before pushing the tag.\n"))

    def _parse_version(self, content: str) -> dict:
        """Parse VERSION_INFO dict from version.py content."""
        m_major = re.search(r"'major':\s*(\d+)", content)
        m_minor = re.search(r"'minor':\s*(\d+)", content)
        m_patch = re.search(r"'patch':\s*(\d+)", content)
        assert m_major and m_minor and m_patch, "Cannot parse VERSION_INFO"
        major = int(m_major.group(1))
        minor = int(m_minor.group(1))
        patch = int(m_patch.group(1))
        pre_match = re.search(r"'pre_release':\s*'([^']*)'", content)
        build_match = re.search(r"'build':\s*'([^']*)'", content)
        return {
            "major": major,
            "minor": minor,
            "patch": patch,
            "pre_release": pre_match.group(1) if pre_match else "",
            "build": build_match.group(1) if build_match else "",
        }

    def _update_version_file(self, content: str, v: dict) -> str:
        """Replace version numbers in version.py content."""
        content = re.sub(r"('major':\s*)\d+", f"\\g<1>{v['major']}", content)
        content = re.sub(r"('minor':\s*)\d+", f"\\g<1>{v['minor']}", content)
        content = re.sub(r"('patch':\s*)\d+", f"\\g<1>{v['patch']}", content)
        content = re.sub(r"('pre_release':\s*)'[^']*'", f"\\g<1>'{v.get('pre_release', '')}'", content)
        if v.get("build") is not None:
            content = re.sub(r"('build':\s*)'[^']*'", f"\\g<1>'{v['build']}'", content)
        return content

    def _show_version(self, v: dict):
        """Display current version information."""
        from inventory.version import get_build_info

        info = get_build_info()  # pylint: disable=unused-variable

        self.stdout.write("""
  ┌──────────────────────────────────────────────────┐
  │  NexusOps Release Information                    │
  ├──────────────────────────────────────────────────┤
  │  Version:      {info['version']:<35}│
  │  Full Version: {info['full_version']:<35}│
  │  Codename:     {info['codename']:<35}│
  │  Release Date: {info['release_date']:<35}│
  │  Git Branch:   {info['git_branch']:<35}│
  │  Git SHA:      {info['git_sha']:<35}│
  │  Git Tag:      {info.get('git_tag', 'none'):<35}│
  │  Environment:  {info['environment']:<35}│
  └──────────────────────────────────────────────────┘
""")

    def _create_git_tag(self, tag: str, dry_run: bool = False):
        """Create an annotated git tag."""
        if dry_run:
            self.stdout.write(self.style.NOTICE(f"  [DRY RUN] Would create git tag: {tag}"))
            return

        try:
            subprocess.run(
                ["git", "tag", "-a", tag, "-m", f"Release {tag}"],
                check=True,
                capture_output=True,
                text=True,
            )
            self.stdout.write(self.style.SUCCESS(f"  ✓ Created git tag: {tag}"))
            self.stdout.write(self.style.WARNING(f"  Push with: git push origin {tag}"))
        except subprocess.CalledProcessError as e:
            self.stdout.write(self.style.ERROR(f"  ✗ Failed to create git tag: {e.stderr.strip()}"))
