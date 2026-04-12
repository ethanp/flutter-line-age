#!/usr/bin/env python3
"""Analyze a Flutter repo's Dart files by line age using git blame."""

import argparse
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


GENERATED_SUFFIXES = [".g.dart", ".freezed.dart", ".gr.dart", ".gen.dart", ".mocks.dart"]
SKIP_DIRS = {".dart_tool", "build", ".symlinks"}


def find_dart_files(repo: Path, extra_excludes: list[str] | None = None) -> list[Path]:
    """Find all non-generated .dart files in the repo."""
    excludes = GENERATED_SUFFIXES + (extra_excludes or [])
    dart_files = []
    for f in repo.rglob("*.dart"):
        # Skip files inside directories we want to ignore
        if any(part in SKIP_DIRS for part in f.parts):
            continue
        # Skip generated files
        if any(f.name.endswith(suffix) for suffix in excludes):
            continue
        dart_files.append(f)
    return sorted(dart_files)


def blame_file(file: Path, repo: Path) -> Counter[str]:
    """Run git blame on a file and return a Counter of YYYY-MM buckets."""
    counts: Counter[str] = Counter()
    rel = file.relative_to(repo)
    result = subprocess.run(
        ["git", "blame", "--line-porcelain", str(rel)],
        cwd=repo,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  warning: git blame failed for {rel}: {result.stderr.strip()}", file=sys.stderr)
        return counts

    for line in result.stdout.splitlines():
        if line.startswith("committer-time "):
            ts = int(line.split(" ", 1)[1])
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            bucket = dt.strftime("%Y-%m")
            counts[bucket] += 1

    return counts


CHART_TEMPLATE = Path(__file__).parent / "chart_template.html"


def build_histogram(
    counts: Counter[str],
    lines_by_file: dict[str, Counter[str]],
    repo_name: str,
    output: str | None,
) -> None:
    """Render a stacked bar chart as a self-contained D3.js HTML file."""
    import json
    import tempfile
    import webbrowser

    sorted_months = sorted(counts.keys())

    month_data = [
        {
            "month": month,
            "total": counts[month],
            "segments": [
                {"file": filename, "count": line_count}
                for filename, line_count in lines_by_file.get(month, Counter()).most_common()
            ],
        }
        for month in sorted_months
    ]

    total_by_file: Counter[str] = Counter()
    for month_file_counts in lines_by_file.values():
        total_by_file.update(month_file_counts)
    all_files = [name for name, _ in total_by_file.most_common()]

    payload = json.dumps({"months": month_data, "files": all_files, "repo": repo_name})
    html = CHART_TEMPLATE.read_text(encoding="utf-8").replace("__PAYLOAD__", payload)

    if output:
        Path(output).write_text(html, encoding="utf-8")
        print(f"Chart saved to {output}")
    else:
        with tempfile.NamedTemporaryFile(
            suffix=".html", delete=False, mode="w", encoding="utf-8"
        ) as tmp:
            tmp.write(html)
            webbrowser.open(f"file://{tmp.name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze Flutter/Dart line age via git blame")
    parser.add_argument("repo", type=Path, help="Path to the Flutter/Dart git repo")
    parser.add_argument(
        "--exclude",
        nargs="*",
        default=[],
        help="Extra generated file suffixes to skip (e.g. .custom.dart)",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Save the chart to an HTML file instead of showing interactively",
    )
    args = parser.parse_args()

    repo: Path = args.repo.resolve()
    if not repo.is_dir():
        sys.exit(f"Error: {repo} is not a directory")
    if not (repo / ".git").exists():
        sys.exit(f"Error: {repo} is not a git repository")

    print(f"Scanning {repo} for Dart files...")
    dart_files = find_dart_files(repo, args.exclude)
    if not dart_files:
        sys.exit("No non-generated Dart files found.")
    print(f"Found {len(dart_files)} Dart files")

    total_counts: Counter[str] = Counter()
    lines_by_file: dict[str, Counter[str]] = defaultdict(Counter)

    for index, filepath in enumerate(dart_files, 1):
        rel = filepath.relative_to(repo)
        print(f"  [{index}/{len(dart_files)}] {rel}")
        file_counts = blame_file(filepath, repo)
        total_counts += file_counts
        for month, line_count in file_counts.items():
            lines_by_file[month][str(rel)] += line_count

    total_lines = sum(total_counts.values())
    print(f"\nAnalyzed {total_lines:,} lines across {len(dart_files)} files")

    build_histogram(total_counts, lines_by_file, repo.name, args.output)


if __name__ == "__main__":
    main()
