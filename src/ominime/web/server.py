"""
Web 服务器启动模块
"""

import uvicorn
from pathlib import Path


def run_server(host: str = "127.0.0.1", port: int = 8001, reload: bool = False):
    """
    启动 Web 服务器
    
    Args:
        host: 主机地址
        port: 端口号
        reload: 是否启用热重载（开发模式）
    """
    print(f"""
╔══════════════════════════════════════════════════════════╗
║                                                          ║
║   ⌨️  OmniMe Web Dashboard                                ║
║                                                          ║
║   🌐 访问地址: http://{host}:{port}                       ║
║   📊 API 文档: http://{host}:{port}/docs                  ║
║                                                          ║
║   按 Ctrl+C 停止服务器                                    ║
║                                                          ║
╚══════════════════════════════════════════════════════════╝
""")
    
    uvicorn.run(
        "ominime.web.api:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )


if __name__ == "__main__":
    run_server()
