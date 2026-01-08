from setuptools import setup, find_packages

setup(
    name="ominime",
    version="0.1.0",
    description="macOS 输入追踪系统 - 记录你的每一次输入",
    author="OmniMe",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.10",
    install_requires=[
        "pyobjc-core>=10.0",
        "pyobjc-framework-Cocoa>=10.0",
        "pyobjc-framework-Quartz>=10.0",
        "pyobjc-framework-ApplicationServices>=10.0",
        "rumps>=0.4.0",
        "python-dateutil>=2.8.2",
        "rich>=13.0.0",
    ],
    extras_require={
        "ai": ["openai>=1.0.0"],
    },
    entry_points={
        "console_scripts": [
            "ominime=ominime.main:main",
        ],
    },
)

