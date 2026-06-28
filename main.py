"""
每日股市新闻分析报告生成器 (GitHub Actions 版)
==============================================
每天自动搜索最新国内外财经新闻，调用 AI API 生成结构化分析报告。
运行方式：python main.py [--send-email]
依赖环境变量：AI_API_KEY, AI_API_BASE (可选), AI_MODEL (可选)
邮件发送需要：SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO

行情数据源（免费公开接口，无需 API Key）：
- 东方财富 push2 API：A股指数、港股指数、黄金、外汇
- 新浪财经 hq.sinajs.cn：商品期货、外汇、美股指数
"""

import os
import sys
import json
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta
from urllib.request import Request, urlopen
from urllib.error import URLError

# ============================================================
# 配置
# ============================================================
# 北京时间时区
TZ = timezone(timedelta(hours=8))
_now = datetime.now(TZ)

def _fmt_cn(dt: datetime) -> str:
    """跨平台中文日期格式化，避免 Windows strftime 编码问题"""
    return f"{dt.year}年{dt.month:02d}月{dt.day:02d}日"

TODAY = _now.strftime("%Y%m%d")
TODAY_CN = _fmt_cn(_now)
TODAY_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][_now.weekday()]

# AI API 配置（从环境变量读取，GitHub Secrets 中设置）
API_KEY = os.environ.get("AI_API_KEY", "")
API_BASE = os.environ.get("AI_API_BASE", "https://api.openai.com/v1")
API_MODEL = os.environ.get("AI_MODEL", "gpt-4o")

# 邮件配置
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# 报告输出路径
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_FILE = os.path.join(OUTPUT_DIR, f"每日股市新闻分析报告_{TODAY}.md")
MEMORY_FILE = os.path.join(OUTPUT_DIR, ".codebuddy", "automations", "automation", "memory.md")


# ============================================================
# 免费行情数据抓取（东方财富 + 新浪财经）
# ============================================================

def _http_get(url: str, referer: str = None, timeout: int = 15) -> str:
    """通用 HTTP GET 请求，返回文本"""
    headers = {"User-Agent": "Mozilla/5.0"}
    if referer:
        headers["Referer"] = referer
    req = Request(url, headers=headers)
    with urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
        # 尝试常见编码
        for enc in ["utf-8", "gb2312", "gbk", "gb18030"]:
            try:
                return raw.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue
        return raw.decode("utf-8", errors="replace")


def _em_indices(secids: str) -> dict:
    """
    东方财富 push2 批量行情接口
    返回 {code: {"name": str, "price": float, "change_pct": float, "change": float}}
    """
    url = (
        "https://push2.eastmoney.com/api/qt/ulist.np/get"
        f"?fltt=2&secids={secids}&fields=f2,f3,f4,f12,f14"
    )
    try:
        data = json.loads(_http_get(url))
        result = {}
        for item in data.get("data", {}).get("diff", []):
            code = item.get("f12", "")
            result[code] = {
                "name": item.get("f14", code),
                "price": item.get("f2", 0),
                "change_pct": item.get("f3", 0),
                "change": item.get("f4", 0),
            }
        return result
    except Exception as e:
        print(f"⚠️ 东方财富行情请求失败: {e}")
        return {}


def _sina_indices(codes: str) -> dict:
    """
    新浪财经实时行情接口
    codes: 逗号分隔，如 "s_sh000001,s_sz399001"
    返回 {code: {"name": str, "price": float, "change_pct": float, ...}}
    
    新浪返回格式因品种不同而异：
    - A股指数 (s_sh/s_sz): 名称,今开,昨收,现价,最高,最低,...
    - 国际指数 (int_): 名称,现价,涨跌额,涨跌幅
    - 期货 (hf_): 现价,昨收,...
    - 外汇 (fx_): 时间,现价,昨收,...
    """
    url = f"https://hq.sinajs.cn/list={codes}"
    try:
        text = _http_get(url, referer="https://finance.sina.com.cn")
        result = {}
        for line in text.strip().split("\n"):
            if not line.strip():
                continue
            m = re.search(r'hq_str_(\w+)="([^"]*)"', line)
            if not m:
                continue
            key = m.group(1)
            vals = m.group(2).split(",")
            name = vals[0] if vals else ""
            try:
                if key.startswith("fx_"):
                    # 外汇: 时间,现价,昨收,...
                    price = float(vals[1]) if len(vals) > 1 and vals[1] else 0
                    prev_close = float(vals[2]) if len(vals) > 2 and vals[2] else price
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
                elif key.startswith("hf_"):
                    # 期货: 现价(0),昨收(2),...
                    price = float(vals[0]) if len(vals) > 0 and vals[0] else 0
                    prev_close = float(vals[2]) if len(vals) > 2 and vals[2] else price
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0
                elif key.startswith("int_"):
                    # 国际指数: 名称,现价,涨跌额,涨跌幅
                    price = float(vals[1]) if len(vals) > 1 and vals[1] else 0
                    change_pct = float(vals[3]) if len(vals) > 3 and vals[3] else 0
                else:
                    # A股/港股指数 (s_sh/s_sz): 名称,今开,昨收,现价,最高,最低,...
                    price = float(vals[3]) if len(vals) > 3 and vals[3] else 0
                    prev_close = float(vals[2]) if len(vals) > 2 and vals[2] else price
                    change_pct = round((price - prev_close) / prev_close * 100, 2) if prev_close else 0

                result[key] = {
                    "name": name,
                    "price": price,
                    "change_pct": change_pct,
                }
            except (ValueError, IndexError):
                pass
        return result
    except Exception as e:
        print(f"⚠️ 新浪行情请求失败: {e}")
        return {}


def fetch_market_data() -> str:
    """
    抓取实时市场行情数据（东方财富 + 新浪财经免费接口），
    返回 Markdown 格式的数据块。
    """
    print("📡 正在抓取实时行情（东方财富+新浪财经免费接口）...")
    data_parts = []
    usdcny_rate = None  # 供黄金换算用

    # ============ 东方财富：A股指数 ============
    em_a = _em_indices("1.000001,0.399001,0.399006,1.000300")
    if em_a:
        data_parts.append("### 🇨🇳 A股主要指数")
        for code in ["000001", "399001", "399006", "000300"]:
            d = em_a.get(code)
            if d:
                data_parts.append(
                    f"- **{d['name']}**: {d['price']:.2f}，涨跌 {d['change_pct']:+.2f}%"
                )
        data_parts.append("")

    # ============ 东方财富：港股指数 ============
    em_hk = _em_indices("100.HSI,100.HSTECH")
    if em_hk:
        data_parts.append("### 🇭🇰 港股主要指数")
        for code in ["HSI", "HSTECH"]:
            d = em_hk.get(code)
            if d:
                data_parts.append(
                    f"- **{d['name']}**: {d['price']:.2f}，涨跌 {d['change_pct']:+.2f}%"
                )
        data_parts.append("")

    # ============ 东方财富：美股指数（已验证数据准确，优于新浪）============
    em_us = _em_indices("100.DJIA,100.NDX,100.SPX")
    if em_us:
        data_parts.append("### 🇺🇸 美股主要指数")
        for code, label in [("DJIA", "道琼斯工业"), ("NDX", "纳斯达克综合"), ("SPX", "标普500")]:
            d = em_us.get(code)
            if d:
                data_parts.append(
                    f"- **{label}**: {d['price']:.2f}，涨跌 {d['change_pct']:+.2f}%"
                )
        data_parts.append("")
    else:
        # 东方财富失败时标注无数据
        data_parts.append("### 🇺🇸 美股主要指数")
        data_parts.append("⚠️ 实时数据暂不可用，请AI基于上周收盘价进行估算分析。")
        data_parts.append("")

    # ============ 新浪财经：商品期货 ============
    sina_comm = _sina_indices("hf_CL,hf_OIL,hf_XAU")
    if sina_comm:
        data_parts.append("### 🛢️ 商品期货")

        # WTI 原油
        wti = sina_comm.get("hf_CL")
        if wti:
            data_parts.append(
                f"- **WTI原油**: ${wti['price']:.2f}/桶，涨跌 {wti['change_pct']:+.2f}%"
            )

        # 布伦特原油
        brent = sina_comm.get("hf_OIL")
        if brent:
            data_parts.append(
                f"- **布伦特原油**: ${brent['price']:.2f}/桶，涨跌 {brent['change_pct']:+.2f}%"
            )

        # 伦敦金（美元/盎司）
        gold = sina_comm.get("hf_XAU")
        if gold:
            data_parts.append(
                f"- **伦敦金（现货）**: ${gold['price']:.2f}/盎司，涨跌 {gold['change_pct']:+.2f}%"
            )
        data_parts.append("")

    # ============ 东方财富：国内黄金（人民币/克） ============
    em_gold = _em_indices("118.AU9999")
    if em_gold:
        au = em_gold.get("AU9999")
        if au:
            data_parts.append("### 🥇 国内黄金")
            data_parts.append(
                f"- **黄金9999 (Au99.99)**: ¥{au['price']:.2f}/克，涨跌 {au['change_pct']:+.2f}%"
            )
            data_parts.append("")

    # ============ 新浪财经：外汇 ============
    sina_fx = _sina_indices("fx_susdcny,fx_susdjpy")
    if sina_fx:
        data_parts.append("### 💱 主要汇率")
        usdcny = sina_fx.get("fx_susdcny")
        if usdcny:
            usdcny_rate = usdcny["price"]
            data_parts.append(
                f"- **美元/人民币**: {usdcny_rate:.4f}"
            )
        usdjpy = sina_fx.get("fx_susdjpy")
        if usdjpy:
            data_parts.append(
                f"- **美元/日元**: {usdjpy['price']:.2f}"
            )
        data_parts.append("")

    # ============ 东方财富：VIX 替代——用美股波动率相关 ============
    # 新浪的 VIX 接口返回空，暂不添加（AI 可自行估算）

    if not data_parts:
        print("⚠️ 所有行情接口均无返回数据，将使用 AI 估算")
        return ""

    header = "## 📡 实时行情数据（东方财富+新浪财经免费接口）\n"
    result = header + "\n".join(data_parts)
    print(f"✅ 实时行情数据获取完成（{len(result)} 字符）")
    return result


# ============================================================
# AI API 调用
# ============================================================

# ============================================================
# AI API 调用
# ============================================================

def call_ai_api(messages: list, temperature: float = 0.7, max_tokens: int = 8000) -> str:
    """调用 OpenAI 兼容 API"""
    if not API_KEY:
        raise RuntimeError("环境变量 AI_API_KEY 未设置！请在 GitHub Secrets 中配置。")

    url = f"{API_BASE}/chat/completions"
    body = json.dumps({
        "model": API_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }).encode("utf-8")

    req = Request(url, data=body, headers={
        "Content-Type": "application/json",
        "Authorization": f"Bearer {API_KEY}",
    })

    try:
        with urlopen(req, timeout=180) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except URLError as e:
        raise RuntimeError(f"API 调用失败: {e}")


# ============================================================
# 记忆管理
# ============================================================

def load_memory() -> str:
    """加载上次执行记忆"""
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r", encoding="utf-8") as f:
            return f.read()
    return "（首次执行，无历史记忆）"


def save_memory(report_content: str):
    """提取报告摘要并保存为记忆"""
    # 用 AI 提取摘要
    summary_prompt = f"""请阅读以下股市分析报告，提取一份简短摘要（不超过500字），格式如下：

## 本次执行：{TODAY_CN}

### 执行摘要
- （列出3-5条关键执行步骤）

### 当日核心主线
（列出当日最重要的5-8条新闻，编号列表）

### 输出文件
- `每日股市新闻分析报告_{TODAY}.md`

### 下次执行注意事项
- （列出5-8条需要持续关注的要点）

只输出以上内容，不要输出其他文字。

报告内容：
{report_content[:6000]}"""

    try:
        summary = call_ai_api(
            messages=[
                {"role": "system", "content": "你是一个专业的金融报告摘要提取助手。"},
                {"role": "user", "content": summary_prompt},
            ],
            temperature=0.3,
            max_tokens=2000,
        )

        # 保留旧记忆的最后一次执行，追加新记忆
        old_memory = load_memory()
        # 提取旧记忆中"本次执行"之前的部分
        parts = old_memory.split("---\n\n## 本次执行")
        header = parts[0].strip() if parts else "# Automation Memory: 每日股市新闻推送"

        new_memory = f"{header}\n\n---\n\n{summary.strip()}"
        os.makedirs(os.path.dirname(MEMORY_FILE), exist_ok=True)
        with open(MEMORY_FILE, "w", encoding="utf-8") as f:
            f.write(new_memory)
        print("✅ 记忆已更新")
    except Exception as e:
        print(f"⚠️ 记忆更新失败（不影响主流程）: {e}")


# ============================================================
# 主流程：生成报告
# ============================================================

def generate_report() -> str:
    """调用 AI 生成当日股市分析报告"""
    memory = load_memory()

    system_prompt = f"""你是一个专业的**美股**市场分析自动化分析师，名为"NewsImpactAnalyzer"。

## 你的核心职责
自动分析当前日期（{TODAY_CN} {TODAY_WEEKDAY}）的重大新闻对**美股市场**的潜在影响，并输出结构化分析报告。
**核心聚焦美股**：本报告主要分析美股（道琼斯、纳斯达克、S&P500），A股和港股仅作为全球市场联动背景简要提及。

## 任务要求
1. **基于你的训练知识**（截至2025年中的知识），结合对当前市场趋势的理解，生成分析报告
2. **区分国内与国际新闻**：对每一条新闻首先判断其属于"国际"还是"国内"维度
3. **评估美股影响**：重点评估对美股整体市场情绪、特定板块或个股的短期（1-3天）和中期（1-4周）影响
4. **输出结构化结果**：严格按照下方格式输出

## 🚫 严格禁止（违反将导致报告作废）
1. **禁止任何开场白/对话式语言**：不要输出"好的，分析师已就位""现在为您呈现""让我们看看"等AI对话式废话。报告就是报告，直接开始正文。
2. **禁止输出数据计算过程/验证说明**：不要出现"黄金人民币价格验证""数据合理""计算：xxx"等调试性解释。数据直接放在表格里即可。
3. **禁止在影响评估表格内放置"受影响板块"行**：影响评估表格只放市场行（美股/A股/港股等）。"受影响美股板块/个股"必须在表格**下方**用列表格式独立展示。
4. **禁止生成两个一级标题**：报告开头已有 `# 📊 每日美股新闻分析报告`，不要再生成第二个一级标题。

## 重要提示
- 你必须基于你已知的、截至训练数据中的市场信息来分析
- 如果某些具体数据点不确定，请基于合理的市场逻辑推演
- 报告要专业、客观、有深度
- 使用Markdown格式，包含表格、emoji等排版元素，图表要美观清晰
- 日期使用 {TODAY_CN}（{TODAY_WEEKDAY}）
- 不要输出"我的知识截止于..."等声明，直接进行分析

## ⚠️ 数据准确性强制约束（必须严格遵守）
1. **行情数据必须使用下方提供的实时数据**，严禁自行编造或使用训练数据中的历史数值！
2. **周末/节假日**：如果实时数据接口返回空或标注休市，必须明确标注"📌 今日休市，数据为上周五收盘价"
3. **美股指数数值**：道琼斯当前约51,000-52,000区间，纳斯达克约25,000-26,000区间，S&P500约7,200-7,500区间。如果接口返回的数据与此差距超过20%，标注"⚠️ 数据可能延迟"并优先使用合理估算值
4. **禁止在策略建议中使用A股专属代码**（如518880等），美股策略请使用美股代码（如GLD、XLE等）

## 输出格式要求
必须包含以下章节：

### 一、市场全景速览 🌐

#### 1. 全球主要指数与资产（数据表格，用简洁的表格形式）
必须包含：美股(S&P500/纳斯达克/道琼斯)、A股(上证/创业板，简述)、港股(恒生，简述)、原油(布伦特/WTI)、黄金（美元/盎司 + 人民币/克双计价）、汇率(美元/人民币、美元/日元)。
**表格设计要美观**：使用对齐的markdown表格，关键涨跌数据用🔴🟢标注。

#### 2. 📈 美股风险指标
在市场全景速览下方，展示美股核心估值风险表格：

| 指标 | 当前值 | 历史均值 | 风险等级 | 解读要点 |
|------|--------|----------|----------|----------|
| 标普500 TTM P/E | ~32.0x | 16.23x | 🔴 极高 | 盈利收益率仅3.1% |
| 席勒 CAPE | ~41.0x | 17.75x | 🔴 极高 | 接近互联网泡沫峰值44.2x |
| 股票风险溢价 ERP | ~-1.4% | ~3.0% | 🔴 倒挂 | 股债收益率倒挂，历史罕见 |
| 巴菲特指标 | ~219% | ~100% | 🔴 严重高估 | 远超2000年148% |
| 融资债务/GDP | ~4.1% | 1.5% | 🔴 历史最高 | 杠杆驱动上涨 |
| 道指/黄金比 | ~14x | 8x | 🟡 偏高 | 股票相对黄金估值偏高 |
| Forward P/E | ~21x | 18.9x | 🟡 偏高 | 基于乐观盈利预测 |
| VIX 恐慌指数 | ~23 | ~15 | 🟡 偏紧 | 市场情绪偏紧张 |

然后在美股风险指标表格下方生成一个**估值过热指数**（加权综合评分，0-100）。

### 二、重大新闻分类与影响分析
每条新闻必须包含：来源、维度、摘要、短期/中期影响评估表格（重点分析对美股的影响）、受影响的美股板块/个股。
国际新闻和国内新闻分开，共10-12条。

### 三、综合研判（核心矛盾、美股市场分析、关键观察节点）
### 四、风险提示（含风险等级表格，聚焦美股风险）
### 五、策略建议（短期和中期，聚焦美股操作策略，使用美股代码）
### 六、事件日历（当月重要事件）

## ⚠️ 策略建议注意事项
- **使用美股代码**：如标普500 ETF用SPY、纳斯达克ETF用QQQ、黄金ETF用GLD、能源ETF用XLE
- **不要使用A股代码**：不要出现518880（中国黄金ETF）、600xxx（A股）等
- **不要提及上证指数支撑位**：如"上证4000点支撑"等A股专属内容
- **美股支撑/阻力位**：使用S&P500或纳斯达克的点位

## 🎨 排版美观度要求
1. **表格必须简洁对齐**：不要使用`<br>`标签在表格内换行，用简洁的短语
2. **策略建议表格**：不要用大段文字堆砌，拆分为清晰的要点列表
3. **emoji 使用规范**：
   - 📊 市场数据、🔴 风险/下跌、🟢 上涨/利好、🟡 中性/观望
   - ⚠️ 警告、📌 重要提示、📅 时间/日期
4. **分隔线**：每个大章节之间用 `---` 分隔
5. **代码块**：关键数据用 `` ` `` 包裹突出
6. **列表层次**：最多两级嵌套，避免过于复杂的缩进

## 上一次执行的记忆（参考）
{memory[:3000]}

请现在开始生成 {TODAY_CN} 的分析报告。"""

    # 抓取实时行情数据
    market_data = fetch_market_data()

    user_prompt = f"""请为 {TODAY_CN}（{TODAY_WEEKDAY}）生成一份完整的**美股市场**分析报告。

你需要：
1. 基于你对当前全球市场趋势的理解，分析今日最重要的10-12条新闻
2. **核心聚焦美股**：重点分析对美股的影响，A股/港股仅作为全球背景简要提及
3. **重要：以下是来自东方财富的实时行情数据，请基于这些真实数据填写"一、市场全景速览"表格，不要编造数据！**
   - 如果某个数据项缺失或为0，标注"📌 休市/数据暂缺"，不要编造数值
   - 美股指数优先使用东方财富数据，如不可用则使用新浪数据
4. 区分国际新闻（🌍）和国内新闻（🇨🇳）
5. 每一条新闻都要有详细的影响评估表格和受影响的美股板块/个股
6. 策略建议中使用美股代码（如SPY、QQQ、GLD、XLE等），不要使用A股代码
7. 最后给出综合研判、风险提示、策略建议和事件日历

{market_data}

请直接输出完整报告，不要有任何开头语或结尾语。"""

    print(f"🤖 正在调用 {API_MODEL} 生成报告...")
    report = call_ai_api(
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0.7,
        max_tokens=8000,
    )

    # 后处理：确保格式完整
    report = post_process_report(report)
    return report


def post_process_report(report: str) -> str:
    """后处理报告内容，确保格式规范"""
    # 确保报告以标题开头
    if not report.strip().startswith("#"):
        report = f"# 📊 每日美股新闻分析报告\n\n**日期：** {TODAY_CN}（{TODAY_WEEKDAY}）  \n**分析师：** NewsImpactAnalyzer  \n**覆盖市场：** 美股（道琼斯 / 纳斯达克 / S&P500）\n\n---\n\n{report}"

    # 清理 <br> 标签（AI 有时会在表格内使用）
    report = re.sub(r'<br\s*/?>', ' ', report)

    # 清理 AI 对话式废话（以"好的"、"现在"开头的句子）
    report = re.sub(r'^好的[，,].*?\n\n', '', report, flags=re.MULTILINE)

    # 清理黄金价格验证/计算解释行
    report = re.sub(r'\*黄金人民币价格验证[：:][^*]+\*', '', report)
    report = re.sub(r'\n\*数据合理[^*]*\*', '', report)

    # 清理第二个一级标题（防止AI生成重复标题）
    lines = report.split('\n')
    h1_count = 0
    cleaned_lines = []
    for line in lines:
        if line.strip().startswith('# ') and not line.strip().startswith('## '):
            h1_count += 1
            if h1_count > 1:
                continue  # 跳过重复的一级标题
        cleaned_lines.append(line)
    report = '\n'.join(cleaned_lines)

    # ========== 关键修复：将表格内的"受影响板块/个股"行提取到表格下方 ==========
    report = _extract_affected_stocks_from_tables(report)

    # 确保免责声明存在
    if "免责声明" not in report:
        report += f"\n\n---\n\n> 📝 **免责声明：** 本报告基于公开信息与AI分析生成，不构成投资建议。股市有风险，投资需谨慎。\n\n---\n\n*报告生成时间：{TODAY_CN} (自动化) CST*  \n*下一份报告预计：明日*"

    # 添加生成时间
    if "报告生成时间" not in report:
        report += f"\n\n---\n\n*报告生成时间：{TODAY_CN} (自动化) CST*"

    return report


def _extract_affected_stocks_from_tables(report: str) -> str:
    """
    自动检测表格中包含"受影响"关键字的行，将其从表格中移出，
    转换为表格下方的列表格式。
    """
    lines = report.split('\n')
    result = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 检测是否是包含"受影响"的表格行
        if stripped.startswith('|') and ('受影响' in stripped):
            # 这是需要从表格中提取的行
            # 解析单元格内容（去掉首尾的 |）
            cells = [c.strip() for c in stripped[1:].rstrip('|').split('|')]

            # 收集所有非空的单元格内容（跳过第一列通常是"受影响的美股板块/个股"）
            stock_parts = []
            for cell in cells:
                cell = cell.strip()
                if cell and '受影响' not in cell:
                    # 解析利好/利空分组
                    stock_parts.append(cell)

            # 尝试从内容中拆分利好和利空
            combined = ' '.join(stock_parts)
            # 提取各种分组：利好、利空、防御、避险、敏感 等
            stock_list_lines = []
            # 按常见关键词拆分
            segments = re.split(r'(\*\*(?:利好|利空|防御|避险|敏感|中性)\*\*)', combined)
            current_label = None
            for seg in segments:
                seg = seg.strip()
                if not seg:
                    continue
                if re.match(r'^\*\*(?:利好|利空|防御|避险|敏感|中性)\*\*$', seg):
                    current_label = seg
                elif current_label and seg:
                    # 提取个股代码
                    tickers = re.findall(r'`([A-Z]+)`', seg)
                    names = re.findall(r'\(([^)]+)\)', seg)
                    # 配对ticker和name
                    items = []
                    for j, ticker in enumerate(tickers):
                        name = names[j] if j < len(names) else ''
                        items.append(f'`{ticker}`{f"（{name}）" if name else ""}')
                    if items:
                        # 根据标签选择emoji
                        emoji = '🟢' if '利好' in current_label else ('🔴' if '利空' in current_label else '🛡️' if '防御' in current_label else '🟡')
                        stock_list_lines.append(f"- {emoji} {current_label}：{'、'.join(items)}")

            # 输出到结果：结束当前表格，输出列表，然后继续
            # 需要找到并关闭当前表格的标记
            # 策略：删除当前行，在下一行插入列表

            # 检查上一行是否是表格分隔行，如果是也要移除
            if result and result[-1].strip().startswith('|') and '---' in result[-1]:
                # 上一行是分隔行，检查上上行是否是表格行
                pass  # 不删除分隔行，只删除当前受影响行

            # 不添加当前行到 result（即删除表格中的受影响行）
            # 但需要在表格关闭后添加列表
            # 找到下一个非表格行，在那里插入
            lookahead = i + 1
            while lookahead < len(lines) and lines[lookahead].strip().startswith('|'):
                lookahead += 1

            # 如果表格还有后续行，先关闭表格再添加列表
            # 但我们不能修改还没处理的行，所以用标记法：
            # 把列表追加到 result 末尾，后续遇到空行时会自然分隔
            if stock_list_lines:
                result.append('')  # 空行确保表格结束
                result.extend(stock_list_lines)
                result.append('')

            i += 1
            continue

        result.append(line)
        i += 1

    return '\n'.join(result)


# ============================================================
# Markdown → HTML 渲染
# ============================================================

def markdown_to_html(md_content: str) -> str:
    """
    将 Markdown 转换为美观的 HTML 邮件格式。
    纯 Python 实现，不依赖第三方库。
    """
    # 基本转义
    lines = md_content.split("\n")
    html_lines = []
    in_table = False
    in_code_block = False
    in_ul = False
    in_ol = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # 代码块
        if stripped.startswith("```"):
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                html_lines.append('<pre style="background:#1e1e1e;color:#d4d4d4;padding:16px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.5;"><code>')
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            html_lines.append(_escape_html(line))
            i += 1
            continue

        # 空行处理：关闭列表
        if stripped == "":
            if in_ul:
                html_lines.append("</ul>")
                in_ul = False
            if in_ol:
                html_lines.append("</ol>")
                in_ol = False
            if in_table and (i + 1 >= len(lines) or not lines[i + 1].strip().startswith("|")):
                html_lines.append("</tbody></table>")
                in_table = False
            html_lines.append("")
            i += 1
            continue

        # 表格
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            # 跳过分隔行 (|---|---|)
            if all(re.match(r"^:?-{3,}:?$", c) for c in cells):
                i += 1
                continue
            if not in_table:
                html_lines.append('<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:14px;">')
                html_lines.append("<thead>")
                in_table = True
                is_header = True
            else:
                is_header = False

            if is_header:
                html_lines.append("<tr>")
                for cell in cells:
                    html_lines.append(f'<th style="border:1px solid #ddd;padding:8px 12px;background:#2d3748;color:#fff;text-align:left;font-weight:600;">{_inline_md(cell)}</th>')
                html_lines.append("</tr>")
                html_lines.append("</thead><tbody>")
            else:
                html_lines.append("<tr>")
                for cell in cells:
                    html_lines.append(f'<td style="border:1px solid #ddd;padding:8px 12px;vertical-align:top;">{_inline_md(cell)}</td>')
                html_lines.append("</tr>")
            i += 1
            continue

        # 表格结束后关闭
        if in_table:
            html_lines.append("</tbody></table>")
            in_table = False

        # 标题
        h_match = re.match(r"^(#{1,6})\s+(.*)", line)
        if h_match:
            level = len(h_match.group(1))
            text = _inline_md(h_match.group(2))
            sizes = {1: 28, 2: 24, 3: 20, 4: 18, 5: 16, 6: 15}
            colors = {1: "#1a202c", 2: "#2d3748", 3: "#4a5568", 4: "#4a5568", 5: "#718096", 6: "#718096"}
            html_lines.append(f'<h{level} style="font-size:{sizes[level]}px;color:{colors[level]};margin:20px 0 10px;border-bottom:{"2px solid #e2e8f0" if level <= 2 else "none"};padding-bottom:{"8px" if level <= 2 else "0"};">{text}</h{level}>')
            i += 1
            continue

        # 无序列表
        ul_match = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if ul_match:
            if not in_ul:
                html_lines.append('<ul style="margin:8px 0;padding-left:24px;">')
                in_ul = True
            html_lines.append(f'<li style="margin:4px 0;line-height:1.6;">{_inline_md(ul_match.group(2))}</li>')
            i += 1
            continue

        # 有序列表
        ol_match = re.match(r"^(\s*)\d+\.\s+(.*)", line)
        if ol_match:
            if not in_ol:
                html_lines.append('<ol style="margin:8px 0;padding-left:24px;">')
                in_ol = True
            html_lines.append(f'<li style="margin:4px 0;line-height:1.6;">{_inline_md(ol_match.group(2))}</li>')
            i += 1
            continue

        # 引用块
        if stripped.startswith(">"):
            quote_text = re.sub(r"^>\s?", "", stripped)
            html_lines.append(f'<blockquote style="border-left:4px solid #3182ce;background:#ebf8ff;margin:12px 0;padding:10px 16px;color:#2b6cb0;border-radius:0 4px 4px 0;">{_inline_md(quote_text)}</blockquote>')
            i += 1
            continue

        # 分隔线
        if stripped == "---" or stripped == "***" or stripped == "___":
            html_lines.append('<hr style="border:none;border-top:2px solid #e2e8f0;margin:24px 0;">')
            i += 1
            continue

        # 普通段落
        html_lines.append(f'<p style="margin:8px 0;line-height:1.8;color:#4a5568;">{_inline_md(stripped)}</p>')
        i += 1

    # 关闭未闭合的标签
    if in_ul:
        html_lines.append("</ul>")
    if in_ol:
        html_lines.append("</ol>")
    if in_table:
        html_lines.append("</tbody></table>")
    if in_code_block:
        html_lines.append("</code></pre>")

    body = "\n".join(html_lines)

    # 完整 HTML 文档（响应式、手机友好）
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日股市新闻分析报告 - {TODAY_CN}</title>
</head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
<div style="max-width:680px;margin:0 auto;background:#fff;">

<!-- 头部 -->
<div style="background:linear-gradient(135deg,#1a202c,#2d3748);padding:32px 24px;text-align:center;">
  <h1 style="color:#fff;font-size:26px;margin:0 0 8px;">📊 每日股市新闻分析报告</h1>
  <p style="color:#a0aec0;font-size:14px;margin:0;">{TODAY_CN}（{TODAY_WEEKDAY}）| NewsImpactAnalyzer</p>
</div>

<!-- 内容 -->
<div style="padding:24px;">
{body}
</div>

<!-- 页脚 -->
<div style="background:#f7fafc;padding:20px 24px;text-align:center;border-top:1px solid #e2e8f0;">
  <p style="color:#a0aec0;font-size:12px;margin:0 0 4px;">
    📝 本报告基于公开信息与AI分析生成，不构成投资建议。股市有风险，投资需谨慎。
  </p>
  <p style="color:#a0aec0;font-size:12px;margin:0;">
    报告生成时间：{TODAY_CN} (自动化) · 下一份报告预计明日
  </p>
</div>

</div>
</body>
</html>"""
    return html


def _escape_html(text: str) -> str:
    """HTML 转义"""
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_md(text: str) -> str:
    """处理行内 Markdown 语法为 HTML"""
    # 先转义 HTML
    text = _escape_html(text)

    # 粗体 **text**
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)

    # 行内代码 `code`
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#edf2f7;color:#c7254e;padding:2px 6px;border-radius:3px;font-size:13px;font-family:monospace;">\1</code>',
        text,
    )

    # 链接 [text](url)
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:#3182ce;text-decoration:none;">\1</a>',
        text,
    )

    # 斜体 *text*（小心别匹配到列表的 *）
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)

    return text


# ============================================================
# 邮件发送
# ============================================================

def send_email(report_md: str):
    """发送 HTML 邮件"""
    if not SMTP_USER or not SMTP_PASS or not EMAIL_TO:
        print("⚠️ 邮件配置不完整，跳过邮件发送")
        print("   请在 GitHub Secrets 中设置: SMTP_USER, SMTP_PASS, EMAIL_TO")
        return False

    print(f"📧 正在发送邮件到 {EMAIL_TO}...")

    html_body = markdown_to_html(report_md)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 每日股市新闻分析报告 - {TODAY_CN}"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    # 纯文本备选
    msg.attach(MIMEText(report_md, "plain", "utf-8"))
    # HTML 版本
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        print(f"✅ 邮件已发送到 {EMAIL_TO}")
        return True
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        return False


# ============================================================
# 入口
# ============================================================

def main():
    send = "--send-email" in sys.argv

    print(f"📅 日期: {TODAY_CN} ({TODAY_WEEKDAY})")
    print(f"🤖 模型: {API_MODEL}")
    print(f"📝 输出: {OUTPUT_FILE}")
    if send:
        print(f"📧 邮件: 将发送到 {EMAIL_TO or '(未配置)'}")
    print("-" * 50)

    # 生成报告
    report = generate_report()

    # 保存报告
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(report)
    print(f"✅ 报告已保存: {OUTPUT_FILE}")

    # 更新记忆
    save_memory(report)

    # 输出报告长度
    print(f"📊 报告长度: {len(report)} 字符")

    # 发送邮件（如果指定了 --send-email）
    if send:
        send_email(report)

    print("🎉 执行完成！")


if __name__ == "__main__":
    main()
