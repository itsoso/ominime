"""
LLM 后端抽象层

支持多种大模型后端：
- OpenAI API
- 本地 Qwen 模型（通过 transformers）
- 本地 Ollama 服务
- 自定义 API（兼容 OpenAI 格式）
"""

import os
from abc import ABC, abstractmethod
from typing import Optional, List, Dict, Any
from dataclasses import dataclass


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


class OpenAIBackend(LLMBackend):
    """OpenAI API 后端"""
    
    def __init__(self, api_key: str, model: str = "gpt-4o-mini", base_url: Optional[str] = None):
        self.api_key = api_key
        self.model = model
        self.base_url = base_url
        self._client = None
    
    def _get_client(self):
        if self._client is None:
            try:
                from openai import OpenAI
                self._client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url
                )
            except ImportError:
                raise ImportError("请安装 openai: pip install openai")
        return self._client
    
    def chat(
        self,
        messages: List[LLMMessage],
        temperature: float = 0.7,
        max_tokens: int = 1000,
    ) -> LLMResponse:
        client = self._get_client()
        
        response = client.chat.completions.create(
            model=self.model,
            messages=[{"role": m.role, "content": m.content} for m in messages],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        
        return LLMResponse(
            content=response.choices[0].message.content,
            model=response.model,
            usage={
                "prompt_tokens": response.usage.prompt_tokens,
                "completion_tokens": response.usage.completion_tokens,
                "total_tokens": response.usage.total_tokens,
            }
        )
    
    def is_available(self) -> bool:
        try:
            self._get_client()
            return True
        except Exception:
            return False


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
    
    def __init__(self, model: str = "qwen2.5:7b", base_url: str = "http://localhost:11434"):
        self.model = model
        self.base_url = base_url
    
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
            }
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
        backend_type = os.getenv("LLM_BACKEND", "openai").lower()
        
        if backend_type == "openai":
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                return None
            
            return OpenAIBackend(
                api_key=api_key,
                model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                base_url=os.getenv("OPENAI_BASE_URL")  # 支持自定义 API 地址
            )
        
        elif backend_type == "qwen-local":
            model_name = os.getenv("QWEN_MODEL", "Qwen/Qwen2.5-7B-Instruct")
            backend = QwenLocalBackend(model_name=model_name)
            if backend.is_available():
                return backend
            return None
        
        elif backend_type == "ollama":
            model = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
            base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
            backend = OllamaBackend(model=model, base_url=base_url)
            if backend.is_available():
                return backend
            return None
        
        return None


# 便捷函数
def get_llm_backend() -> Optional[LLMBackend]:
    """获取配置的 LLM 后端"""
    return LLMBackendFactory.create_from_config()
