# chrisxxxx — 深度视频 / depth & 3D video

把普通 2D 视频转成**深度图视频**和**立体 3D 视频**的一套流水线。

深度由 [Depth Anything V2](https://github.com/DepthAnything/Depth-Anything-V2)
(ViT-S, ONNX 导出版) 估计，用 `onnxruntime` 在 **CPU** 上跑，不需要显卡、不需要
PyTorch。视频的解码和编码交给 `ffmpeg`。

## 安装

```bash
./setup.sh
```

会装好 `ffmpeg`、`numpy`、`opencv-python-headless`、`onnxruntime`，
并把约 95 MB 的模型权重下载到 `models/`（该目录不进版本库）。

## 使用

```bash
python3 depth_video.py -i clip.mp4 -o out --outputs gray,color,sbs,anaglyph --pad
```

### 产出

| 文件 | 内容 |
| --- | --- |
| `depth_gray.mp4` | 灰度深度图，越亮越近 |
| `depth_color.mp4` | 上色深度图（默认 inferno 色带） |
| `stereo_sbs.mp4` | 左右格式立体视频（left \| right），给 VR 头显 / 3D 电视 / 手机分屏看 |
| `anaglyph_red_cyan.mp4` | 红蓝（红-青）眼镜版，普通屏幕直接看 |
| `compare.mp4` | 原片在上、深度图在下，用来快速检查效果 |

原片的音轨会自动复制到每个产出文件里（`--no-audio` 可关掉）。

### 常用参数

| 参数 | 说明 |
| --- | --- |
| `--crop auto\|none\|W:H:X:Y` | 黑边处理。`auto` 用 `cropdetect` 自动找出真正的画面区域，避免模型把黑边也当成景物 |
| `--pad` | 把深度图贴回原始画布（保留黑边），让 `depth_gray/depth_color` 和原片同尺寸 |
| `--divergence` | 立体强度，按画面宽度的百分比算。默认 `2.0`；想更"出屏"就调大，但太大会有边缘拉丝 |
| `--convergence` | 0–1，哪个深度落在屏幕平面上。默认 `0.5`：比它近的出屏，比它远的入屏 |
| `--smooth` | 深度归一化的时间平滑系数，默认 `0.25`。数值越小越稳，`1.0` 表示关闭 |
| `--colormap` | `inferno` / `magma` / `turbo` / `viridis` / `plasma` / `bone` |
| `--max-frames` | 只处理前 N 帧，调参试片用 |
| `--threads` | 推理线程数，默认等于 CPU 核数 |
| `--crf` / `--preset` | x264 编码质量与速度 |

## 实现说明

1. **解码** — `ffmpeg` 直接吐 `bgr24` 裸流到管道，按需要先 `crop` 掉黑边。
2. **深度推理** — 每帧缩放到模型固定的 518×518，做 ImageNet 归一化后送进网络，
   拿到的是**逆深度**（值越大越近），再插值回工作分辨率。
3. **时间稳定** — 逐帧独立归一化会让整个画面一帧一帧地"呼吸"。这里的做法是只取
   每帧的 2%/98% 分位数作为归一化上下界，再对这两条曲线做**前向+反向 EMA** 平滑，
   然后才用平滑后的区间去归一化。细节保留，闪烁消失。
4. **立体合成** — DIBR（depth-image-based rendering）：视差 `d = (深度 - convergence) × 强度`，
   左眼采样 `x + d/2`、右眼采样 `x - d/2`。用**反向** warp，所以不会出现需要补的空洞；
   视差图先做一次横向高斯模糊，避免物体边缘撕裂。
5. **红蓝合成** — Dubois 优化矩阵，比直接抽通道的鬼影少很多。

深度先落盘成 float16 memmap，两趟处理：第一趟只做推理，第二趟渲染所有输出格式。
所以多要几种产出不会重复跑模型。

## 性能

4 核 CPU、864×538 的画面上，约 **0.5 秒/帧**。54 秒 / 1631 帧的片子大约 15 分钟跑完推理，
渲染和编码再几分钟。

## 关于素材

`out/` 不进版本库——里面是渲染出来的视频和上百 MB 的深度缓存，而且测试用的是一段
港产喜剧片的片段。这类版权素材请只作自用测试，不要传上仓库或直接对外发布。
