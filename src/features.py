"""特征提取与相似度计算：二值图、IoU（粗排）、SDF+NCC（精排）。"""
import numpy as np
from scipy.ndimage import distance_transform_edt

SIZE = 128          # 渲染/比对主尺寸
SDF_SIZE = 64       # 索引存储的 SDF 尺寸（省内存）


def to_binary(img: np.ndarray, threshold: int = 32) -> np.ndarray:
    """灰度 uint8 → 0/1 uint8。"""
    return (np.asarray(img, dtype=np.uint8) > threshold).astype(np.uint8)


def iou_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """二值图交并比，[0,1]。粗排用。"""
    inter = np.logical_and(a, b).sum()
    union = np.logical_or(a, b).sum()
    return float(inter / union) if union else 0.0


def sdf(binary: np.ndarray, size: int = SDF_SIZE) -> np.ndarray:
    """二值图 → 有符号距离场（下采样到 size×size，float32）。
    内部为负距离、外部为正距离。对笔画粗细/轻微错位不敏感。
    """
    img = Image_resize_nearest(binary, size)
    inside = distance_transform_edt(img)
    outside = distance_transform_edt(1 - img)
    field = outside - inside          # 内正外负取反：字体越"实心"内越深
    std = field.std()
    return (field / std).astype(np.float32) if std > 1e-6 else np.zeros_like(field, dtype=np.float32)


def Image_resize_nearest(binary: np.ndarray, size: int) -> np.ndarray:
    from PIL import Image as PILImage
    im = PILImage.fromarray((binary * 255).astype(np.uint8))
    im = im.resize((size, size), PILImage.NEAREST)
    return (np.asarray(im) > 127).astype(np.uint8)


def ncc_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """两个 SDF 的归一化互相关，[-1,1]，截断到 [0,1]。"""
    a = a - a.mean()
    b = b - b.mean()
    denom = np.sqrt((a * a).sum() * (b * b).sum())
    if denom < 1e-9:
        return 0.0
    return float(np.clip((a * b).sum() / denom, 0.0, 1.0))


def ncc_aligned(a: np.ndarray, b: np.ndarray, max_shift: int = 2) -> float:
    """带小范围平移搜索的 NCC：对截图裁剪的 1-2px 偏移鲁棒。
    在 ±max_shift 的整数平移中取最大相似度。"""
    best = 0.0
    for dy in range(-max_shift, max_shift + 1):
        for dx in range(-max_shift, max_shift + 1):
            shifted = np.roll(np.roll(b, dy, axis=0), dx, axis=1)
            best = max(best, ncc_similarity(a, shifted))
    return best


def hog(binary: np.ndarray, cells: int = 8, bins: int = 8) -> np.ndarray:
    """简化 HOG：字形二值图梯度方向直方图，捕获笔画走向（横/竖/撇/捺）。
    对近重复字体（同源不同渲染）的差异敏感。返回归一化特征向量。
    """
    img = Image_resize_nearest(binary, 128).astype(np.float32)
    gy, gx = np.gradient(img)
    mag = np.hypot(gx, gy)
    ang = np.arctan2(gy, gx)          # [-pi, pi]
    ang = (ang + np.pi) % np.pi       # 折叠到 [0, pi)：方向无向
    H = img.shape[0]
    cell = H // cells
    feat = np.zeros((cells, cells, bins), dtype=np.float32)
    bin_idx = (ang / (np.pi / bins)).astype(int).clip(0, bins - 1)
    for cy in range(cells):
        for cx in range(cells):
            sl_y = slice(cy * cell, (cy + 1) * cell)
            sl_x = slice(cx * cell, (cx + 1) * cell)
            m, b = mag[sl_y, sl_x], bin_idx[sl_y, sl_x]
            for k in range(bins):
                feat[cy, cx, k] = m[b == k].sum()
    v = feat.ravel()
    n = np.linalg.norm(v)
    return (v / n).astype(np.float32) if n > 1e-9 else v


def hog_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """HOG 特征余弦相似度，截断到 [0,1]。"""
    d = float(np.dot(a, b))
    return float(np.clip(d, 0.0, 1.0))


# 三档判定阈值（SDF+NCC 相似度）
THRESHOLD_FREE = 0.90      # ≥0.90 → ✅ 免费
THRESHOLD_SUSPECT = 0.75   # ≥0.75 → 🤔 疑似；否则 ⚠️ 版权风险
