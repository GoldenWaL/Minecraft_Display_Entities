# Minecraft Display Entities Generator

将图片转换为 Minecraft **展示实体（block_display）** 指令集合的工具，支持 **16 色 concrete**，并提供 GUI 操作界面。可自定义缩放、坐标、发光、颜色选择，并进行二维优化，减少实体数量。

---

## 功能特点

- 支持 **横向/竖向模式**，竖向模式自动上下翻转输入图片以保证生成方向正确。
- **二维优化**：相邻同色区域合并为单个实体，大幅减少 Minecraft 中生成实体数量。
- **实时图片预览**：按原比例缩放，使用 `CTkImage` 支持 HighDPI 显示。
- 自定义 **像素大小（scale_factor）**，调整每个像素对应 Minecraft 中的间距。
- 可选择 **发光模式**（`brightness: block 15` 或 `0`）。
- 支持启用/禁用 **16 色 concrete**，避免伪色问题。
- GUI 使用 **CustomTkinter + Win11 风格 + 微软雅黑字体**，操作简单直观。
- 输出文件为 `.mcfunction` 或 `.txt`，可直接用于命令方块或 datapack。

---

## 安装与依赖

1. 安装 Python 3.10+
2. 安装依赖：

```bash
pip install pillow customtkinter
```

---

## 使用方法

1. 运行 GUI：

```bash
python app.py
```

2. 在 GUI 中设置参数：
   - **输入图片**：选择 PNG/JPG 等图片
   - **输出文件**：生成的 `.mcfunction` 或 `.txt` 文件
   - **坐标**：X / Y / Z
   - **像素大小**：控制每个像素在 Minecraft 世界中的大小
   - **发光**：是否启用发光
   - **翻转 Y**：纵向翻转
   - **显示方向**：横向 / 竖向
   - **启用颜色**：可勾选需要使用的颜色

3. 点击 **生成指令**，程序会在指定路径生成 Minecraft 命令文件。
4. 将输出文件内容复制到 **命令方块** 或 **datapack** 中，即可生成对应实体。

---

## 注意事项

- 竖向模式会在生成指令前上下翻转图片，但预览保持原样。
- 为了性能，程序会自动合并相邻同色区域生成实体。
- 建议在世界中空旷区域测试生成，以避免实体量过多导致卡顿。

---

## 示例效果

- 支持将任意图片转换为 Minecraft block_display 指令集合
- 可生成彩色像素画、图标等

---

## 项目文件

- `app.py`：GUI 主程序  
- `image_to_display_entities.py`：核心生成逻辑（可单独使用）  
- `README.md`：项目说明

---

## 开源协议

MIT License