"""极简 cv2 兼容层：用 PIL + NumPy 实现 RapidOCR 运行路径实际用到的 API。

为什么要它：opencv-python 占 120MB，是分发包里最大的一块，而 RapidOCR 只用到
24 个函数（resize/cvtColor/fillPoly/warpPerspective/findContours 等）。业务代码
（src/）零 cv2 依赖，OCR 又跑在独立子进程里 —— 因此在子进程 `import rapidocr`
之前把本模块塞进 `sys.modules["cv2"]`，就能完全不改 RapidOCR 源码地剥掉 opencv。

只实现 RapidOCR 真实调用到的子集，不追求通用性；未实现的属性访问会报错，
避免静默跑出错误结果（宁可直接失败）。
"""
from __future__ import annotations

import numpy as np
from PIL import Image

# ---- 常量（数值与 OpenCV 保持一致，RapidOCR 会按名引用）----
INTER_CUBIC = 2
INTER_LINEAR = 1
INTER_NEAREST = 0

BORDER_REPLICATE = 1
BORDER_CONSTANT = 0

COLOR_GRAY2BGR = 8
COLOR_BGR2GRAY = 6
COLOR_GRAY2RGB = 8
COLOR_BGR2RGB = 4

RETR_LIST = 1
CHAIN_APPROX_SIMPLE = 2

ROTATE_90_CLOCKWISE = 0
ROTATE_180 = 1
ROTATE_90_COUNTERCLOCKWISE = 2

_PIL_RESAMPLE = {
    INTER_NEAREST: Image.NEAREST,
    INTER_LINEAR: Image.BILINEAR,
    INTER_CUBIC: Image.BICUBIC,
}


class _Contour(np.ndarray):
    """findContours 返回的轮廓：需支持 cv2.minAreaRect / boxPoints / arcLength 等。

    直接就是 (N,1,2) int32 的 ndarray 子类，行为与 cv2 一致。
    """


def resize(img: np.ndarray, dsize, interpolation: int = INTER_LINEAR) -> np.ndarray:
    """缩放。OpenCV 的 dsize 是 (宽, 高)，PIL 的 size 也是 (宽, 高)，语义一致。"""
    w, h = int(dsize[0]), int(dsize[1])
    resample = _PIL_RESAMPLE.get(interpolation, Image.BILINEAR)
    im = Image.fromarray(img)
    out = im.resize((w, h), resample)
    return np.array(out)


def cvtColor(img: np.ndarray, code: int) -> np.ndarray:
    """仅支持 RapidOCR 用到的灰度→BGR 与 BGR↔RGB。"""
    if code in (COLOR_GRAY2BGR, COLOR_GRAY2RGB):
        # 灰度 (h,w) → (h,w,3)，三通道同值
        return np.repeat(img[:, :, None], 3, axis=2)
    if code in (COLOR_BGR2RGB, COLOR_BGR2GRAY):
        if code == COLOR_BGR2GRAY:
            # 与 OpenCV 一致的加权灰度：0.299R + 0.587G + 0.114B（输入按 BGR）
            b, g, r = img[:, :, 0], img[:, :, 1], img[:, :, 2]
            gray = 0.114 * b + 0.587 * g + 0.299 * r
            return gray.astype(img.dtype)
        return img[:, :, ::-1]
    raise NotImplementedError(f"cvtColor code={code} 未实现（本项目不需要）")


def split(img: np.ndarray):
    """按通道拆开，等价于沿最后一维切分。"""
    return tuple(img[:, :, i] for i in range(img.shape[2]))


def merge(mv) -> np.ndarray:
    """多通道合并。"""
    return np.stack(mv, axis=-1)


def bitwise_not(src: np.ndarray) -> np.ndarray:
    return np.bitwise_not(src)


def bitwise_and(src1: np.ndarray, src2: np.ndarray, mask=None) -> np.ndarray:
    if mask is None:
        return np.bitwise_and(src1, src2)
    # cv2 语义：mask 非 0 处取 and 结果，0 处取 0；mask 单通道需广播到图像通道
    if mask.ndim == 2 and src1.ndim == 3:
        mask = mask[:, :, None]
    return np.bitwise_and(src1, src2) & mask.astype(src1.dtype)


def add(src1: np.ndarray, src2: np.ndarray) -> np.ndarray:
    """饱和加法（OpenCV 的 cv2.add 是 saturate，不是 numpy 直接相加回绕）。"""
    if src2.ndim == 2 and src1.ndim == 3:
        src2 = src2[:, :, None]
    return np.clip(src1.astype(np.int32) + src2.astype(np.int32), 0, 255).astype(src1.dtype)


def mean(src: np.ndarray, mask=None):
    """返回 (mean_b, mean_g, mean_r, 0) —— RapidOCR 只取 [0]，但保持 cv2 的 4 元组形状。"""
    if mask is None:
        m = src.mean(axis=(0, 1))
    else:
        # mask 指定参与统计的像素；标量结果（RapidOCR 的 box_score_fast 走这条）
        idx = mask.astype(bool)
        if src.ndim == 2:
            m = src[idx].mean() if idx.any() else 0.0
            return (float(m), 0.0, 0.0, 0.0)
        m = src[idx].mean(axis=0) if idx.any() else np.zeros(src.shape[2])
    m = np.atleast_1d(m)
    if m.size == 1:
        return (float(m[0]), 0.0, 0.0, 0.0)
    return (float(m[0]), float(m[1]), float(m[2]), 0.0) if m.size == 3 else tuple(float(x) for x in m)


def fillPoly(img: np.ndarray, pts, color) -> np.ndarray:
    """填充多边形（原地）。RapidOCR 用它生成 box 的 mask（值为 1）。"""
    from PIL import ImageDraw
    h, w = img.shape[:2]
    mask = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(mask)
    for poly in pts:
        arr = np.asarray(poly, dtype=np.int32).reshape(-1, 2)
        d.polygon([tuple(p) for p in arr], fill=1)
    m = np.array(mask).astype(bool)
    if img.ndim == 2:
        img[m] = color
    else:
        img[m] = color
    return img


def dilate(src: np.ndarray, kernel) -> np.ndarray:
    """膨胀。kernel 是 np.ones((k,k),uint8)。用最大值滤波实现（纯 NumPy 滑窗）。"""
    if kernel is None:
        return src
    k = np.asarray(kernel)
    kh, kw = k.shape[0], k.shape[1]
    if kh == 0 or kw == 0:
        return src
    # 边缘用 -inf 填充后取局部最大；pad 值取 0 更贴近二值图语义（不产生假的 1）
    pad_h, pad_w = kh // 2, kw // 2
    padded = np.pad(src, ((pad_h, pad_h), (pad_w, pad_w)), mode="constant", constant_values=0)
    out = np.zeros_like(src)
    for i in range(kh):
        for j in range(kw):
            if k[i, j]:
                out = np.maximum(out, padded[i:i + src.shape[0], j:j + src.shape[1]])
    return out


def findContours(bitmap: np.ndarray, mode: int = RETR_LIST, method: int = CHAIN_APPROX_SIMPLE):
    """提取轮廓，返回 (contours, hierarchy) —— 与 cv2 4.x 的 2 元组一致。

    ponytail: 用「连通域外接轮廓」近似，不做真正的边界跟踪。DB 后处理只用轮廓取
    外接旋转矩形（get_mini_boxes → minAreaRect）并算 box 得分，外接框足够。
    连通域用纯 NumPy 洪水填充（运行时不带 scipy，勿引入）。
    """
    contours = []
    for pts in _connected_components(bitmap > 0):
        contours.append(pts.reshape(-1, 1, 2).astype(np.int32))
    if not contours:
        return [np.zeros((0, 1, 2), dtype=np.int32)], None
    return contours, None


def _connected_components(mask: np.ndarray):
    """4-邻域连通域 → 每个域的所有像素点 (N,2) 的 [x,y]（纯 NumPy 扫描填充）。

    ponytail: 逐域 BFS，最坏 O(像素数)；DB 输出是缩过的特征图（~1/4 尺寸），
    量级没问题。若日后大图上变慢，换 scipy.ndimage.label。
    """
    h, w = mask.shape
    seen = np.zeros((h, w), dtype=bool)
    out = []
    ys, xs = np.nonzero(mask)
    for sy, sx in zip(ys, xs):
        if seen[sy, sx]:
            continue
        stack = [(sy, sx)]
        seen[sy, sx] = True
        comp = []
        while stack:
            y, x = stack.pop()
            comp.append((x, y))
            for ny, nx in ((y - 1, x), (y + 1, x), (y, x - 1), (y, x + 1)):
                if 0 <= ny < h and 0 <= nx < w and mask[ny, nx] and not seen[ny, nx]:
                    seen[ny, nx] = True
                    stack.append((ny, nx))
        out.append(np.array(comp, dtype=np.int32))
    return out


def minAreaRect(contour: np.ndarray):
    """最小外接旋转矩形 → ((cx,cy),(w,h),angle)。用 OpenCV 同款算法：凸包 + 旋转卡壳近似。

    ponytail: 用「按凸包各边对齐求最小外接矩形」的经典 O(n·h) 做法，与 OpenCV 结果
    在角点精度上可能有极小差异；DB 后处理只用来定字框，不影响识别。
    """
    pts = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
    if pts.shape[0] == 0:
        return ((0.0, 0.0), (0.0, 0.0), 0.0)
    hull = _convex_hull(pts)
    best = None
    for i in range(len(hull)):
        p0, p1 = hull[i], hull[(i + 1) % len(hull)]
        edge = p1 - p0
        n = np.linalg.norm(edge)
        if n < 1e-9:
            continue
        ux, uy = edge / n
        # 投影到该边方向与其法向
        proj_x = hull @ np.array([ux, uy])
        proj_y = hull @ np.array([-uy, ux])
        w = proj_x.max() - proj_x.min()
        h = proj_y.max() - proj_y.min()
        area = w * h
        if best is None or area < best[0]:
            cx = (proj_x.max() + proj_x.min()) / 2
            cy = (proj_y.max() + proj_y.min()) / 2
            # 换回图像坐标
            center = cx * np.array([ux, uy]) + cy * np.array([-uy, ux])
            angle = np.degrees(np.arctan2(uy, ux))
            best = (area, (float(center[0]), float(center[1])), (float(w), float(h)),
                    float(angle))
    if best is None:
        return ((0.0, 0.0), (0.0, 0.0), 0.0)
    return (best[1], best[2], best[3])


def boxPoints(rect):
    """旋转矩形的 4 个角点（cv2.boxPoints 同语义）。rect = ((cx,cy),(w,h),angle)。"""
    (cx, cy), (w, h), angle = rect
    a = np.deg2rad(angle)
    cos_a, sin_a = np.cos(a), np.sin(a)
    # OpenCV 返回 order: 左下、左上、右上、右下（相对未旋转的 w/h 定义）
    pts = np.array([
        [-w / 2, h / 2], [w / 2, h / 2], [w / 2, -h / 2], [-w / 2, -h / 2],
    ], dtype=np.float32)
    rot = np.array([[cos_a, -sin_a], [sin_a, cos_a]], dtype=np.float32)
    return pts @ rot.T + np.array([cx, cy], dtype=np.float32)


def _convex_hull(pts: np.ndarray) -> np.ndarray:
    """Andrew monotone chain 凸包。"""
    pts = np.unique(pts, axis=0)
    if len(pts) <= 2:
        return pts
    pts = pts[np.lexsort((pts[:, 1], pts[:, 0]))]

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    lower = []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    upper = []
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    return np.array(lower[:-1] + upper[:-1])


def rotate(img: np.ndarray, rotate_code: int) -> np.ndarray:
    """按 90/180/270 旋转。RapidOCR 只用 ROTATE_180(=1)。"""
    if rotate_code == ROTATE_180:
        return img[::-1, ::-1]
    if rotate_code == ROTATE_90_CLOCKWISE:
        return np.rot90(img, k=-1)
    if rotate_code == ROTATE_90_COUNTERCLOCKWISE:
        return np.rot90(img, k=1)
    raise NotImplementedError(f"rotate code={rotate_code} 未实现")


def getPerspectiveTransform(src, dst) -> np.ndarray:
    """求 3x3 透视变换矩阵（4 点对应）。解 8 元线性方程组。"""
    src = np.asarray(src, dtype=np.float64).reshape(4, 2)
    dst = np.asarray(dst, dtype=np.float64).reshape(4, 2)
    A = []
    for (x, y), (u, v) in zip(src, dst):
        A.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        A.append([0, 0, 0, x, y, 1, -v * x, -v * y])
    A = np.array(A, dtype=np.float64)
    b = dst.reshape(-1)
    res = np.linalg.solve(A, b)
    return np.append(res, 1.0).reshape(3, 3)


def warpPerspective(img: np.ndarray, M: np.ndarray, dsize, borderMode: int = BORDER_CONSTANT,
                    flags: int = INTER_LINEAR) -> np.ndarray:
    """透视变换。用逆映射 + 双线性/最近邻采样（纯 NumPy）。"""
    w, h = int(dsize[0]), int(dsize[1])
    if w <= 0 or h <= 0:
        return np.zeros((max(h, 1), max(w, 1)) + img.shape[2:], dtype=img.dtype)

    M_inv = np.linalg.inv(M)
    # 目标图每个像素 → 源图坐标
    xs, ys = np.meshgrid(np.arange(w), np.arange(h))
    ones = np.ones_like(xs)
    coords = np.stack([xs, ys, ones], axis=-1).reshape(-1, 3).T
    src = M_inv @ coords
    sx = (src[0] / src[2]).reshape(h, w)
    sy = (src[1] / src[2]).reshape(h, w)

    return _sample(img, sx, sy, flags, borderMode)


def _sample(img: np.ndarray, sx: np.ndarray, sy: np.ndarray, flags: int,
            borderMode: int) -> np.ndarray:
    """按浮点源坐标采样。越界按 borderMode 处理（REPLICATE=夹取边缘）。"""
    ih, iw = img.shape[:2]

    if borderMode == BORDER_REPLICATE:
        sx = np.clip(sx, 0, iw - 1)
        sy = np.clip(sy, 0, ih - 1)
    else:  # BORDER_CONSTANT：越界置 0
        pass

    if flags == INTER_NEAREST:
        ix = np.clip(np.round(sx).astype(np.int64), 0, iw - 1)
        iy = np.clip(np.round(sy).astype(np.int64), 0, ih - 1)
        return img[iy, ix]

    # 双线性
    x0 = np.floor(sx).astype(np.int64)
    y0 = np.floor(sy).astype(np.int64)
    x1, y1 = x0 + 1, y0 + 1
    wx = (sx - x0)[..., None] if img.ndim == 3 else (sx - x0)
    wy = (sy - y0)[..., None] if img.ndim == 3 else (sy - y0)

    def at(xa, ya):
        ok = (xa >= 0) & (xa < iw) & (ya >= 0) & (ya < ih)
        xc = np.clip(xa, 0, iw - 1)
        yc = np.clip(ya, 0, ih - 1)
        v = img[yc, xc].astype(np.float64)
        if borderMode != BORDER_REPLICATE:
            v = v * ok[..., None] if img.ndim == 3 else v * ok
        return v

    top = at(x0, y0) * (1 - wx) + at(x1, y0) * wx
    bot = at(x0, y1) * (1 - wx) + at(x1, y1) * wx
    out = top * (1 - wy) + bot * wy
    return np.clip(out, 0, 255).astype(img.dtype) if img.dtype == np.uint8 else out.astype(img.dtype)


def imread(path, flags: int = 1):
    """读文件（RapidOCR 运行路径不走这里，仅为兼容 import 期引用）。"""
    return np.array(Image.open(path))


def imdecode(buf, flags: int = 1):
    """从内存解码（同上，兼容用）。"""
    import io as _io
    data = buf if isinstance(buf, (bytes, bytearray)) else np.asarray(buf).tobytes()
    return np.array(Image.open(_io.BytesIO(data)))


def imwrite(path, img) -> bool:
    Image.fromarray(img).save(path)
    return True


def polylines(img, pts, isClosed, color, thickness: int = 1):
    """画多边形（仅用于 demo 可视化，RapidOCR 运行路径不触发）。"""
    from PIL import ImageDraw
    im = Image.fromarray(img)
    d = ImageDraw.Draw(im)
    for poly in pts:
        arr = np.asarray(poly, dtype=np.int32).reshape(-1, 2)
        d.line([tuple(p) for p in arr] + ([tuple(arr[0])] if isClosed else []),
               fill=tuple(color), width=thickness)
    img[...] = np.array(im)
    return img


def arcLength(curve, closed: bool) -> float:
    pts = np.asarray(curve, dtype=np.float64).reshape(-1, 2)
    if len(pts) < 2:
        return 0.0
    seg = np.linalg.norm(np.diff(pts, axis=0), axis=1).sum()
    if closed:
        seg += np.linalg.norm(pts[0] - pts[-1])
    return float(seg)


def boundingRect(contour) -> tuple:
    pts = np.asarray(contour, dtype=np.int32).reshape(-1, 2)
    x0, y0 = pts[:, 0].min(), pts[:, 1].min()
    x1, y1 = pts[:, 0].max(), pts[:, 1].max()
    return int(x0), int(y0), int(x1 - x0), int(y1 - y0)


def contourArea(contour, oriented: bool = False) -> float:
    pts = np.asarray(contour, dtype=np.float64).reshape(-1, 2)
    if len(pts) < 3:
        return 0.0
    x, y = pts[:, 0], pts[:, 1]
    return float(0.5 * abs(np.dot(x, np.roll(y, -1)) - np.dot(y, np.roll(x, -1))))


__version__ = "4.11.0-fontcop-shim"


if __name__ == "__main__":
    # 最小自检：跑一遍 RapidOCR 实际会走的关键路径，确认几何结果合理
    a = np.arange(12, dtype=np.uint8).reshape(3, 4)
    assert resize(a, (8, 6)).shape == (6, 8), "resize 尺寸 (w,h) 语义"
    assert cvtColor(a, COLOR_GRAY2BGR).shape == (3, 4, 3), "gray→bgr"
    rgba = np.dstack([a, a[::-1], a, np.full_like(a, 255)])
    r, g, b, al = split(rgba)
    # cv2.split/merge 是 BGR 语义：split 得到 (B,G,R,A)，merge((b,g,r)) 还原成 BGR 序
    assert np.array_equal(merge((b, g, r)), rgba[:, :, :3]), "split/merge 通道顺序"
    assert add(np.full((2, 2), 250, np.uint8), np.full((2, 2), 10, np.uint8)).max() == 255, "add 饱和"

    # 矩形 → minAreaRect/boxPoints 往返
    box = np.array([[10, 10], [60, 10], [60, 30], [10, 30]], dtype=np.int32).reshape(-1, 1, 2)
    (cx, cy), (w, h), ang = minAreaRect(box)
    assert abs(w - 50) < 2 and abs(h - 20) < 2, f"minAreaRect 尺寸错: {(w, h)}"
    assert abs(cx - 35) < 2 and abs(cy - 20) < 2, f"minAreaRect 中心错: {(cx, cy)}"
    pts = boxPoints(((cx, cy), (w, h), ang))
    assert pts.shape == (4, 2), "boxPoints 形状"

    # findContours：两个分离方块应得 2 个轮廓
    bm = np.zeros((40, 40), np.uint8)
    bm[5:15, 5:15] = 1
    bm[25:35, 25:35] = 1
    cs, _ = findContours(bm)
    assert len(cs) == 2, f"findContours 应得 2 个轮廓，实际 {len(cs)}"

    # 透视变换：单位矩阵应近似恒等
    img = np.random.randint(0, 255, (20, 30, 3), dtype=np.uint8)
    M = getPerspectiveTransform([[0, 0], [29, 0], [29, 19], [0, 19]],
                                [[0, 0], [29, 0], [29, 19], [0, 19]])
    out = warpPerspective(img, M, (30, 20), borderMode=BORDER_REPLICATE, flags=INTER_CUBIC)
    assert out.shape == img.shape, "warpPerspective 形状"
    assert np.abs(out.astype(int) - img.astype(int)).mean() < 2, "恒等变换应近似原图"

    # dilate：1 像素应扩成 3x3
    d = dilate(np.eye(5, dtype=np.uint8), np.ones((3, 3), np.uint8))
    assert d[1:4, 1:4].sum() == 9, "dilate 应把孤立点扩成 3x3"

    print("cv2 shim 自检通过 ✅")
