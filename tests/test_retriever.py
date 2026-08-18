from insightforge.services.retriever import KnowledgeBase


def test_ingest_search_and_deduplicate(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db")
    text = "星云科技的 AI 客服试点将首次响应时间从八分钟降低到十八秒。"
    assert kb.ingest_text(text, "pilot.md", "试点报告") == 1
    assert kb.ingest_text(text, "pilot.md", "试点报告") == 1
    assert kb.count() == 1

    results = kb.search("AI 客服 响应时间")
    assert len(results) == 1
    assert results[0].title == "试点报告"
    assert "十八秒" in results[0].content


def test_irrelevant_query_returns_no_results(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb.ingest_text("客服产品资料", "product.md")
    assert kb.search("火星地质勘探") == []


def test_chinese_query_without_spaces_uses_bigrams(tmp_path):
    kb = KnowledgeBase(tmp_path / "kb.db")
    kb.ingest_text("人工智能客服可以降低重复咨询量。", "product.md")
    assert kb.search("请分析智能客服投入价值")
