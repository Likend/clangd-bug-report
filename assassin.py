#!/usr/bin/env python3
"""
Precise reproduction script -- based on the request sequence from the latest Zed log
"""

import asyncio
import json
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

CPP_FILE = "test.cpp"


async def read_message(stream):
    headers = {}
    while True:
        line = await stream.readline()
        if not line:
            return None
        line = line.decode("utf-8", errors="replace").rstrip("\r\n")
        if line == "":
            break
        key, _, value = line.partition(":")
        headers[key.strip()] = value.strip()
    length = int(headers.get("Content-Length", 0))
    if length == 0:
        return None
    body = await stream.readexactly(length)
    return json.loads(body.decode("utf-8", errors="replace"))


async def send_message(writer, msg):
    content = json.dumps(msg)
    header = f"Content-Length: {len(content)}\r\n\r\n"
    writer.write(header.encode() + content.encode())
    await writer.drain()


async def main():
    cpp_path = os.path.abspath(CPP_FILE)
    project_dir = os.path.dirname(cpp_path)
    uri = "file:///" + cpp_path.replace(os.sep, "/")

    # Start clangd
    proc = await asyncio.create_subprocess_exec(
        "clangd",
        "--log=verbose",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_dir,
    )

    # Background task to consume stdout to prevent blocking
    async def drain_stdout():
        while True:
            msg = await read_message(proc.stdout)
            if msg is None:
                break

    asyncio.create_task(drain_stdout())

    # Initialization
    await send_message(
        proc.stdin,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "processId": None,
                "rootUri": "file:///" + project_dir.replace(os.sep, "/"),
                "capabilities": {},
            },
        },
    )
    await asyncio.sleep(0.5)
    await send_message(
        proc.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}}
    )

    # Open the file
    with open(cpp_path, encoding="utf-8") as f:
        original = f.read()
    await send_message(
        proc.stdin,
        {
            "jsonrpc": "2.0",
            "method": "textDocument/didOpen",
            "params": {
                "textDocument": {
                    "uri": uri,
                    "languageId": "cpp",
                    "version": 0,
                    "text": original,
                }
            },
        },
    )
    # Wait for clangd to build the preamble and finish indexing (about 4.5 seconds in the log)
    await asyncio.sleep(5)  # Give it plenty of time

    marker = "test_concept"
    idx = original.find(marker)
    if idx == -1:
        print(f"Error: Could not find `{marker}`")
        return
    before = original[:idx]
    line = before.count("\n")
    col = idx - before.rfind("\n") - 1 if line > 0 else idx
    print(line, col)

    await send_message(
        proc.stdin,
        {
            "jsonrpc": "2.0",
            "id": 51,
            "method": "textDocument/typeDefinition",
            "params": {
                "textDocument": {"uri": uri},
                "position": {"line": line, "character": col},
            },
        },
    )

    # Wait 1 second, then check if clangd crashed
    await asyncio.sleep(1)
    if proc.returncode is not None:
        print(f"Crash reproduced successfully! Return code: {proc.returncode}")
        stderr_data = await proc.stderr.read()
        if stderr_data:
            print("stderr:", stderr_data.decode("utf-8", errors="replace"))
    else:
        print("Did not crash, clangd is still alive.", file=sys.stderr)
        proc.terminate()
        await proc.wait()


if __name__ == "__main__":
    asyncio.run(main())
