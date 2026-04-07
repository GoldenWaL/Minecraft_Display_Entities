import os
import time
import threading
import multiprocessing
from functools import lru_cache
from concurrent.futures import ProcessPoolExecutor, as_completed
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

_WORKER_RGB_GRID = None
_WORKER_ENABLED = None
_WORKER_LOSS = 0.0

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

def nearest_color_name_with_error(rgb, enabled_colors):
    best = None
    bestname = None
    for name, col in MC_COLORS.items():
        if not enabled_colors[name]:
            continue
        d = rgb_dist(rgb, col)
        if best is None or d < best:
            best = d
            bestname = name
    return bestname, best if best is not None else 0

def build_color_grid(img, skip_transparent, enabled_colors):
    w, h = img.size
    pixels = img.load()
    grid = [[None]*w for _ in range(h)]
    rgb_grid = [[None]*w for _ in range(h)]
    for j in range(h):
        for i in range(w):
            r,g,b,a = pixels[i,j]
            if skip_transparent and a == 0:
                grid[j][i] = None
                rgb_grid[j][i] = None
            else:
                if a < 255:
                    alpha = a / 255.0
                    bg = (255,255,255)
                    r = int(round(r * alpha + bg[0] * (1-alpha)))
                    g = int(round(g * alpha + bg[1] * (1-alpha)))
                    b = int(round(b * alpha + bg[2] * (1-alpha)))
                rgb = (r, g, b)
                rgb_grid[j][i] = rgb
                grid[j][i] = nearest_color_name(rgb, enabled_colors)
    return grid, rgb_grid

def _build_prefix(rgb_grid):
    h = len(rgb_grid)
    w = len(rgb_grid[0]) if h else 0
    occ = [[0] * (w + 1) for _ in range(h + 1)]
    sr = [[0] * (w + 1) for _ in range(h + 1)]
    sg = [[0] * (w + 1) for _ in range(h + 1)]
    sb = [[0] * (w + 1) for _ in range(h + 1)]
    sr2 = [[0] * (w + 1) for _ in range(h + 1)]
    sg2 = [[0] * (w + 1) for _ in range(h + 1)]
    sb2 = [[0] * (w + 1) for _ in range(h + 1)]
    for y in range(h):
        for x in range(w):
            pix = rgb_grid[y][x]
            o = 0 if pix is None else 1
            r = 0 if pix is None else pix[0]
            g = 0 if pix is None else pix[1]
            b = 0 if pix is None else pix[2]
            occ[y + 1][x + 1] = occ[y][x + 1] + occ[y + 1][x] - occ[y][x] + o
            sr[y + 1][x + 1] = sr[y][x + 1] + sr[y + 1][x] - sr[y][x] + r
            sg[y + 1][x + 1] = sg[y][x + 1] + sg[y + 1][x] - sg[y][x] + g
            sb[y + 1][x + 1] = sb[y][x + 1] + sb[y + 1][x] - sb[y][x] + b
            sr2[y + 1][x + 1] = sr2[y][x + 1] + sr2[y + 1][x] - sr2[y][x] + r * r
            sg2[y + 1][x + 1] = sg2[y][x + 1] + sg2[y + 1][x] - sg2[y][x] + g * g
            sb2[y + 1][x + 1] = sb2[y][x + 1] + sb2[y + 1][x] - sb2[y][x] + b * b
    return occ, sr, sg, sb, sr2, sg2, sb2

def _worker_init(rgb_grid, enabled, loss_threshold):
    global _WORKER_RGB_GRID, _WORKER_ENABLED, _WORKER_LOSS
    _WORKER_RGB_GRID = rgb_grid
    _WORKER_ENABLED = enabled
    _WORKER_LOSS = loss_threshold

def _solve_rect_exact(rgb_grid, enabled, loss_threshold, rect):
    x1, y1, x2, y2 = rect
    occ, sr, sg, sb, sr2, sg2, sb2 = _build_prefix(rgb_grid)

    def rect_sum(prefix, ax1, ay1, ax2, ay2):
        return prefix[ay2][ax2] - prefix[ay1][ax2] - prefix[ay2][ax1] + prefix[ay1][ax1]

    def one_rect_plan(ax1, ay1, ax2, ay2):
        area = (ax2 - ax1) * (ay2 - ay1)
        n = rect_sum(occ, ax1, ay1, ax2, ay2)
        if n == 0:
            return True, None
        if n != area:
            return False, None
        sum_r = rect_sum(sr, ax1, ay1, ax2, ay2)
        sum_g = rect_sum(sg, ax1, ay1, ax2, ay2)
        sum_b = rect_sum(sb, ax1, ay1, ax2, ay2)
        sum_r2 = rect_sum(sr2, ax1, ay1, ax2, ay2)
        sum_g2 = rect_sum(sg2, ax1, ay1, ax2, ay2)
        sum_b2 = rect_sum(sb2, ax1, ay1, ax2, ay2)
        sum_sq = sum_r2 + sum_g2 + sum_b2
        best_color = None
        best_avg = None
        for name in enabled:
            cr, cg, cb = MC_COLORS[name]
            c_sq = cr * cr + cg * cg + cb * cb
            dot = cr * sum_r + cg * sum_g + cb * sum_b
            err_sum = sum_sq - 2 * dot + n * c_sq
            avg_err = err_sum / n
            if best_avg is None or avg_err < best_avg:
                best_avg = avg_err
                best_color = name
        return (best_avg is not None and best_avg <= loss_threshold), best_color

    choice = {}

    @lru_cache(maxsize=None)
    def dp(ax1, ay1, ax2, ay2):
        area = (ax2 - ax1) * (ay2 - ay1)
        if area <= 0:
            return 0
        n = rect_sum(occ, ax1, ay1, ax2, ay2)
        if n == 0:
            choice[(ax1, ay1, ax2, ay2)] = ("empty",)
            return 0

        best = 10 ** 12
        can_one, one_color = one_rect_plan(ax1, ay1, ax2, ay2)
        if can_one and one_color is not None:
            best = 1
            choice[(ax1, ay1, ax2, ay2)] = ("one", one_color)
        for xm in range(ax1 + 1, ax2):
            v = dp(ax1, ay1, xm, ay2) + dp(xm, ay1, ax2, ay2)
            if v < best:
                best = v
                choice[(ax1, ay1, ax2, ay2)] = ("vsplit", xm)
        for ym in range(ay1 + 1, ay2):
            v = dp(ax1, ay1, ax2, ym) + dp(ax1, ym, ax2, ay2)
            if v < best:
                best = v
                choice[(ax1, ay1, ax2, ay2)] = ("hsplit", ym)
        return best

    best_count = dp(x1, y1, x2, y2)
    rects = []

    def rebuild(ax1, ay1, ax2, ay2):
        ch = choice.get((ax1, ay1, ax2, ay2))
        if not ch or ch[0] == "empty":
            return
        if ch[0] == "one":
            rects.append((ax1, ay1, ax2 - ax1, ay2 - ay1, ch[1]))
            return
        if ch[0] == "vsplit":
            xm = ch[1]
            rebuild(ax1, ay1, xm, ay2)
            rebuild(xm, ay1, ax2, ay2)
            return
        ym = ch[1]
        rebuild(ax1, ay1, ax2, ym)
        rebuild(ax1, ym, ax2, ay2)

    rebuild(x1, y1, x2, y2)
    return best_count, rects

def _evaluate_root_split(candidate):
    split_type, val, w, h = candidate
    if split_type == "v":
        c1, r1 = _solve_rect_exact(_WORKER_RGB_GRID, _WORKER_ENABLED, _WORKER_LOSS, (0, 0, val, h))
        c2, r2 = _solve_rect_exact(_WORKER_RGB_GRID, _WORKER_ENABLED, _WORKER_LOSS, (val, 0, w, h))
    else:
        c1, r1 = _solve_rect_exact(_WORKER_RGB_GRID, _WORKER_ENABLED, _WORKER_LOSS, (0, 0, w, val))
        c2, r2 = _solve_rect_exact(_WORKER_RGB_GRID, _WORKER_ENABLED, _WORKER_LOSS, (0, val, w, h))
    return c1 + c2, r1 + r2

def optimize_rectangles(color_grid, rgb_grid, enabled_colors, acceptable_loss, parallel_workers=0):
    h = len(color_grid)
    w = len(color_grid[0]) if h else 0
    if w == 0 or h == 0:
        return []
    start_time = time.time()
    # DP 子矩形状态总数：C(w+1,2) * C(h+1,2)
    total_states = (w * (w + 1) // 2) * (h * (h + 1) // 2)
    print(f"[optimizer] start: size={w}x{h}, acceptable_loss={acceptable_loss}")
    enabled = [name for name in MC_COLORS if enabled_colors[name]]
    if not enabled:
        print("[optimizer] no enabled colors, stop.")
        return []

    occ, sr, sg, sb, sr2, sg2, sb2 = _build_prefix(rgb_grid)

    def rect_sum(prefix, x1, y1, x2, y2):
        return prefix[y2][x2] - prefix[y1][x2] - prefix[y2][x1] + prefix[y1][x1]

    def one_rect_plan(x1, y1, x2, y2, loss_threshold):
        area = (x2 - x1) * (y2 - y1)
        n = rect_sum(occ, x1, y1, x2, y2)
        if n == 0:
            return True, None, 0.0  # 全透明，不需要实体
        if n != area:
            return False, None, None  # 含透明洞，不允许单实体覆盖

        sum_r = rect_sum(sr, x1, y1, x2, y2)
        sum_g = rect_sum(sg, x1, y1, x2, y2)
        sum_b = rect_sum(sb, x1, y1, x2, y2)
        sum_r2 = rect_sum(sr2, x1, y1, x2, y2)
        sum_g2 = rect_sum(sg2, x1, y1, x2, y2)
        sum_b2 = rect_sum(sb2, x1, y1, x2, y2)
        sum_sq = sum_r2 + sum_g2 + sum_b2

        best_color = None
        best_avg = None
        for name in enabled:
            cr, cg, cb = MC_COLORS[name]
            c_sq = cr * cr + cg * cg + cb * cb
            dot = cr * sum_r + cg * sum_g + cb * sum_b
            err_sum = sum_sq - 2 * dot + n * c_sq
            avg_err = err_sum / n
            if best_avg is None or avg_err < best_avg:
                best_avg = avg_err
                best_color = name
        if best_avg is not None and best_avg <= loss_threshold:
            return True, best_color, best_avg
        return False, None, best_avg

    loss_threshold = max(0.0, float(acceptable_loss))
    INF = 10 ** 12
    choice = {}
    progress = {"calls": 0, "last_print": 0}

    @lru_cache(maxsize=None)
    def dp(x1, y1, x2, y2):
        progress["calls"] += 1
        if progress["calls"] - progress["last_print"] >= 5000:
            elapsed = time.time() - start_time
            ratio = min(1.0, progress["calls"] / max(1, total_states))
            eta = (elapsed / ratio - elapsed) if ratio > 0 else 0.0
            print(
                f"[optimizer] running... states={progress['calls']}/{total_states} "
                f"({ratio*100:.1f}%), elapsed={elapsed:.2f}s, eta~{eta:.2f}s"
            )
            progress["last_print"] = progress["calls"]
        area = (x2 - x1) * (y2 - y1)
        if area <= 0:
            return 0
        n = rect_sum(occ, x1, y1, x2, y2)
        if n == 0:
            choice[(x1, y1, x2, y2)] = ("empty",)
            return 0

        best = INF
        can_one, one_color, _ = one_rect_plan(x1, y1, x2, y2, loss_threshold)
        if can_one and one_color is not None:
            best = 1
            choice[(x1, y1, x2, y2)] = ("one", one_color)

        # 竖切
        for xm in range(x1 + 1, x2):
            v = dp(x1, y1, xm, y2) + dp(xm, y1, x2, y2)
            if v < best:
                best = v
                choice[(x1, y1, x2, y2)] = ("vsplit", xm)

        # 横切
        for ym in range(y1 + 1, y2):
            v = dp(x1, y1, x2, ym) + dp(x1, ym, x2, y2)
            if v < best:
                best = v
                choice[(x1, y1, x2, y2)] = ("hsplit", ym)

        return best

    root_cost = dp(0, 0, w, h)
    rects = []

    def rebuild(x1, y1, x2, y2):
        key = (x1, y1, x2, y2)
        ch = choice.get(key)
        if not ch:
            return
        t = ch[0]
        if t == "empty":
            return
        if t == "one":
            rects.append((x1, y1, x2 - x1, y2 - y1, ch[1]))
            return
        if t == "vsplit":
            xm = ch[1]
            rebuild(x1, y1, xm, y2)
            rebuild(xm, y1, x2, y2)
            return
        if t == "hsplit":
            ym = ch[1]
            rebuild(x1, y1, x2, ym)
            rebuild(x1, ym, x2, y2)
            return

    rebuild(0, 0, w, h)

    workers = parallel_workers if parallel_workers and parallel_workers > 1 else 0
    if workers > 1 and w > 1 and h > 1:
        print(f"[optimizer] multiprocessing root-split enabled: workers={workers}")
        candidates = [("v", xm, w, h) for xm in range(1, w)] + [("h", ym, w, h) for ym in range(1, h)]
        best_parallel_cost = root_cost
        best_parallel_rects = rects
        ctx = multiprocessing.get_context("spawn")
        with ProcessPoolExecutor(
            max_workers=workers,
            mp_context=ctx,
            initializer=_worker_init,
            initargs=(rgb_grid, enabled, loss_threshold),
        ) as ex:
            futures = [ex.submit(_evaluate_root_split, c) for c in candidates]
            for f in as_completed(futures):
                cost, split_rects = f.result()
                if cost < best_parallel_cost:
                    best_parallel_cost = cost
                    best_parallel_rects = split_rects
        if best_parallel_cost < root_cost:
            print(f"[optimizer] parallel root split improved: {root_cost} -> {best_parallel_cost}")
            rects = best_parallel_rects

    elapsed = time.time() - start_time
    print(
        f"[optimizer] done: rectangles={len(rects)}, "
        f"states={progress['calls']}/{total_states}, elapsed={elapsed:.2f}s"
    )
    return rects

def ensure_dir(path):
    d = os.path.dirname(path)
    if d and not os.path.exists(d):
        os.makedirs(d, exist_ok=True)

def image_to_commands_2d(img_path, out_path, base_x, base_y, base_z,
                         pixel_size, invert_y, skip_transparent,
                         glow, enabled_colors, orientation="横向",
                         acceptable_loss=0.0, parallel_workers=0):

    print(f"[generator] load image: {img_path}")
    img = Image.open(img_path).convert("RGBA")
    if orientation in ("竖向", "竖向（z延申）"):
        img = img.transpose(Image.Transpose.FLIP_TOP_BOTTOM)

    w, h = img.size
    color_grid, rgb_grid = build_color_grid(img, skip_transparent, enabled_colors)
    commands = []

    brightness_str = "brightness:{block:15,sky:0}" if glow else "brightness:{block:0,sky:0}"

    selected_rects = optimize_rectangles(
        color_grid, rgb_grid, enabled_colors, acceptable_loss, parallel_workers=parallel_workers
    )
    print(f"[generator] selected rectangles: {len(selected_rects)}")

    for i, j, rect_w, rect_h, color_name in selected_rects:
            block = MC_BLOCK_TEMPLATE.format(color_name)
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
    ensure_dir(out_path)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write("# Generated by Minecraft Display Entities Generator\n")
        for c in commands:
            f.write(c + "\n")
    print(f"[generator] output written: {out_path}")
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
        # 使用 StringVar 避免 Entry 临时为空字符串时触发 DoubleVar 的 TclError
        self.acceptable_loss = ctk.StringVar(value="0")
        self.parallel_workers = ctk.StringVar(value="0")
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
        ctk.CTkLabel(left_frame, text="可接受损失(0~20000):", font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5, pady=(6,0))
        ctk.CTkEntry(left_frame, textvariable=self.acceptable_loss, width=280, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)
        ctk.CTkLabel(left_frame, text="并行进程数(0=自动):", font=("Microsoft YaHei", 11)).pack(anchor="w", padx=5, pady=(6,0))
        ctk.CTkEntry(left_frame, textvariable=self.parallel_workers, width=280, font=("Microsoft YaHei", 11)).pack(padx=5, pady=2)
        self.generate_button = ctk.CTkButton(left_frame, text="生成指令", command=self.run, font=("Microsoft YaHei", 12, "bold"))
        self.generate_button.pack(pady=10)

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
            acceptable_loss = self.parse_acceptable_loss()
            parallel_workers = self.parse_parallel_workers()
        except Exception as e:
            messagebox.showerror("错误", str(e))
            return

        self.generate_button.configure(state="disabled", text="生成中...")
        print("[gui] dispatch worker thread...")
        worker = threading.Thread(
            target=self.run_generation_worker,
            args=(img_path, out_path, enabled_colors_dict, acceptable_loss, parallel_workers),
            daemon=True,
        )
        worker.start()

    def run_generation_worker(self, img_path, out_path, enabled_colors_dict, acceptable_loss, parallel_workers):
        try:
            print("[gui] start generating...")
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
                orientation=self.orientation.get(),
                acceptable_loss=acceptable_loss,
                parallel_workers=parallel_workers,
            )
            print(f"[gui] done: commands={n}, image={w}x{h}")
            self.after(0, lambda: self.on_generation_success(n, w, h))
        except Exception as e:
            print(f"[gui] failed: {e}")
            self.after(0, lambda: self.on_generation_fail(e))

    def on_generation_success(self, n, w, h):
        self.generate_button.configure(state="normal", text="生成指令")
        messagebox.showinfo("完成", f"生成 {n} 条指令，图片尺寸 {w}×{h}")

    def on_generation_fail(self, err):
        self.generate_button.configure(state="normal", text="生成指令")
        messagebox.showerror("错误", str(err))
        print(err)

    def parse_acceptable_loss(self):
        value = self.acceptable_loss.get().strip()
        if value == "":
            return 0.0
        try:
            return max(0.0, float(value))
        except ValueError:
            raise ValueError("可接受损失必须是数字")

    def parse_parallel_workers(self):
        value = self.parallel_workers.get().strip()
        if value == "" or value == "0":
            return max(1, os.cpu_count() or 1)
        try:
            workers = int(value)
        except ValueError:
            raise ValueError("并行进程数必须是整数")
        if workers < 1:
            raise ValueError("并行进程数必须 >= 1")
        return workers

if __name__ == "__main__":
    app = App()
    app.mainloop()
