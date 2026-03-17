"""Generate a site report for remote troubleshooting.

This script is meant to be run by a local Claude instance (Claude Code,
Cursor, etc.) when a user reports a problem. It collects system state
and writes a structured report that can be sent to the remote developer.

Usage:
    python tools/site_report.py
    python tools/site_report.py --issue "describe the problem"
    python tools/site_report.py --output /path/to/reports/

The report is designed to be read by another Claude instance or a human
developer, so it includes context that would otherwise be lost in
user-mediated communication.
"""

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path


def get_system_info() -> dict:
    """Collect basic system information."""
    return {
        "os": platform.system(),
        "os_version": platform.version(),
        "python": sys.version,
        "hostname": platform.node(),
        "timestamp": datetime.now().isoformat(),
    }


def get_docker_status() -> dict:
    """Check Docker/container status."""
    info = {"docker_available": False}

    docker_cmd = shutil.which("docker")
    if not docker_cmd:
        return info

    info["docker_available"] = True

    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Ports}}"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            containers = []
            for line in result.stdout.strip().splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    containers.append({
                        "name": parts[0],
                        "status": parts[1],
                        "ports": parts[2] if len(parts) > 2 else "",
                    })
            info["running_containers"] = containers
    except Exception as e:
        info["docker_error"] = str(e)

    return info


def get_project_status(project_dir: Path) -> dict:
    """Check the state of the project directory."""
    info = {"project_dir": str(project_dir), "exists": project_dir.exists()}

    if not project_dir.exists():
        return info

    # Git status
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
            cwd=project_dir,
        )
        if result.returncode == 0:
            info["git_dirty"] = bool(result.stdout.strip())
            info["git_changes"] = result.stdout.strip() if result.stdout.strip() else None

        result = subprocess.run(
            ["git", "log", "--oneline", "-5"],
            capture_output=True, text=True, timeout=10,
            cwd=project_dir,
        )
        if result.returncode == 0:
            info["recent_commits"] = result.stdout.strip().splitlines()

        result = subprocess.run(
            ["git", "branch", "--show-current"],
            capture_output=True, text=True, timeout=10,
            cwd=project_dir,
        )
        if result.returncode == 0:
            info["branch"] = result.stdout.strip()

    except Exception as e:
        info["git_error"] = str(e)

    # Check for key files
    key_files = [
        "config.yaml", "requirements.txt", ".env", "Dockerfile",
        "docker-compose.yaml", "src/main.py", "src/agents/librarian.py",
        "src/agents/orchestrator.py", "src/web/server.py",
    ]
    info["files_present"] = {f: (project_dir / f).exists() for f in key_files}

    # Check venv
    venv_paths = [project_dir / ".venv", project_dir / "venv"]
    info["venv_exists"] = any(p.exists() for p in venv_paths)

    return info


def get_content_status(content_dir: Path) -> dict:
    """Check the state of the content directory."""
    info = {"content_dir": str(content_dir), "exists": content_dir.exists()}

    if not content_dir.exists():
        return info

    # Lore files
    lore_dir = content_dir / "lore"
    if lore_dir.exists():
        lore_files = list(lore_dir.rglob("*.md"))
        info["lore_file_count"] = len(lore_files)
        info["lore_total_size"] = sum(f.stat().st_size for f in lore_files)
        info["lore_directories"] = sorted(set(
            str(f.parent.relative_to(lore_dir))
            for f in lore_files
            if f.parent != lore_dir
        ))
    else:
        info["lore_dir_exists"] = False

    # Story files
    story_dir = content_dir / "story"
    if story_dir.exists():
        story_files = list(story_dir.rglob("*.md"))
        info["story_file_count"] = len(story_files)
        info["story_total_size"] = sum(f.stat().st_size for f in story_files)
    else:
        info["story_dir_exists"] = False

    # Code requests
    cr_dir = content_dir / "code-requests"
    if cr_dir.exists():
        cr_files = list(cr_dir.glob("*.md"))
        info["pending_code_requests"] = len(cr_files)
        info["code_request_files"] = [f.name for f in sorted(cr_files)]
    else:
        info["code_requests_dir_exists"] = False

    # .env exists (don't read contents!)
    info["env_file_exists"] = (content_dir / ".env").exists()

    return info


def get_api_status() -> dict:
    """Check API key availability (not the key itself)."""
    info = {}
    info["ANTHROPIC_API_KEY_set"] = bool(os.environ.get("ANTHROPIC_API_KEY"))
    info["OPENAI_API_KEY_set"] = bool(os.environ.get("OPENAI_API_KEY"))
    return info


def check_imports() -> dict:
    """Check if key Python dependencies are importable."""
    deps = ["anthropic", "pydantic", "yaml", "fastapi", "uvicorn", "dotenv"]
    results = {}
    for dep in deps:
        try:
            __import__(dep)
            results[dep] = "ok"
        except ImportError:
            results[dep] = "missing"
    return results


def get_recent_logs(content_dir: Path) -> dict:
    """Check for recent session logs."""
    log_dir = content_dir / "story" / "logs"
    if not log_dir.exists():
        return {"log_dir_exists": False}

    log_files = sorted(log_dir.glob("session-*.md"), reverse=True)
    info = {"log_count": len(log_files)}

    if log_files:
        latest = log_files[0]
        info["latest_log"] = latest.name
        info["latest_log_size"] = latest.stat().st_size
        # Read last 2000 chars of most recent log
        content = latest.read_text(encoding="utf-8")
        if len(content) > 2000:
            content = "...\n" + content[-2000:]
        info["latest_log_tail"] = content

    return info


def generate_report(
    project_dir: Path,
    content_dir: Path,
    issue: str | None = None,
) -> str:
    """Generate a full site report."""
    report = {
        "report_type": "site_report",
        "generated_at": datetime.now().isoformat(),
        "issue": issue,
        "system": get_system_info(),
        "docker": get_docker_status(),
        "project": get_project_status(project_dir),
        "content": get_content_status(content_dir),
        "api_keys": get_api_status(),
        "dependencies": check_imports(),
        "recent_logs": get_recent_logs(content_dir),
    }

    # Build the markdown report
    lines = [
        "---",
        f"title: Site Report",
        f"date: {report['generated_at']}",
        f"hostname: {report['system']['hostname']}",
        "type: site_report",
        "status: pending_review",
        "---",
        "",
        "# Site Report",
        "",
    ]

    if issue:
        lines.extend([
            "## Reported Issue",
            "",
            issue,
            "",
        ])

    lines.extend([
        "## System",
        "",
        f"- OS: {report['system']['os']} {report['system']['os_version']}",
        f"- Python: {report['system']['python'].split()[0]}",
        f"- Docker available: {report['docker']['docker_available']}",
    ])

    if report["docker"].get("running_containers"):
        lines.append("- Running containers:")
        for c in report["docker"]["running_containers"]:
            lines.append(f"  - {c['name']}: {c['status']} ({c['ports']})")

    lines.extend(["", "## Project State", ""])

    proj = report["project"]
    lines.append(f"- Directory: `{proj['project_dir']}` (exists: {proj['exists']})")
    if proj.get("branch"):
        lines.append(f"- Branch: `{proj['branch']}`")
    if proj.get("recent_commits"):
        lines.append("- Recent commits:")
        for c in proj["recent_commits"]:
            lines.append(f"  - `{c}`")
    if proj.get("git_dirty"):
        lines.append(f"- Uncommitted changes:\n```\n{proj['git_changes']}\n```")
    if proj.get("files_present"):
        missing = [f for f, exists in proj["files_present"].items() if not exists]
        if missing:
            lines.append(f"- Missing expected files: {', '.join(missing)}")
        else:
            lines.append("- All expected files present")
    lines.append(f"- Virtual environment: {'found' if proj.get('venv_exists') else 'not found'}")

    lines.extend(["", "## Content State", ""])

    content = report["content"]
    lines.append(f"- Directory: `{content['content_dir']}` (exists: {content['exists']})")
    if content.get("lore_file_count") is not None:
        lines.append(f"- Lore files: {content['lore_file_count']} ({content['lore_total_size']:,} bytes)")
        if content.get("lore_directories"):
            lines.append(f"- Lore categories: {', '.join(content['lore_directories'])}")
    if content.get("story_file_count") is not None:
        lines.append(f"- Story files: {content['story_file_count']} ({content['story_total_size']:,} bytes)")
    if content.get("pending_code_requests"):
        lines.append(f"- Pending code requests: {content['pending_code_requests']}")
        for cr in content["code_request_files"]:
            lines.append(f"  - {cr}")
    lines.append(f"- .env file: {'present' if content.get('env_file_exists') else 'MISSING'}")

    lines.extend(["", "## API Keys", ""])
    lines.append(f"- ANTHROPIC_API_KEY: {'set' if report['api_keys']['ANTHROPIC_API_KEY_set'] else 'NOT SET'}")
    lines.append(f"- OPENAI_API_KEY: {'set' if report['api_keys']['OPENAI_API_KEY_set'] else 'not set'}")

    lines.extend(["", "## Dependencies", ""])
    deps = report["dependencies"]
    missing_deps = [d for d, s in deps.items() if s == "missing"]
    if missing_deps:
        lines.append(f"- Missing: {', '.join(missing_deps)}")
    else:
        lines.append("- All dependencies installed")

    if report["recent_logs"].get("latest_log"):
        lines.extend([
            "", "## Recent Session Log", "",
            f"File: `{report['recent_logs']['latest_log']}`",
            "",
            "```",
            report["recent_logs"].get("latest_log_tail", "(empty)"),
            "```",
        ])

    lines.extend(["", "---", "",
        "Generated by `tools/site_report.py`. "
        "Send this file to Patch for remote troubleshooting.",
    ])

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate a site report for remote troubleshooting")
    parser.add_argument("--issue", "-i", type=str, help="Description of the problem")
    parser.add_argument("--project-dir", type=Path, default=Path("."), help="Project directory")
    parser.add_argument("--content-dir", type=Path, default=None, help="Content directory")
    parser.add_argument("--output", "-o", type=Path, default=None, help="Output directory for the report")
    args = parser.parse_args()

    # Try to find content dir
    content_dir = args.content_dir
    if content_dir is None:
        candidates = [
            Path.home() / "Documents" / "narrative-content",
            Path("/app"),  # In-container path
            args.project_dir,
        ]
        for c in candidates:
            if c.exists() and (c / "lore").exists():
                content_dir = c
                break
        if content_dir is None:
            content_dir = Path.home() / "Documents" / "narrative-content"

    report = generate_report(args.project_dir, content_dir, args.issue)

    # Write report
    timestamp = datetime.now().strftime("%Y-%m-%d-%H%M%S")
    hostname = platform.node().split(".")[0]
    filename = f"site-report-{hostname}-{timestamp}.md"

    if args.output:
        output_dir = args.output
    else:
        output_dir = content_dir / "code-requests" if content_dir.exists() else Path(".")

    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / filename

    output_path.write_text(report, encoding="utf-8")
    print(f"Site report written to: {output_path}")
    print()
    print("Send this file to Patch for troubleshooting.")
    print(f"Or paste the contents: cat {output_path}")


if __name__ == "__main__":
    main()
