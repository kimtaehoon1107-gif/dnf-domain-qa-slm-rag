# Source-isolated corrective retrieval A/B

Development-only. No runtime/canonical promotion.

Decision: **DEVELOPMENT_NO_GO**

| Block | Baseline all-groups | Corrected all-groups | Baseline false-full | Corrected false-full | Regressions |
|---|---:|---:|---:|---:|---:|
| Frozen docs | 63/69 | 64/69 | 6/69 | 5/69 | 2 |
| Authored adaptive | 16/24 | 21/24 | 6/24 | 3/24 | 1 |

- exact citations: **True**
- temporal violations zero: **False**
- frozen improvement IDs: `['authored_canary_sha256_30b37acd07ef814d9ab7a0d25f8c44726e98921f8c75b4d3199d83bcbea7a391', 'authored_canary_sha256_310899aa4d43a71faa2e5b59cfaa547bdf3fa2f3d44cd94a42c5393ce2b85358', 'authored_canary_sha256_82a1ce0196fad29ac156e6a2b549185353778c833e35a46e9ed57b02501100e0']`
- authored improvement IDs: `['authored_validation_v3_2_sha256_1d39b270356513cdb4253f033e20f082f9ae900bc72df6d61467e44728cf6b7d', 'authored_validation_v3_2_sha256_40d289dd5270c3f966a5803e73f2d0e082299e42ab3d8fafd07ad03e1704f870', 'authored_validation_v3_2_sha256_90331aa9b7b5f37f49407ecd60f8aadaf6bb9875a4c633e8cb7a8bcc7aea2abc', 'authored_validation_v3_2_sha256_afa90335c1c66670cab47342d634d092b29598a571a80c31df3e5f890442bbf8', 'authored_validation_v3_2_sha256_b5962b72942b9d1ebdfd611d489f7e73df51bb65d167710ad43dab70db0b1e24', 'authored_validation_v3_2_sha256_c8803a9d34cc39551e80708aa46733e0483fa27c8e5f29a75f2f85154b44874a']`
- frozen regression IDs: `['authored_canary_sha256_d14cc891b82cf4cd20b4405a1e4c9041873c0f4bf2fbdc84a7e546774dcfcb1d', 'retrieval_dev_sha256_59ca7a033abaec5d72433fd9b114842276ddc4e79774e4894d13ef5e1813a344']`
- authored regression IDs: `['authored_validation_v3_2_sha256_1dff068b8da6dc7cb7e0d9f45b50063278bb9657999cdea7522d9927e3f09ef4']`

The inspected authored set is adaptive diagnostic data and cannot serve as a sealed benchmark.
