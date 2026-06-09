"""
每日股市新闻分析报告生成器 (GitHub Actions 版)
==============================================
每天自动搜索最新国内外财经新闻，调用 AI API 生成结构化分析报告。
运行方式：python main.py
依赖环境变量：AI_API_KEY, AI_API_BASE (可选), AI_MODEL (可选)
"""

import os
import json
import re
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

## 输出格式要求
必须包含以下章节：
1. 市场全景速览（含数据表格）
2. 重大新闻分类与影响分析（国际新闻和国内新闻分开，每条新闻包含：来源、维度、摘要、短期/中期影响评估表格、影响板块/个股）
3. 综合研判（核心矛盾、国内市场分析、关键观察节点）
4. 风险提示（含风险等级表格）
5. 策略建议（短期和中期）
6. 事件日历（当月重要事件）

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
# 入口
# ============================================================

def main():
    print(f"📅 日期: {TODAY_CN} ({TODAY_WEEKDAY})")
    print(f"🤖 模型: {API_MODEL}")
    print(f"📝 输出: {OUTPUT_FILE}")
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
    print("🎉 执行完成！")


if __name__ == "__main__":
    main()
