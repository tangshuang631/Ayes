import json
import sqlite3

from ayes.events.factory import build_event
from ayes.events.models import EventTarget, EventText, EventTextBlock, EventVisual, Observability
from ayes.memory.search_index import MemorySearchIndex


def test_memory_search_index_writes_fts_and_compact_chunks(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="ocr",
        event_type="text_change",
        priority="medium",
        confidence=0.92,
        target=EventTarget(type="process", process_name="Chrome", window_title="Apifox 登录页"),
        observability=Observability(True, True, True, True, "ok"),
        summary="Apifox 登录页",
    )
    event = event.__class__(
        **{
            **event.__dict__,
            "text": EventText(
                ocr_text="Apifox 登录页",
                normalized_text="Apifox 登录页",
                blocks=[EventTextBlock(text="Apifox", confidence=0.9, bbox=[1, 2, 3, 4], rect_norm={"x": 0.1})],
            ),
            "visual": EventVisual(attributes={"request_payload": {"images": ["x" * 1000]}}),
        }
    )

    index.index_event(event)

    index_dir = tmp_path / "tasks" / "2026-10-25" / "task_browser" / "index"
    assert (index_dir / "fts.sqlite").exists()
    chunk_path = index_dir / "chunks" / "2026-10-25-16.jsonl"
    payload = json.loads(chunk_path.read_text(encoding="utf-8").splitlines()[0])
    assert payload["info"] == "Apifox 登录页"
    encoded = json.dumps(payload, ensure_ascii=False)
    assert "blocks" not in encoded
    assert "bbox" not in encoded
    assert "request_payload" not in encoded


def test_memory_search_index_does_not_index_no_change_events(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    event = build_event(
        task_id="task_browser",
        spec_version="1.0",
        task_mode="observe",
        timestamp=1792944000.0,
        source="diff",
        event_type="visual_change",
        priority="low",
        confidence=0.9,
        target=EventTarget(type="process", process_name="Chrome"),
        observability=Observability(True, True, True, True, "ok"),
        summary="未检测到显著变化",
    )

    chunk = index.index_event(event)

    assert chunk is None
    assert not (tmp_path / "tasks").exists()


def test_memory_search_index_query_filters_legacy_no_change_chunks(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    index.index_chunk(
        {
            "chunk_id": "no_change",
            "task_id": "task_browser",
            "timestamp": 1792944000.0,
            "layer": "short",
            "source": "diff",
            "event_type": "visual_change",
            "info": "未检测到显著变化",
            "tags": [],
            "confidence": 0.9,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "real",
            "task_id": "task_browser",
            "timestamp": 1792944300.0,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "Chrome 中出现 Apifox 登录页",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )

    result = index.query(task_id="task_browser", question="最近页面有什么", minutes=240, now=1792944600.0)

    assert "Chrome 中出现 Apifox 登录页" in result["answer"]
    assert "未检测到显著变化" not in result["answer"]


def test_memory_search_index_does_not_append_duplicate_chunk_rows(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    chunk = {
        "chunk_id": "chunk_1",
        "task_id": "task_browser",
        "timestamp": 1792944000.0,
        "layer": "short",
        "source": "ocr",
        "event_type": "text_change",
        "info": "Apifox 登录页",
        "tags": ["ocr"],
        "confidence": 0.9,
    }

    index.index_chunk(chunk)
    index.index_chunk(chunk)

    chunk_path = tmp_path / "tasks" / "2026-10-25" / "task_browser" / "index" / "chunks" / "2026-10-25-16.jsonl"
    lines = chunk_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    assert json.loads(lines[0])["chunk_id"] == "chunk_1"


def test_memory_search_index_delete_and_rebuild_from_compact_memory(tmp_path) -> None:
    task_id = "task_browser"
    compact_dir = tmp_path / "tasks" / "2026-10-25" / task_id / "memory" / "compact"
    compact_dir.mkdir(parents=True)
    (compact_dir / "2026-10-25-task_browser-segments.jsonl").write_text(
        '{"from":"2026-10-25T16:00:00Z","to":"2026-10-25T16:05:00Z","info":"Apifox 登录页持续显示","repeat_count":12}\n',
        encoding="utf-8",
    )
    index = MemorySearchIndex(runtime_dir=tmp_path)
    index.index_chunk(
        {
            "chunk_id": "stale",
            "task_id": task_id,
            "timestamp": 1792943000.0,
            "layer": "short",
            "source": "ocr",
            "event_type": "text_change",
            "info": "旧索引内容",
            "tags": ["ocr"],
            "confidence": 0.9,
        }
    )

    removed = index.delete_task_index(task_id)
    rebuilt = index.rebuild_task_index(task_id, since_timestamp=0.0)
    result = index.query(task_id=task_id, question="Apifox 页面", minutes=240, now=1792944600.0)

    assert removed["deleted"] is True
    assert rebuilt["indexed_chunks"] == 1
    assert "Apifox 登录页持续显示" in result["answer"]
    assert "旧索引内容" not in result["answer"]


def test_memory_search_index_query_reranks_specific_fact_over_generic_visual(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    index.index_chunk(
        {
            "chunk_id": "title",
            "task_id": "task_bilibili",
            "timestamp": 1792944000.0,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
            "tags": ["window_title"],
            "confidence": 0.86,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "visual",
            "task_id": "task_bilibili",
            "timestamp": 1792944300.0,
            "layer": "short",
            "source": "vision",
            "event_type": "visual_summary",
            "info": "这张图片展示了两个卡通人物坐在沙发上对话的场景。",
            "tags": ["vision"],
            "confidence": 0.9,
        }
    )

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=1792944600.0)

    assert result["items"]
    assert "布欧怎么出现的" in result["answer"]
    assert "卡通人物坐在沙发" not in result["answer"]
    assert result["items"][0]["chunk_id"] == "title"


def test_memory_search_index_backfills_from_existing_compact_memory_files(tmp_path) -> None:
    memory_dir = tmp_path / "tasks" / "2026-10-25" / "task_bilibili" / "memory" / "short"
    memory_dir.mkdir(parents=True)
    (memory_dir / "2026-10-25-task_bilibili-details.jsonl").write_text(
        '{"time":"2026-10-25T16:00:00Z","info":"进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】"}\n',
        encoding="utf-8",
    )
    index = MemorySearchIndex(runtime_dir=tmp_path)

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=1792944300.0)

    assert "布欧怎么出现的" in result["answer"]
    assert result["retrieval"]["backfilled"] is True
    assert (tmp_path / "tasks" / "2026-10-25" / "task_bilibili" / "index" / "fts.sqlite").exists()


def test_memory_search_index_preserves_region_from_short_memory_files(tmp_path) -> None:
    memory_dir = tmp_path / "tasks" / "2026-10-25" / "task_wechat" / "memory" / "short"
    memory_dir.mkdir(parents=True)
    (memory_dir / "2026-10-25-task_wechat-details.jsonl").write_text(
        '{"time":"2026-10-25T16:00:00Z","region":"自动主内容区","info":"微信左侧会话列表显示 服务号、接单群、SZU校集9群"}\n',
        encoding="utf-8",
    )
    index = MemorySearchIndex(runtime_dir=tmp_path)

    result = index.query(task_id="task_wechat", question="微信页面有什么", minutes=240, now=1792944300.0)

    assert result["items"]
    assert result["items"][0]["region"] == "自动主内容区"


def test_memory_search_index_content_question_filters_thumbnail_and_garbage_noise(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    for offset in range(5):
        index.index_chunk(
            {
                "chunk_id": f"thumb_{offset}",
                "task_id": "task_bilibili",
                "timestamp": base + offset,
                "layer": "short",
                "source": "vision",
                "event_type": "visual_summary",
                "info": "图中有多个视频缩略图展示，每个缩略图下方有播放次数和点赞数等信息。",
                "tags": ["vision"],
                "confidence": 0.9,
            }
        )
    index.index_chunk(
        {
            "chunk_id": "garbage",
            "task_id": "task_bilibili",
            "timestamp": base + 10,
            "layer": "short",
            "source": "ocr",
            "event_type": "text_change",
            "info": "g*%l*fo. 6-21 7.45 0113 03:43 6-3",
            "tags": ["ocr"],
            "confidence": 0.8,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "title",
            "task_id": "task_bilibili",
            "timestamp": base - 300,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=base + 60)

    assert "布欧怎么出现的" in result["answer"]
    assert "多个视频缩略图" not in result["answer"]
    assert "g*%l*fo" not in result["answer"]
    assert all("g*%l*fo" not in item["info"] for item in result["items"])


def test_memory_search_index_content_question_searches_past_recent_noise_window(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "title",
            "task_id": "task_bilibili",
            "timestamp": base,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )
    for offset in range(420):
        index.index_chunk(
            {
                "chunk_id": f"recent_noise_{offset}",
                "task_id": "task_bilibili",
                "timestamp": base + 60 + offset,
                "layer": "short",
                "source": "file_memory",
                "event_type": "compact_short_memory",
                "info": "g*%l*fo. 6-21 7.45 0113 03:43 6-3" if offset % 2 else "图中有多个视频缩略图展示，每个缩略图下方有播放次数和点赞数等信息。",
                "tags": ["short_memory"],
                "confidence": 0.84,
            }
        )

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=base + 180)

    assert result["items"][0]["chunk_id"] == "title"
    assert "布欧怎么出现的" in result["answer"]
    assert "多个视频缩略图" not in result["answer"]
    assert "g*%l*fo" not in result["answer"]


def test_memory_search_index_content_question_filters_short_non_title_fragments(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "title",
            "task_id": "task_bilibili",
            "timestamp": base,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "进程 哔哩哔哩 代表窗口切换: 哔哩哔哩 -> 皮特替子从军高兴的都哭了",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )
    for offset in range(20):
        index.index_chunk(
            {
                "chunk_id": f"fragment_{offset}",
                "task_id": "task_bilibili",
                "timestamp": base + offset,
                "layer": "short",
                "source": "file_memory",
                "event_type": "compact_short_memory",
                "info": "DEEPESt.,",
                "tags": ["short_memory"],
                "confidence": 0.84,
            }
        )

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=base + 60)

    assert "皮特替子从军" in result["answer"]
    assert "DEEPESt" not in result["answer"]


def test_memory_search_index_content_question_answer_prefers_title_over_visual_details(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "visual",
            "task_id": "task_bilibili",
            "timestamp": base,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "图中角色张大嘴巴，露出牙齿和舌头，背景为蓝色天空。",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "title",
            "task_id": "task_bilibili",
            "timestamp": base + 60,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=base + 120)

    assert result["answer"].startswith("进程 哔哩哔哩 代表窗口切换")
    assert result["items"][0]["chunk_id"] == "title"
    assert "图中角色" not in result["answer"]


def test_memory_search_index_content_question_filters_ascii_arrow_garbage_when_titles_exist(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "title",
            "task_id": "task_bilibili",
            "timestamp": base,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "进程 哔哩哔哩 代表窗口切换: 首页 -> 布欧怎么出现的？太古恶魔or魔法产物？哪个形态最强？【话说龙珠】",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "ascii_arrow_noise",
            "task_id": "task_bilibili",
            "timestamp": base + 60,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "-.2,*.Yt.]E;-IHA iJ->AIJIfiEtJ L,I,L'l'",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )

    result = index.query(task_id="task_bilibili", question="最近看的视频是什么", minutes=240, now=base + 120)

    assert "布欧怎么出现的" in result["answer"]
    assert "AIJIfiEtJ" not in result["answer"]


def test_memory_search_index_answer_includes_region_for_spatial_memory(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    index.index_chunk(
        {
            "chunk_id": "left_panel",
            "task_id": "task_chat",
            "timestamp": 1792944000.0,
            "layer": "short",
            "source": "file_memory",
            "event_type": "compact_short_memory",
            "info": "会话列表显示订单提醒",
            "region": "自动左侧栏",
            "tags": ["short_memory"],
            "confidence": 0.84,
        }
    )

    result = index.query(task_id="task_chat", question="订单提醒在哪里", minutes=240, now=1792944300.0)

    assert result["answer"].startswith("自动左侧栏：会话列表显示订单提醒@")


def test_memory_search_index_backfills_region_from_compact_segments(tmp_path) -> None:
    task_id = "task_spatial"
    compact_dir = tmp_path / "tasks" / "2026-10-25" / task_id / "memory" / "compact"
    compact_dir.mkdir(parents=True)
    (compact_dir / "2026-10-25-task_spatial-segments.jsonl").write_text(
        '{"from":"2026-10-25T16:00:00Z","to":"2026-10-25T16:05:00Z","region":"自动左侧栏","info":"会话列表显示订单提醒","repeat_count":8}\n',
        encoding="utf-8",
    )
    index = MemorySearchIndex(runtime_dir=tmp_path)

    result = index.query(task_id=task_id, question="订单提醒在哪里", minutes=240, now=1792944300.0)

    assert result["items"]
    assert result["items"][0]["region"] == "自动左侧栏"
    assert "自动左侧栏：会话列表显示订单提醒" in result["answer"]


def test_memory_search_index_ignores_empty_long_summary_placeholder(tmp_path) -> None:
    task_id = "task_browser"
    long_dir = tmp_path / "tasks" / "2026-10-25" / task_id / "memory" / "long"
    long_dir.mkdir(parents=True)
    (long_dir / "2026-10-25-task_browser-summary.jsonl").write_text(
        '{"from":"2026-10-25T16:00:00Z","to":"2026-10-25T16:05:00Z","info":"该时间段内无高价值摘要"}\n'
        '{"from":"2026-10-25T16:05:00Z","to":"2026-10-25T16:10:00Z","info":"Chrome 中出现 Apifox 登录页"}\n',
        encoding="utf-8",
    )
    index = MemorySearchIndex(runtime_dir=tmp_path)

    result = index.query(task_id=task_id, question="最近页面内容是什么", minutes=240, now=1792944900.0)

    assert "Chrome 中出现 Apifox 登录页" in result["answer"]
    assert "无高价值摘要" not in result["answer"]


def test_memory_search_index_prefers_compact_fact_chunks_over_raw_scene_fragments(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "fact_main",
            "task_id": "task_general",
            "timestamp": base,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：文档页面，标题：项目进展汇报，三条要点说明",
            "code": "scn=cnt|reg=main|k1=文档页面|k2=标题：项目进展汇报|k3=三条要点说明",
            "region": "自动主内容区",
            "tags": ["compact_memory", "fact_content"],
            "confidence": 0.9,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "raw_visual",
            "task_id": "task_general",
            "timestamp": base + 10,
            "layer": "short",
            "source": "vision",
            "event_type": "visual_summary",
            "info": "画面里有一些文本和布局元素，像是一个普通页面。",
            "region": "自动全目标",
            "tags": ["vision"],
            "confidence": 0.91,
        }
    )

    result = index.query(task_id="task_general", question="最近主要内容是什么", minutes=240, now=base + 60)

    assert result["items"][0]["chunk_id"] == "fact_main"
    assert result["answer"].startswith("自动主内容区：内容：文档页面")
    assert "普通页面" not in result["answer"]


def test_memory_search_index_prefers_code_terms_when_info_is_shorter(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "coded_fact",
            "task_id": "task_general",
            "timestamp": base,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：文档页面",
            "code": "scn=cnt|reg=main|k1=文档页面|k2=标题：项目进展汇报|k3=三条要点说明",
            "region": "自动主内容区",
            "tags": ["compact_memory", "fact_content"],
            "confidence": 0.9,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "other_fact",
            "task_id": "task_general",
            "timestamp": base + 1,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：普通页面",
            "code": "scn=cnt|reg=main|k1=普通页面|k2=常规布局",
            "region": "自动主内容区",
            "tags": ["compact_memory"],
            "confidence": 0.92,
        }
    )

    result = index.query(task_id="task_general", question="最近项目进展汇报的内容是什么", minutes=240, now=base + 60)

    assert result["items"][0]["chunk_id"] == "coded_fact"
    assert "项目进展汇报" in result["answer"]


def test_memory_search_index_normalizes_code_into_structured_fields(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)

    index.index_chunk(
        {
            "chunk_id": "coded_fact",
            "task_id": "task_general",
            "timestamp": 1792944000.0,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：文档页面",
            "code": "scn=cnt|reg=main|k1=文档页面|k2=标题：项目进展汇报|k3=三条要点说明",
            "region": "自动主内容区",
            "tags": ["compact_memory", "fact_content"],
            "confidence": 0.9,
        }
    )

    chunk_path = tmp_path / "tasks" / "2026-10-25" / "task_general" / "index" / "chunks" / "2026-10-25-16.jsonl"
    payload = json.loads(chunk_path.read_text(encoding="utf-8").splitlines()[0])

    assert payload["scene"] == "cnt"
    assert payload["region_slot"] == "main"
    assert payload["k1"] == "文档页面"
    assert payload["k2"] == "标题：项目进展汇报"
    assert payload["k3"] == "三条要点说明"


def test_memory_search_index_persists_structured_code_fields_in_sqlite(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)

    index.index_chunk(
        {
            "chunk_id": "coded_fact",
            "task_id": "task_general",
            "timestamp": 1792944000.0,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：文档页面",
            "code": "scn=cnt|reg=main|k1=文档页面|k2=标题：项目进展汇报|k3=三条要点说明",
            "region": "自动主内容区",
            "tags": ["compact_memory", "fact_content"],
            "confidence": 0.9,
        }
    )

    db_path = tmp_path / "tasks" / "2026-10-25" / "task_general" / "index" / "fts.sqlite"
    with sqlite3.connect(str(db_path)) as connection:
        columns = [row[1] for row in connection.execute("PRAGMA table_info(memory_chunks)").fetchall()]
        row = connection.execute(
            "SELECT scene, region_slot, k1, k2, k3 FROM memory_chunks WHERE chunk_id = ?",
            ("coded_fact",),
        ).fetchone()

    assert "scene" in columns
    assert "region_slot" in columns
    assert "k1" in columns
    assert "k2" in columns
    assert "k3" in columns
    assert row == ("cnt", "main", "文档页面", "标题：项目进展汇报", "三条要点说明")


def test_memory_search_index_prefers_status_fact_from_edge_over_generic_main_noise(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "main_noise",
            "task_id": "task_general",
            "timestamp": base,
            "layer": "short",
            "source": "vision",
            "event_type": "visual_summary",
            "info": "画面：主界面，若干内容区域",
            "region": "自动主内容区",
            "tags": ["vision"],
            "confidence": 0.7,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "status_fact",
            "task_id": "task_general",
            "timestamp": base + 5,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "状态：右上错误提示，请重新登录",
            "region": "自动右侧栏",
            "tags": ["compact_memory", "fact_status", "alert"],
            "confidence": 0.93,
        }
    )

    result = index.query(task_id="task_general", question="有没有异常提示", minutes=240, now=base + 60)

    assert result["items"][0]["chunk_id"] == "status_fact"
    assert "请重新登录" in result["answer"]


def test_memory_search_index_does_not_duplicate_near_identical_fact_chunks_in_answer(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    for idx, offset in enumerate([0, 30, 60]):
        index.index_chunk(
            {
                "chunk_id": f"fact_dup_{idx}",
                "task_id": "task_general",
                "timestamp": base + offset,
                "layer": "compact",
                "source": "file_memory_compact",
                "event_type": "compact_memory_segment",
                "info": "内容：文档页面，标题：项目进展汇报，三条要点说明",
                "region": "自动主内容区",
                "tags": ["compact_memory", "fact_content"],
                "confidence": 0.9,
            }
        )

    result = index.query(task_id="task_general", question="最近主要内容是什么", minutes=240, now=base + 120)

    assert result["answer"].count("项目进展汇报") == 1
    assert len([item for item in result["items"] if "项目进展汇报" in item["info"]]) == 1


def test_memory_search_index_prefers_top_before_bottom_within_same_region_priority(tmp_path) -> None:
    index = MemorySearchIndex(runtime_dir=tmp_path)
    base = 1792944000.0
    index.index_chunk(
        {
            "chunk_id": "lower_main",
            "task_id": "task_spatial_order",
            "timestamp": base,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：主内容下半区，表格详情",
            "region": "自动主内容区",
            "tags": ["compact_memory"],
            "confidence": 0.9,
        }
    )
    index.index_chunk(
        {
            "chunk_id": "upper_main",
            "task_id": "task_spatial_order",
            "timestamp": base + 1,
            "layer": "compact",
            "source": "file_memory_compact",
            "event_type": "compact_memory_segment",
            "info": "内容：主内容上半区，页面标题和摘要",
            "region": "自动主内容区",
            "tags": ["compact_memory"],
            "confidence": 0.9,
        }
    )

    result = index.query(task_id="task_spatial_order", question="最近主要内容是什么", minutes=240, now=base + 60)

    assert result["items"][0]["chunk_id"] in {"upper_main", "lower_main"}
    assert "内容：" in result["answer"]
