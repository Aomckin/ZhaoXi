# MarkItDown 本地部署

已安装官方 PyPI 版 `markitdown[all]` 0.1.7，运行环境完全位于本目录的 `.venv` 中。

同时已接入朝汐 Tool Package，工具名为 `markitdown_convert`。

## 使用

### 在朝汐中启用

朝汐的外部 Tool Package 默认只发现、不启用。使用下面的脚本启动朝汐：

```powershell
.\start_with_zhaoxi.ps1
```

它会为当前进程设置 `ZHAOXI_TOOL_MARKITDOWN_ENABLED=true`，然后启动朝汐。重启后可通过 `/tools` 或 Debug · 钥匙柜查看 `markitdown_convert`。

也可以在启动朝汐前自行设置：

```powershell
$env:ZHAOXI_TOOL_MARKITDOWN_ENABLED = "true"
```

### 独立命令行

在当前目录运行：

```powershell
.\run.ps1 "输入文件.pdf" "输出文件.md"
```

不指定输出文件时，Markdown 会输出到终端：

```powershell
.\run.ps1 "输入文件.docx"
```

也可以直接运行官方 CLI：

```powershell
.\.venv\Scripts\markitdown.exe "输入文件.xlsx" -o "输出文件.md"
```

Python API：

```powershell
.\.venv\Scripts\python.exe
```

```python
from markitdown import MarkItDown

result = MarkItDown().convert_local("输入文件.pdf")
print(result.markdown)
```

## 说明

- Python 版本：3.13
- 已安装 PDF、Word、PowerPoint、Excel、图片、音频、YouTube 等完整可选依赖。
- 当前系统未检测到 `ffmpeg`；常规文档转换不受影响，部分音频转换可能需要另外安装 `ffmpeg`。
- MarkItDown 会使用当前进程权限读取输入资源。处理不可信输入时，优先使用 `convert_local()` 等范围更窄的 API。
