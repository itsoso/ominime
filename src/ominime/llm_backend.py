"""
LLM 后端抽象层

支持多种大模型后端：
- 本地 Qwen 模型（通过 transformers）
- 本地 Ollama 服务
"""

import os
import ipaddress
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from urllib.parse import urlparse


@dataclass
class LLMMessage:
    """LLM 消息"""
    role: str  # system, user, assistant
    content: str


@dataclass
class LLMResponse:
    """LLM 响应"""
    content: str
    model: str
    usage: Optional[Dict[str, int]] = None


class LLMBackend(ABC):
    """LLM 后端抽象基类"""
    
    @abstractmethod
    def chat(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        """发送聊天请求"""
        pass
    
    @abstractmethod
    def is_available(self) -> bool:
        """检查后端是否可用"""
        pass


class QwenLocalBackend(LLMBackend):
    """本地 Qwen 模型后端（使用 transformers）"""
    
    def __init__(self, model_name: str = "Qwen/Qwen2.5-7B-Instruct"):
        self.model_name = model_name
        self._model = None
        self._tokenizer = None
    
    def _load_model(self):
        """懒加载模型"""
        if self._model is None:
            try:
                from transformers import AutoModelForCausalLM, AutoTokenizer
                import torch
                
                print(f"正在加载本地模型 {self.model_name}...")
                
                self._tokenizer = AutoTokenizer.from_pretrained(
                    self.model_name,
                    trust_remote_code=True
                )
                
                # 根据可用硬件选择设备
                device = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
                
                self._model = AutoModelForCausalLM.from_pretrained(
                    self.model_name,
                    torch_dtype=torch.float16 if device != "cpu" else torch.float32,
                    device_map="auto" if device == "cuda" else None,
                    trust_remote_code=True
                )
                
                if device == "mps":
                    self._model = self._model.to(device)
                
                print(f"模型加载完成，使用设备: {device}")
                
            except ImportError:
                raise ImportError(
                    "请安装必要的包:\n"
                    "pip install transformers torch accelerate"
                )
    
    def chat(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        self._load_model()
        
        # 构建对话文本
        text = self._tokenizer.apply_chat_template(
            [{"role": m.role, "content": m.content} for m in messages],
            tokenize=False,
            add_generation_prompt=True
        )
        
        # 生成响应
        model_inputs = self._tokenizer([text], return_tensors="pt").to(self._model.device)
        
        generated_ids = self._model.generate(
            **model_inputs,
            max_new_tokens=max_tokens,
            temperature=temperature,
            do_sample=True,
        )
        
        generated_ids = [
            output_ids[len(input_ids):] 
            for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
        ]
        
        response_text = self._tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
        
        return LLMResponse(
            content=response_text,
            model=self.model_name,
        )
    
    def is_available(self) -> bool:
        try:
            import transformers
            import torch
            return True
        except ImportError:
            return False


class OllamaBackend(LLMBackend):
    """Ollama 本地服务后端"""
    
    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://127.0.0.1:11434"):
        parsed = urlparse(base_url)
        hostname = parsed.hostname
        try:
            is_loopback_ip = bool(hostname and ipaddress.ip_address(hostname).is_loopback)
        except ValueError:
            is_loopback_ip = False
        if parsed.scheme != "http" or not (hostname == "localhost" or is_loopback_ip):
            raise ValueError("Ollama endpoint must use HTTP on a loopback address")
        self.model = model
        self.base_url = base_url.rstrip("/")
    
    def chat(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        import requests
        
        response = requests.post(
            f"{self.base_url}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": m.role, "content": m.content} for m in messages],
                "stream": False,
                "options": {
                    "temperature": temperature,
                    "num_predict": max_tokens,
                }
            },
            timeout=30,
        )
        response.raise_for_status()
        
        data = response.json()
        return LLMResponse(
            content=data["message"]["content"],
            model=self.model,
        )
    
    def is_available(self) -> bool:
        try:
            import requests
            response = requests.get(f"{self.base_url}/api/tags", timeout=2)
            return response.status_code == 200
        except Exception:
            return False


class LLMBackendFactory:
    """LLM 后端工厂"""
    
    @staticmethod
    def create_from_config() -> Optional[LLMBackend]:
        """从配置创建后端"""
        backend_type = os.getenv("LLM_BACKEND", "ollama").lower()

        if backend_type == "qwen-local":
            model_name = os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
            backend = QwenLocalBackend(model_name=model_name)
            if backend.is_available():
                return backend
            return None
        
        if backend_type == "ollama":
            model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
            base_url = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
            try:
                backend = OllamaBackend(model=model, base_url=base_url)
            except ValueError:
                return None
            if backend.is_available():
                return backend
            return None
        
        return None


# 便捷函数
def get_llm_backend() -> Optional[LLMBackend]:
    """获取配置的 LLM 后端"""
    return LLMBackendFactory.create_from_config()
