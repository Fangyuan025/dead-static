<div align="center">

```
 ██████╗ ███████╗ █████╗ ██████╗     ███████╗████████╗ █████╗ ████████╗██╗ ██████╗
 ██╔══██╗██╔════╝██╔══██╗██╔══██╗    ██╔════╝╚══██╔══╝██╔══██╗╚══██╔══╝██║██╔════╝
 ██║  ██║█████╗  ███████║██║  ██║    ███████╗   ██║   ███████║   ██║   ██║██║     
 ██║  ██║██╔══╝  ██╔══██║██║  ██║    ╚════██║   ██║   ██╔══██║   ██║   ██║██║     
 ██████╔╝███████╗██║  ██║██████╔╝    ███████║   ██║   ██║  ██║   ██║   ██║╚██████╗
 ╚═════╝ ╚══════╝╚═╝  ╚═╝╚═════╝     ╚══════╝   ╚═╝   ╚═╝  ╚═╝   ╚═╝   ╚═╝ ╚═════╝
```

**由本地大语言模型驱动的单人丧尸末日文字冒险游戏。**

**无需云端。无需 API Key。无需安装。无处可逃。**

</div>

你在一间被洗劫的公寓中醒来。窗外的城市已经死了。你有 15 天时间到达最后一架撤离直升机——否则就加入尸群。

每一局都不同。本地语言模型会根据你的选择实时叙述你的故事。游戏逻辑确保一切有据可循：战斗基于骰子和技能，资源每回合消耗，感染是一个无法忽视的倒计时。

一切都在你的电脑上运行。AI 引擎（[llama.cpp](https://github.com/ggml-org/llama.cpp)）和模型（Q4 量化 GGUF，约 1 GB）已随游戏打包或在首次启动时自动下载。无需 Python、无需驱动、无需配置。

---

## 快速开始

### 玩家（打包发行版）

双击 **`Play DeadStatic.bat`**，完事。

### 开发者（从源码运行）

```bash
pip install rich requests huggingface-hub
python game.py
```

首次启动时，游戏会自动下载：
1. **llama-server**（约 200 MB，自动检测 CUDA 或 CPU 版本）
2. **AI 模型**（约 1.05 GB，Q4 量化 GGUF）

之后无需联网。

---

## 工作原理

### 架构

```
玩家输入
     |
     v
+--------------------+
|    游戏主循环        |
|  +--------------+   |     +-----------+     +------------------+
|  | 事件系统     |---+--->| 提示词     |---->| llama-server.exe |
|  +--------------+   |    | 构建器     |     | (子进程)          |
|  | 规则引擎     |   |    +-----------+     | HTTP API         |
|  +--------------+   |          ^            +------------------+
|  | 状态管理     |<--+---------+--- 解析后的输出
|  +--------------+   |
+--------------------+
     |
     v
  Rich TUI
```

**LLM 负责叙事。代码负责逻辑。** 所有状态变化——伤害、拾取、移动、感染——都由规则引擎确定性地计算。LLM 接收结构化的游戏状态，输出叙事文本和玩家选项。

游戏以后台子进程启动 `llama-server.exe`，通过 OpenAI 兼容的 HTTP API 通信。游戏退出时服务器自动关闭。自动检测 NVIDIA GPU 以启用 CUDA 加速；纯 CPU 模式同样可用。

**模型：** [Josiefied-Qwen3-1.7B-abliterated-v1](https://huggingface.co/Goekdeniz-Guelmez/Josiefied-Qwen3-1.7B-abliterated-v1-gguf)（Q4_0 量化，1.05 GB）

### 15 天结构

| 天数 | 事件 | 压力等级 |
|------|------|----------|
| 1-2 | 新手区。熟悉机制，搜刮附近。 | 低 |
| 3 | **无线电信号** — 撤离点揭晓。 | 倒计时开始 |
| 5 | **第一波尸潮** — 起始区域不再安全。 | 必须转移 |
| 8 | **军事广播** — 凝固汽油弹空袭在即。过河。 | 强制迁移 |
| 13 | **最后的广播** — 最后一架直升机，第 15 天黎明。 | 终局 |
| 15 | 黎明时到达撤离区即可获胜。 | 生死一刻 |

### 游戏系统

**生存** — 饥饿、口渴和体力每回合消耗。降至零后开始掉血。

**感染** — 丧尸咬伤会注入感染，每回合上升。达到 100% 就会变异。

**战斗** — 基于技能和骰子的判定。火器伤害高但会产生噪音，吸引更多丧尸。

**士气** — 反映你的心理状态。道德抉择会影响士气走向。

**探索** — 14 个互联的地点，各有威胁等级、拾取列表和通道连接。

### 内容

- **14 个地点** — 公寓、街道、医院、下水道、军事检查站、最终撤离区
- **45 种物品**，8 大类 — 食物、水、武器、医疗用品、护甲、弹药、工具，以及一种实验性抗病毒药物
- **15 种事件** — 6 种探索事件、5 种夜间事件、4 种剧情事件
- **5 项技能** — 战斗、潜行、医疗、生存、说服（使用后提升）
- **3 种结局** — 死亡、感染（变异）、逃离

---

## 操作

| 输入 | 功能 |
|------|------|
| `A` / `B` / `C` | 选择一个叙事选项 |
| `inventory` | 查看物品及描述 |
| `use <物品>` | 使用食物、药品等 |
| `equip <物品>` | 设置当前武器 |
| `map` | 查看已发现的地点和连通关系 |
| `status` | 技能、击杀数、存活天数 |
| `save` | 保存到 `dead_static_save.json` |
| `help` | 完整命令列表 |
| `quit` | 保存并退出 |

---

## 构建可分发包

### 步骤 1 — 编译为 exe

```bash
pip install pyinstaller
python build.py
```

### 步骤 2 — 打包运行时 + 模型

```bash
python package.py
```

需要先下载运行时和模型（先运行一次 `python game.py`）。

生成完全独立的发行目录：

```
release/DeadStatic/
  DeadStatic.exe
  _internal/
  runtime/
    llama-server.exe    + CUDA DLLs
  models/
    *.q4_0.gguf         (~1.05 GB)
  Play DeadStatic.bat
  README.txt
```

压缩为 `.zip` 即可分发。玩家只需解压后双击运行。

### 步骤 3（可选）— Windows 安装程序

安装 [Inno Setup](https://jrsoftware.org/isinfo.php)，打开 `installer.iss` 并构建。

---

## 配置

所有设置位于 `game.py` 顶部的 `Config` 类中：

```python
class Config:
    HF_REPO_ID = "Goekdeniz-Guelmez/Josiefied-Qwen3-1.7B-abliterated-v1-gguf"
    GGUF_FILENAME = "josiefied-qwen3-1.7b-abliterated-v1.q4_0.gguf"
    N_CTX = 4096              # 上下文窗口大小
    N_GPU_LAYERS = 99         # 卸载到 GPU 的层数
    SERVER_PORT = 8384        # 本地服务器端口
    LLM_TEMPERATURE = 0.8
    LLM_MAX_TOKENS = 400
    LANG = "zh"               # 语言: "en" 或 "zh"
```

### 使用不同的量化版本

| 文件 | 大小 | 说明 |
|------|------|------|
| `...q4_0.gguf` | 1.05 GB | 默认。速度快，体积小。 |
| `...q5_0.gguf` | 1.23 GB | 更好的质量。 |
| `...q6_k.gguf` | 1.42 GB | 质量与速度平衡。 |
| `...q8_0.gguf` | 1.83 GB | 接近无损。 |

修改 `Config` 中的 `GGUF_FILENAME` 即可切换。

---

## 扩展游戏

### 添加地点

```python
"Gas Station": {
    "type": "building",
    "base_threat": 5,
    "description": "Pumps are dry. The convenience store window is smashed.",
    "desc_zh": "油泵已经干了。便利店的窗户被砸碎了。",
    "connections": ["Main Street"],
    "loot_table": ["energy bar", "matchbox", "glass bottle"],
    "loot_chance": 0.4,
},
```

### 添加物品

```python
"molotov cocktail": {
    "type": "weapon",
    "damage": 35,
    "noise": 6,
    "desc": "Glass bottle, gasoline, rag. One throw.",
},
```

### 修改叙事风格

编辑 `SYSTEM_PROMPT_ZH`（中文）或 `SYSTEM_PROMPT_EN`（英文）。游戏机制不受叙事风格影响。

---

## 项目结构

```
game.py           主游戏 — 所有系统集成在单个文件中
build.py          PyInstaller 构建脚本
package.py        打包 exe + llama-server + GGUF 模型
installer.iss     Inno Setup Windows 安装程序脚本
requirements.txt  Python 依赖 (rich, requests, huggingface-hub)
```

---

## 系统要求

| | 最低配置 | 推荐配置 |
|---|---------|----------|
| 系统 | Windows 10 x64 | 同左 |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 约 1.5 GB | 同左 |
| 显卡 | 不需要 | NVIDIA GPU（自动检测） |
| 网络 | 仅首次启动需要 | 打包版无需联网 |

---

## 许可证

MIT

---

*没有任何数据离开你的电脑。死者不需要你的数据分析。*
