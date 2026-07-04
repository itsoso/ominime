"""
配置管理模块
"""

import os
from pathlib import Path
from dataclasses import dataclass, field
from typing import Dict, List, Optional
import json

# 尝试加载 dotenv（如果可用）
try:
    from dotenv import load_dotenv
    _dotenv_available = True
except ImportError:
    _dotenv_available = False

# 加载 .env 文件（如果存在）
if _dotenv_available:
    # 从项目根目录加载 .env 文件 (config.py 位于 src/ominime/ 下，3 层 parent 到仓库根)
    project_root = Path(__file__).parent.parent.parent
    env_path = project_root / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        # 也尝试从当前工作目录加载
        load_dotenv()


@dataclass
class AppConfig:
    """应用配置"""
    
    # 数据目录
    data_dir: Path = field(default_factory=lambda: Path.home() / ".ominime")
    
    # 数据库文件
    db_path: Path = field(default_factory=lambda: Path.home() / ".ominime" / "ominime.db")
    
    # 日志目录
    log_dir: Path = field(default_factory=lambda: Path.home() / ".ominime" / "logs")
    
    # 是否启用 AI 总结（如果提供了 API Key 则自动启用）
    ai_enabled: bool = field(default=False)
    
    # OpenAI API Key (从环境变量或 .env 文件读取)
    openai_api_key: Optional[str] = field(default_factory=lambda: os.getenv("OPENAI_API_KEY"))
    
    # OpenAI 模型
    openai_model: str = "gpt-4o-mini"
    
    # 应用别名映射 (bundle_id -> 显示名称)
    app_aliases: Dict[str, str] = field(default_factory=lambda: {
        # 微信相关
        "com.tencent.xinWeChat": "微信",
        "com.tencent.WeChat": "微信",
        "com.tencent.webplusdevtools": "微信开发者工具",
        # 通讯工具
        "com.apple.MobileSMS": "信息",
        "com.tencent.qq": "QQ",
        "com.bytedance.feishu": "飞书",
        "com.alibaba.DingTalkMac": "钉钉",
        "us.zoom.xos": "Zoom",
        "com.slack.Slack": "Slack",
        # 开发工具
        "com.todesktop.230313mzl4w4u92": "Cursor",
        "com.microsoft.VSCode": "VS Code",
        "com.jetbrains.intellij": "IntelliJ IDEA",
        "com.sublimetext.4": "Sublime Text",
        "com.apple.Terminal": "终端",
        "com.googlecode.iterm2": "iTerm",
        "com.kapeli.dashdoc": "Dash",
        # 笔记应用
        "md.obsidian": "Obsidian",
        "com.apple.Notes": "备忘录",
        "com.notion.Notion": "Notion",
        # Kim (可能有多种 bundle_id)
        "com.electron.kim": "Kim",
        "Kem": "Kim",
        "Kem.Renderer": "Kim",
        "Kim": "Kim",
        # 浏览器
        "com.apple.Safari": "Safari",
        "com.google.Chrome": "Chrome",
        "org.mozilla.firefox": "Firefox",
        "com.brave.Browser": "Brave",
        "com.microsoft.edgemac": "Edge",
        # 办公软件
        "com.apple.mail": "邮件",
        "com.microsoft.Word": "Word",
        "com.microsoft.Excel": "Excel",
        "com.microsoft.Powerpoint": "PowerPoint",
        "com.apple.finder": "Finder",
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

    # 输入保存模式:
    # - enter-text: 保存 Enter 提交的完整文本
    # - count-only: 只保存字符数，不保存原文
    input_capture_mode: str = "enter-text"

    # 业务日时区：所有“今日/昨日/日报”统计按这个时区切天。
    day_timezone: str = field(default_factory=lambda: os.getenv("OMINIME_DAY_TIMEZONE", "Asia/Shanghai"))

    # 数据库存储时区：历史记录是无时区时间戳，按该时区解释。
    storage_timezone: str = field(
        default_factory=lambda: os.getenv("OMINIME_STORAGE_TIMEZONE") or os.getenv("TZ") or "America/New_York"
    )

    # 是否在无法读取输入框文本时按物理按键数降级计数。
    # 默认关闭：IME/候选词/不可访问输入框会造成严重虚高。
    count_unreadable_submissions: bool = False

    # AXValue 不可读时，是否使用 CGEvent 提供的 Unicode 文本作为真实文本兜底。
    # 运行时只保存包含 CJK 的提交文本，避免把中文 IME 拼音预编辑串当成真实输入。
    capture_key_event_text_fallback: bool = True

    # Enter 提交上下文捕获（仅文字，不再截屏）
    capture_context_on_enter: bool = True
    multimodal_context_analysis: bool = False
    multimodal_backend: str = "qwen-vl-local"
    qwen_vl_model: str = "Qwen/Qwen2.5-VL-7B-Instruct"
    qwen_vl_device: str = "auto"
    qwen_vl_max_new_tokens: int = 768
    qwen_vl_analysis_timeout_seconds: int = 20
    
    def __post_init__(self):
        """初始化后创建必要的目录"""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # 如果提供了 API Key，自动启用 AI 功能
        if self.openai_api_key and not self.ai_enabled:
            self.ai_enabled = True
    
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
            "input_capture_mode": self.input_capture_mode,
            "day_timezone": self.day_timezone,
            "storage_timezone": self.storage_timezone,
            "count_unreadable_submissions": self.count_unreadable_submissions,
            "capture_key_event_text_fallback": self.capture_key_event_text_fallback,
            "capture_context_on_enter": self.capture_context_on_enter,
            "multimodal_context_analysis": self.multimodal_context_analysis,
            "multimodal_backend": self.multimodal_backend,
            "qwen_vl_model": self.qwen_vl_model,
            "qwen_vl_device": self.qwen_vl_device,
            "qwen_vl_max_new_tokens": self.qwen_vl_max_new_tokens,
            "qwen_vl_analysis_timeout_seconds": self.qwen_vl_analysis_timeout_seconds,
        }
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config_data, f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load(cls, path: Optional[Path] = None) -> "AppConfig":
        """从文件加载配置"""
        config = cls()
        config_path = path or (config.data_dir / "config.json")
        
        # 从 .env 文件读取配置（如果可用）
        if _dotenv_available:
            # 重新加载环境变量（确保最新）
            project_root = Path(__file__).parent.parent.parent
            env_path = project_root / ".env"
            if env_path.exists():
                load_dotenv(env_path, override=True)
            else:
                load_dotenv(override=True)
            
            # 从环境变量更新配置
            env_api_key = os.getenv("OPENAI_API_KEY")
            if env_api_key:
                config.openai_api_key = env_api_key
            
            env_model = os.getenv("OPENAI_MODEL")
            if env_model:
                config.openai_model = env_model
            
            env_ai_enabled = os.getenv("AI_ENABLED")
            if env_ai_enabled:
                config.ai_enabled = env_ai_enabled.lower() in ("true", "1", "yes", "on")
        
        # 从 config.json 加载配置（会覆盖环境变量中的部分设置）
        if config_path.exists():
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                config.ai_enabled = data.get("ai_enabled", config.ai_enabled)
                config.openai_model = data.get("openai_model", config.openai_model)
                config.app_aliases.update(data.get("app_aliases", {}))
                config.ignored_apps = data.get("ignored_apps", config.ignored_apps)
                config.session_timeout = data.get("session_timeout", config.session_timeout)
                config.min_record_length = data.get("min_record_length", config.min_record_length)
                config.input_capture_mode = data.get("input_capture_mode", config.input_capture_mode)
                config.day_timezone = data.get("day_timezone", config.day_timezone)
                config.storage_timezone = data.get("storage_timezone", config.storage_timezone)
                config.count_unreadable_submissions = data.get(
                    "count_unreadable_submissions",
                    config.count_unreadable_submissions,
                )
                config.capture_key_event_text_fallback = data.get(
                    "capture_key_event_text_fallback",
                    config.capture_key_event_text_fallback,
                )
                config.capture_context_on_enter = data.get("capture_context_on_enter", config.capture_context_on_enter)
                config.multimodal_context_analysis = data.get("multimodal_context_analysis", config.multimodal_context_analysis)
                config.multimodal_backend = data.get("multimodal_backend", config.multimodal_backend)
                config.qwen_vl_model = data.get("qwen_vl_model", config.qwen_vl_model)
                config.qwen_vl_device = data.get("qwen_vl_device", config.qwen_vl_device)
                config.qwen_vl_max_new_tokens = data.get("qwen_vl_max_new_tokens", config.qwen_vl_max_new_tokens)
                config.qwen_vl_analysis_timeout_seconds = data.get("qwen_vl_analysis_timeout_seconds", config.qwen_vl_analysis_timeout_seconds)
        
        # 如果提供了 API Key，自动启用 AI 功能
        if config.openai_api_key and not config.ai_enabled:
            config.ai_enabled = True
        
        return config


# 全局配置实例
config = AppConfig.load()
