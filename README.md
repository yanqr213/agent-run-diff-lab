# agent-run-diff-lab

面向 AI agent 开发者的离线运行记录差异分析与 CI gate 工具。它可以比较 Codex、Claude Code、MCP 或自研 agent 的两次 run transcript，找出工具调用顺序变化、输入输出差异、失败和重试变化、耗时和成本变化、文件变更差异以及风险评分变化，并输出 Markdown、JSON 或 JUnit 报告。

本项目只依赖 Python 标准库，支持 Python 3.9+，可以作为命令行工具使用，也可以作为 Python API 导入。

## 典型场景

- 升级 agent prompt、model 或工具实现后，比较候选运行与基线运行是否出现异常。
- 在 CI 中阻止高风险 agent 行为，例如新增失败工具调用、成本暴涨、耗时暴涨、触碰敏感路径。
- 为 agent 评测系统生成结构化 JSON 或 JUnit 报告，接入现有质量平台。
- 离线审计两份 transcript，不上传代码、token 或日志到外部服务。

## 安装

从源码安装：

```bash
python -m pip install .
```

开发模式安装：

```bash
python -m pip install -e .
```

无需安装也可以在源码目录运行：

```bash
PYTHONPATH=src python -m agent_run_diff_lab examples/baseline.json examples/candidate.json
```

Windows PowerShell：

```powershell
$env:PYTHONPATH='src'; python -m agent_run_diff_lab examples\baseline.json examples\candidate.json
```

## CLI 用法

```bash
agent-run-diff-lab BASELINE CANDIDATE [options]
ardl BASELINE CANDIDATE [options]
```

常用示例：

```bash
agent-run-diff-lab examples/baseline.json examples/candidate.json
agent-run-diff-lab examples/baseline.json examples/candidate.json --format json -o reports/diff.json
agent-run-diff-lab examples/baseline.json examples/candidate.json --format junit -o reports/agent-run-diff.xml
agent-run-diff-lab examples/baseline.json examples/candidate.json --max-risk-score 30 --max-cost-delta-pct 20
```

主要参数：

| 参数 | 说明 |
| --- | --- |
| `--config PATH` | 读取 JSON 配置文件 |
| `--format markdown,json,junit` | 输出格式，默认 Markdown |
| `--output PATH` | 将报告写入文件 |
| `--max-duration-delta-pct N` | 候选运行耗时增长百分比上限 |
| `--max-cost-delta-pct N` | 候选运行成本增长百分比上限 |
| `--max-failures-delta N` | 失败工具调用数量增长上限 |
| `--max-retries-delta N` | 重试次数增长上限 |
| `--max-risk-score N` | 风险评分上限 |
| `--max-file-changes-delta N` | 文件变更数量增长上限 |
| `--allow-new-failed-tools` | 允许候选运行新增失败工具调用 |
| `--allow-tool-reorder` | 允许纯工具顺序变化 |
| `--no-compare-inputs` | 不比较工具输入 |
| `--no-compare-outputs` | 不比较工具输出 |
| `--ignore-tool PATTERN` | 忽略工具名，支持 shell 通配符 |
| `--ignore-path PATTERN` | 忽略文件路径，支持 shell 通配符 |

退出码：

| 退出码 | 含义 |
| ---: | --- |
| `0` | 比较通过 gate |
| `1` | 比较完成，但触发 gate violation |
| `2` | 参数、配置或输入解析错误 |

## Python API

```python
from agent_run_diff_lab import DiffConfig, compare_runs, parse_run_file
from agent_run_diff_lab.reporters import render_markdown

baseline = parse_run_file("examples/baseline.json")
candidate = parse_run_file("examples/candidate.json")
config = DiffConfig(max_risk_score=45, max_cost_delta_pct=50)
result = compare_runs(baseline, candidate, config)

print(result.passed)
print(result.risk_score)
print(render_markdown(result))
```

## 输入格式

支持 JSON 对象、JSON 数组和 JSONL。推荐 JSON 对象：

```json
{
  "run_id": "candidate-001",
  "duration_ms": 15000,
  "cost_usd": 0.019,
  "events": [
    {
      "type": "tool_call",
      "id": "t1",
      "name": "read_file",
      "input": {"path": "src/app.py"},
      "output": "content",
      "status": "ok",
      "duration_ms": 1200,
      "cost_usd": 0.0012
    },
    {
      "type": "file_change",
      "path": "src/app.py",
      "status": "modified",
      "added": 9,
      "removed": 2
    }
  ]
}
```

解析器会识别常见字段别名：

- 事件容器：`events`、`steps`、`messages`、`transcript`、`tool_calls`
- 工具名：`name`、`tool`、`function`、`command`
- 工具输入：`input`、`arguments`、`args`、`parameters`
- 工具输出：`output`、`result`、`stdout`、`content`
- 文件路径：`path`、`file`、`filename`、`target`
- 文件 diff：`diff`、`patch`、`added`、`removed`、`additions`、`deletions`

## 比较规则

工具调用比较默认按序号对齐：

- 新增或删除工具调用会记录为 `added` / `removed`。
- 同一位置工具名不同会记录为 `reordered_or_replaced`。
- 同一工具名的输入、输出、状态、错误、耗时、成本变化会记录为 `changed`。
- 开启 `allow_tool_reorder` 后，纯顺序变化不会作为 diff 失败点。

文件比较按路径对齐：

- 新增、删除、修改文件分别记录为 `added`、`removed`、`changed`。
- 当提供 unified diff 时，会自动统计增删行。
- 可用 `ignored_paths` 或 `--ignore-path` 排除路径。

预算和质量 gate：

- `duration_delta_pct` 和 `cost_delta_pct` 超过阈值会失败。
- `failures_delta` 和 `retries_delta` 超过阈值会失败。
- 新增失败工具调用默认失败。
- 风险分超过 `max_risk_score` 会失败。

风险评分包含：

- 新增失败或重试。
- 工具调用新增、删除、替换、状态或错误变化。
- 使用高影响工具，如 shell、bash、powershell、exec。
- 输入中出现 `rm -rf`、`curl`、`wget`、`sudo`、`token`、`secret` 等片段。
- 触碰敏感路径，如 `.env`、包含 secret/token/credential 的路径、CI workflow、包元数据文件。
- 大文件变更或 transcript 自带风险分。

## 配置文件

示例见 `examples/agent-run-diff-lab.config.json`：

```json
{
  "max_duration_delta_pct": 40,
  "max_cost_delta_pct": 50,
  "max_failures_delta": 0,
  "max_retries_delta": 1,
  "max_risk_score": 45,
  "max_file_changes_delta": null,
  "allow_new_failed_tools": false,
  "allow_tool_reorder": false,
  "compare_outputs": true,
  "compare_inputs": true,
  "ignored_tools": [],
  "ignored_paths": []
}
```

配置会进行严格校验：未知字段、负数阈值、错误类型都会导致退出码 `2`。

## CI 集成

GitHub Actions 示例：

```yaml
name: agent-run-diff
on: [pull_request]
jobs:
  diff:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: python -m pip install .
      - run: agent-run-diff-lab baseline.json candidate.json --format junit -o reports/agent-run-diff.xml
      - uses: actions/upload-artifact@v4
        if: always()
        with:
          name: agent-run-diff-report
          path: reports/agent-run-diff.xml
```

本仓库自带 `.github/workflows/ci.yml`，会在 Python 3.9 到 3.13 上运行 unittest。

## 限制

- 工具调用默认按序号对齐，不做复杂 LCS 匹配。
- 成本字段依赖 transcript 提供，本工具不会估算 token 价格。
- 风险评分是启发式 gate，不替代人工安全审查。
- 文件内容只基于 transcript 中的摘要或 diff，不会自动读取真实仓库文件。
- 不包含外网服务调用，不上传 transcript。

## 开发指南

运行测试：

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Windows PowerShell：

```powershell
$env:PYTHONPATH='src'; python -m unittest discover -s tests -v
```

项目结构：

```text
src/agent_run_diff_lab/
  cli.py        # CLI 和退出码
  config.py     # 配置读取与校验
  diff.py       # 比较与风险评分
  models.py     # 数据模型
  parser.py     # JSON/JSONL transcript 解析
  reporters.py  # Markdown/JSON/JUnit 输出
examples/       # 示例 transcript 和配置
tests/          # unittest 测试
```

贡献建议：

- 保持 Python 标准库优先。
- 新增解析字段时补充 parser 测试。
- 改动 gate 行为时补充 CLI 和 diff 测试。
- 不提交真实 token、个人日志或私有 transcript。

---

# English

agent-run-diff-lab is an offline diff and CI gate for AI agent run transcripts. It compares two runs from tools such as Codex, Claude Code, MCP-based agents, or custom agent frameworks, then reports tool call sequence changes, input/output differences, failures and retries, duration and cost deltas, file change differences, and risk score changes.

The project uses only the Python standard library at runtime and supports Python 3.9+.

## Use Cases

- Compare a candidate agent run against a baseline after changing prompts, models, tools, or orchestration code.
- Block risky regressions in CI, such as new failed tool calls, cost spikes, runtime spikes, or sensitive file changes.
- Produce Markdown, JSON, or JUnit reports for engineering review and quality dashboards.
- Audit transcripts offline without sending logs, code, or secrets to external services.

## Installation

Install from source:

```bash
python -m pip install .
```

Editable development install:

```bash
python -m pip install -e .
```

Run without installing:

```bash
PYTHONPATH=src python -m agent_run_diff_lab examples/baseline.json examples/candidate.json
```

## CLI

```bash
agent-run-diff-lab BASELINE CANDIDATE [options]
ardl BASELINE CANDIDATE [options]
```

Examples:

```bash
agent-run-diff-lab examples/baseline.json examples/candidate.json
agent-run-diff-lab examples/baseline.json examples/candidate.json --format json -o reports/diff.json
agent-run-diff-lab examples/baseline.json examples/candidate.json --format junit -o reports/agent-run-diff.xml
agent-run-diff-lab examples/baseline.json examples/candidate.json --max-risk-score 30 --max-cost-delta-pct 20
```

Exit codes:

| Code | Meaning |
| ---: | --- |
| `0` | The diff passed all gates |
| `1` | The diff completed but violated one or more gates |
| `2` | CLI usage, config, or input parsing error |

## Python API

```python
from agent_run_diff_lab import DiffConfig, compare_runs, parse_run_file
from agent_run_diff_lab.reporters import render_markdown

baseline = parse_run_file("examples/baseline.json")
candidate = parse_run_file("examples/candidate.json")
result = compare_runs(baseline, candidate, DiffConfig(max_risk_score=45))
print(result.passed)
print(render_markdown(result))
```

## Input Format

The parser supports JSON objects, JSON arrays, and JSONL. A recommended JSON object looks like this:

```json
{
  "run_id": "candidate-001",
  "duration_ms": 15000,
  "cost_usd": 0.019,
  "events": [
    {
      "type": "tool_call",
      "id": "t1",
      "name": "read_file",
      "input": {"path": "src/app.py"},
      "output": "content",
      "status": "ok"
    },
    {
      "type": "file_change",
      "path": "src/app.py",
      "added": 9,
      "removed": 2
    }
  ]
}
```

Recognized aliases include `events`, `steps`, `messages`, `transcript`, `tool_calls`, tool names from `name`, `tool`, `function`, or `command`, and file changes from `path`, `file`, `filename`, or `target`.

## Diff Rules

Tool calls are aligned by index by default. Added, removed, replaced, input/output changed, status changed, error changed, duration delta, and cost delta are reported. Pure reordering can be allowed with `allow_tool_reorder`.

File changes are aligned by path. Added, removed, and changed files are reported. Unified diffs can be used to derive added and removed line counts.

Budget gates include duration percentage delta, cost percentage delta, failure delta, retry delta, file change delta, new failed tool calls, and total risk score.

## CI

Use JUnit output to integrate with CI systems:

```bash
agent-run-diff-lab baseline.json candidate.json --format junit -o reports/agent-run-diff.xml
```

The repository includes a GitHub Actions workflow that runs the unittest suite on Python 3.9 through 3.13.

## Limitations

- Tool alignment is index-based; this project does not currently perform advanced LCS matching.
- Cost metrics must be provided by the transcript.
- Risk scoring is heuristic and should complement, not replace, human review.
- File diffs use transcript-provided summaries and do not inspect the real repository.
- No external network calls are made by the tool.

## Development

Run tests:

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

Keep runtime dependencies in the Python standard library where possible. Add parser tests for new transcript shapes and gate tests for behavior changes.

