#!/usr/bin/env python3
"""
Web 仪表盘启动器

使用方法:
    python -m commodity_assistant.web_launcher
    python -m commodity_assistant.web_launcher --port 8080
    python -m commodity_assistant.web_launcher --no-browser  # 不自动打开浏览器
"""

import argparse
import logging
import threading
import time
import webbrowser

import uvicorn


def main():
    parser = argparse.ArgumentParser(description="大宗商品量化助手 - Web 仪表盘")
    parser.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="监听端口 (默认 8765)")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    parser.add_argument("--reload", action="store_true", help="开启热重载 (开发模式)")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    url = f"http://{args.host}:{args.port}"
    print("=" * 60)
    print("  大宗商品量化助手 - Web 仪表盘")
    print("=" * 60)
    print(f"  访问地址: {url}")
    print(f"  停止服务: Ctrl+C")
    print("=" * 60)

    # 延迟打开浏览器 (等服务器启动)
    if not args.no_browser:
        def open_browser():
            time.sleep(1.5)
            try:
                webbrowser.open(url)
            except Exception as e:
                print(f"  ⚠ 无法自动打开浏览器: {e}")
                print(f"  请手动访问: {url}")
        threading.Thread(target=open_browser, daemon=True).start()

    # 启动服务器
    uvicorn.run(
        "commodity_assistant.web.server:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level="info",
    )


if __name__ == "__main__":
    main()
