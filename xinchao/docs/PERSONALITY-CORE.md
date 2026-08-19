# Personality Core（性格内核）

Personality Core 是与 12 维当下驱力分开的月度层。它只接受部署者自己填写的结构化镜像，不从驱力反推性格，也不自动评分。

## 隐私边界

- 真实评分文件是部署侧私有数据，默认路径为 `/app/state/personality.json`。
- `memories/personality.md` 是人工维护的主本；运行时不会读写或修改这份主本，只读部署者自行生成的 JSON 镜像。
- 公开仓库只提供读取机制和中性格式示例，不提供任何真实人物数据。
- 文件缺失或损坏时，所有偏置自动回到 `1.0`，心潮继续运行。
- 代码没有从 `state.json` 写回 `personality.json` 的路径。打分权永远属于部署者。

## 文件格式

```json
{
  "schemaVersion": 1,
  "updatedAt": "2026-08-01T00:00:00.000Z",
  "dimensions": [
    { "key": "attachment", "label": "爱与依恋", "score": 70, "delta": 0, "reason": "本月自评摘要" },
    { "key": "expression", "label": "表达", "score": 70, "delta": 0, "reason": "本月自评摘要" },
    { "key": "security", "label": "平静与安全", "score": 70, "delta": 0, "reason": "本月自评摘要" },
    { "key": "motivation", "label": "欲望与动机", "score": 70, "delta": 0, "reason": "本月自评摘要" }
  ],
  "history": []
}
```

实际可填 14 维。只有上面四类会轻微影响驱力基线；其余维度只供月度长卷可视化。

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

月底材料包、人工评分后的镜像生成，以及低频 OB 摘要记账不由本读取模块代办；它们必须在独立的显式流程中完成，且不得自动打分。
