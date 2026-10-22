"""Stop フック：作業を終える前に単体テストを実行し、失敗していれば終了をブロックする。

終了コード 2 で stderr の内容が Claude に返され、修正を続けさせる。
stop_hook_active が真のとき（このフックで一度止められた後）は、無限ループを避けるため通す。
"""
import json
import os
import subprocess
import sys


def main():
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        payload = {}
    if payload.get("stop_hook_active"):
        return 0

    project_dir = os.environ.get("CLAUDE_PROJECT_DIR") or os.getcwd()
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests"],
        cwd=project_dir, capture_output=True, text=True, timeout=300,
    )
    if proc.returncode == 0:
        return 0

    tail = "\n".join((proc.stdout + proc.stderr).strip().splitlines()[-40:])
    sys.stderr.write(
        "単体テストが失敗しています。作業を終える前に修正してください。\n"
        "テストの閾値（tests/sanity_config.json）を緩めたり、テストをスキップ・削除したりしてはいけません。\n"
        "閾値そのものが不適切だと考える場合は、変更せずにその理由をオーナーに報告してください。\n\n"
        + tail + "\n"
    )
    return 2


if __name__ == "__main__":
    sys.exit(main())
