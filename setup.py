from setuptools import setup, find_packages

setup(
    name="ominime",
    version="0.1.0",
    description="macOS 输入追踪系统 - 记录你的每一次输入",
    author="OmniMe",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    include_package_data=True,
    package_data={"ominime": ["web/templates/*.html"]},
    python_requires=">=3.10",
    install_requires=[
        "pyobjc-core>=10.0",
        "pyobjc-framework-Cocoa>=10.0",
        "pyobjc-framework-Quartz>=10.0",
        "pyobjc-framework-ApplicationServices>=10.0",
        "rumps>=0.4.0",
        "python-dateutil>=2.8.2",
        "fastapi>=0.109.0",
        "uvicorn[standard]>=0.27.0",
        "pydantic>=2.0.0",
        "python-dotenv>=1.0.0",
        "requests>=2.31.0",
        "rich>=13.0.0",
    ],
    entry_points={
        "console_scripts": [
            "ominime=ominime.main:main",
        ],
    },
)
