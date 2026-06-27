#!/usr/bin/env python3
"""
Precise reproduction script -- based on the request sequence from the latest Zed log
"""
import asyncio
import json
import os

CPP_FILE = "test.cpp"

async def read_message(stream):
    headers = {}
    while True:
        line = await stream.readline()
        if not line:
            return None
        line = line.decode('utf-8', errors='replace').rstrip('\r\n')
        if line == '':
            break
        key, _, value = line.partition(':')
        headers[key.strip()] = value.strip()
    length = int(headers.get('Content-Length', 0))
    if length == 0:
        return None
    body = await stream.readexactly(length)
    return json.loads(body.decode('utf-8', errors='replace'))

async def send_message(writer, msg):
    content = json.dumps(msg)
    header = f'Content-Length: {len(content)}\r\n\r\n'
    writer.write(header.encode() + content.encode())
    await writer.drain()

async def main():
    cpp_path = os.path.abspath(CPP_FILE)
    project_dir = os.path.dirname(cpp_path)
    uri = "file:///" + cpp_path.replace(os.sep, '/')

    # Start clangd
    proc = await asyncio.create_subprocess_exec(
        "clangd",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_dir
    )

    # Background task to consume stdout to prevent blocking
    async def drain_stdout():
        while True:
            msg = await read_message(proc.stdout)
            if msg is None:
                break
    asyncio.create_task(drain_stdout())

    # Initialization
    await send_message(proc.stdin, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "processId": None,
            "rootUri": "file:///" + project_dir.replace(os.sep, '/'),
            "capabilities": {}
        }
    })
    await asyncio.sleep(0.5)
    await send_message(proc.stdin, {"jsonrpc": "2.0", "method": "initialized", "params": {}})

    # Open the file
    with open(cpp_path, encoding='utf-8') as f:
        original = f.read()
    await send_message(proc.stdin, {
        "jsonrpc": "2.0", "method": "textDocument/didOpen",
        "params": {
            "textDocument": {
                "uri": uri, "languageId": "cpp", "version": 0, "text": original
            }
        }
    })
    # Wait for clangd to build the preamble and finish indexing (about 4.5 seconds in the log)
    await asyncio.sleep(5)  # Give it plenty of time

    # Locate the starting character position of ro/*TARGET*/ (column = 42, line = 37)
    marker = "ro/*TARGET*/"
    idx = original.find(marker)
    if idx == -1:
        print("Error: Could not find ro/*TARGET*/")
        return
    before = original[:idx]
    line = before.count('\n')
    col = idx - before.rfind('\n') - 1 if line > 0 else idx

    # ---------- Step 1: Delete "ro" ----------
    await send_message(proc.stdin, {
        "jsonrpc": "2.0", "method": "textDocument/didChange",
        "params": {
            "textDocument": {"uri": uri, "version": 1},
            "contentChanges": [
                {"range": {"start": {"line": line, "character": col},
                           "end": {"line": line, "character": col+2}},
                 "text": ""}
            ]
        }
    })
    # Simulate thinking time (about 11 seconds in the log)
    await asyncio.sleep(11)

    # ---------- Step 2: Type "r" ----------
    await send_message(proc.stdin, {
        "jsonrpc": "2.0", "method": "textDocument/didChange",
        "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [
                {"range": {"start": {"line": line, "character": col},
                           "end": {"line": line, "character": col}},
                 "text": "r"}
            ]
        }
    })

    # ---------- Step 3: Immediately send all requests concurrently ----------
    # Cursor position is right after the newly inserted "r", i.e., column = col+1
    pos = {"line": line, "character": col+1}
    doc = {"textDocument": {"uri": uri}, "position": pos}

    # Follow the order and concurrency from the log; send simultaneously using create_task
    tasks = [
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 43,
            "method": "textDocument/completion",
            "params": {"textDocument": {"uri": uri}, "position": pos, "context": {"triggerKind": 1}}
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 44,
            "method": "textDocument/documentHighlight",
            "params": doc
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 45,
            "method": "textDocument/documentLink",
            "params": {"textDocument": {"uri": uri}}
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 46,
            "method": "textDocument/definition",
            "params": doc
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 47,
            "method": "textDocument/typeDefinition",
            "params": doc
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 48,
            "method": "textDocument/definition",
            "params": {"textDocument": {"uri": uri}, "position": {"line": 10, "character": 8}}
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 49,
            "method": "textDocument/typeDefinition",
            "params": {"textDocument": {"uri": uri}, "position": {"line": 10, "character": 8}}
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 50,
            "method": "textDocument/definition",
            "params": {"textDocument": {"uri": uri}, "position": {"line": 9, "character": 19}}
        }),
        send_message(proc.stdin, {
            "jsonrpc": "2.0", "id": 51,
            "method": "textDocument/typeDefinition",
            "params": {"textDocument": {"uri": uri}, "position": {"line": 9, "character": 19}}
        }),
    ]
    await asyncio.gather(*tasks)

    # Wait 1 second, then check if clangd crashed
    await asyncio.sleep(1)
    if proc.returncode is not None:
        print(f"Crash reproduced successfully! Return code: {proc.returncode}")
        stderr_data = await proc.stderr.read()
        if stderr_data:
            print("stderr:", stderr_data.decode(errors='replace'))
    else:
        print("Did not crash, clangd is still alive.")
        proc.terminate()
        await proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
