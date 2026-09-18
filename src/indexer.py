"""建库：每款字体渲染常用字 → 二值图 + SDF → 存 data/glyph_index.npz。

索引结构（npz）：
  font_ids : [n_fonts] str
  chars    : [n_chars] str（每字符一个 unicode 码点）
  glyphs   : [n_fonts, n_chars, 64, 64] uint8   二值图（粗排 IoU 用）
  sdfs     : [n_fonts, n_chars, 64, 64] float16 SDF（精排 NCC 用）
"""
import json
import sys
import time
from pathlib import Path

import numpy as np

from src.features import SDF_SIZE, sdf
from src.render import FINAL_SIZE, glyph_files, render_char
from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
INDEX_PATH = ROOT / "data" / "glyph_index.npz"

# 索引字符集：500 常用字 + 常见标点/字母数字（与 verify_fonts.py 保持同源逻辑即可）
CHARS = (
    "的一是了我不人在他有这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日手又行意动方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感见明问力理尔点文几定本公特做外孩相西果走将月十实向声车全信重三机工物气每并别真打太新比才便夫再书部水像眼等体却加电主界门利海受听表德少克代员许稜先口由死安写性马光白或住难望教命花结乐色更拉东神记处让母父应直字场平报友关放至张认接告入笑内英军候民岁往何度山觉路带万男边风解叫任金快原吃妈变通师立象数四失满战远格士音轻目条呢病始达深完今提求清王化空业思切怎非找片罗钱语元喜曾离飞科言干流欢约各即指合反题必该论交终林请医晚制球决传画保读运及则房早院量苦火布品近坐产答星精视五连司巴奇管类未朋且婚台夜青北队久乎越观落尽形影红爸百令周吧识步希亚术留市半热送兴造谈容极随演收首根讲整式取照办强石古华拿计您装似足双妻尼转诉米称丽客南领节衣站黑刻统断福城故历惊脸选包紧争另建维绝树系伤示愿持千史谁准联妇纪基买志静阿诗独复痛消社算义竟确酒需单治卡幸兰念举仅钟怕共毛句息功官待究跟穿室易游程号居考突皮哪费倒价图具刚脑永歌响商礼细专黄块脚味灵改据般破引食仍存众注笔甚某沉血备习校默务土微娘须试怀料调广蜻苏显赛查密议底列富梦错座参八除跑亮假印设线温虽掉京初养香停际致阳纸李纳验助激够严证帝饭忘趣支春集丈木研班普导顿睡展跳获艺六波察群皇段急庭创区奥器谢弟店否害草排背止组州朝封睛板角况曲馆育忙质河续哥呼若推境遇雨标姐充围案伦护冷警贝著雪索剧啊船险烟依斗值帮汉慢佛肯闻唱沙局伴"
    "，。、；：？！""''（）《》【】…—·0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"
)


def build(verbose: bool = True) -> None:
    files = glyph_files()
    font_ids = sorted(files)
    chars = [c for c in CHARS]

    n_f, n_c = len(font_ids), len(chars)
    glyphs = np.zeros((n_f, n_c, SDF_SIZE, SDF_SIZE), dtype=np.uint8)
    sdfs = np.zeros((n_f, n_c, SDF_SIZE, SDF_SIZE), dtype=np.float16)

    t0 = time.time()
    for i, fid in enumerate(font_ids):
        t1 = time.time()
        for j, ch in enumerate(chars):
            g = render_char(files[fid], ch)
            if g is None:
                continue  # 缺字形保持全 0（IoU/NCC 自然为低分）
            g64 = np.asarray(
                Image.fromarray(g * 255).resize((SDF_SIZE, SDF_SIZE), Image.NEAREST)
            )
            b64 = (g64 > 127).astype(np.uint8)
            glyphs[i, j] = b64
            sdfs[i, j] = sdf(b64).astype(np.float16)
        if verbose:
            print(f"[{i+1}/{n_f}] {fid} done in {time.time()-t1:.1f}s", flush=True)

    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        INDEX_PATH,
        font_ids=np.array(font_ids),
        chars=np.array(chars),
        glyphs=glyphs,
        sdfs=sdfs,
    )
    mb = INDEX_PATH.stat().st_size / 1e6
    print(f"\nsaved {INDEX_PATH} ({mb:.0f} MB) in {time.time()-t0:.0f}s")


def load() -> dict:
    if not INDEX_PATH.exists():
        sys.exit("索引不存在，先运行: python -m src.indexer")
    z = np.load(INDEX_PATH, allow_pickle=False)
    return {
        "font_ids": z["font_ids"].tolist(),
        "chars": z["chars"].tolist(),
        "glyphs": z["glyphs"],
        "sdfs": z["sdfs"].astype(np.float32),
    }


if __name__ == "__main__":
    build()
