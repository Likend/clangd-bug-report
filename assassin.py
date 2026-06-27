#!/usr/bin/env python3
"""
精确复现脚本 —— 基于最新 Zed 日志的请求序列
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

    # 启动 clangd
    proc = await asyncio.create_subprocess_exec(
        "clangd",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=project_dir
    )

    # 后台消费 stdout，防止阻塞
    async def drain_stdout():
        while True:
            msg = await read_message(proc.stdout)
            if msg is None:
                break
    asyncio.create_task(drain_stdout())

    # 初始化
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

    # 打开文件
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
    # 等待 clangd 完成 preamble 构建和索引（日志中约 4.5 秒）
    await asyncio.sleep(5)  # 给足时间

    # 定位 ro/*TARGET*/ 的起始字符位置（column = 42, line = 37）
    marker = "ro/*TARGET*/"
    idx = original.find(marker)
    if idx == -1:
        print("错误: 找不到 ro/*TARGET*/")
        return
    before = original[:idx]
    line = before.count('\n')
    col = idx - before.rfind('\n') - 1 if line > 0 else idx

    # ---------- 第一步：删除 "ro" ----------
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
    # 模拟思考时间（日志中约 11 秒）
    await asyncio.sleep(11)

    # ---------- 第二步：输入 "r" ----------
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

    # ---------- 第三步：立即并发发送全部请求 ----------
    # 光标位置在刚插入的 "r" 之后，即 column = col+1
    pos = {"line": line, "character": col+1}
    doc = {"textDocument": {"uri": uri}, "position": pos}

    # 按照日志顺序和并发度，使用 create_task 同时发送
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

    # 等待 1 秒，检查 clangd 是否崩溃
    await asyncio.sleep(1)
    if proc.returncode is not None:
        print(f"✅ 崩溃复现成功！返回码: {proc.returncode}")
        stderr_data = await proc.stderr.read()
        if stderr_data:
            print("stderr:", stderr_data.decode(errors='replace'))
    else:
        print("未崩溃，clangd 仍存活。")
        proc.terminate()
        await proc.wait()

if __name__ == "__main__":
    asyncio.run(main())
