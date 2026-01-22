#!/usr/bin/env python3
"""
LLM 后端测试脚本

测试配置的 LLM 后端是否正常工作
"""

import sys
import os
from pathlib import Path

# 添加项目路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(project_root / ".env")

from ominime.llm_backend import get_llm_backend, LLMMessage


def test_backend():
    """测试 LLM 后端"""
    print("🧪 测试 LLM 后端配置")
    print("=" * 60)
    print()
    
    # 显示配置
    backend_type = os.getenv("LLM_BACKEND", "openai")
    print(f"📋 配置信息:")
    print(f"   LLM_BACKEND: {backend_type}")
    
    if backend_type == "openai":
        print(f"   OPENAI_MODEL: {os.getenv('OPENAI_MODEL', 'gpt-4o-mini')}")
        print(f"   OPENAI_BASE_URL: {os.getenv('OPENAI_BASE_URL', '默认')}")
        api_key = os.getenv("OPENAI_API_KEY", "")
        if api_key:
            print(f"   OPENAI_API_KEY: {api_key[:10]}...{api_key[-4:]}")
        else:
            print(f"   OPENAI_API_KEY: ❌ 未配置")
    elif backend_type == "qwen-local":
        print(f"   QWEN_MODEL: {os.getenv('QWEN_MODEL', 'Qwen/Qwen2.5-7B-Instruct')}")
    elif backend_type == "ollama":
        print(f"   OLLAMA_MODEL: {os.getenv('OLLAMA_MODEL', 'qwen2.5:7b')}")
        print(f"   OLLAMA_BASE_URL: {os.getenv('OLLAMA_BASE_URL', 'http://localhost:11434')}")
    
    print()
    print("-" * 60)
    print()
    
    # 获取后端
    print("🔌 初始化后端...")
    try:
        backend = get_llm_backend()
        if backend is None:
            print("❌ 后端初始化失败")
            print()
            print("请检查:")
            print("  1. .env 文件是否正确配置")
            print("  2. 必要的依赖是否已安装")
            print("  3. 服务是否正在运行 (Ollama)")
            return False
        
        print(f"✅ 后端初始化成功: {backend.__class__.__name__}")
        print()
    except Exception as e:
        print(f"❌ 后端初始化失败: {e}")
        return False
    
    # 检查可用性
    print("🔍 检查后端可用性...")
    try:
        if not backend.is_available():
            print("❌ 后端不可用")
            return False
        print("✅ 后端可用")
        print()
    except Exception as e:
        print(f"❌ 检查失败: {e}")
        return False
    
    # 测试对话
    print("💬 测试对话功能...")
    print()
    
    test_messages = [
        LLMMessage(role="system", content="你是一个友好的助手。"),
        LLMMessage(role="user", content="请用一句话介绍你自己。")
    ]
    
    try:
        print("   发送测试消息...")
        response = backend.chat(
            messages=test_messages,
            temperature=0.7,
            max_tokens=100
        )
        
        print()
        print("   📨 响应:")
        print(f"      模型: {response.model}")
        print(f"      内容: {response.content}")
        
        if response.usage:
            print(f"      Token 使用: {response.usage}")
        
        print()
        print("✅ 对话测试成功！")
        print()
        
    except Exception as e:
        print(f"❌ 对话测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    # 性能测试
    print("-" * 60)
    print()
    print("⚡ 性能测试...")
    print()
    
    import time
    
    test_cases = [
        ("简单问题", "1+1等于几？"),
        ("中等问题", "请列举3个提高工作效率的方法。"),
    ]
    
    for name, question in test_cases:
        print(f"   测试: {name}")
        start_time = time.time()
        
        try:
            response = backend.chat(
                messages=[
                    LLMMessage(role="user", content=question)
                ],
                temperature=0.7,
                max_tokens=200
            )
            
            elapsed = time.time() - start_time
            print(f"      耗时: {elapsed:.2f}秒")
            print(f"      响应长度: {len(response.content)} 字符")
            print()
            
        except Exception as e:
            print(f"      ❌ 失败: {e}")
            print()
    
    print("=" * 60)
    print()
    print("🎉 所有测试完成！")
    print()
    print("后端配置正常，可以使用 AI 功能了。")
    print()
    
    return True


if __name__ == "__main__":
    try:
        success = test_backend()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print()
        print("测试已取消")
        sys.exit(1)
    except Exception as e:
        print(f"❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
