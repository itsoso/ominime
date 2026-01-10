#!/usr/bin/env python3
"""
OmniMe 桌面应用入口点

作为 macOS 应用运行时的入口
"""

import sys
import os
import threading
import webbrowser

# 确保能找到包
if getattr(sys, 'frozen', False):
    # 如果是打包后的应用
    bundle_dir = os.path.dirname(sys.executable)
    sys.path.insert(0, os.path.join(bundle_dir, '..', 'Resources', 'lib', 'python3.13', 'site-packages'))

from ominime.menu_bar_app import OmniMeMenuBarApp


def main():
    """主函数"""
    app = OmniMeMenuBarApp()
    app.run()


if __name__ == "__main__":
    main()
