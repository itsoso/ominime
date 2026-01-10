"""
py2app 配置文件
用于将 OmniMe 打包成 macOS 应用

使用方法:
    python setup_app.py py2app
"""

from setuptools import setup

APP = ['src/ominime/app_entry.py']
DATA_FILES = [
    ('templates', ['src/ominime/web/templates/index.html']),
    ('static', []),  # 静态文件目录
]

OPTIONS = {
    'argv_emulation': False,
    'iconfile': 'resources/OmniMe.icns',
    'plist': {
        'CFBundleName': 'OmniMe',
        'CFBundleDisplayName': 'OmniMe',
        'CFBundleIdentifier': 'com.ominime.app',
        'CFBundleVersion': '0.1.0',
        'CFBundleShortVersionString': '0.1.0',
        'NSHumanReadableCopyright': '© 2026 OmniMe',
        'LSBackgroundOnly': False,
        'LSUIElement': True,  # 菜单栏应用，不显示在 Dock
        'NSAccessibilityUsageDescription': 'OmniMe 需要辅助功能权限来监听键盘输入',
        'NSAppleEventsUsageDescription': 'OmniMe 需要访问系统事件来追踪应用使用',
    },
    'packages': [
        'ominime',
        'rumps',
        'rich',
        'dateutil',
        'fastapi',
        'uvicorn',
        'starlette',
        'pydantic',
        'anyio',
        'sniffio',
        'click',
        'h11',
    ],
    'includes': [
        'AppKit',
        'Foundation',
        'Cocoa',
        'Quartz',
        'ApplicationServices',
        'CoreFoundation',
        'objc',
    ],
    'excludes': [
        'tkinter',
        'test',
        'unittest',
    ],
}

setup(
    name='OmniMe',
    app=APP,
    data_files=DATA_FILES,
    options={'py2app': OPTIONS},
    setup_requires=['py2app'],
)
