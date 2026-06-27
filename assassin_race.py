import subprocess
import json
import time
import os

CLANGD_PATH = r"D:\MSYS2\clang64\bin\clangd.exe"

def send_request(proc, req_dict):
    body = json.dumps(req_dict, separators=(',', ':'))
    header = f"Content-Length: {len(body)}\r\n\r\n"
    proc.stdin.write(header.encode('utf-8'))
    proc.stdin.write(body.encode('utf-8'))
    proc.stdin.flush()

def main():
    print(f"[*] 启动 Clangd: {CLANGD_PATH} (单线程模式)")
    proc = subprocess.Popen(
        [CLANGD_PATH, "-j=1", "--offset-encoding=utf-8"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )

    send_request(proc, {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {"processId": None, "rootUri": None, "capabilities": {}}
    })
    time.sleep(1)

    # 我们依然使用上一轮生成的 test.cpp（或者你直接把 ImageSpan.hpp 的内容写进去）
    uri = f"file:///{os.path.abspath('test.cpp').replace(chr(92), '/')}"

    with open("test.cpp", "r", encoding="utf-8") as f:
        code_content = f.read()

    # 寻找攻击坐标：假设 /*TARGET*/ 前面只有一个 'r'
    target_line, target_char = -1, -1
    for i, line in enumerate(code_content.split('\n')):
        if "/*TARGET*/" in line:
            target_line = i
            target_char = line.find("/*TARGET*/")
            break

    # 1. 模拟 Version 1: 只发送 'r' (把 test.cpp 里的 ro 改成 r)
    v1_content = code_content.replace("ro/*TARGET*/", "r")

    print("[*] 发送 Version 1: 包含残缺变量 'r'")
    send_request(proc, {
        "jsonrpc": "2.0", "method": "textDocument/didOpen",
        "params": {
            "textDocument": {"uri": uri, "languageId": "cpp", "version": 1, "text": v1_content}
        }
    })
    time.sleep(3.0) # 等它慢慢把庞大的 GCC 头文件和 ranges 解析完

    print("[*] 开始发动并发/时序攻击 (The Zed Simulation)...")

    # 2. 发送一个耗时的 FindType 请求 (让后台去查 'r')
    send_request(proc, {
        "jsonrpc": "2.0", "id": 2, "method": "textDocument/typeDefinition",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": target_line, "character": target_char - 1} # 指向 'r'
        }
    })

    # 【核心】：不等待！在 40 毫秒内瞬间发送 didChange (加入 'o') 和 completion
    time.sleep(0.04) # 模拟你日志里的 41ms 时差

    print("[*] 瞬间发送 didChange (Version 2) 添加 'o'...")
    send_request(proc, {
        "jsonrpc": "2.0", "method": "textDocument/didChange",
        "params": {
            "textDocument": {"uri": uri, "version": 2},
            "contentChanges": [{"range": {
                "start": {"line": target_line, "character": target_char},
                "end": {"line": target_line, "character": target_char}
            }, "text": "o"}]
        }
    })

    print("[*] 瞬间发送 completion 请求打断它...")
    send_request(proc, {
        "jsonrpc": "2.0", "id": 3, "method": "textDocument/completion",
        "params": {
            "textDocument": {"uri": uri},
            "position": {"line": target_line, "character": target_char + 1}
        }
    })

    print("[*] 观察进程是否能在打断中存活...")
    time.sleep(2)

    proc.poll()
    if proc.returncode is not None:
        hex_code = hex(proc.returncode & 0xFFFFFFFF)
        print(f"\n[!!!] 完美复现！Clangd 在处理 Version 1 时被中断击杀！")
        print(f"[!!!] 退出代码: {proc.returncode} ({hex_code})")
    else:
        print("\n[-] 进程依然存活。")
        proc.kill()
        print("\n坦白局：如果这个时序攻击依然不崩溃，说明触发崩溃的 AST 内存结构必须 100% 依赖你完整的 Croplines 项目级联依赖。除了你亲自把项目推到 GitHub 让 LLVM 开发者去跑，外部写单文件脚本已达到复现极限。")

if __name__ == "__main__":
    main()
