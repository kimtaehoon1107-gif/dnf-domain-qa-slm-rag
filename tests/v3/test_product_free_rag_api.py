from __future__ import annotations

import app.product_free_rag_api as api


def test_api_uses_the_same_product_profile_as_the_demo(monkeypatch):
    captured = {}
    runtime = object()

    def fake_product_free_rag(**kwargs):
        captured.update(kwargs)
        return runtime

    monkeypatch.setattr(api, "_RUNTIME", None)
    monkeypatch.setattr(api, "ProductFreeRAG", fake_product_free_rag)

    assert api._runtime() is runtime
    assert captured["use_table_comparison_reservation"] is True
    assert captured["use_server_availability_rendering"] is True
    assert captured["use_server_content_kind_rendering"] is True
    assert captured["use_server_reward_kind_rendering"] is True
    assert captured["handoff_cuda_to_generation"] is True
