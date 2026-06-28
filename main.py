"""
每日股市新闻分析报告生成器 (GitHub Actions 版)
==============================================
每天自动搜索最新国内外财经新闻，调用 AI API 生成结构化分析报告。
运行方式：python main.py [--send-email]
依赖环境变量：AI_API_KEY, AI_API_BASE (可选), AI_MODEL (可选)
邮件发送需要：SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, EMAIL_TO
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
TODAY = datetime.now(TZ).strftime("%Y%m%d")
TODAY_CN = datetime.now(TZ).strftime("%Y年%m月%d日")
TODAY_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][datetime.now(TZ).weekday()]

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

    system_prompt = f"""你是一个专业的股市新闻分析自动化分析师，名为"NewsImpactAnalyzer"。

## 你的核心职责
自动分析当前日期（{TODAY_CN} {TODAY_WEEKDAY}）的国内和国际主要新闻对股市（特别是A股、港股、美股）的潜在影响，并输出结构化分析报告。

## 任务要求
1. **基于你的训练知识**（截至2025年中的知识），结合对当前市场趋势的理解，生成分析报告
2. **区分国内与国际新闻**：对每一条新闻首先判断其属于"国内"还是"国际"维度
3. **评估股市影响**：评估对整体市场情绪、特定板块或个股的短期（1-3天）和中期（1-4周）影响
4. **输出结构化结果**：严格按照下方格式输出

## 重要提示
- 你必须基于你已知的、截至训练数据中的市场信息来分析
- 如果某些具体数据点不确定，请基于合理的市场逻辑推演
- 报告要专业、客观、有深度
- 使用Markdown格式，包含表格、emoji等排版元素
- 日期使用 {TODAY_CN}（{TODAY_WEEKDAY}）
- 不要输出"我的知识截止于..."等声明，直接进行分析

## ⚠️ 数据一致性校验（必须遵守）
**黄金人民币价格计算**：必须使用公式 `人民币/克 = 美元/盎司 × 美元人民币汇率 / 31.1035` 计算，确保与美元计价的价格和涨跌幅一致。
- 例：$4,280/oz × 7.25 / 31.1035 ≈ ¥998/克
- 美元涨跌幅必须与人民币涨跌幅方向一致（差值仅来自汇率波动）
- **禁止编造不合理的价格数据**，如果不确定请标注"估算"

## 输出格式要求
必须包含以下章节：

### 一、市场全景速览 🌐

#### 1. 全球主要指数与资产（数据表格）
必须包含以下行：美股(S&P500/纳斯达克)、A股(上证/创业板)、港股(恒生/恒生科技)、原油(布伦特)、黄金（美元/盎司 + 人民币/克双计价）、汇率(美元/人民币、美元/日元)。

#### 2. 📈 美股风险指标
在市场全景速览下方，紧接着展示美股核心估值风险表格：

| 指标 | 当前值 | 历史均值 | 风险等级 | 解读要点 |
|------|--------|----------|----------|----------|
| 标普500 TTM P/E | ~32.0x | 16.23x | 🔴 极高 | 盈利收益率仅3.1%，均值倍数1.97x |
| 席勒 CAPE | ~41.0x | 17.75x | 🔴 极高 | 历史87%分位，接近互联网泡沫峰值44.2x |
| 股票风险溢价 ERP | ~-1.4% | ~3.0% | 🔴 倒挂 | 股债收益率倒挂，历史罕见 |
| 巴菲特指标 | ~219% | ~100% | 🔴 严重高估 | 远超2000年148%、2007年138% |
| 融资债务/GDP | ~4.1% | 1.5% | 🔴 历史最高 | 杠杆水平创历史新高 |
| 道指/黄金比 | ~14x | 8x | 🟡 偏高 | 股票相对黄金估值偏高 |
| Forward P/E | ~21x | 18.9x | 🟡 偏高 | 基于乐观盈利预测 |
| VIX 恐慌指数 | ~23 | ~15 | 🟡 偏紧 | 市场情绪偏紧张 |

对每个指标的解读要参考以下标准：
- **TTM P/E**: 历史均值16.23x，极值44.20x。突破30x后未来5-10年回报率大幅低于长期均值
- **CAPE**: 席勒10年通胀调整市盈率，均值17.75x。超过30x时未来10年实际回报率接近零
- **ERP**: 股票盈利收益率 - 10Y国债收益率。过去50年出现负值时都在重大调整前夕(1987/2000/2007/2022)
- **巴菲特指标**: 总市值/GDP，巴菲特称为"最佳单一估值指标"。2000年148%、2007年138%
- **融资债务/GDP**: 杠杆驱动上涨的信号。2000/2007/2021见顶后均大幅下跌
- **道指/黄金比**: 跨资产估值标尺。均值8x，1999年顶峰44x
- **VIX**: >30极度恐慌，20-30偏紧，<20平静

然后在美股风险指标表格下方生成一个**估值过热指数**（加权综合评分，0-100），简要说明当前风险水平。

### 二、重大新闻分类与影响分析（国际新闻和国内新闻分开，每条新闻包含：来源、维度、摘要、短期/中期影响评估表格、影响板块/个股）
### 三、综合研判（核心矛盾、国内市场分析、关键观察节点）
### 四、风险提示（含风险等级表格）
### 五、策略建议（短期和中期）
### 六、事件日历（当月重要事件）

## 上一次执行的记忆（参考）
{memory[:3000]}

请现在开始生成 {TODAY_CN} 的分析报告。"""

    user_prompt = f"""请为 {TODAY_CN}（{TODAY_WEEKDAY}）生成一份完整的每日股市新闻分析报告。

你需要：
1. 基于你对当前全球市场趋势的理解，分析今日最重要的10-12条新闻
2. 包含市场数据（指数点位、商品价格等），尽可能准确
3. 区分国际新闻（🌍）和国内新闻（🇨🇳）
4. 每一条新闻都要有详细的影响评估表格和受影响板块/个股
5. 最后给出综合研判、风险提示、策略建议和事件日历

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
        report = f"# 📊 每日股市新闻分析报告\n\n**日期：** {TODAY_CN}（{TODAY_WEEKDAY}）  \n**分析师：** NewsImpactAnalyzer  \n**覆盖市场：** A股 / 港股 / 美股\n\n---\n\n{report}"

    # 确保免责声明存在
    if "免责声明" not in report:
        report += f"\n\n---\n\n> 📝 **免责声明：** 本报告基于公开信息与AI分析生成，不构成投资建议。股市有风险，投资需谨慎。\n\n---\n\n*报告生成时间：{TODAY_CN} (自动化) CST*  \n*下一份报告预计：明日*"

    # 添加生成时间
    if "报告生成时间" not in report:
        report += f"\n\n---\n\n*报告生成时间：{TODAY_CN} (自动化) CST*"

    return report


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
