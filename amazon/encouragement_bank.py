# -*- coding: utf-8 -*-
"""
encouragement_bank.py
—— 运营日报/播报用的励志语料库（上涨/稳定/回落）
特性：
1) 三类趋势（rise/stable/fall），每类包含：
   - 100 条【古诗词/翻译/典故】复合句
   - 100 条【鼓励词】句式
2) 提供 get_encouragement(trend) 一键随机组合输出
3) 语料由小规模种子 + 模板自动扩展为 100 条，确保可维护 & 可复用

用法：
from encouragement_bank import get_encouragement
msg = get_encouragement("rise")
"""

from __future__ import annotations
import random
from typing import List, Dict, Tuple

# ========== 基础工具 ==========
def _ensure_100(items: List[str], wants: int = 100) -> List[str]:
    """把列表扩展/打乱至 wants 条（循环采样 + 打散，保证稳定 100 条）"""
    if not items:
        return ["" for _ in range(wants)]
    out = (items * (wants // len(items) + 1))[:wants]
    random.Random(20251017).shuffle(out)  # 固定种子：导入即稳定乱序，但每次运行一致
    return out

def _fmt_poem_line(cn: str, en: str, src: str) -> str:
    # “中文”（English）—— 典故/出处
    return f"“{cn}”（{en}）—— {src}"

def _expand_poems(
    seeds: List[Tuple[str, str, str]],
    wrappers: List[str],
    wants: int = 100
) -> List[str]:
    """
    seeds: [(cn, en, source)]
    wrappers: 对诗句进行轻量包装的模板，使用 {line} 占位
    生成：{wrapper_prefix}{诗句行}
    """
    lines = []
    for cn, en, src in seeds:
        core = _fmt_poem_line(cn, en, src)
        for w in wrappers:
            if "{line}" in w:
                lines.append(w.format(line=core))
            else:
                lines.append(core if not w else f"{w}{core}")
    return _ensure_100(lines, wants=wants)

def _expand_encourage(
    seeds: List[str],
    tails: List[str],
    wants: int = 100
) -> List[str]:
    """
    把鼓励语种子和收尾/补充语句做笛卡尔扩展，再裁剪到 100 条。
    """
    combos = [f"{s}{(' ' + t) if t else ''}".strip() for s in seeds for t in tails]
    return _ensure_100(combos, wants=wants)

# ========== 种子语料 ==========
# 说明：
# - 为避免消息极端超长，诗句英文翻译皆为简洁译文；
# - 不同趋势选取了语义贴合的名句；
# - 你可以随时增减或微调 seeds，系统仍会自动扩展为 100 条。

# —— 上涨（rise）诗句种子（cn, en, source）
RISE_POEM_SEEDS: List[Tuple[str, str, str]] = [
    ("会挽雕弓如满月", "Draw the bow like the full moon", "苏轼《江城子》"),
    ("长风破浪会有时", "Riding winds and breaking waves will come", "李白《行路难》"),
    ("雄关漫道真如铁", "The iron pass is hard indeed", "毛泽东《忆秦娥》"),
    ("直挂云帆济沧海", "Hoist the sails to cross the vast sea", "李白《行路难》"),
    ("千磨万击还坚劲", "Tempered by hardships yet stronger", "郑板桥《竹石》"),
    ("天生我材必有用", "Heaven gave me talent for a reason", "李白《将进酒》"),
    ("不畏浮云遮望眼", "Fear no clouds that block the view", "王安石《登飞来峰》"),
    ("更上一层楼", "Climb one story higher", "王之涣《登鹳雀楼》"),
    ("一日看尽长安花", "See Chang'an’s blossoms in one day", "卢照邻《长安古意》"),
    ("宝剑锋从磨砺出", "A sword is forged by honing", "谚语"),
    ("会当凌绝顶", "Stand atop the peak", "杜甫《望岳》"),
    ("燕雀安知鸿鹄之志", "Sparrows can't know swans' ambition", "《史记》陈涉世家"),
    ("青，取之于蓝而青于蓝", "From indigo yet surpassing indigo", "《荀子·劝学》"),
    ("天行健，君子以自强不息", "Heaven keeps moving, be self-strengthened", "《周易》"),
    ("路漫漫其修远兮", "Long is the road ahead", "屈原《离骚》"),
    ("会挽雕弓当射雕", "Draw the bow to shoot eagles", "化用"),
    ("扶摇直上九万里", "Soar up to the skies", "《庄子》逍遥游"),
    ("大鹏一日同风起", "A roc rides the same wind", "李白《上李邕》"),
    ("乘风破浪正当时", "Now is the time to set sail", "化用"),
    ("不积跬步，无以至千里", "No miles without steps", "《荀子·劝学》"),
]

# —— 稳定（stable）诗句种子
STABLE_POEM_SEEDS: List[Tuple[str, str, str]] = [
    ("不驰于空想，不骛于虚声", "No empty fantasy, no vain fame", "李大钊《守常》"),
    ("行百里者半九十", "Last miles are the hardest", "《战国策》"),
    ("滴水穿石，绳锯木断", "Dripping water pierces stone", "谚语"),
    ("沉舟侧畔千帆过", "By the sunken boat, thousands of sails pass", "刘禹锡《酬乐天》"),
    ("衣带渐宽终不悔", "Slimming my waist without regret", "柳永《蝶恋花》"),
    ("锲而不舍，金石可镂", "Carving unceasingly cuts metal", "《荀子·劝学》"),
    ("博观而约取，厚积而薄发", "Observe widely, choose precisely", "苏轼《稼说送张琥》"),
    ("择其善者而从之", "Follow what is good", "《论语》"),
    ("守拙归田园", "Keep simplicity, return to the field", "陶渊明《归园田居》"),
    ("静以修身，俭以养德", "Cultivate by stillness and thrift", "诸葛亮《诫子书》"),
    ("不温不火，稳扎稳打", "Neither rash nor slow; solid", "成语/口语"),
    ("行而不辍，未来可期", "Walk on without stopping", "化用"),
    ("大道至简，实干为先", "Simplicity first, action foremost", "化用"),
    ("当春乃发生", "Spring brings growth", "《易经》"),
    ("岁寒，然后知松柏之后凋", "In winter, pines stay green", "《论语》"),
]

# —— 回落（fall）诗句种子（偏“勉励复盘、蓄力反弹”的基调）
FALL_POEM_SEEDS: List[Tuple[str, str, str]] = [
    ("山重水复疑无路，柳暗花明又一村", "After mountains and rivers, a village appears", "陆游《游山西村》"),
    ("穷且益坚，不坠青云之志", "In adversity, keep high aims", "《后汉书》"),
    ("长风破浪会有时，直挂云帆济沧海", "Winds will come; sail on", "李白《行路难》"),
    ("莫听穿林打叶声，何妨吟啸且徐行", "Let the storm blow; walk on", "苏轼《定风波》"),
    ("不经一番寒彻骨，怎得梅花扑鼻香", "No winter, no plum fragrance", "黄蘖禅师《上堂开示颂》"),
    ("失之东隅，收之桑榆", "Lose in the east, gain in the west", "《后汉书》"),
    ("青山遮不住，毕竟东流去", "Green hills can't stop the eastward flow", "辛弃疾《菩萨蛮》"),
    ("行到水穷处，坐看云起时", "Reach the water’s end, watch clouds rise", "王维《终南别业》"),
    ("生当作人杰，死亦为鬼雄", "Be a hero alive or dead", "李清照《夏日绝句》"),
    ("屈原未死，后人自强", "Qu Yuan's spirit lives on", "化用"),
    ("天将降大任于斯人也", "Heaven tests before entrusting", "《孟子》"),
    ("否极泰来", "After downturn comes upturn", "《周易》"),
    ("风乍起，吹皱一池春水", "Wind ripples spring water", "冯延巳《谒金门》"),
]

# —— 典故/包装模板（为诗句增加语气/承接）
RISE_WRAP = [
    "", "此刻最贴切的一句：{line}", "以此自勉：{line}", "精神坐标：{line}", "战报签名：{line}",
]
STABLE_WRAP = [
    "", "静水深流，谨记：{line}", "方法论底座：{line}", "刻度尺：{line}", "节拍器：{line}",
]
FALL_WRAP = [
    "", "逆风翻盘的底气：{line}", "复盘勉励：{line}", "扳回一城的注脚：{line}", "心定如山：{line}",
]

# —— 鼓励词种子（短句）
RISE_ENC_SEEDS = [
    "好势头，继续扩大领先！", "乘胜追击，把优势打满！", "节奏对了，再提一档！",
    "状态拉满，向更高目标冲刺！", "保持火力，巩固第一增长曲线！",
    "漂亮！延长高光区间！", "把确定性做厚，把波动性做薄！",
]
STABLE_ENC_SEEDS = [
    "稳中求进，打磨核心单品！", "节奏平稳，继续累加有效增量！",
    "把每一单的确定性再提高一点！", "今天的稳定，是明天的突破口！",
    "工艺于细，优势于稳！", "保持专注，别被噪声牵着走～",
]
FALL_ENC_SEEDS = [
    "小幅回落，先稳住，再反弹！", "复盘两件事：结构 & 投放节奏。",
    "先把“基本盘”找回来！", "波动是常态，修正后再起跑！",
    "聚焦可控项，别与偶然性拉扯。", "别慌，一步步把指数拉回来！",
]

# —— 鼓励词尾/补充（可为空字符串代表不加尾巴）
COMMON_TAILS = [
    "", "一起把目标拆小做实。", "数据会说话，我们让它更好看。",
    "保持反馈闭环，进步自然发生。", "记一笔复盘，下一次就能更快升级。",
    "祝今天也闪闪发光！", "让“可复制的确定性”多一点。"
]

# ========== 自动扩展为 100 条 ==========
RISE_POEMS_100   = _expand_poems(RISE_POEM_SEEDS, RISE_WRAP, wants=100)
STABLE_POEMS_100 = _expand_poems(STABLE_POEM_SEEDS, STABLE_WRAP, wants=100)
FALL_POEMS_100   = _expand_poems(FALL_POEM_SEEDS, FALL_WRAP, wants=100)

RISE_ENCS_100    = _ensure_100(_expand_encourage(RISE_ENC_SEEDS, COMMON_TAILS, wants=100))
STABLE_ENCS_100  = _ensure_100(_expand_encourage(STABLE_ENC_SEEDS, COMMON_TAILS, wants=100))
FALL_ENCS_100    = _ensure_100(_expand_encourage(FALL_ENC_SEEDS, COMMON_TAILS, wants=100))

# ========== 对外暴露的 6 组库（每组 100 条）==========
poem_lines_rise:   List[str] = RISE_POEMS_100
poem_lines_stable: List[str] = STABLE_POEMS_100
poem_lines_fall:   List[str] = FALL_POEMS_100

encourage_lines_rise:   List[str] = RISE_ENCS_100
encourage_lines_stable: List[str] = STABLE_ENCS_100
encourage_lines_fall:   List[str] = FALL_ENCS_100

# ========== 一键组合输出 ==========
def get_encouragement(trend: str = "rise") -> str:
    """
    返回格式：
    「古诗词/翻译/典故句」 + 「鼓励词」
    例如：
    “长风破浪会有时”（Riding winds and breaking waves will come）—— 李白《行路难》。好势头，继续扩大领先！
    """
    t = (trend or "").strip().lower()
    if t not in {"rise", "stable", "fall"}:
        t = "stable"

    if t == "rise":
        poem = random.choice(poem_lines_rise)
        enc  = random.choice(encourage_lines_rise)
    elif t == "fall":
        poem = random.choice(poem_lines_fall)
        enc  = random.choice(encourage_lines_fall)
    else:
        poem = random.choice(poem_lines_stable)
        enc  = random.choice(encourage_lines_stable)

    # 用全角句号连接，便于直接粘到 Markdown 引用块中
    return f"{poem}。{enc}"

__all__ = [
    "get_encouragement",
    "poem_lines_rise", "poem_lines_stable", "poem_lines_fall",
    "encourage_lines_rise", "encourage_lines_stable", "encourage_lines_fall",
]
