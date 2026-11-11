# LLM API 定价表

价格单位: ¥ (人民币) / 百万 tokens

| LLM 变体 | 模型名称 | 输入价格 (¥/1M tokens) | 输出价格 (¥/1M tokens) | 数据来源 |
|----------|---------|----------------------|----------------------|---------|
| DeepSeek-v4 | deepseek-v4-flash | 1.00 | 2.00 | [DeepSeek 官方定价](https://ap-deepseek.com.cn/pricing.html) (缓存未命中) |
| GLM-4-flash | glm-4-flash | 0 | 0 | [智谱AI开放平台](https://bigmodel.cn/pricing) (免费) |
| Kimi | moonshot-v1-8k | 2.00 | 10.00 | [Kimi API 官方定价](https://platform.kimi.com/docs/pricing/chat-v1) |
| MiniMax-M3 | MiniMax-M3 | 4.20 | 16.80 | [MiniMax 官方定价](https://www.llmabacus.com/models/minimax-m3) |

## 花费计算公式

```
每次调用花费 (¥) = (prompt_tokens / 1,000,000) × 输入价格 + (completion_tokens / 1,000,000) × 输出价格
```

## 备注

- DeepSeek-v4-flash 缓存命中时输入价格仅 ¥0.02/1M tokens，但当前数据无缓存命中标记，统一按缓存未命中计算
- GLM-4-flash 为完全免费模型，花费恒为 0
- 定价获取日期: 2026-07-11
