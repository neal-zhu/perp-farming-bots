"""Check repository-local Markdown links and heading anchors without network reads."""

from __future__ import annotations

import re
import subprocess
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
INLINE_LINK = re.compile(r"!?\[[^\]\n]*\]\((<[^>]+>|[^\s)]+)(?:\s+[^)]*)?\)")
REFERENCE_LINK = re.compile(r"^\s*\[[^\]]+\]:\s*(\S+)", re.MULTILINE)


def without_code(text: str) -> str:
    lines = []
    fence: str | None = None
    for line in text.splitlines():
        marker = re.match(r"^\s*(`{3,}|~{3,})", line)
        if marker:
            if fence is None:
                fence = marker[1][0]
            elif marker[1][0] == fence:
                fence = None
            continue
        if fence is None:
            lines.append(line)
    return "\n".join(lines)


def heading_anchors(text: str) -> set[str]:
    anchors = set()
    counts: dict[str, int] = {}
    for line in without_code(text).splitlines():
        match = re.match(r"^#{1,6}\s+(.+?)\s*#*\s*$", line)
        if match is None:
            continue
        heading = re.sub(r"!?\[([^\]]+)\]\([^)]*\)", r"\1", match[1])
        heading = re.sub(r"<[^>]+>", "", heading).lower()
        slug = re.sub(r"[^\w\- ]", "", heading).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        anchors.add(f"{slug}-{count}" if count else slug)
    return anchors


def check() -> int:
    listed = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=ROOT, capture_output=True, check=True,
    ).stdout.decode().split("\0")
    files = sorted({ROOT / name for name in listed if name.endswith(".md") or name == "llms.txt"})
    checked, failures = 0, []
    for source in files:
        if not source.is_file():
            continue  # Tracked deletions in a working tree have no outgoing links.
        checked += 1
        text = without_code(source.read_text())
        links = [match[1].strip("<>") for match in INLINE_LINK.finditer(text)]
        links.extend(match[1] for match in REFERENCE_LINK.finditer(text))
        for link in links:
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
            label = f"{source.relative_to(ROOT)}: {link}"
            if not target.is_relative_to(ROOT) or not target.exists():
                failures.append(label + " (missing repository target)")
            elif parsed.fragment and target.suffix == ".md" and unquote(parsed.fragment) not in heading_anchors(target.read_text()):
                failures.append(label + " (missing heading anchor)")
    if failures:
        print("Documentation errors:\n" + "\n".join(failures))
        return 1
    print(f"Documentation links OK ({checked} files; no external requests)")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())
