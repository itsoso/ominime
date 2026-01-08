"""
配置管理模块
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json


@dataclass
class AppConfig:
    """应用配置"""
    
    # 数据目录
    data_dir: Path = field(default_factory=lambda: Path.home() / ".ominime")
    
    # 数据库文件
    db_path: Path = field(default_factory=lambda: Path.home() / ".ominime" / "ominime.db")
    
    # 日志目录
    log_dir: Path = field(default_factory=lambda: Path.home() / ".ominime" / "logs")
    
    # 是否启用 AI 总结
    ai_enabled: bool = False
    
    # OpenAI API Key (从环境变量读取)
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    
    # OpenAI 模型
    openai_model: str = "gpt-4o-mini"
    
    # 应用别名映射 (bundle_id -> 显示名称)
    app_aliases: Dict[str, str] = field(default_factory=lambda: {
        "com.tencent.xinWeChat": "微信",
        "com.apple.MobileSMS": "信息",
        "com.todesktop.230313mzl4w4u92": "Cursor",
        "md.obsidian": "Obsidian",
        "com.electron.kim": "Kim",
        "com.apple.Safari": "Safari",
        "com.google.Chrome": "Chrome",
        "com.apple.mail": "邮件",
        "com.apple.Notes": "备忘录",
        "com.microsoft.Word": "Word",
        "com.microsoft.Excel": "Excel",
        "com.apple.Terminal": "终端",
        "com.googlecode.iterm2": "iTerm",
        "com.kapeli.dashdoc": "Dash",
        "com.jetbrains.intellij": "IntelliJ IDEA",
        "com.microsoft.VSCode": "VS Code",
        "com.sublimetext.4": "Sublime Text",
        "com.apple.finder": "Finder",
        "com.tencent.qq": "QQ",
        "com.bytedance.feishu": "飞书",
        "com.alibaba.DingTalkMac": "钉钉",
        "us.zoom.xos": "Zoom",
        "com.slack.Slack": "Slack",
        "com.notion.Notion": "Notion",
    })
    
    # 忽略的应用 (不记录这些应用的输入)
    ignored_apps: List[str] = field(default_factory=lambda: [
        "com.apple.loginwindow",
        "com.apple.SecurityAgent",
    ])
    
    # 会话超时时间（秒）- 超过这个时间没有输入，视为新会话
    session_timeout: int = 300  # 5分钟
    
    # 最小记录长度 (少于这个字符数的输入不单独记录)
    min_record_length: int = 1
    
    def __post_init__(self):
        """初始化后创建必要的目录"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
    
    def get_app_display_name(self, bundle_id: str, default_name: str) -> str:
        """获取应用显示名称"""
        return self.app_aliases.get(bundle_id, default_name)
    
    def is_app_ignored(self, bundle_id: str) -> bool:
        """检查应用是否被忽略"""
        return bundle_id in self.ignored_apps
    
    def save(self, path: Optional[Path] = None):
        """保存配置到文件"""
        config_path = path or (self.data_dir / "config.json")
        config_data = {
            "ai_enabled": self.ai_enabled,
            "openai_model": self.openai_model,
            "app_aliases": self.app_aliases,
            "ignored_apps": self.ignored_apps,
            "session_timeout": self.session_timeout,
            "min_record_length": self.min_record_length,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """从文件加载配置"""
        config = cls()
        config_path = path or (config.data_dir / "config.json")
        
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config.ai_enabled = data.get("ai_enabled", config.ai_enabled)
                config.openai_model = data.get("openai_model", config.openai_model)
                config.app_aliases.update(data.get("app_aliases", {}))
                config.ignored_apps = data.get("ignored_apps", config.ignored_apps)
                config.session_timeout = data.get("session_timeout", config.session_timeout)
                config.min_record_length = data.get("min_record_length", config.min_record_length)
        
        return config


# 全局配置实例
config = AppConfig.load()

