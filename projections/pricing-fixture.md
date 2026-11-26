# Synthetic parser fixture, not current official tariffs

1 AI credit = $0.01 USD. All prices are per 1 million tokens.

| Model | Tier | Threshold (input tokens) | Input | Cached input | Cache write | Output |
| --- | --- | --- | ---: | ---: | ---: | ---: |
| GPT-6 Luna | Default | ≤ 272K | $1.00 | $0.10 | $1.25 | $5.00 |
| GPT-6 Luna | Long context | > 272K | $2.00 | $0.20 | $2.50 | $7.50 |
| GPT-6.2 Sol | Default | Not applicable | $2.00 | $0.20 | $2.50 | $10.00 |
| Claude Sonnet 5.5 | Default | Not applicable | $3.00 | $0.30 | $3.75 | $15.00 |
| Claude Opus 5.5 | Default | Not applicable | $4.00 | $0.40 | $5.00 | $20.00 |
| Gemini 4 Carbon[^example-promo] | Default | Not applicable | $2.00 | $0.10 | Not applicable | $10.00 |

[^example-promo]: Example promotional pricing until December 1, 2026. Starting December 1, 2026, pricing is $4.00 per 1M input tokens, $0.20 per 1M cached input tokens, and $20.00 per 1M output tokens.
