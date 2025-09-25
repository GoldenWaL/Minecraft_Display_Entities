import os
import customtkinter as ctk
from tkinter import filedialog, messagebox
from PIL import Image
from customtkinter import CTkImage

# ---------- Minecraft 配色 ----------
MC_COLORS = {
    "white":       (255,255,255),
    "orange":      (216,127,51),
    "magenta":     (178,76,216),
    "light_blue":  (102,153,216),
    "yellow":      (229,229,51),
    "lime":        (127,204,25),
    "pink":        (242,127,165),
    "gray":        (76,76,76),
    "light_gray":  (153,153,153),
    "cyan":        (76,127,153),
    "purple":      (127,63,178),
    "blue":        (51,76,178),
    "brown":       (102,76,51),
    "green":       (102,127,51),
    "red":         (178,76,51),
    "black":       (25,25,25),
}
MC_BLOCK_TEMPLATE = "minecraft:{}_concrete"

# ---------- 工具函数 ----------
def rgb_dist(a, b):
    return (a[0]-b[0])**2 + (a[1]-b[1])**2 + (a[2]-b[2])**2

def nearest_color_name(rgb, enabled_colors):
    best = None
    bestname = None
    for name, col in MC_COLORS.items():
        if not enabled_colors[name]:
            continue
        d = rgb_dist(rgb, col)
        if best is None or d < best:
            best = d
            bestname = name
    return bestname

def build_color_grid(img, skip_transparent, enabled_colors):
    w, h = img.size
    pixels = img.load()
    grid = [[None]*w for _ in range(h)]
    for j in range(h):
        for i in range(w):
            r,g,b,a = pixels[i,j]
            if skip_transparent and a == 0:
                grid[j][i] = None
            else:
                if a < 255:
                    alpha = a / 255.0
                    bg = (255,255,255)
                    r = int(round(r * alpha + bg[0] * (1-alpha)))
                    g = int(round(g * alpha + bg[1] * (1-alpha)))
                    b = int(round(b * alpha + bg[2] * (1-alpha)))
                grid[j][i] = nearest_color_name((r,g,b), enabled_colors)
    return grid

def ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def image_to_commands_2d(img_path, out_path, base_x, base_y, base_z,
                         pixel_size, invert_y, skip_transparent,
                         glow, enabled_colors, orientation="横向"):

    img = Image.open(img_path).convert("RGBA")
    if orientation == "竖向" or "竖向（z延申）":
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    w, h = img.size
    color_grid = build_color_grid(img, skip_transparent, enabled_colors)
    processed = [[False]*w for _ in range(h)]
    commands = []

    brightness_str = "brightness:{block:15,sky:0}" if glow else "brightness:{block:0,sky:0}"

    for j in range(h):
        i = 0
        while i < w:
            if processed[j][i] or color_grid[j][i] is None:
                i += 1
                continue
            color_name = color_grid[j][i]
            block = MC_BLOCK_TEMPLATE.format(color_name)
            # 横向扩展
            max_w_run = 1
            while i + max_w_run < w and (not processed[j][i+max_w_run]) and color_grid[j][i+max_w_run] == color_name:
                max_w_run += 1
            # 向下扩展
            height = 1
            cur_width = max_w_run
            while True:
                next_row = j + height
                if next_row >= h:
                    break
                run2 = 0
                while run2 < cur_width and (i + run2) < w and (not processed[next_row][i+run2]) and color_grid[next_row][i+run2] == color_name:
                    run2 += 1
                if run2 == 0:
                    break
                cur_width = run2
                height += 1
            rect_w = cur_width
            rect_h = height
            for jj in range(j, j+rect_h):
                for ii in range(i, i+rect_w):
                    processed[jj][ii] = True
            # 坐标计算
            if orientation == "横向":
                world_x = base_x + i * pixel_size
                world_y = base_y
                world_z = (base_z + j * pixel_size) #if not invert_y else (base_z - j * pixel_size)
                scale_x = rect_w * pixel_size
                scale_y = pixel_size
                scale_z = rect_h * pixel_size
            elif orientation == "竖向":
                world_x = base_x + i * pixel_size
                world_y = (base_y + j * pixel_size) #if not invert_y else (base_y - j * pixel_size)
                world_z = base_z
                scale_x = rect_w * pixel_size
                scale_y = rect_h * pixel_size
                scale_z = pixel_size
            elif orientation == "竖向（z延申）":
                world_x = base_x
                world_y = (base_y + j * pixel_size)  # if not invert_y else (base_y - j * pixel_size)
                world_z = base_z + i * pixel_size
                scale_x = pixel_size
                scale_y = rect_h * pixel_size
                scale_z = rect_w * pixel_size
            else:  # 竖向
                world_x = base_x + i * pixel_size
                world_y = (base_y + j * pixel_size)  # if not invert_y else (base_y - j * pixel_size)
                world_z = base_z
                scale_x = rect_w * pixel_size
                scale_y = rect_h * pixel_size
                scale_z = pixel_size
            pos_part = f'summon minecraft:block_display {world_x:.6f} {world_y:.6f} {world_z:.6f} '
            nbt_part = ('{block_state:{Name:"' + block + '"},' +
                        brightness_str + ',' +
                        'transformation:{left_rotation:{angle:0f,axis:[1f,0f,0f]},'
                        'right_rotation:{angle:0f,axis:[1f,0f,0f]},'
                        f'scale:[{scale_x:.6f}f,{scale_y:.6f}f,{scale_z:.6f}f],translation:[0f,0f,0f]}}}}')
            cmd = pos_part + nbt_part
            commands.append(cmd)
            i += rect_w
    ensure_dir(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Generated by Minecraft Display Entities Generator\n")
        for c in commands:
            f.write(c + "\n")
    return len(commands), w, h

# ---------- GUI ----------
class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Minecraft Display Entities Generator")
        self.geometry("960x680")
        ctk.set_appearance_mode("Light")
        ctk.set_default_color_theme("blue")

        # ---------- 变量 ----------
        self.image_path = ctk.StringVar()
        self.out_path = ctk.StringVar()
        self.base_x = ctk.DoubleVar(value=0.0)
        self.base_y = ctk.DoubleVar(value=64.0)
        self.base_z = ctk.DoubleVar(value=0.0)
        self.pixel_size = ctk.DoubleVar(value=0.1)
        self.invert_y = ctk.BooleanVar(value=False)
        self.glow = ctk.BooleanVar(value=False)
        self.orientation = ctk.StringVar(value="横向")
        self.enabled_colors = {name: ctk.BooleanVar(value=True) for name in MC_COLORS}

        # ---------- 左右分栏 ----------
        left_frame = ctk.CTkFrame(self, width=320)
        left_frame.pack(side="left", fill="y", padx=10, pady=10)
        right_frame = ctk.CTkFrame(self)
        right_frame.pack(side="right", fill="both", expand=True, padx=10, pady=10)

        # ---------- 文件选择 ----------
        ctk.CTkLabel(left_frame, text="文件选择", font=("Microsoft YaHei", 14, "bold")).pack(pady=5)
        ctk.CTkLabel(left_frame, text="输入图片:", font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5)
        ctk.CTkEntry(left_frame, textvariable=self.image_path, width=280, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)
        ctk.CTkButton(left_frame, text="选择", command=self.choose_image, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)

        ctk.CTkLabel(left_frame, text="输出文件:", font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5)
        ctk.CTkEntry(left_frame, textvariable=self.out_path, width=280, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)
        ctk.CTkButton(left_frame, text="选择", command=self.choose_output, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)

        # ---------- 参数设置 ----------
        ctk.CTkLabel(left_frame, text="参数设置", font=("Microsoft YaHei", 14, "bold")).pack(pady=10)
        for label_text, var in [("X 坐标:", self.base_x), ("Y 坐标:", self.base_y), ("Z 坐标:", self.base_z),
                                ("像素大小:", self.pixel_size)]:
            ctk.CTkLabel(left_frame, text=label_text, font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5)
            ctk.CTkEntry(left_frame, textvariable=var, width=280, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)
        #ctk.CTkCheckBox(left_frame, text="翻转Y", variable=self.invert_y, font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5, pady=2)
        ctk.CTkCheckBox(left_frame, text="发光", variable=self.glow, font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5, pady=2)
        ctk.CTkLabel(left_frame, text="显示方向:", font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5, pady=(10,0))
        ctk.CTkOptionMenu(left_frame, variable=self.orientation, values=["横向", "竖向", "竖向（z延申）"], font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5, pady=2)
        ctk.CTkButton(left_frame, text="生成指令", command=self.run, font=("Microsoft YaHei", 12, "bold")).pack(pady=10)

        # ---------- 颜色选择 ----------
        ctk.CTkLabel(right_frame, text="启用颜色", font=("Microsoft YaHei", 14, "bold")).pack(pady=5)
        scroll_frame = ctk.CTkScrollableFrame(right_frame, height=180)
        scroll_frame.pack(fill="x", pady=5)
        col = 0
        row = 0
        for name in MC_COLORS:
            ctk.CTkCheckBox(scroll_frame, text=name, variable=self.enabled_colors[name],
                            font=("Microsoft YaHei", 11)).grid(row=row, column=col, padx=5, pady=5, sticky="w")
            col += 1
            if col % 4 == 0:
                row += 1
                col = 0

        # ---------- 实时预览 ----------
        ctk.CTkLabel(right_frame, text="图片预览", font=("Microsoft YaHei", 14, "bold")).pack(pady=5)
        self.preview_label = ctk.CTkLabel(right_frame)
        self.preview_label.pack(pady=5)

    def choose_image(self):
        path = filedialog.askopenfilename(filetypes=[("图片文件","*.png;*.jpg;*.jpeg;*.bmp")])
        if path:
            self.image_path.set(path)
            self.update_preview(path)

    def choose_output(self):
        path = filedialog.asksaveasfilename(defaultextension=".mcfunction",
                                            filetypes=[("MCFunction files","*.mcfunction"),("Text files","*.txt")])
        if path:
            self.out_path.set(path)

    def update_preview(self, path):
        try:
            img = Image.open(path)
            max_w, max_h = 400, 300
            w, h = img.size
            scale = min(max_w / w, max_h / h, 1.0)
            new_w = int(w * scale)
            new_h = int(h * scale)
            img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)
            self.tkimg = CTkImage(img, size=(new_w, new_h))
            self.preview_label.configure(image=self.tkimg, text="")
        except Exception as e:
            self.preview_label.configure(text="无法加载图片")
            print("加载图片错误:", e)

    def run(self):
        img_path = self.image_path.get()
        out_path = self.out_path.get()
        if not img_path or not out_path:
            messagebox.showerror("错误", "请先选择输入图片和输出文件")
            return
        enabled_colors_dict = {name: var.get() for name, var in self.enabled_colors.items()}
        try:
            n, w, h = image_to_commands_2d(
                img_path, out_path,
                base_x=self.base_x.get(),
                base_y=self.base_y.get(),
                base_z=self.base_z.get(),
                pixel_size=self.pixel_size.get(),
                invert_y=self.invert_y.get(),
                skip_transparent=True,
                glow=self.glow.get(),
                enabled_colors=enabled_colors_dict,
                orientation=self.orientation.get()
            )
            messagebox.showinfo("完成", f"生成 {n} 条指令，图片尺寸 {w}×{h}")
        except Exception as e:
            messagebox.showerror("错误", str(e))
            print(e)

if __name__ == "__main__":
    app = App()
    app.mainloop()
