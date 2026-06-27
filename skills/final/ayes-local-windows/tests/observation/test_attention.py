from ayes.observation.attention import apply_attention_text_boost, build_default_attention_regions


def test_attention_keeps_edge_context_lower_than_main_content() -> None:
    regions = build_default_attention_regions(width=1200, height=800)
    main = next(item for item in regions if item.primary)
    right_panel = next(item for item in regions if item.region.region_id == "auto_right_panel")

    boosted = apply_attention_text_boost(right_panel, "推荐视频 列表")

    assert boosted.weight == right_panel.weight
    assert boosted.weight < main.weight
    assert boosted.abnormal_keyword_boosted is False


def test_attention_boosts_edge_abnormal_keywords_without_overriding_main_content() -> None:
    regions = build_default_attention_regions(width=1200, height=800)
    main = next(item for item in regions if item.primary)
    right_panel = next(item for item in regions if item.region.region_id == "auto_right_panel")

    boosted = apply_attention_text_boost(right_panel, "支付失败，请重新登录")

    assert boosted.weight > right_panel.weight
    assert boosted.weight < main.weight
    assert boosted.abnormal_keyword_boosted is True
    assert "异常关键词" in boosted.reason
