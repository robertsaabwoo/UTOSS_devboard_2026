#!/usr/bin/env python3
"""Create the RTL work breakdown as GitHub issues from .github/issues/*.md.

The issues are written as files so they are reviewable in a pull request, and
so the specification lives in the repository next to the code rather than only
in GitHub. This pushes them up.

    python3 scripts/sync_issues.py                 # dry run: say what it would do
    python3 scripts/sync_issues.py --labels        # create/update labels only
    python3 scripts/sync_issues.py --apply         # create the missing issues
    python3 scripts/sync_issues.py --apply --update-bodies
                                                   # also push edited bodies

Needs the GitHub CLI, authenticated:  gh auth login

Matching is by exact issue title, including the `[ID]` prefix, across open AND
closed issues. So re-running is safe: it creates what is missing and leaves the
rest alone. Bodies are only ever overwritten with --update-bodies, because
somebody may have added useful discussion to an issue after it was filed.
"""
import argparse
import json
import pathlib
import shutil
import subprocess
import sys
import unicodedata

try:
    import yaml
except ImportError:
    sys.exit("PyYAML is required: pip install pyyaml")

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
ISSUE_DIR = REPO_ROOT / ".github" / "issues"
LABEL_FILE = REPO_ROOT / ".github" / "labels.yml"


class IssueFile:
    def __init__(self, path: pathlib.Path):
        self.path = path
        text = path.read_text(encoding="utf-8")
        if not text.startswith("---\n"):
            raise ValueError(
                "%s: must start with a YAML front-matter block delimited by ---"
                % path.name
            )
        _, front, body = text.split("---\n", 2)
        meta = yaml.safe_load(front) or {}

        missing = [key for key in ("id", "title") if not meta.get(key)]
        if missing:
            raise ValueError("%s: front matter is missing %s"
                             % (path.name, ", ".join(missing)))

        self.id = str(meta["id"])
        self.summary = str(meta["title"])
        self.labels = [str(label) for label in (meta.get("labels") or [])]
        self.milestone = meta.get("milestone")
        self.depends_on = [str(d) for d in (meta.get("depends_on") or [])]
        self.blocked_by_decision = meta.get("blocked_by_decision")
        self.body = body.strip() + "\n"

    @property
    def title(self) -> str:
        # The ID prefix is what makes matching stable when a title is reworded,
        # and what lets `depends_on` be rendered as a readable reference.
        return "[%s] %s" % (self.id, self.summary)

    def rendered_body(self, index) -> str:
        parts = [self.body]
        if self.depends_on:
            lines = ["", "---", "", "**Depends on**"]
            for dep in self.depends_on:
                other = index.get(dep)
                if other is None:
                    lines.append("- `%s` (not filed -- check "
                                 ".github/issues/)" % dep)
                else:
                    lines.append("- `%s` %s" % (dep, other.summary))
            parts.append("\n".join(lines))
        parts.append("\n*Filed from `%s`. Edit the file and re-run "
                     "`scripts/sync_issues.py` rather than only editing here, so "
                     "the specification stays in the repository.*\n"
                     % self.path.relative_to(REPO_ROOT).as_posix())
        return "\n".join(parts)


def gh(*args, check=True, capture=True):
    """Run gh, decoding its output as UTF-8 regardless of the host locale.

    `text=True` alone decodes with the locale encoding, which on Windows is
    cp1252. gh emits UTF-8, so every em dash in an issue title came back as
    mojibake ("---" as three bytes read one at a time), the title-match against
    .github/issues/*.md failed for exactly those issues, and a re-run created
    duplicates of them while correctly skipping the pure-ASCII ones. That is
    how this repo briefly acquired 14 duplicate issues.

    errors="replace" rather than strict: a decode error here should degrade the
    display of one title, not abort a sync half-way through creating issues.
    """
    command = ["gh"] + list(args)
    return subprocess.run(command, cwd=str(REPO_ROOT), check=check, text=True,
                          encoding="utf-8", errors="replace",
                          stdout=subprocess.PIPE if capture else None,
                          stderr=subprocess.STDOUT if capture else None)


def normalize_title(title: str) -> str:
    """Canonical form used for matching a file against an existing issue."""
    return " ".join(unicodedata.normalize("NFC", title).split())


def require_gh() -> None:
    if shutil.which("gh") is None:
        sys.exit(
            "The GitHub CLI (gh) is not installed, so issues cannot be pushed "
            "from here.\n"
            "  Windows: winget install --id GitHub.cli\n"
            "  macOS:   brew install gh\n"
            "  Linux:   see https://github.com/cli/cli#installation\n"
            "Then: gh auth login\n\n"
            "The issue specifications are all in .github/issues/ either way -- "
            "they are files first and GitHub issues second."
        )
    result = gh("auth", "status", check=False)
    if result.returncode != 0:
        sys.exit("gh is installed but not authenticated. Run: gh auth login\n\n"
                 + (result.stdout or ""))


def existing_issues() -> dict:
    result = gh("issue", "list", "--state", "all", "--limit", "500",
                "--json", "number,title,state")
    try:
        rows = json.loads(result.stdout or "[]")
    except json.JSONDecodeError:
        sys.exit("could not parse `gh issue list` output:\n" + (result.stdout or ""))
    # Normalise: NFC composition, and collapse whitespace. A title that
    # differs from the file's only by how Unicode spelled it must still match,
    # because the cost of a false negative here is a duplicate issue.
    return {normalize_title(row["title"]): row for row in rows}


def sync_labels(apply_changes: bool) -> None:
    if not LABEL_FILE.is_file():
        print("no %s, skipping labels" % LABEL_FILE.name)
        return
    labels = yaml.safe_load(LABEL_FILE.read_text(encoding="utf-8")) or []
    for label in labels:
        name = label["name"]
        color = str(label.get("color", "cccccc")).lstrip("#")
        description = label.get("description", "")
        if not apply_changes:
            print("would ensure label: %-22s #%s  %s" % (name, color, description))
            continue
        # --force makes this idempotent: create, or update colour/description.
        result = gh("label", "create", name, "--color", color,
                    "--description", description, "--force", check=False)
        status = "ok" if result.returncode == 0 else "FAILED"
        print("label %-22s %s" % (name, status))
        if result.returncode != 0:
            print("  " + (result.stdout or "").strip())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--apply", action="store_true",
                        help="actually create issues (default is a dry run)")
    parser.add_argument("--labels", action="store_true",
                        help="sync labels from .github/labels.yml")
    parser.add_argument("--update-bodies", action="store_true",
                        help="overwrite the body of issues that already exist")
    parser.add_argument("--only", help="only the issue with this id, e.g. I-01")
    args = parser.parse_args()

    if not ISSUE_DIR.is_dir():
        sys.exit("%s does not exist" % ISSUE_DIR)

    files = []
    for path in sorted(ISSUE_DIR.glob("*.md")):
        if path.name.upper() == "README.MD":
            continue
        try:
            files.append(IssueFile(path))
        except (ValueError, yaml.YAMLError) as exc:
            sys.exit("ISSUE FILE ERROR: %s" % exc)

    seen = {}
    for issue in files:
        if issue.id in seen:
            sys.exit("duplicate issue id %s in %s and %s"
                     % (issue.id, seen[issue.id], issue.path.name))
        seen[issue.id] = issue.path.name

    index = {issue.id: issue for issue in files}
    for issue in files:
        for dep in issue.depends_on:
            if dep not in index:
                print("warning: %s depends on %s, which no file declares"
                      % (issue.id, dep))

    if args.only:
        files = [f for f in files if f.id == args.only]
        if not files:
            sys.exit("no issue file with id %r" % args.only)

    if args.labels:
        require_gh() if args.apply else None
        sync_labels(args.apply)
        if not args.apply:
            print("\n(dry run -- re-run with --apply)")
        return 0

    if not args.apply:
        print("DRY RUN -- nothing will be created. Re-run with --apply.\n")
        for issue in files:
            print("%-8s %s" % (issue.id, issue.title))
            print("         labels: %s" % (", ".join(issue.labels) or "-"))
            if issue.depends_on:
                print("         depends on: %s" % ", ".join(issue.depends_on))
        print("\n%d issue file(s). `--apply` creates the ones that do not exist "
              "yet, matched by exact title." % len(files))
        return 0

    require_gh()
    existing = existing_issues()

    created = updated = skipped = 0
    for issue in files:
        body = issue.rendered_body(index)
        match = existing.get(normalize_title(issue.title))
        if match:
            if args.update_bodies:
                result = gh("issue", "edit", str(match["number"]),
                            "--body", body, check=False)
                if result.returncode == 0:
                    print("updated  #%-5s %s" % (match["number"], issue.title))
                    updated += 1
                else:
                    print("FAILED   %s\n  %s"
                          % (issue.title, (result.stdout or "").strip()))
            else:
                print("exists   #%-5s %s" % (match["number"], issue.title))
                skipped += 1
            continue

        command = ["issue", "create", "--title", issue.title, "--body", body]
        for label in issue.labels:
            command += ["--label", label]
        if issue.milestone:
            command += ["--milestone", str(issue.milestone)]
        result = gh(*command, check=False)
        output = (result.stdout or "").strip()
        if result.returncode == 0:
            print("created  %s\n  %s" % (issue.title, output.splitlines()[-1]
                                         if output else ""))
            created += 1
        else:
            print("FAILED   %s\n  %s" % (issue.title, output))
            if "could not add label" in output or "not found" in output.lower():
                print("  Hint: create the labels first with "
                      "`python3 scripts/sync_issues.py --labels --apply`")

    print("\n%d created, %d updated, %d already existed."
          % (created, updated, skipped))
    return 0


if __name__ == "__main__":
    sys.exit(main())
