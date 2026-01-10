#!/usr/bin/env python3
"""
创建 OmniMe 应用图标

生成一个简单的键盘图标作为应用图标
"""

import subprocess
import os

# 创建一个简单的 SVG 图标
SVG_CONTENT = '''<?xml version="1.0" encoding="UTF-8"?>
<svg width="1024" height="1024" viewBox="0 0 1024 1024" xmlns="http://www.w3.org/2000/svg">
  <!-- 背景 -->
  <defs>
    <linearGradient id="bg" x1="0%" y1="0%" x2="100%" y2="100%">
      <stop offset="0%" style="stop-color:#667eea"/>
      <stop offset="100%" style="stop-color:#764ba2"/>
    </linearGradient>
  </defs>
  <rect width="1024" height="1024" rx="200" fill="url(#bg)"/>
  
  <!-- 键盘外框 -->
  <rect x="112" y="312" width="800" height="400" rx="40" fill="white" opacity="0.95"/>
  
  <!-- 键盘按键行1 -->
  <rect x="152" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="232" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="312" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="392" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="472" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="552" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="632" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="712" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="792" y="352" width="60" height="60" rx="8" fill="#e0e0e0"/>
  
  <!-- 键盘按键行2 -->
  <rect x="172" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="252" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="332" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="412" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="492" y="432" width="60" height="60" rx="8" fill="#667eea"/>
  <rect x="572" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="652" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="732" y="432" width="60" height="60" rx="8" fill="#e0e0e0"/>
  
  <!-- 键盘按键行3 -->
  <rect x="192" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="272" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="352" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="432" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="512" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="592" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="672" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  <rect x="752" y="512" width="60" height="60" rx="8" fill="#e0e0e0"/>
  
  <!-- 空格键 -->
  <rect x="252" y="592" width="520" height="60" rx="8" fill="#e0e0e0"/>
  
  <!-- 输入光标闪烁效果 -->
  <rect x="510" y="365" width="4" height="35" fill="#667eea">
    <animate attributeName="opacity" values="1;0;1" dur="1s" repeatCount="indefinite"/>
  </rect>
</svg>'''


def create_icon():
    """创建应用图标"""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    project_dir = os.path.dirname(script_dir)
    resources_dir = os.path.join(project_dir, 'resources')
    
    os.makedirs(resources_dir, exist_ok=True)
    
    # 保存 SVG
    svg_path = os.path.join(resources_dir, 'OmniMe.svg')
    with open(svg_path, 'w') as f:
        f.write(SVG_CONTENT)
    
    print(f"✅ SVG 图标已创建: {svg_path}")
    
    # 创建 iconset 目录
    iconset_dir = os.path.join(resources_dir, 'OmniMe.iconset')
    os.makedirs(iconset_dir, exist_ok=True)
    
    # 使用 qlmanage 或 sips 来转换（如果有 ImageMagick 或其他工具更好）
    # 这里我们创建一个简单的 PNG 占位符
    
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    
    print("正在生成不同尺寸的图标...")
    
    for size in sizes:
        png_path = os.path.join(iconset_dir, f'icon_{size}x{size}.png')
        png_path_2x = os.path.join(iconset_dir, f'icon_{size//2}x{size//2}@2x.png') if size > 16 else None
        
        # 尝试使用 rsvg-convert 或 cairosvg
        try:
            # 尝试使用 cairosvg（如果安装了的话）
            import cairosvg
            cairosvg.svg2png(
                bytestring=SVG_CONTENT.encode(),
                write_to=png_path,
                output_width=size,
                output_height=size
            )
            if png_path_2x and size <= 512:
                # 复制作为 @2x 版本
                import shutil
                shutil.copy(png_path, png_path_2x)
        except ImportError:
            # 如果没有 cairosvg，使用 sips（macOS 内置）转换
            # 先用 qlmanage 转换 SVG 到 PNG
            try:
                subprocess.run([
                    'qlmanage', '-t', '-s', str(size), '-o', iconset_dir, svg_path
                ], capture_output=True, check=True)
                
                # qlmanage 输出的文件名不同，需要重命名
                generated = os.path.join(iconset_dir, 'OmniMe.svg.png')
                if os.path.exists(generated):
                    os.rename(generated, png_path)
            except:
                print(f"⚠️  无法生成 {size}x{size} 图标")
    
    # 使用 iconutil 生成 .icns 文件
    icns_path = os.path.join(resources_dir, 'OmniMe.icns')
    
    try:
        subprocess.run([
            'iconutil', '-c', 'icns', iconset_dir, '-o', icns_path
        ], capture_output=True, check=True)
        print(f"✅ ICNS 图标已创建: {icns_path}")
    except subprocess.CalledProcessError:
        print("⚠️  无法创建 .icns 文件，请手动转换 SVG 到 ICNS")
        print(f"   SVG 文件位置: {svg_path}")
    
    return svg_path


if __name__ == "__main__":
    create_icon()
