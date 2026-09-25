"""Invoke one hub MCP tool via the official SDK. No implicit live request.

Arguments: exact JSON file containing {"tool": name, "arguments": {...}}.
Used for transparent local integration checks and supported batch scripting.
"""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

from mcp import Client
from mcp.client.stdio import StdioServerParameters


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("request_file", type=Path)
    parser.add_argument("--state-dir", type=Path)
    parser.add_argument('--call-timeout', type=int, default=180, help='MCP call timeout in seconds, including model catalog refresh (30..600). A timeout never authorizes a duplicate send.')
    parser.add_argument("--wait", action="store_true", help="Keep the MCP connection alive through a submitted batch; print status changes")
    args = parser.parse_args()
    if not 30 <= args.call_timeout <= 600:
        parser.error('--call-timeout must be between 30 and 600 seconds')
    request = json.loads(args.request_file.read_text(encoding="utf-8-sig"))
    command = ["-m", "coda_review_hub.mcp_server"]
    if args.state_dir:
        command += ["--state-dir", str(args.state_dir.resolve())]
    env = {k: v for k, v in os.environ.items() if k.upper() in {
        "SYSTEMROOT", "WINDIR", "USERPROFILE", "HOME", "HOMEDRIVE", "HOMEPATH",
        "APPDATA", "LOCALAPPDATA", "TEMP", "TMP", "COMSPEC", "PATHEXT", "PATH"}}
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[1] / "src")
    async with Client(StdioServerParameters(command=sys.executable, args=command, env=env), read_timeout_seconds=args.call_timeout) as client:
        result = await client.call_tool(request["tool"], request.get("arguments", {}))
        print(json.dumps(result.model_dump(mode="json"), ensure_ascii=True), flush=True)
        if args.wait and request["tool"] == "submit" and not result.is_error:
            batch = result.structured_content["batch_id"]
            project = request["arguments"]["project"]
            last = None
            for _ in range(800):
                jobs = await client.call_tool("jobs", {"project": project, "batch_id": batch})
                if jobs.is_error:
                    print(json.dumps({"error": "Job collection failed; inspect the saved batch before any retry", "batch": batch}), flush=True)
                    return 2
                content = jobs.structured_content
                rows = content if isinstance(content, list) else (content or {}).get("result", [])
                if rows:
                    statuses = [(r["id"], r["state"]) for r in rows]
                    if statuses != last:
                        print(json.dumps({"batch": batch, "states": statuses}), flush=True)
                        last = statuses
                    if all(r["state"] not in ("prepared", "running") for r in rows):
                        for row in rows:
                            answer = await client.call_tool("result", {"project": project, "job_id": row["id"]})
                            print(json.dumps(answer.model_dump(mode="json"), ensure_ascii=True), flush=True)
                        return 0 if all(r["state"] == "returned" for r in rows) else 2
                await asyncio.sleep(5)
            print(json.dumps({"error": "Collection deadline reached; inspect the saved batch before any retry", "batch": batch}), flush=True)
            return 2
        return 1 if result.is_error else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
