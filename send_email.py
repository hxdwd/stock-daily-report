"""
邮件发送脚本（GitHub Actions 版）
==============================
读取 main.py 生成的 Markdown 报告，转换为 HTML 并发送邮件。
不依赖 AI API，只使用邮件配置。
"""

import os
import sys
import re
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timezone, timedelta

# 北京时间
TZ = timezone(timedelta(hours=8))
_now = datetime.now(TZ)

def _fmt_cn(dt: datetime) -> str:
    """跨平台中文日期格式化，避免 Windows strftime 编码问题"""
    return f"{dt.year}年{dt.month:02d}月{dt.day:02d}日"

TODAY = _now.strftime("%Y%m%d")
TODAY_CN = _fmt_cn(_now)
TODAY_WEEKDAY = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][_now.weekday()]

# 邮件配置
SMTP_HOST = os.environ.get("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))
SMTP_USER = os.environ.get("SMTP_USER", "")
SMTP_PASS = os.environ.get("SMTP_PASS", "")
EMAIL_TO = os.environ.get("EMAIL_TO", "")

# 报告文件路径
OUTPUT_DIR = os.path.dirname(os.path.abspath(__file__))
REPORT_FILE = os.path.join(OUTPUT_DIR, f"每日股市新闻分析报告_{TODAY}.md")


# ============================================================
# Markdown → HTML（与 main.py 中相同的渲染逻辑）
# ============================================================

def _is_table_separator(cells: list) -> bool:
    """判断是否是 Markdown 表格的分隔行（如 |---|---| 或 |:---:|:---|）"""
    return all(re.match(r"^:?-{3,}:?$", c) for c in cells)


def _render_table_block(rows: list, html_lines: list):
    """将收集到的表格行渲染为 HTML 表格"""
    if len(rows) < 2:
        return  # 至少需要表头+分隔行+一行数据
    header_cells = rows[0]
    # 跳过可能存在的多余分隔行
    data_start = 1
    if data_start < len(rows) and _is_table_separator(rows[data_start]):
        data_start += 1
    data_rows = rows[data_start:]

    # 计算列数
    col_count = len(header_cells)

    html_lines.append(
        '<table style="border-collapse:collapse;width:100%;margin:12px 0;font-size:14px;'
        'table-layout:auto;word-break:break-word;">'
    )
    html_lines.append("<thead>")
    html_lines.append("<tr>")
    for cell in header_cells:
        html_lines.append(
            f'<th style="border:1px solid #ddd;padding:8px 10px;'
            f'background:#2d3748;color:#fff;text-align:left;font-weight:600;'
            f'white-space:nowrap;">{_inline_md(cell)}</th>'
        )
    html_lines.append("</tr>")
    html_lines.append("</thead><tbody>")

    for row in data_rows:
        # 跳过空行或非表格行
        if not row or all(c == "" for c in row):
            continue
        # 确保列数一致（补齐或截断）
        while len(row) < col_count:
            row.append("")
        row = row[:col_count]
        html_lines.append("<tr>")
        for cell in row:
            html_lines.append(
                f'<td style="border:1px solid #ddd;padding:8px 10px;'
                f'vertical-align:top;">{_inline_md(cell)}</td>'
            )
        html_lines.append("</tr>")

    html_lines.append("</tbody></table>")


def markdown_to_html(md_content: str) -> str:
    lines = md_content.split("\n")
    html_lines = []
    in_code_block = False
    in_ul = False
    in_ol = False
    # 表格状态机：收集连续表格行，遇到非表格行时统一渲染
    table_rows = []  # 收集表格的所有行（每行是 cell 列表）

    def _flush_table():
        """渲染并清空当前收集的表格行"""
        nonlocal table_rows
        if table_rows:
            _render_table_block(table_rows, html_lines)
            table_rows = []

    def _flush_inline():
        """关闭所有行内状态（列表等）"""
        nonlocal in_ul, in_ol
        if in_ul:
            html_lines.append("</ul>")
            in_ul = False
        if in_ol:
            html_lines.append("</ol>")
            in_ol = False

    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()

        # --- 代码块 ---
        if stripped.startswith("```"):
            _flush_table()
            _flush_inline()
            if in_code_block:
                html_lines.append("</code></pre>")
                in_code_block = False
            else:
                html_lines.append(
                    '<pre style="background:#1e1e1e;color:#d4d4d4;padding:16px;'
                    'border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.5;">'
                    '<code>'
                )
                in_code_block = True
            i += 1
            continue

        if in_code_block:
            html_lines.append(_escape_html(line))
            i += 1
            continue

        # --- 表格行检测 ---
        if stripped.startswith("|") and stripped.endswith("|"):
            cells = [c.strip() for c in stripped[1:-1].split("|")]
            # 先关闭列表状态
            _flush_inline()
            table_rows.append(cells)
            i += 1
            continue

        # --- 非表格行：先 flush 表格 ---
        _flush_table()

        # --- 空行 ---
        if stripped == "":
            _flush_inline()
            html_lines.append("")
            i += 1
            continue

        # --- 标题 ---
        h_match = re.match(r"^(#{1,6})\s+(.*)", line)
        if h_match:
            _flush_inline()
            level = len(h_match.group(1))
            text = _inline_md(h_match.group(2))
            sizes = {1: 28, 2: 24, 3: 20, 4: 18, 5: 16, 6: 15}
            colors = {1: "#1a202c", 2: "#2d3748", 3: "#4a5568", 4: "#4a5568", 5: "#718096", 6: "#718096"}
            border = "2px solid #e2e8f0" if level <= 2 else "none"
            pad = "8px" if level <= 2 else "0"
            html_lines.append(
                f'<h{level} style="font-size:{sizes[level]}px;color:{colors[level]};'
                f'margin:20px 0 10px;border-bottom:{border};padding-bottom:{pad};">'
                f'{text}</h{level}>'
            )
            i += 1
            continue

        # --- 无序列表 ---
        ul_match = re.match(r"^(\s*)[-*+]\s+(.*)", line)
        if ul_match:
            if not in_ul:
                html_lines.append('<ul style="margin:8px 0;padding-left:24px;">')
                in_ul = True
            html_lines.append(
                f'<li style="margin:4px 0;line-height:1.6;">'
                f'{_inline_md(ul_match.group(2))}</li>'
            )
            i += 1
            continue

        # --- 有序列表 ---
        ol_match = re.match(r"^(\s*)\d+\.\s+(.*)", line)
        if ol_match:
            if not in_ol:
                html_lines.append('<ol style="margin:8px 0;padding-left:24px;">')
                in_ol = True
            html_lines.append(
                f'<li style="margin:4px 0;line-height:1.6;">'
                f'{_inline_md(ol_match.group(2))}</li>'
            )
            i += 1
            continue

        # --- 引用块 ---
        if stripped.startswith(">"):
            quote_text = re.sub(r"^>\s?", "", stripped)
            html_lines.append(
                f'<blockquote style="border-left:4px solid #3182ce;background:#ebf8ff;'
                f'margin:12px 0;padding:10px 16px;color:#2b6cb0;border-radius:0 4px 4px 0;">'
                f'{_inline_md(quote_text)}</blockquote>'
            )
            i += 1
            continue

        # --- 分隔线 ---
        if stripped in ("---", "***", "___"):
            html_lines.append(
                '<hr style="border:none;border-top:2px solid #e2e8f0;margin:24px 0;">'
            )
            i += 1
            continue

        # --- 普通段落 ---
        html_lines.append(
            f'<p style="margin:8px 0;line-height:1.8;color:#4a5568;">'
            f'{_inline_md(stripped)}</p>'
        )
        i += 1

    # 收尾：flush 所有未关闭的状态
    _flush_table()
    _flush_inline()
    if in_code_block:
        html_lines.append("</code></pre>")

    body = "\n".join(html_lines)

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>每日股市新闻分析报告 - {TODAY_CN}</title>
</head>
<body style="margin:0;padding:0;background:#f7fafc;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif;">
<div style="max-width:680px;margin:0 auto;background:#fff;">
<div style="background:linear-gradient(135deg,#1a202c,#2d3748);padding:32px 24px;text-align:center;">
  <h1 style="color:#fff;font-size:26px;margin:0 0 8px;">📊 每日股市新闻分析报告</h1>
  <p style="color:#a0aec0;font-size:14px;margin:0;">{TODAY_CN}（{TODAY_WEEKDAY}）| NewsImpactAnalyzer</p>
</div>
<div style="padding:24px;">
{body}
</div>
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


def _escape_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _inline_md(text: str) -> str:
    text = _escape_html(text)
    text = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(
        r"`([^`]+)`",
        r'<code style="background:#edf2f7;color:#c7254e;padding:2px 6px;'
        r'border-radius:3px;font-size:13px;font-family:monospace;">\1</code>',
        text,
    )
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2" style="color:#3182ce;text-decoration:none;">\1</a>',
        text,
    )
    text = re.sub(r"(?<!\*)\*([^*\n]+)\*(?!\*)", r"<em>\1</em>", text)
    return text


# ============================================================
# 发送邮件
# ============================================================

def main():
    if not SMTP_USER or not SMTP_PASS or not EMAIL_TO:
        print("⚠️ 邮件配置不完整，跳过邮件发送")
        print("   需要设置: SMTP_USER, SMTP_PASS, EMAIL_TO")
        sys.exit(0)

    if not os.path.exists(REPORT_FILE):
        print(f"❌ 报告文件不存在: {REPORT_FILE}")
        print("   请确保 main.py 先生成报告")
        sys.exit(1)

    print(f"📧 正在发送邮件到 {EMAIL_TO}...")

    with open(REPORT_FILE, "r", encoding="utf-8") as f:
        report_md = f.read()

    html_body = markdown_to_html(report_md)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"📊 每日股市新闻分析报告 - {TODAY_CN}"
    msg["From"] = SMTP_USER
    msg["To"] = EMAIL_TO

    msg.attach(MIMEText(report_md, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT, timeout=30) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.sendmail(SMTP_USER, EMAIL_TO, msg.as_string())
        print(f"✅ 邮件已发送到 {EMAIL_TO}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
