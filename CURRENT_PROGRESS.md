# 当前进度

## 目标分段状态

### 1. 完成数据入口确认

状态：已完成第一版验证。

当前证据：

- 鸣潮列表页：`https://www.pxb7.com/seo/buy/10302/1`
- 列表 API：`https://api-pc.pxb7.com/api/search/product/v2/selectSearchPageList`
- 详情页：`https://www.pxb7.com/product/{productId}/1`
- 详情 API：`https://api-pc.pxb7.com/api/product/web/product/detail?productId={productId}`
- `fetch_list.py` 可抓取第 1 页 `20` 个账号，并保存到 `data/sample_list.json`。

验收标准：

- 能稳定拿到至少 `1` 页列表数据：已验证。
- 包含不少于 `20` 个账号：已验证。
- 基础字段包含价格、标题、详情链接、发布时间：已验证。

### 2. 完成账号详情抓取

状态：已完成第一版验证。

当前证据：

- `fetch_detail.py` 可从 `data/sample_list.json` 抽取账号并调用详情 API。
- 已生成 `data/sample_detail.json`。
- 本轮验证：随机抽取 `10` 个账号，详情请求成功 `10/10`，核心字段解析成功 `10/10`，错误 `0`。

已解析字段：

- 角色：`characters[]`，包含名称与共鸣链。
- 武器：`weapons[]`，包含名称与精炼。
- 资源：`星声`、`月相`、`余波珊瑚`、`浮金波纹`、`铸潮波纹`。
- 等级：`level`。
- 区服：`server`。
- 安全/绑定：`tap_binding`、`wegame_binding`、`change_bind_cd`、`guarantee`、`screenshot_source`。

验收标准：

- 随机抽取 `10` 个账号：已完成。
- 至少 `8` 个能成功解析核心字段：已达到 `10/10`。

### 3. 建立标准数据结构

状态：已完成第一版验证。

当前证据：

- 已新增 `SCHEMA.md`，定义账号、角色、武器、资源、风险项的标准结构。
- `fetch_detail.py` 已经输出 `price`、`characters`、`weapons`、`resources`、`server`、`risk_flags` 等字段。
- 已新增 `validate_schema.py`。
- 本轮验证：`data/sample_detail.json` 中 `10` 个账号、`10` 个核心字段，缺失率 `0.0%`。

验收标准：

- 每个账号输出统一字段：已完成。
- 字段缺失率控制在 `20%` 以内：当前为 `0.0%`。

### 4. 建立鸣潮评分规则

状态：已完成 v1。

当前证据：

- 已新增 `configs/scoring_rules.json`，总分 `100` 分。
- 已新增 `score_accounts.py`。
- 评分维度包含：角色 `40` 分、武器 `25` 分、资源 `20` 分、风险 `15` 分。
- 本轮验证：`data/sample_detail.json` 中 `10` 个账号均可输出分项分、总分、推荐理由和扣分原因。

验收标准：

- 完成角色、武器、资源、风险项四类评分规则：已完成。
- 总分设为 `100` 分：已完成。
- 能输出每个账号的分项分、总分和扣分原因：已完成。

### 5. 实现批量评分与排序

状态：已完成第一版验证。

当前证据：

- 已新增 `batch_scorer.py`。
- 本轮执行：抓取列表 `5` 页，每页 `20` 条，共 `100` 个唯一账号。
- 详情抓取：成功 `100/100`，错误 `0`。
- 标准字段校验：`100` 个账号核心字段缺失率 `0.3%`。
- 已生成 `data/accounts_raw.json` 和 `data/score_results_batch.json`。
- `data/score_results_batch.json` 包含总分排序结果和 Top `20` 推荐账号。

验收标准：

- 一次运行处理不少于 `100` 个账号：已完成。
- 生成按总分排序结果文件：已完成。
- 包含 Top `20` 推荐账号：已完成。

### 6. 实现性价比判断

状态：已完成第一版验证。

当前证据：

- 已新增 `value_model.py`。
- 已生成 `data/value_results.json`。
- 本轮验证：为 `100` 个账号全部计算 `value_score`。
- 价格段 `0-100`、`100-300`、`300-600`、`600+` 均有候选输出；每段最多 Top `5`。

验收标准：

- 为每个账号计算 `value_score`：已完成。
- 综合总分和价格：已完成，输出 `expected_score`、`value_delta`、`price_efficiency`、`value_score`。
- 不同价格段筛出性价比 Top `5`：已完成。

### 7. 生成可读报告

状态：已完成第一版验证。

当前证据：

- 已新增 `report.py`。
- 已生成 `reports/report.html`。
- 报告包含：性价比 Top `20`、总分 Top `20`、各价格段 Top、价格、核心资产、总分、性价比、推荐理由和风险提示。

验收标准：

- 生成 HTML 或 Markdown 报告：已完成 HTML。
- 展示账号价格、核心资产、总分、性价比排名、推荐理由和风险提示：已完成。

### 8. 实现自动运行

状态：已完成并验证。

当前证据：

- 已新增 `run_all.py`。
- 本轮执行 `python run_all.py --pages 5 --page-size 20 --limit 100 --list-delay 1.0 --detail-delay 0.2 --top-n 20 --top-per-segment 5` 成功。
- 完整流程输出：
  - `data/accounts_raw.json`
  - `data/score_results_batch.json`
  - `data/value_results.json`
  - `reports/report.html`
  - `logs/run_all.log`
  - `data/errors.json`
- 日志包含 `Pipeline finished`。
- `data/errors.json` 当前为空错误列表。

验收标准：

- 通过一个 `run_all.py` 一键运行全流程：已完成。
- 留下日志：已完成，见 `logs/run_all.log`。
- 失败时能记录失败账号和失败原因：已完成，见 `data/errors.json`。
