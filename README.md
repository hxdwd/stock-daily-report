# 📊 每日股市新闻分析报告（自动化版）

每天自动搜索最新国内外财经新闻，通过 AI 分析对 A股/港股/美股 的影响，生成结构化分析报告。

> 🕘 **每天北京时间 9:00 自动运行** | ☁️ **基于 GitHub Actions，无需服务器** | 💰 **完全免费**

---

## 快速开始

### 1. Fork 本仓库

点击 GitHub 页面右上角的 **Fork** 按钮，将仓库复制到你自己的账号下。

### 2. 配置 AI API Key

在你 Fork 的仓库中，进入 **Settings → Secrets and variables → Actions**，添加以下 Secrets：

| Secret 名称 | 说明 | 必填 |
|:------------|:-----|:-----|
| `AI_API_KEY` | AI API 密钥 | ✅ 是 |
| `AI_API_BASE` | API 地址（默认 OpenAI） | ❌ 否 |
| `AI_MODEL` | 模型名称（默认 gpt-4o） | ❌ 否 |

#### 推荐 API 提供商

| 提供商 | API_BASE | 费用估算 |
|:-------|:---------|:---------|
| **OpenAI** | `https://api.openai.com/v1` | ~$0.5/次 |
| **DeepSeek** | `https://api.deepseek.com/v1` | ~¥0.1/次 |
| **阿里百炼** | `https://dashscope.aliyuncs.com/compatible-mode/v1` | ~¥0.1/次 |
| **硅基流动** | `https://api.siliconflow.cn/v1` | ~¥0.05/次 |

### 3. 启用 GitHub Actions

1. 进入仓库的 **Actions** 标签页
2. 点击 "I understand my workflows, go ahead and enable them"
3. 找到 "每日股市新闻分析报告" 工作流，点击 **Enable workflow**

### 4. 手动测试（可选）

1. 进入 **Actions** → **每日股市新闻分析报告**
2. 点击 **Run workflow** → **Run workflow**
3. 等待约 2-3 分钟，查看运行结果

---

## 定时执行

工作流配置为 **北京时间每天 9:00** 自动运行。执行完成后：

- 📄 报告自动保存为 `每日股市新闻分析报告_YYYYMMDD.md`
- 🔄 自动提交到仓库，手机/电脑随时查看
- 📝 执行记忆保存在 `.codebuddy/automations/automation/memory.md`

---

## 项目结构

```
.
├── main.py                          # 主脚本（调用 AI API 生成报告）
├── requirements.txt                 # Python 依赖（仅用标准库）
├── .github/workflows/daily-report.yml  # GitHub Actions 工作流
├── .gitignore
├── 每日股市新闻分析报告_YYYYMMDD.md  # 生成的报告文件
└── .codebuddy/automations/automation/
    └── memory.md                    # 执行记忆（自动维护）
```

---

## 常见问题

### Q: GitHub Actions 免费额度够用吗？
**A:** 完全够。每月 2000 分钟免费额度，本任务每次约 3 分钟，每天一次仅用 ~90 分钟/月。

### Q: API 费用贵吗？
**A:** 不贵。使用 DeepSeek 等国产模型，每天约 0.1 元，月费约 3 元。

### Q: 报告什么时候能看到？
**A:** 每天北京时间 9:00 触发，约 9:03 完成并提交，刷新 GitHub 仓库页面即可看到。

### Q: 可以改成每小时运行吗？
**A:** 可以。修改 `.github/workflows/daily-report.yml` 中的 cron 表达式为 `0 * * * *`。

---

## 免责声明

本报告基于 AI 分析生成，不构成投资建议。股市有风险，投资需谨慎。
