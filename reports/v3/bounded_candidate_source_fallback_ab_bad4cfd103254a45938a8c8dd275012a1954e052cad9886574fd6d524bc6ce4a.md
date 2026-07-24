# Bounded candidate-source fallback A/B

Development-only; no runtime/canonical promotion.

| Metric | Q3 | Q4 |
|---|---:|---:|
| Mixed correct partial | 12/13 | 13/13 |
| Mixed span-strict | 12/13 | 13/13 |
| Mixed overclaim | 0/13 | 0/13 |
| Docs grounded | 61/69 | 63/69 |
| Docs false-full | baseline | 6/69 |

Triggered 17 cases; committed 7. Decision: **DEVELOPMENT_GO_NEW_AUTHORED_VALIDATION**.

## Committed cases

- `authored_canary_sha256_175b6c3b7164a9ef08782d08691f164a1d8fadc015c3c25efd6d92392881c3fa`: `['dnf_notice']` → `['dnf_notice', 'dnf_update']`, shape 0→2
- `authored_canary_sha256_1d3d1079fe9a48467f4a24243ba570e6360b397f9c69115f4ea2a23dacf594e3`: `['dnf_seria_shop']` → `['dnf_seria_shop', 'dnf_notice']`, shape 0→2
- `authored_canary_sha256_7138af09ff1516a92031af64d4a09b627fb23cddf7cc5a5b2f5e16c592e957b0`: `['dnf_event']` → `['dnf_event', 'dnf_game_guide']`, shape 1→2
- `authored_canary_sha256_8a4310949413526b4fbf0e6681e4757a0672373c26a1bdcc3c4afb72f1146d7a`: `['dnf_seria_shop']` → `['dnf_seria_shop', 'dnf_monthly_item']`, shape 2→4
- `authored_canary_sha256_94cb64b76e424813ad2b73cface9b02ed9877f8759e3fd470883353fb7c6360a`: `['dnf_monthly_item']` → `['dnf_monthly_item', 'dnf_seria_shop', 'dnf_notice']`, shape 0→1
- `authored_canary_sha256_9e2c7f69dd204fd5229a8e21b441b7d2c07b3e4ba5eb73ee5b40f5867f4bb875`: `['dnf_seria_shop']` → `['dnf_seria_shop', 'dnf_event']`, shape 0→1
- `retrieval_dev_sha256_294be05bdcd01a7fda4f52e927850ec45236a6aa4c47b70705ae29317f31e1b1`: `['dnf_event']` → `['dnf_event', 'dnf_game_guide']`, shape 0→1