# Personality Core（性格内核）

Personality Core 是与 12 维当下驱力分开的月度层。每月由 AI 通过受鉴权的 MCP 工具完成一次自主回顾与评分，人类不参与打分；系统也不会从驱力数值自动反推性格。

## 隐私边界

- 真实评分文件是部署侧私有数据，默认路径为 `/app/state/personality.json`。
- 评分只由已连接的 AI 显式调用 `xinchao_personality_reflect` 产生，不开放 Dashboard 人工改分接口。
- 公开仓库只提供读取机制和中性格式示例，不提供任何真实人物数据。
- 文件缺失或损坏时，所有偏置自动回到 `1.0`，心潮继续运行。
- 代码没有从 `state.json` 写回 `personality.json` 的路径；12 维驱力再高也不能自动改写内核。
- 同一月份只能形成一份快照，网络重试只返回既有结果，不能悄悄覆盖历史。

## 文件格式

```json
{
  "schemaVersion": 1,
  "source": "ai-self-assessment",
  "scoredBy": "ai",
  "month": "2026-08",
  "updatedAt": "2026-08-31T00:00:00.000Z",
  "dimensions": [
    { "key": "love", "label": "爱与依恋", "score": 70, "delta": 0, "reason": "AI 的本月回顾摘要" },
    { "key": "expression", "label": "表达", "score": 70, "delta": 0, "reason": "AI 的本月回顾摘要" },
    { "key": "calm", "label": "平静与安全", "score": 70, "delta": 0, "reason": "AI 的本月回顾摘要" },
    { "key": "desire", "label": "欲望与动机", "score": 70, "delta": 0, "reason": "AI 的本月回顾摘要" }
  ],
  "history": []
}
```

工具必须一次提交完整 14 维。只有上面四类会轻微影响驱力基线；其余维度只供月度长卷可视化。

## AI 月度自评

AI 每月调用一次 `xinchao_personality_reflect`，提交 `month` 与完整 14 维 `{key, score, reason}`。运行时负责校验维度、根据上月分数计算 `delta`、原子写入私有文件并保存历史。人类无需填写 JSON，也没有人工打分入口。

这是显式、可审计的月度动作，不是后台拿当前驱力偷偷推断人格。文件只写入 `PERSONALITY_PATH`，权限设为仅服务账户可读写，不进入 Git。

## 单向偏置

以 70 分为中性，每偏离 30 分对应 10%，并硬封顶在 `0.9–1.1`：

- 爱与依恋 → `possess` / `crave`
- 表达 → `share`
- 平静与安全 → `grieve` / `monitor`（反向：安全越低，反应越敏感）
- 欲望与动机 → `libido` / `curiosity`

偏置只改变时间增长的有效天花板，不更改事件结算，不直接改当前数值。

## Dashboard 读取

鉴权后请求 `GET /dashboard/api/personality`，可获取当前 14 维与历史快照，用于独立的月度趋势/长卷视图。该视图不与 12 维花瓣合并。

主快照 `GET /dashboard/api/snapshot` 也会附带一份最小化的 `personality`投影：`available`、可选 `constellation`、最新 `month`、`updatedAt` 和 `{key,label,score,delta}` 维度数组。缺失分值回落到 70；数组顺序不构成语义，网页应按中文标签匹配。`reason` 只在部署者显式开启 `DASHBOARD_INCLUDE_PRIVATE_TEXT=true` 时返回。

月底材料包和低频 OB 摘要记账仍属于后续显式流程；3.1 不修改 OB，也不会把评分理由默认暴露给网页。
