"""Stamp the build with its source commit and date (viewer/_build_info.py, not committed)."""

import datetime
import os
import subprocess  # nosec B404 - runs git with a fixed argument list
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def commit():
    sha = os.environ.get("GITHUB_SHA", "")
    if sha:
        return sha[:12]
    try:
        out = subprocess.run(["git", "rev-parse", "--short=12", "HEAD"], cwd=ROOT, capture_output=True,  # nosec
                             text=True, timeout=20)
        return out.stdout.strip() or "local"
    except (OSError, subprocess.SubprocessError):
        return "local"


def main():
    date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(ROOT, "viewer", "_build_info.py")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(f'"""Written by tools/write_build_info.py during the build."""\n\n'
                 f'BUILD_COMMIT = {commit()!r}\nBUILD_DATE = {date!r}\n')
    print("build info:", path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
