# Changelog / 变更记录

## 中文

### 0.2.0 - 2026-06-09

- 新增 `--format sarif`，可上传到 GitHub Code Scanning 展示 agent run 回归风险。
- 新增 `--format pr-comment`，可直接写入 GitHub PR 评论或 Actions Step Summary。
- SARIF 报告包含 gate violation、risk reason 与 file diff 结果。
- PR 评论报告包含稳定 HTML marker、PASS/FAIL 摘要、违规项、风险原因和机器可读摘要。
- 更新 GitHub Actions smoke 测试与中英文 README。

### 0.1.0 - 2026-06-08

- 首次公开版本。
- 支持比较 AI agent run transcript 的工具调用、文件变更、耗时、成本、失败、重试和风险评分。
- 支持 Markdown、JSON、JUnit 报告和 CI gate 退出码。

## English

### 0.2.0 - 2026-06-09

- Added `--format sarif` for GitHub Code Scanning upload.
- Added `--format pr-comment` for GitHub PR comments and Actions step summaries.
- SARIF reports include gate violations, risk reasons, and file diff findings.
- PR comment reports include a stable HTML marker, PASS/FAIL summary, violations, risk reasons, and a machine-readable summary.
- Updated GitHub Actions smoke coverage and bilingual README docs.

### 0.1.0 - 2026-06-08

- Initial public release.
- Compared AI agent run transcripts across tool calls, file changes, duration, cost, failures, retries, and risk scoring.
- Supported Markdown, JSON, JUnit reports, and CI gate exit codes.
