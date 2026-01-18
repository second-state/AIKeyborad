# Vibecoder HUD

Vibecoder HUD 是一个专为“心流编程 (Vibecoding)”设计的桌面辅助系统。它通过一个定制的 6 键外设键盘（或模拟快捷键）触发，在桌面上唤起一个极简、无边框的抬头显示器 (HUD)。该系统利用 OpenRouter API 处理语音指令和代码逻辑，通过模拟剪贴板和键盘操作，实现与任意 IDE 的无缝集成。

## 功能特性

*   **沉浸式 HUD**: 极客风、半透明、无边框设计。
*   **语音输入**: 按住 Alt+Shift+F2 录音，松开停止，HUD 显示识别结果。
*   **智能编程**: 选中代码 -> Alt+Shift+F3 (Execute) -> AI 生成优化代码 -> Alt+Shift+F3 (Accept) 自动粘贴。
*   **YOLO 模式**: Alt+Shift+F6 触发，直接生成并执行 Shell 命令（如 git commit）。
*   **完全键盘操作**: 手不离键盘即可完成所有交互。

## 硬件/按键映射

| 物理按键 | 映射键值           | 功能 |
| :--- |:---------------| :--- |
| **Btn 1** | `Alt+Shift+F2` | **Voice**: 按住录音，松开结束录音。HUD 显示识别到的结果。 |
| **Btn 2** | `Alt+Shift+F3` | **Action**: <br>1. 录音结束后：开始执行语音命令。<br>2. AI 生成代码后：**同意**并替换代码。 |
| **Btn 3** | `Alt+Shift+F1` | **Cancel**: <br>1. 任何时候：打断当前步骤。<br>2. AI 生成代码后：**不同意**替换代码。 |
| **Btn 4** | `Alt+Shift+F5` | **New**: 重置上下文，开启新的聊天。 |
| **Btn 5** | `Tab`          | **Tab**: 透传 Tab 键，保留 IDE 原有功能。 |
| **Btn 6** | `Alt+Shift+F6` | **YOLO**: 执行 Shell 命令模式。 |

## 安装与配置

1.  **克隆项目**:
    ```bash
    git clone <repository_url>
    cd aiKeyboard
    ```

2.  **安装依赖**:
    ```bash
    pip install -r requirements.txt
    ```
    *注意: `PyQt6`, `sounddevice` 等库可能需要系统级依赖（如 PortAudio）。*

3.  **配置 API Key**:
    在项目根目录创建 `.env` 文件（已提供模板），填入你的 OpenRouter API Key：
    ```env
    OPENROUTER_API_KEY=sk-or-your-api-key-here
    ```

## 使用示例

### 场景 1: 优化代码
1.  在 IDE (如 VS Code) 中选中一段需要优化的代码。
2.  按住 **Btn 1 (Alt+Shift+F2)**，口述指令：“优化这段代码，增加错误处理。”，然后松开。
3.  HUD 显示识别到的文字。
4.  按下 **Btn 2 (Alt+Shift+F3)**。HUD 显示 "THINKING..."，随后显示 AI 生成的代码。
5.  检查代码无误后，再次按下 **Btn 2 (Alt+Shift+F3)**。新代码将自动替换选中的代码。

### 场景 2: 执行命令 (YOLO)
1.  按住 **Btn 1 (Alt+Shift+F2)** 录音：“`提交代码，信息是修复了登录 bug”。` 松开。
2.  按下 **Btn 6 (Alt+Shift+F6)** (YOLO)。
3.  HUD 显示生成的命令 `git commit -am "fix login bug"` 并自动执行。
4.  执行结果回显在 HUD 中。

## 注意事项

*   请确保 Alt+Shift+F1 到 Alt+Shift+F6 键未被其他软件占用。
*   YOLO 模式直接执行 Shell 命令，请谨慎使用。
