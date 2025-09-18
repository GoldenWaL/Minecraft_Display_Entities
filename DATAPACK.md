# Minecraft Data Pack 制作教程

本教程将教你如何使用 Minecraft 数据包（Data Pack）创建一个简单的功能包，将图片生成的 `block_display` 指令整合进游戏。适用于 Java 版 Minecraft 1.20+。

---

## 什么是数据包（Data Pack）

Minecraft 数据包是一种自定义游戏内容的方法，可以添加新的功能、指令、进度、loot 表等，而无需修改游戏核心。通过数据包，你可以方便地将生成的 block_display 指令整合进游戏。

---

## 数据包目录结构

一个简单的数据包结构如下：

```
my_datapack/
├─ pack.mcmeta
└─ data/
   └─ my_namespace/
       └─ functions/
           └─ generate_image.mcfunction
```

- `pack.mcmeta`：数据包元信息文件，必须存在。
- `data/<namespace>/functions/`：放置 Minecraft 函数文件 (`.mcfunction`)。

### 示例 `pack.mcmeta`
```json
{
  "pack": {
    "pack_format": 48,
    "description": "Minecraft Display Entities Data Pack"
  }
}
```

> `pack_format` 根据 Minecraft 版本而定，1.21.1 对应 48。[点我查看版本对应关系](https://minecraft.fandom.com/wiki/Pack_format)

---

## 将生成的指令文件加入数据包

1. 生成 block_display 指令文件，例如 `out.mcfunction`。
2. 将文件重命名为 `generate_image.mcfunction`（或其他名字，但必须以 `.mcfunction` 结尾）。
3. 放入 `data/my_namespace/functions/` 目录下。

---

## 在游戏中使用数据包

1. 将整个 `my_datapack/` 文件夹放入世界的 `datapacks` 文件夹中，例如：
```
.minecraft/saves/你的世界/datapacks/my_datapack/
```

2. 进入 Minecraft 游戏并加载世界。

3. 在游戏内运行以下命令以加载数据包：
```
/datapack list
```
确认数据包已启用。

4. 执行生成指令：
```
/function my_namespace:generate_image
```
此时，你在游戏中就会看到 block_display 生成的像素画。

---

## 小技巧

- 可将多张图片生成的 `.mcfunction` 文件分组到同一个 namespace 下，方便管理。
- 或者也可以去[Release页面](https://github.com/GoldenWaL/Minecraft_Display_Entities/releases)下载一个模板，在里面改（
