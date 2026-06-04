# MetaSkill Run Progress (Step Ribbon) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在 WebUI 聊天里给 MetaSkill 跑加一条 step ribbon，展示每一步状态、当前进度、失败救援动作，并保持 CLI/MCP 兼容。

**Architecture:** 后端在 `engine/types.py` 加 3 个新 dataclass 事件（`MetaRunAnnouncedEvent` / `MetaStepStateEvent` / `MetaRunCompletedEvent`），`skills/meta/scheduler.py` 在已有 ToolUseStart/Result 旁并发新事件；`engine/types.py` 风格遵循现有 `kind: Literal[…]` 区分符约定。前端独立模块 `gateway/static/js/views/chat/meta-ribbon.js` 接收事件渲染 ribbon；`chat.js` 只做接线。SKILL.md 加可选 `label:` / `progress_emits:` 两字段。

**Tech Stack:** Python 3.12 + asyncio + structlog（后端）；vanilla ES module + CSS（前端）；pytest + ruff + mypy（测试与门禁）。

**Spec:** `docs/proposals/specs/2026-06-04-meta-skill-run-progress-design.md`

---

## File Structure

**Create:**

- `src/opensquilla/skills/meta/progress_throttle.py` — 500ms `status_text` 节流 + state 去重 helper
- `src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js` — ribbon 渲染模块（纯函数 + render）
- `src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css` — ribbon 样式
- `tests/test_meta_skill_step_events.py` — scheduler 新事件序列测试
- `tests/test_meta_skill_run_announce.py` — `meta_run_announced` 内容测试
- `tests/test_meta_skill_status_text_throttle.py` — 节流单元测试
- `tests/test_session_streams_meta_events.py` — replay buffer 新事件保留测试
- `tests/test_meta_skill_parser_label_progress_emits.py` — parser 新字段测试
- `tests/test_gateway/test_chat_meta_ribbon_static.py` — 前端 DOM 静态测试
- `tests/test_gateway/test_chat_meta_ribbon_failure.py` — 失败动作行交互测试

**Modify:**

- `src/opensquilla/engine/types.py` — 新增 3 个事件 dataclass（仿 `RouterDecisionEvent` 风格）
- `src/opensquilla/skills/meta/types.py` — `MetaStep` 加 `label`、`progress_emits` 字段
- `src/opensquilla/skills/meta/parser.py` — 读 `label:` / `progress_emits:`，传给 `MetaStep`
- `src/opensquilla/skills/meta/scheduler.py` — 6 个发布点
- `src/opensquilla/gateway/static/js/views/chat.js` — 接线 3 个 handler + DOM 插入容器
- `src/opensquilla/skills/bundled/meta-document-to-decision/SKILL.md` — 步加 `label:`
- `src/opensquilla/skills/bundled/meta-web-research-to-report/SKILL.md` — 步加 `label:`
- `src/opensquilla/skills/bundled/meta-daily-operator-brief/SKILL.md` — 步加 `label:`
- `docs/authoring/meta-skills.md` — 文档加新字段说明

**Tests:** 见 Create 列。

---

### Task 1: 新增三个 engine 事件 dataclass

**Files:**

- Modify: `src/opensquilla/engine/types.py`（在 `RouterDecisionEvent` 之后追加）

- [ ] **Step 1: 写失败测试**

新建 `tests/test_engine_meta_events.py`：

```python
"""MetaSkill 事件 dataclass 形状与默认值。"""

from opensquilla.engine.types import (
    MetaRunAnnouncedEvent,
    MetaRunCompletedEvent,
    MetaStepStateEvent,
)


def test_meta_run_announced_minimal():
    ev = MetaRunAnnouncedEvent(
        run_id="r1",
        meta_skill_name="meta-document-to-decision",
        steps=[
            {"id": "intake", "label": "意图提取", "kind": "llm_chat", "depends_on": []},
            {"id": "search", "label": "检索证据", "kind": "agent", "depends_on": ["intake"]},
        ],
        total=2,
        parent_run_id=None,
    )
    assert ev.kind == "meta_run_announced"
    assert ev.total == 2
    assert ev.parent_run_id is None


def test_meta_step_state_minimal():
    ev = MetaStepStateEvent(
        run_id="r1",
        step_id="search",
        state="running",
        status_text="检索中…",
    )
    assert ev.kind == "meta_step_state"
    assert ev.error is None
    assert ev.substitute_for is None


def test_meta_step_state_failed_with_error():
    ev = MetaStepStateEvent(
        run_id="r1",
        step_id="search",
        state="failed",
        error="web-research timeout",
    )
    assert ev.state == "failed"
    assert ev.error == "web-research timeout"


def test_meta_step_state_substituted_links_origin():
    ev = MetaStepStateEvent(
        run_id="r1",
        step_id="search_fallback",
        state="substituted",
        substitute_for="search",
    )
    assert ev.substitute_for == "search"


def test_meta_run_completed_minimal():
    ev = MetaRunCompletedEvent(
        run_id="r1",
        outcome="ok",
        completed_steps=["intake", "search"],
        failed_steps=[],
        skipped_steps=[],
    )
    assert ev.kind == "meta_run_completed"
    assert ev.outcome == "ok"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_engine_meta_events.py -v
```

Expected: ImportError — 三个类未定义。

- [ ] **Step 3: 在 `engine/types.py` 末尾加 dataclass**

把这段加在文件末尾（紧随 `RouterDecisionEvent` 之后）：

```python
@dataclass
class MetaRunAnnouncedEvent:
    """Emitted once when a MetaSkill run starts and its plan has been
    compiled. WebUI uses this to seed the step ribbon with all declared
    step ids, labels, kinds, and dependency edges. `parent_run_id` is
    reserved for nested meta-skill rollouts (always None today).
    """

    kind: Literal["meta_run_announced"] = field(default="meta_run_announced", init=False)
    run_id: str = ""
    meta_skill_name: str = ""
    steps: list[dict[str, Any]] = field(default_factory=list)
    total: int = 0
    parent_run_id: str | None = None


@dataclass
class MetaStepStateEvent:
    """One state transition for a single MetaSkill step within a run.

    `state` is one of pending / running / succeeded / failed / skipped /
    substituted. `status_text` is an optional short human-readable label
    shown under the active chip; `error` carries the failure message when
    `state == "failed"`; `substitute_for` is set on the substitute step
    yielded after an `on_failure` branch fires.
    """

    kind: Literal["meta_step_state"] = field(default="meta_step_state", init=False)
    run_id: str = ""
    step_id: str = ""
    state: str = "pending"
    status_text: str | None = None
    error: str | None = None
    substitute_for: str | None = None


@dataclass
class MetaRunCompletedEvent:
    """Terminal event for a MetaSkill run. `outcome` is one of
    ok / failed / cancelled. The three step-id lists let the WebUI freeze
    the final ribbon state without scanning back through the stream.
    """

    kind: Literal["meta_run_completed"] = field(default="meta_run_completed", init=False)
    run_id: str = ""
    outcome: str = "ok"
    completed_steps: list[str] = field(default_factory=list)
    failed_steps: list[str] = field(default_factory=list)
    skipped_steps: list[str] = field(default_factory=list)
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_engine_meta_events.py -v
uv run ruff check src/opensquilla/engine/types.py
uv run mypy src/opensquilla/engine/types.py
```

Expected: 全部 PASS / clean。

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/engine/types.py tests/test_engine_meta_events.py
git commit -m "$(cat <<'EOF'
Introduce meta-skill run progress event types

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Event-bridge 把新事件名暴露到 session 流

**Files:**

- Modify: `src/opensquilla/gateway/event_bridge.py`
- Test: `tests/test_gateway/test_event_bridge_meta_events.py`（新建）

- [ ] **Step 1: 探查 event_bridge.py 的现有 kind → event_name 映射**

```bash
grep -n "session\.event\.\|kind\|event_name" src/opensquilla/gateway/event_bridge.py | head -40
```

读出现有映射表的位置，确认风格（dict 还是 if-elif）。

- [ ] **Step 2: 写失败测试**

新建 `tests/test_gateway/test_event_bridge_meta_events.py`：

```python
"""event_bridge 把 3 个新 meta 事件 dataclass 映射到正确的 session.event 名。"""

from opensquilla.engine.types import (
    MetaRunAnnouncedEvent,
    MetaRunCompletedEvent,
    MetaStepStateEvent,
)
from opensquilla.gateway.event_bridge import bridge_event_name


def test_meta_run_announced_event_name():
    ev = MetaRunAnnouncedEvent(run_id="r1", meta_skill_name="x", steps=[], total=0)
    assert bridge_event_name(ev) == "session.event.meta_run_announced"


def test_meta_step_state_event_name():
    ev = MetaStepStateEvent(run_id="r1", step_id="s1", state="running")
    assert bridge_event_name(ev) == "session.event.meta_step_state"


def test_meta_run_completed_event_name():
    ev = MetaRunCompletedEvent(run_id="r1", outcome="ok")
    assert bridge_event_name(ev) == "session.event.meta_run_completed"
```

`bridge_event_name` 是一个公开 helper — 若 `event_bridge.py` 当前没暴露这个名字，先在该模块加 thin wrapper（一行）暴露内部映射。

- [ ] **Step 3: 运行测试确认失败**

```bash
uv run pytest tests/test_gateway/test_event_bridge_meta_events.py -v
```

Expected: KeyError 或 AttributeError — 新事件未在映射表内。

- [ ] **Step 4: 修改 event_bridge.py 加映射**

找到 kind → event_name 映射点（Step 1 已定位），加入 3 条：

```python
# inside the kind-to-event-name mapping
"meta_run_announced": "session.event.meta_run_announced",
"meta_step_state": "session.event.meta_step_state",
"meta_run_completed": "session.event.meta_run_completed",
```

如果该模块用 if-elif 风格，按相同位置加 3 个 elif；若使用 dataclass `kind` Literal 自动派生，则只需引入 import 即可。

- [ ] **Step 5: 运行测试确认通过**

```bash
uv run pytest tests/test_gateway/test_event_bridge_meta_events.py -v
uv run ruff check src/opensquilla/gateway/event_bridge.py
```

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/gateway/event_bridge.py tests/test_gateway/test_event_bridge_meta_events.py
git commit -m "$(cat <<'EOF'
Route meta-skill progress events through gateway bridge

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: 确认 replay buffer 保留 meta 事件

**Files:**

- Test: `tests/test_session_streams_meta_events.py`（新建）

**注**：`session_streams.SessionStreamRegistry._is_replay_lossy` 当前只丢 `session.event.text_delta` 和 `session.event.run_heartbeat`。新事件应天然保留。本 task 只加测试锚定行为，不改 production code。

- [ ] **Step 1: 写测试**

新建 `tests/test_session_streams_meta_events.py`：

```python
"""新增 meta 事件被 replay buffer 完整保留，断线重连可补齐。"""

from opensquilla.gateway.session_streams import SessionStreamRegistry


def _record_and_replay(events_to_record, since=0):
    reg = SessionStreamRegistry(max_events_per_session=500)
    for name, payload in events_to_record:
        reg.record("sess1", name, payload)
    return reg.replay("sess1", since)


def test_meta_run_announced_preserved_through_replay():
    result = _record_and_replay([
        ("session.event.meta_run_announced",
         {"run_id": "r1", "meta_skill_name": "x", "total": 2}),
    ])
    assert result.replay_complete is True
    assert len(result.events) == 1
    assert result.events[0].event_name == "session.event.meta_run_announced"
    assert result.events[0].payload["run_id"] == "r1"


def test_meta_step_state_preserved_through_replay():
    result = _record_and_replay([
        ("session.event.meta_run_announced", {"run_id": "r1", "total": 1}),
        ("session.event.meta_step_state",
         {"run_id": "r1", "step_id": "s1", "state": "running"}),
        ("session.event.meta_step_state",
         {"run_id": "r1", "step_id": "s1", "state": "succeeded"}),
    ])
    assert len(result.events) == 3
    states = [
        e.payload["state"]
        for e in result.events
        if e.event_name == "session.event.meta_step_state"
    ]
    assert states == ["running", "succeeded"]


def test_meta_events_survive_buffer_trim_pressure():
    reg = SessionStreamRegistry(max_events_per_session=5)
    # Fill with lossy events (text_delta) first; should be evictable.
    for i in range(10):
        reg.record("s", "session.event.text_delta", {"i": i})
    # Now record meta events; lossy evictions should make room.
    reg.record("s", "session.event.meta_run_announced", {"run_id": "r1"})
    reg.record("s", "session.event.meta_step_state",
               {"run_id": "r1", "step_id": "a", "state": "running"})
    result = reg.replay("s", 10)
    kept = [e.event_name for e in result.events]
    assert "session.event.meta_run_announced" in kept
    assert "session.event.meta_step_state" in kept
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_session_streams_meta_events.py -v
```

Expected: 全部 PASS（验证 anchor 行为，无 production 改动）。

- [ ] **Step 3: Commit**

```bash
git add tests/test_session_streams_meta_events.py
git commit -m "$(cat <<'EOF'
Lock meta-skill events as replay-safe in session streams

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: MetaStep 加 label / progress_emits

**Files:**

- Modify: `src/opensquilla/skills/meta/types.py`

- [ ] **Step 1: 写失败测试**

在 `tests/test_meta_skill_parser_label_progress_emits.py` 创建：

```python
"""MetaStep 暴露 label 与 progress_emits，默认安全回退。"""

from opensquilla.skills.meta.types import MetaStep


def test_meta_step_default_label_empty():
    s = MetaStep(id="intake", skill="intake")
    assert s.label == ""
    assert s.progress_emits is True


def test_meta_step_explicit_label():
    s = MetaStep(id="intake", skill="intake", label="意图提取")
    assert s.label == "意图提取"


def test_meta_step_progress_emits_off():
    s = MetaStep(id="tool", skill="tool", kind="tool_call",
                 tool="memory_save", progress_emits=False)
    assert s.progress_emits is False
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_parser_label_progress_emits.py::test_meta_step_default_label_empty -v
```

Expected: AttributeError — 字段不存在。

- [ ] **Step 3: 修改 `meta/types.py` 给 MetaStep 加字段**

在 `MetaStep` dataclass 内（紧随 `clarify_config` 字段之后）追加：

```python
    # New in P0-1: human-readable label for the step ribbon chip.
    # Empty string ⇒ frontend humanizes ``id``.
    label: str = ""
    # New in P0-1: whether the executor may emit per-step ``status_text``
    # updates via the run-progress event channel. ``tool_call`` defaults
    # to False (single deterministic call); ``agent`` / ``skill_exec``
    # default to True; ``llm_chat`` / ``llm_classify`` ignore this flag.
    progress_emits: bool = True
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_parser_label_progress_emits.py -v
uv run mypy src/opensquilla/skills/meta/types.py
```

Expected: PASS / clean.

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/skills/meta/types.py tests/test_meta_skill_parser_label_progress_emits.py
git commit -m "$(cat <<'EOF'
Add label and progress_emits fields to MetaStep

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: parser 读 label / progress_emits

**Files:**

- Modify: `src/opensquilla/skills/meta/parser.py`
- Test: `tests/test_meta_skill_parser_label_progress_emits.py`（在 Task 4 已建，本 task 追加）

- [ ] **Step 1: 追加失败测试**

在已建的 `tests/test_meta_skill_parser_label_progress_emits.py` 末尾追加：

```python
from dataclasses import dataclass, field
from typing import Any

from opensquilla.skills.meta.parser import MetaPlanError, parse_meta_plan


@dataclass
class _FakeSpec:
    name: str = "fake-meta"
    kind: str = "meta"
    composition_raw: dict[str, Any] = field(default_factory=dict)
    triggers: list[str] = field(default_factory=list)
    meta_priority: int = 0
    content: str = ""
    final_text_mode: str = "auto"


def _spec_with(steps):
    return _FakeSpec(composition_raw={"steps": steps})


def test_parser_reads_label():
    plan = parse_meta_plan(_spec_with([
        {"id": "intake", "kind": "llm_chat", "label": "意图提取"},
    ]))
    assert plan is not None
    assert plan.steps[0].label == "意图提取"


def test_parser_reads_progress_emits_false():
    plan = parse_meta_plan(_spec_with([
        {"id": "tool", "kind": "tool_call", "tool": "memory_save",
         "progress_emits": False},
    ]))
    assert plan is not None
    assert plan.steps[0].progress_emits is False


def test_parser_label_must_be_string():
    with pytest.raises(MetaPlanError, match="label"):
        parse_meta_plan(_spec_with([
            {"id": "intake", "kind": "llm_chat", "label": 123},
        ]))


def test_parser_progress_emits_must_be_bool():
    with pytest.raises(MetaPlanError, match="progress_emits"):
        parse_meta_plan(_spec_with([
            {"id": "intake", "kind": "llm_chat", "progress_emits": "yes"},
        ]))


def test_parser_label_optional():
    plan = parse_meta_plan(_spec_with([
        {"id": "intake", "kind": "llm_chat"},
    ]))
    assert plan is not None
    assert plan.steps[0].label == ""
```

文件顶部加 `import pytest`。

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_parser_label_progress_emits.py -v
```

Expected: 新增 5 个 case 失败（parser 未读 label / 未验证类型）。

- [ ] **Step 3: 修改 parser.py**

在 `parse_meta_plan` 函数中，紧随 `on_failure_raw` 处理段之后、`steps.append(MetaStep(...))` 之前，插入：

```python
        label_raw = raw.get("label", "")
        if not isinstance(label_raw, str):
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step {step_id!r} label must be "
                f"a string (or omitted)",
            )
        label = label_raw

        progress_emits_raw = raw.get("progress_emits")
        if progress_emits_raw is None:
            # Defaults by kind: tool_call → False; everything else → True.
            progress_emits = kind != "tool_call"
        elif isinstance(progress_emits_raw, bool):
            progress_emits = progress_emits_raw
        else:
            raise MetaPlanError(
                f"meta-skill {spec.name!r}: step {step_id!r} progress_emits "
                f"must be a boolean (or omitted)",
            )
```

把这两个变量传给 MetaStep 构造（在原 `MetaStep(...)` 调用末尾追加：

```python
                label=label,
                progress_emits=progress_emits,
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_parser_label_progress_emits.py -v
uv run ruff check src/opensquilla/skills/meta/parser.py
uv run mypy src/opensquilla/skills/meta/parser.py
```

- [ ] **Step 5: 运行全量 meta 解析回归**

```bash
uv run pytest tests -k "meta_skill" -q
```

Expected: 现有解析测试全绿（新字段全部可选，向后兼容）。

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/skills/meta/parser.py tests/test_meta_skill_parser_label_progress_emits.py
git commit -m "$(cat <<'EOF'
Parse label and progress_emits on meta-skill steps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: 节流 / 去重 helper

**Files:**

- Create: `src/opensquilla/skills/meta/progress_throttle.py`
- Create: `tests/test_meta_skill_status_text_throttle.py`

- [ ] **Step 1: 写失败测试**

```python
"""500ms per-step status_text 节流 + (run, step, state) 去重。"""

import pytest

from opensquilla.skills.meta.progress_throttle import ProgressThrottle


def test_throttle_allows_first_status_text():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 1000.0)
    assert t.allow_status_text("r1", "search") is True


def test_throttle_blocks_within_window():
    now = [1000.0]
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: now[0])
    assert t.allow_status_text("r1", "search") is True
    now[0] = 1000.4  # 400ms later
    assert t.allow_status_text("r1", "search") is False


def test_throttle_allows_after_window():
    now = [1000.0]
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: now[0])
    t.allow_status_text("r1", "search")
    now[0] = 1000.6
    assert t.allow_status_text("r1", "search") is True


def test_throttle_per_step_independent():
    now = [1000.0]
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: now[0])
    assert t.allow_status_text("r1", "search") is True
    assert t.allow_status_text("r1", "draft") is True  # different step


def test_state_dedupe_first_seen():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 0.0)
    assert t.allow_state("r1", "search", "running") is True


def test_state_dedupe_repeats_blocked():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 0.0)
    t.allow_state("r1", "search", "running")
    assert t.allow_state("r1", "search", "running") is False


def test_state_dedupe_transition_allowed():
    t = ProgressThrottle(min_interval_ms=500, clock=lambda: 0.0)
    t.allow_state("r1", "search", "running")
    assert t.allow_state("r1", "search", "succeeded") is True
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_status_text_throttle.py -v
```

Expected: ImportError — 模块未建。

- [ ] **Step 3: 写实现**

`src/opensquilla/skills/meta/progress_throttle.py`：

```python
"""Per-run/per-step throttle for status_text bursts + state-transition
de-duplication for meta-skill step events.

The orchestrator may receive status_text updates very frequently when an
`agent` step's sub-turn fires multiple tool calls per second. This helper
caps emission to one status_text per (run_id, step_id) per
``min_interval_ms`` (default 500ms) so the WebUI ribbon does not flood.

It also tracks the last emitted state per (run_id, step_id) so identical
state transitions (e.g. running → running) are suppressed; only first
occurrence of each state is allowed through.
"""

from __future__ import annotations

import time
from collections.abc import Callable


class ProgressThrottle:
    """Per-(run_id, step_id) throttle + state dedupe."""

    def __init__(
        self,
        *,
        min_interval_ms: int = 500,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._min_interval = min_interval_ms / 1000.0
        self._clock = clock or time.monotonic
        self._last_status_text_at: dict[tuple[str, str], float] = {}
        self._last_state: dict[tuple[str, str], str] = {}

    def allow_status_text(self, run_id: str, step_id: str) -> bool:
        """Return True if a new status_text emission is permitted."""
        key = (run_id, step_id)
        now = self._clock()
        last = self._last_status_text_at.get(key)
        if last is not None and (now - last) < self._min_interval:
            return False
        self._last_status_text_at[key] = now
        return True

    def allow_state(self, run_id: str, step_id: str, state: str) -> bool:
        """Return True if this state transition has not been emitted yet."""
        key = (run_id, step_id)
        if self._last_state.get(key) == state:
            return False
        self._last_state[key] = state
        return True
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_status_text_throttle.py -v
uv run ruff check src/opensquilla/skills/meta/progress_throttle.py
uv run mypy src/opensquilla/skills/meta/progress_throttle.py
```

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/skills/meta/progress_throttle.py tests/test_meta_skill_status_text_throttle.py
git commit -m "$(cat <<'EOF'
Add progress-event throttle and state dedupe helper

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: scheduler 发布 meta_run_announced

**Files:**

- Modify: `src/opensquilla/skills/meta/scheduler.py`
- Create: `tests/test_meta_skill_run_announce.py`

- [ ] **Step 1: 写失败测试**

```python
"""scheduler.run_dag 入口在第一个 step 派发前 yield meta_run_announced。"""

import pytest

from opensquilla.engine.types import (
    MetaRunAnnouncedEvent,
    ToolUseStartEvent,
)


@pytest.mark.asyncio
async def test_announces_plan_before_first_tool_use(make_two_step_match, fake_dispatch_stream, fake_preface):
    """meta_run_announced 必须先于任何 step 的 ToolUseStartEvent。"""

    from opensquilla.skills.meta.scheduler import run_dag

    events = []
    async for ev in run_dag(
        make_two_step_match,
        dispatch_step_stream=fake_dispatch_stream,
        yield_skill_view_preface=fake_preface,
    ):
        events.append(ev)
        if len(events) >= 3:
            break

    kinds = [type(e).__name__ for e in events]
    assert "MetaRunAnnouncedEvent" in kinds
    first_announce = next(i for i, e in enumerate(events) if isinstance(e, MetaRunAnnouncedEvent))
    first_tool = next(
        (i for i, e in enumerate(events) if isinstance(e, ToolUseStartEvent)),
        None,
    )
    assert first_tool is None or first_announce < first_tool


@pytest.mark.asyncio
async def test_announce_payload_lists_all_steps(make_two_step_match, fake_dispatch_stream, fake_preface):
    from opensquilla.skills.meta.scheduler import run_dag

    announce = None
    async for ev in run_dag(
        make_two_step_match,
        dispatch_step_stream=fake_dispatch_stream,
        yield_skill_view_preface=fake_preface,
    ):
        if isinstance(ev, MetaRunAnnouncedEvent):
            announce = ev
            break

    assert announce is not None
    assert announce.total == 2
    ids = [s["id"] for s in announce.steps]
    assert ids == ["intake", "summary"]
    assert announce.steps[0]["label"] == "意图提取"
    assert announce.steps[1]["depends_on"] == ["intake"]
```

并配套在 `tests/conftest.py` 加 fixture（或新建 `tests/test_meta_skill_run_announce_conftest.py`）：

```python
import pytest

from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaStep


@pytest.fixture
def make_two_step_match():
    plan = MetaPlan(
        name="meta-fake",
        triggers=("fake",),
        priority=0,
        steps=(
            MetaStep(id="intake", skill="intake", kind="llm_chat", label="意图提取"),
            MetaStep(
                id="summary", skill="summary", kind="llm_chat",
                label="总结", depends_on=("intake",),
            ),
        ),
        final_text_mode="raw",
    )
    return MetaMatch(plan=plan, inputs={"user_message": "hi"})


@pytest.fixture
def fake_dispatch_stream():
    from opensquilla.skills.meta.events import _StepDone

    async def _dispatch(step, effective_skill, inputs, outputs):
        yield _StepDone(text=f"out:{step.id}")

    return _dispatch


@pytest.fixture
def fake_preface():
    async def _preface(step_id, effective_skill):
        return
        yield  # never reached; keeps it an async generator

    return _preface
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_run_announce.py -v
```

Expected: 没找到 `MetaRunAnnouncedEvent` 在 stream 中。

- [ ] **Step 3: 在 scheduler.py 加发布点**

在 `run_dag` 函数体的开头，紧随 `outputs: dict[str, str] = dict(seed_outputs or {})` 初始化、且**先于**所有 `_run_one` 任务被 spawn 之前（实际位置：找到第一次出现 `_spawn_ready()` 前），插入：

```python
    # Announce the static composition so the WebUI can seed its step
    # ribbon before any per-step tool-call event arrives. Run-scoped id
    # is the orchestrator's existing handle on this DAG run; if no
    # explicit run_id is plumbed, fall back to the first step's id +
    # plan name (good enough to bind ribbon DOM nodes; not used for
    # persistence keys).
    _run_id = getattr(match, "run_id", "") or f"{match.plan.name}:{id(match)}"
    yield MetaRunAnnouncedEvent(
        run_id=_run_id,
        meta_skill_name=match.plan.name,
        steps=[
            {
                "id": s.id,
                "label": s.label,
                "kind": s.kind,
                "depends_on": list(s.depends_on),
            }
            for s in match.plan.steps
        ],
        total=len(match.plan.steps),
        parent_run_id=None,
    )
```

并在文件顶部 `from opensquilla.engine.types import (...)` 处把 `MetaRunAnnouncedEvent` 加进 import。

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_run_announce.py -v
```

- [ ] **Step 5: 回归**

```bash
uv run pytest tests -k "meta" -q
uv run mypy src/opensquilla/skills/meta/scheduler.py
```

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/skills/meta/scheduler.py tests/test_meta_skill_run_announce.py tests/conftest.py
git commit -m "$(cat <<'EOF'
Announce meta-skill composition before run dispatch

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: scheduler 发布 step_state(running / succeeded)

**Files:**

- Modify: `src/opensquilla/skills/meta/scheduler.py`
- Create: `tests/test_meta_skill_step_events.py`

- [ ] **Step 1: 写失败测试**

```python
"""scheduler 在 step 开始/成功时分别发出 meta_step_state(running/succeeded)。"""

import pytest

from opensquilla.engine.types import MetaStepStateEvent


@pytest.mark.asyncio
async def test_running_emitted_at_step_start(make_two_step_match, fake_dispatch_stream, fake_preface):
    from opensquilla.skills.meta.scheduler import run_dag

    events = [ev async for ev in run_dag(
        make_two_step_match,
        dispatch_step_stream=fake_dispatch_stream,
        yield_skill_view_preface=fake_preface,
    )]

    step_states = [
        (ev.step_id, ev.state)
        for ev in events
        if isinstance(ev, MetaStepStateEvent)
    ]
    assert ("intake", "running") in step_states
    assert ("intake", "succeeded") in step_states


@pytest.mark.asyncio
async def test_running_precedes_succeeded(make_two_step_match, fake_dispatch_stream, fake_preface):
    from opensquilla.skills.meta.scheduler import run_dag

    seq = []
    async for ev in run_dag(
        make_two_step_match,
        dispatch_step_stream=fake_dispatch_stream,
        yield_skill_view_preface=fake_preface,
    ):
        if isinstance(ev, MetaStepStateEvent) and ev.step_id == "intake":
            seq.append(ev.state)
    assert seq.index("running") < seq.index("succeeded")
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_step_events.py -v
```

Expected: 没有 MetaStepStateEvent 在 stream 中。

- [ ] **Step 3: 在 scheduler.py 加 running/succeeded 发布**

在 `_run_one(step)` 函数内：

(a) 紧随 `step_use_id = f"meta_step_{step.id}"` 之后、`event_queue.put((step.id, ToolUseStartEvent(...)))` 之前，加：

```python
            await event_queue.put((
                step.id,
                MetaStepStateEvent(
                    run_id=_run_id,
                    step_id=step.id,
                    state="running",
                    status_text=_default_status_text(step, effective_skill),
                ),
            ))
```

(b) 紧随 step 成功路径的 `event_queue.put((step.id, _StepDone(text=final_text)))` 之前，加：

```python
            await event_queue.put((
                step.id,
                MetaStepStateEvent(
                    run_id=_run_id,
                    step_id=step.id,
                    state="succeeded",
                ),
            ))
```

并在文件顶部 import：

```python
from opensquilla.engine.types import (
    AgentEvent,
    MetaRunAnnouncedEvent,
    MetaStepStateEvent,
    ToolResultEvent,
    ToolUseStartEvent,
)
```

`_default_status_text` 在 `scheduler.py` 顶部加 module-level helper：

```python
def _default_status_text(step: MetaStep, effective_skill: str) -> str:
    """Default status_text per step kind (design §3.3)."""
    if step.kind == "llm_chat":
        return "起草中…"
    if step.kind == "llm_classify":
        return "分类中…"
    if step.kind == "agent":
        return f"调用 {effective_skill} 中…"
    if step.kind == "skill_exec":
        return f"执行 {effective_skill} 中…"
    if step.kind == "tool_call":
        return f"调用 {step.tool}…"
    if step.kind == "user_input":
        return "等待你回复表单"
    return "运行中…"
```

`_run_id` 在 Task 7 已注入到 `run_dag` 局部作用域；`_run_one` 是 `run_dag` 内嵌函数，可直接闭包捕获。

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_step_events.py -v
```

- [ ] **Step 5: 回归**

```bash
uv run pytest tests -k "meta" -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/skills/meta/scheduler.py tests/test_meta_skill_step_events.py
git commit -m "$(cat <<'EOF'
Emit running and succeeded states for meta-skill steps

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: scheduler 发布 step_state(skipped)

**Files:**

- Modify: `src/opensquilla/skills/meta/scheduler.py`
- Modify: `tests/test_meta_skill_step_events.py`（追加 cases）

- [ ] **Step 1: 追加失败测试**

在 `tests/test_meta_skill_step_events.py` 追加：

```python
@pytest.fixture
def make_skipped_match():
    from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaStep

    plan = MetaPlan(
        name="meta-skip-fake",
        triggers=("fake",),
        priority=0,
        steps=(
            MetaStep(id="intake", skill="intake", kind="llm_chat", label="意图提取"),
            MetaStep(
                id="optional", skill="optional", kind="llm_chat",
                label="可选", depends_on=("intake",), when="False",
            ),
        ),
        final_text_mode="raw",
    )
    return MetaMatch(plan=plan, inputs={"user_message": "hi"})


@pytest.mark.asyncio
async def test_skipped_emitted_on_when_false(make_skipped_match, fake_dispatch_stream, fake_preface):
    from opensquilla.skills.meta.scheduler import run_dag

    states = [
        (ev.step_id, ev.state)
        async for ev in run_dag(
            make_skipped_match,
            dispatch_step_stream=fake_dispatch_stream,
            yield_skill_view_preface=fake_preface,
        )
        if isinstance(ev, MetaStepStateEvent)
    ]
    assert ("optional", "skipped") in states
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_step_events.py::test_skipped_emitted_on_when_false -v
```

- [ ] **Step 3: 修改 scheduler.py skip 分支**

在 `_run_one` 函数中、`if not evaluate_when(...)` 分支内，紧随 `await event_queue.put((step.id, _StepDone(text="", status="skipped")))` **之前**追加：

```python
            await event_queue.put((
                step.id,
                MetaStepStateEvent(
                    run_id=_run_id,
                    step_id=step.id,
                    state="skipped",
                ),
            ))
```

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_step_events.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/skills/meta/scheduler.py tests/test_meta_skill_step_events.py
git commit -m "$(cat <<'EOF'
Emit skipped state when meta-step when-condition is false

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 10: scheduler 发布 step_state(failed / substituted)

**Files:**

- Modify: `src/opensquilla/skills/meta/scheduler.py`
- Modify: `tests/test_meta_skill_step_events.py`

- [ ] **Step 1: 追加失败测试**

```python
@pytest.fixture
def failing_dispatch():
    from opensquilla.skills.meta.events import _StepDone

    async def _dispatch(step, effective_skill, inputs, outputs):
        if step.id == "search":
            raise RuntimeError("simulated step failure")
        yield _StepDone(text=f"out:{step.id}")

    return _dispatch


@pytest.fixture
def make_failover_match():
    from opensquilla.skills.meta.types import MetaMatch, MetaPlan, MetaStep

    plan = MetaPlan(
        name="meta-fail-fake",
        triggers=("fake",),
        priority=0,
        steps=(
            MetaStep(
                id="search", skill="search", kind="agent", label="检索",
                on_failure="search_fallback",
            ),
            MetaStep(
                id="search_fallback", skill="search_fallback",
                kind="llm_chat", label="替代检索",
            ),
        ),
        final_text_mode="raw",
    )
    return MetaMatch(plan=plan, inputs={"user_message": "hi"})


@pytest.mark.asyncio
async def test_failed_then_substituted(make_failover_match, failing_dispatch, fake_preface):
    from opensquilla.skills.meta.scheduler import run_dag

    states = []
    async for ev in run_dag(
        make_failover_match,
        dispatch_step_stream=failing_dispatch,
        yield_skill_view_preface=fake_preface,
    ):
        if isinstance(ev, MetaStepStateEvent):
            states.append((ev.step_id, ev.state, ev.substitute_for))

    assert ("search", "failed", None) in states
    assert ("search_fallback", "substituted", "search") in states
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_step_events.py::test_failed_then_substituted -v
```

- [ ] **Step 3: 修改 scheduler.py fail/failover 分支**

在 `_run_one` 的 `except Exception` 分支里，紧随 `event_queue.put((step.id, ToolResultEvent(..., is_error=True, ...)))` **之后**追加：

```python
            await event_queue.put((
                step.id,
                MetaStepStateEvent(
                    run_id=_run_id,
                    step_id=step.id,
                    state="failed",
                    error=str(exc),
                ),
            ))
```

另外，在 scheduler 主循环中找到处理 `_FailoverTriggered` 的分支（dispatch substitute 时），紧随派发 substitute step 之前或之后，加：

```python
            await event_queue.put((
                substitute_id,
                MetaStepStateEvent(
                    run_id=_run_id,
                    step_id=substitute_id,
                    state="substituted",
                    substitute_for=failed_step_id,
                ),
            ))
```

substitute 之后该 step 继续走 `_run_one`，但它已经进入 substituted 标识，后续如果成功仍会发 `succeeded`（前端按"以最后一次为准"渲染）。

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_step_events.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/skills/meta/scheduler.py tests/test_meta_skill_step_events.py
git commit -m "$(cat <<'EOF'
Emit failed and substituted states for meta-skill failover

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 11: scheduler 发布 meta_run_completed

**Files:**

- Modify: `src/opensquilla/skills/meta/scheduler.py`
- Modify: `tests/test_meta_skill_step_events.py`

- [ ] **Step 1: 追加失败测试**

```python
@pytest.mark.asyncio
async def test_run_completed_emitted_at_end(make_two_step_match, fake_dispatch_stream, fake_preface):
    from opensquilla.engine.types import MetaRunCompletedEvent
    from opensquilla.skills.meta.scheduler import run_dag

    completed = None
    async for ev in run_dag(
        make_two_step_match,
        dispatch_step_stream=fake_dispatch_stream,
        yield_skill_view_preface=fake_preface,
    ):
        if isinstance(ev, MetaRunCompletedEvent):
            completed = ev
            break

    assert completed is not None
    assert completed.outcome == "ok"
    assert sorted(completed.completed_steps) == ["intake", "summary"]
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_step_events.py::test_run_completed_emitted_at_end -v
```

- [ ] **Step 3: 修改 scheduler.py 末尾**

在 `run_dag` 主循环结束、`yield MetaResult(...)` **之前**追加：

```python
    # Classify each step's terminal state for the completion event by
    # scanning ``outputs`` (filled on success) and the failed/skipped
    # tracking sets the scheduler already maintains. Outcome is "ok" iff
    # nothing failed.
    completed_ids = [sid for sid in outputs if outputs[sid] != "" or sid in succeeded_step_ids]
    failed_ids = sorted(failed_step_ids)
    skipped_ids = sorted(skipped_step_ids)
    outcome = "failed" if failed_ids else "ok"
    yield MetaRunCompletedEvent(
        run_id=_run_id,
        outcome=outcome,
        completed_steps=sorted(completed_ids),
        failed_steps=failed_ids,
        skipped_steps=skipped_ids,
    )
```

并把 `MetaRunCompletedEvent` 加进 import。`succeeded_step_ids` / `failed_step_ids` / `skipped_step_ids` 若 scheduler 主循环未跟踪，则在主循环 dispatch/queue 处理处添加 3 个 set：

- `succeeded_step_ids: set[str] = set()` ←  `_StepDone(status != "skipped")` 处加入
- `failed_step_ids: set[str] = set()` ← `is_error=True` 处加入
- `skipped_step_ids: set[str] = set()` ← `_StepDone(status="skipped")` 处加入

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_step_events.py -v
```

- [ ] **Step 5: 回归**

```bash
uv run pytest tests -k "meta" -q
```

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/skills/meta/scheduler.py tests/test_meta_skill_step_events.py
git commit -m "$(cat <<'EOF'
Yield meta-run completion event at scheduler end

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 12: 前端 CSS — meta-ribbon 样式

**Files:**

- Create: `src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css`

- [ ] **Step 1: 写文件**

```css
/* MetaSkill run progress ribbon — design §2, §8.3. */

.meta-ribbon {
  border: 1px solid var(--border-subtle, #d0d7de);
  border-radius: 8px;
  padding: 8px 12px;
  margin: 8px 0;
  background: var(--surface-1, #f6f8fa);
  font-size: 0.9em;
}

.meta-ribbon-head {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}

.meta-ribbon-toggle {
  background: none;
  border: none;
  cursor: pointer;
  padding: 0;
  font-size: 1em;
  color: inherit;
}

.meta-ribbon-title {
  font-weight: 600;
  flex: 1;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.meta-ribbon-counter {
  color: var(--text-subtle, #57606a);
  font-variant-numeric: tabular-nums;
}

.meta-ribbon-chips {
  list-style: none;
  padding: 0;
  margin: 0;
  display: flex;
  gap: 6px;
  overflow-x: auto;
  scroll-behavior: smooth;
}

.meta-ribbon-chips .chip {
  flex: 0 0 auto;
  padding: 3px 10px;
  border-radius: 999px;
  background: var(--chip-bg, #e7ebf0);
  color: var(--text-subtle, #57606a);
  cursor: pointer;
  white-space: nowrap;
  transition: background 120ms, color 120ms;
}

.meta-ribbon-chips .chip.pending { opacity: 0.6; }
.meta-ribbon-chips .chip.running {
  background: var(--accent-soft, #ddf4ff);
  color: var(--accent, #0969da);
  font-weight: 600;
}
.meta-ribbon-chips .chip.succeeded {
  background: var(--success-soft, #dafbe1);
  color: var(--success, #1a7f37);
}
.meta-ribbon-chips .chip.failed {
  background: var(--danger-soft, #ffebe9);
  color: var(--danger, #cf222e);
  font-weight: 600;
}
.meta-ribbon-chips .chip.skipped {
  opacity: 0.4;
  text-decoration: line-through;
}
.meta-ribbon-chips .chip.substituted {
  background: var(--warn-soft, #fff8c5);
  color: var(--warn, #9a6700);
}

.meta-ribbon-chips .chip.running::after {
  content: " ●";
  animation: meta-ribbon-pulse 1.2s infinite;
}

@keyframes meta-ribbon-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.meta-ribbon-status {
  margin-top: 6px;
  color: var(--text-subtle, #57606a);
  min-height: 1.2em;
}

.meta-ribbon[data-collapsed="true"] .meta-ribbon-chips,
.meta-ribbon[data-collapsed="true"] .meta-ribbon-actions {
  display: none;
}

.meta-ribbon-actions {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

.meta-ribbon-actions button {
  padding: 4px 10px;
  border-radius: 6px;
  border: 1px solid var(--border-subtle, #d0d7de);
  background: var(--surface-2, #fff);
  cursor: pointer;
  font-size: 0.9em;
}

.meta-ribbon-actions button:hover {
  background: var(--accent-soft, #ddf4ff);
}
```

- [ ] **Step 2: 在 chat 主 CSS 入口注册**

`src/opensquilla/gateway/static/css/views/chat.css` 找到 `@import` 段（如果存在）或加 link 引用方式。若 chat.css 无 import，则在 `templates/` 的 HTML 模板里 `<link>` 注册：

```bash
grep -rn "chat\.css" src/opensquilla/gateway/templates/ | head -5
```

按结果加新的 `<link rel="stylesheet" href="/static/css/views/chat-meta-ribbon.css">`。

- [ ] **Step 3: 静态验证 CSS 解析**

```bash
uv run python -c "from pathlib import Path; print(Path('src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css').read_text()[:200])"
```

- [ ] **Step 4: Commit**

```bash
git add src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css \
        src/opensquilla/gateway/templates/  # 如果模板被改
git commit -m "$(cat <<'EOF'
Style meta-skill run progress ribbon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 13: 前端 JS — meta-ribbon 核心模块

**Files:**

- Create: `src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js`

- [ ] **Step 1: 写模块**

```javascript
// MetaSkill run progress ribbon — design §8.
// Pure render functions; chat.js wires the event handlers and DOM root.

const STATE_GLYPH = {
  pending: '○',
  running: '⚙',
  succeeded: '✓',
  failed: '✗',
  skipped: '↷',
  substituted: '⇄',
};

function humanizeStepId(id) {
  if (!id) return '';
  return id.charAt(0).toUpperCase() + id.slice(1).replace(/[_-]/g, ' ');
}

export function createRibbon(announce) {
  return {
    runId: announce.run_id,
    metaSkillName: announce.meta_skill_name,
    steps: (announce.steps || []).map((s) => ({
      id: s.id,
      label: s.label || humanizeStepId(s.id),
      kind: s.kind,
      dependsOn: s.depends_on || [],
      state: 'pending',
      statusText: '',
      error: '',
      substituteFor: null,
    })),
    total: announce.total || 0,
    collapsed: false,
    runOutcome: null,
    currentIndex: 0,
  };
}

export function updateStep(state, stepStateEvent) {
  const step = state.steps.find((s) => s.id === stepStateEvent.step_id);
  if (!step) return state;
  step.state = stepStateEvent.state;
  if (stepStateEvent.status_text != null) step.statusText = stepStateEvent.status_text;
  if (stepStateEvent.error) step.error = stepStateEvent.error;
  if (stepStateEvent.substitute_for) step.substituteFor = stepStateEvent.substitute_for;
  state.currentIndex = Math.max(
    state.currentIndex,
    state.steps.findIndex((s) => s.id === step.id),
  );
  return state;
}

export function completeRun(state, completedEvent) {
  state.runOutcome = completedEvent.outcome;
  return state;
}

export function renderRibbon(rootEl, state) {
  const completedCount = state.steps.filter(
    (s) => s.state === 'succeeded' || s.state === 'skipped' || s.state === 'substituted',
  ).length;
  const runningIndex = state.steps.findIndex((s) => s.state === 'running');
  const headerIndex = runningIndex >= 0 ? runningIndex + 1 : completedCount;

  rootEl.classList.add('meta-ribbon');
  rootEl.setAttribute('data-run-id', state.runId);
  rootEl.setAttribute('data-collapsed', String(state.collapsed));
  rootEl.setAttribute('role', 'region');
  rootEl.setAttribute(
    'aria-label',
    `MetaSkill ${state.metaSkillName} run progress: ${headerIndex} of ${state.total}`,
  );

  const currentStep = runningIndex >= 0 ? state.steps[runningIndex] : null;
  const statusText = currentStep ? currentStep.statusText || '运行中…' : '';

  rootEl.innerHTML = `
    <header class="meta-ribbon-head">
      <button class="meta-ribbon-toggle" aria-label="折叠/展开 ribbon">${state.collapsed ? '▶' : '▼'}</button>
      <span class="meta-ribbon-title">${escapeHtml(state.metaSkillName)}</span>
      <span class="meta-ribbon-counter">${headerIndex}/${state.total}</span>
    </header>
    <ol class="meta-ribbon-chips" aria-live="polite">
      ${state.steps.map((s, i) => `
        <li class="chip ${s.state}" data-step-id="${escapeAttr(s.id)}"
            tabindex="0"
            aria-label="step ${i + 1} of ${state.total}: ${escapeAttr(s.label)} ${s.state}">
          ${STATE_GLYPH[s.state] || '○'} ${escapeHtml(s.label)}
        </li>
      `).join('')}
    </ol>
    <div class="meta-ribbon-status">${escapeHtml(statusText)}</div>
    <div class="meta-ribbon-actions" ${shouldShowActions(state) ? '' : 'hidden'}>
      ${shouldShowActions(state) ? renderActions(state) : ''}
    </div>
  `;

  wireToggle(rootEl, state);
  wireChipClicks(rootEl);
  wireActionClicks(rootEl, state);

  return rootEl;
}

function shouldShowActions(state) {
  return state.steps.some((s) => s.state === 'failed');
}

function renderActions(state) {
  const failedStep = state.steps.find((s) => s.state === 'failed');
  const errText = failedStep ? failedStep.error || '步骤失败' : '';
  return `
    <span class="meta-ribbon-fail-summary">
      ✗ ${escapeHtml(failedStep.label)} 失败 · ${escapeHtml(truncate(errText, 80))}
    </span>
    <button data-action="retry-run">重试整个 run</button>
    <button data-action="switch-skill">切换 meta-skill…</button>
    <button data-action="show-detail" data-step-id="${escapeAttr(failedStep.id)}">查看错误详情</button>
  `;
}

function wireToggle(rootEl, state) {
  const btn = rootEl.querySelector('.meta-ribbon-toggle');
  if (!btn) return;
  btn.addEventListener('click', () => {
    state.collapsed = !state.collapsed;
    renderRibbon(rootEl, state);
  });
}

function wireChipClicks(rootEl) {
  rootEl.querySelectorAll('.meta-ribbon-chips .chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const stepId = chip.getAttribute('data-step-id');
      const card = document.querySelector(
        `[data-tool-use-id="meta_step_${cssEscape(stepId)}"]`,
      );
      if (card && typeof card.scrollIntoView === 'function') {
        card.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    });
  });
}

function wireActionClicks(rootEl, state) {
  rootEl.querySelectorAll('.meta-ribbon-actions button').forEach((btn) => {
    btn.addEventListener('click', (ev) => {
      const action = btn.getAttribute('data-action');
      const stepId = btn.getAttribute('data-step-id');
      rootEl.dispatchEvent(new CustomEvent('meta-ribbon-action', {
        bubbles: true,
        detail: { action, stepId, runId: state.runId },
      }));
    });
  });
}

function escapeHtml(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function escapeAttr(s) {
  return escapeHtml(s);
}

function truncate(s, n) {
  const str = String(s ?? '');
  return str.length <= n ? str : str.slice(0, n - 1) + '…';
}

function cssEscape(s) {
  if (window.CSS && typeof window.CSS.escape === 'function') return window.CSS.escape(s);
  return String(s ?? '').replace(/[^a-zA-Z0-9_-]/g, '\\$&');
}
```

- [ ] **Step 2: 静态语法检查**

```bash
node -c src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js \
  || python3 -c "import esprima; esprima.parseModule(open('src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js').read())"
```

如果两者都不可用，跳过 syntax check（静态测试 Task 17 会覆盖）。

- [ ] **Step 3: Commit**

```bash
git add src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js
git commit -m "$(cat <<'EOF'
Render meta-skill run progress ribbon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 14: chat.js 接线 3 个 handler + DOM 插入

**Files:**

- Modify: `src/opensquilla/gateway/static/js/views/chat.js`

- [ ] **Step 1: 定位事件 dispatcher**

```bash
grep -n "session\.event\.\|onEvent\|handleEvent\|switch (event" src/opensquilla/gateway/static/js/views/chat.js | head -30
```

定位 dispatcher 函数位置（或事件名 switch/if 链）。

- [ ] **Step 2: 在 dispatcher 顶部 import**

在 `chat.js` 顶部已有 import 段加：

```javascript
import {
  createRibbon,
  updateStep,
  completeRun,
  renderRibbon,
} from './chat/meta-ribbon.js';

const _metaRibbonState = new Map();  // run_id → ribbon state
const _metaRibbonEl = new Map();      // run_id → DOM element
```

- [ ] **Step 3: 注册 3 个 handler**

在 dispatcher 中加 3 个分支（紧邻已有事件分支）：

```javascript
if (eventName === 'session.event.meta_run_announced') {
  const state = createRibbon(payload);
  _metaRibbonState.set(state.runId, state);
  const el = document.createElement('section');
  el.dataset.runId = state.runId;
  // 插入位置：当前 turn 容器内、第一个 meta-step tool-card 之前。
  // 这里用临时方案：插入到当前 turn 末尾，由 CSS order 控制；
  // 待 turn 容器对象稳定后改为前插。
  const turnEl = document.querySelector('[data-current-turn]') || document.body;
  turnEl.prepend(el);
  _metaRibbonEl.set(state.runId, el);
  renderRibbon(el, state);
  return;
}

if (eventName === 'session.event.meta_step_state') {
  const state = _metaRibbonState.get(payload.run_id);
  const el = _metaRibbonEl.get(payload.run_id);
  if (!state || !el) return;
  updateStep(state, payload);
  renderRibbon(el, state);
  return;
}

if (eventName === 'session.event.meta_run_completed') {
  const state = _metaRibbonState.get(payload.run_id);
  const el = _metaRibbonEl.get(payload.run_id);
  if (!state || !el) return;
  completeRun(state, payload);
  renderRibbon(el, state);
  return;
}
```

- [ ] **Step 4: 接 action 事件**

在文件靠 dispatcher 注册附近加：

```javascript
document.addEventListener('meta-ribbon-action', (ev) => {
  const { action, stepId, runId } = ev.detail || {};
  if (action === 'retry-run') {
    // 简版：把上次 user_message 重发
    if (typeof window.__opensquillaResendLastUserMessage === 'function') {
      window.__opensquillaResendLastUserMessage();
    }
  } else if (action === 'switch-skill') {
    // MVP 简版：把焦点放回输入框 + placeholder 提示
    const input = document.querySelector('[data-chat-input]');
    if (input) {
      input.placeholder = '想换哪个 meta-skill？例如：Use meta-skill `meta-web-research-to-report`';
      input.focus();
    }
  } else if (action === 'show-detail') {
    const card = document.querySelector(`[data-tool-use-id="meta_step_${stepId}"]`);
    if (card) {
      card.setAttribute('data-expanded', 'true');
      if (typeof card.scrollIntoView === 'function') {
        card.scrollIntoView({ block: 'center', behavior: 'smooth' });
      }
    }
  }
});
```

`__opensquillaResendLastUserMessage` / `[data-chat-input]` / `[data-current-turn]` 假定 chat.js 已暴露这些钩子；如果当前命名不同，按现有 chat.js 实际命名替换。

- [ ] **Step 5: 静态测试钩子（占位）**

ribbon 模块的 DOM 渲染本身在 Task 17 测试。本 step 只检查 chat.js 没 ruff/类型回归（前端无类型，主要看语法）：

```bash
uv run pytest tests/test_gateway/test_chat_view_static.py -v
```

Expected: 现有静态测试不回归（chat.js 仍能被解析、关键模板 token 仍在）。

- [ ] **Step 6: Commit**

```bash
git add src/opensquilla/gateway/static/js/views/chat.js
git commit -m "$(cat <<'EOF'
Wire meta-skill ribbon events into chat dispatcher

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 15: 前端静态测试 — DOM 渲染

**Files:**

- Create: `tests/test_gateway/test_chat_meta_ribbon_static.py`

- [ ] **Step 1: 写测试**

```python
"""meta-ribbon.js DOM 渲染契约（静态 / 基于读文件 + 简易 string assert）。

完整 DOM 行为由 Task 18 的 browser E2E 覆盖；本测试锁结构与字符串。
"""

from pathlib import Path

import pytest

RIBBON_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js")
RIBBON_CSS = Path("src/opensquilla/gateway/static/css/views/chat-meta-ribbon.css")
CHAT_JS = Path("src/opensquilla/gateway/static/js/views/chat.js")


def test_ribbon_module_exists():
    assert RIBBON_JS.exists()
    text = RIBBON_JS.read_text()
    for export in ("createRibbon", "updateStep", "completeRun", "renderRibbon"):
        assert f"export function {export}" in text, f"missing export {export}"


def test_ribbon_glyph_table_covers_all_states():
    text = RIBBON_JS.read_text()
    for state in ("pending", "running", "succeeded", "failed", "skipped", "substituted"):
        assert f"{state}:" in text, f"STATE_GLYPH missing {state}"


def test_ribbon_css_has_chip_state_classes():
    text = RIBBON_CSS.read_text()
    for cls in ("chip.pending", "chip.running", "chip.succeeded",
                "chip.failed", "chip.skipped", "chip.substituted"):
        assert cls in text, f"CSS missing {cls}"


def test_chat_js_imports_ribbon_module():
    text = CHAT_JS.read_text()
    assert "chat/meta-ribbon.js" in text
    assert "createRibbon" in text
    assert "updateStep" in text
    assert "completeRun" in text


def test_chat_js_dispatches_meta_events():
    text = CHAT_JS.read_text()
    assert "session.event.meta_run_announced" in text
    assert "session.event.meta_step_state" in text
    assert "session.event.meta_run_completed" in text


def test_chat_js_handles_ribbon_action_events():
    text = CHAT_JS.read_text()
    assert "meta-ribbon-action" in text
    for action in ("retry-run", "switch-skill", "show-detail"):
        assert action in text, f"chat.js missing action {action}"
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_gateway/test_chat_meta_ribbon_static.py -v
```

Expected: 全 PASS（Task 12-14 已实现）。

- [ ] **Step 3: Commit**

```bash
git add tests/test_gateway/test_chat_meta_ribbon_static.py
git commit -m "$(cat <<'EOF'
Lock meta-ribbon DOM and dispatcher contract

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 16: 前端静态测试 — 失败动作行

**Files:**

- Create: `tests/test_gateway/test_chat_meta_ribbon_failure.py`

- [ ] **Step 1: 写测试**

```python
"""失败 chip 的动作行渲染 + show-detail 行为 — 通过最小 JSDOM 等价模拟。

由于仓库无 JS 测试 runner，这里采用与现有 test_gateway_static_skills_view.py
相同的"读取 + assert 文本契约"策略；行为细节由 E2E 覆盖。
"""

from pathlib import Path

RIBBON_JS = Path("src/opensquilla/gateway/static/js/views/chat/meta-ribbon.js")


def test_action_row_renders_three_buttons():
    text = RIBBON_JS.read_text()
    # renderActions 必须存在 3 个动作按钮
    assert 'data-action="retry-run"' in text
    assert 'data-action="switch-skill"' in text
    assert 'data-action="show-detail"' in text


def test_action_row_only_when_failed_step_present():
    text = RIBBON_JS.read_text()
    assert "shouldShowActions" in text
    # The boolean comes from any step with state === 'failed'
    assert "'failed'" in text


def test_fail_summary_shows_error_truncated():
    text = RIBBON_JS.read_text()
    # 错误文本走 truncate(errText, 80)
    assert "truncate(errText, 80)" in text
```

- [ ] **Step 2: 运行测试**

```bash
uv run pytest tests/test_gateway/test_chat_meta_ribbon_failure.py -v
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_gateway/test_chat_meta_ribbon_failure.py
git commit -m "$(cat <<'EOF'
Lock failure action row contract on meta-ribbon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 17: E2E browser 测试

**Files:**

- Modify: `tests/functional/test_webui_browser_chat_e2e.py`

- [ ] **Step 1: 定位现有 E2E gate**

```bash
grep -n "OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E\|def test_chat_" tests/functional/test_webui_browser_chat_e2e.py | head -20
```

- [ ] **Step 2: 加 E2E case**

在该文件追加：

```python
@pytest.mark.skipif(
    not os.environ.get("OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E"),
    reason="set OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 to run browser e2e",
)
def test_meta_skill_ribbon_renders_and_progresses_in_real_browser(
    live_gateway, browser_page,
):
    """跑一个 stub meta-skill 后 ribbon 出现、chip 状态推进。"""
    browser_page.goto(live_gateway.url)
    browser_page.fill('[data-chat-input]', 'Use meta-skill `meta-stub-two-step`.')
    browser_page.press('[data-chat-input]', 'Enter')

    # ribbon 出现
    browser_page.wait_for_selector('.meta-ribbon', timeout=10_000)
    ribbon = browser_page.query_selector('.meta-ribbon')
    assert ribbon is not None
    assert ribbon.query_selector('.chip') is not None

    # 等到 ribbon counter 推进到 2/2
    browser_page.wait_for_function(
        "() => document.querySelector('.meta-ribbon-counter')?.textContent === '2/2'",
        timeout=20_000,
    )
```

`meta-stub-two-step` 假设存在于 functional 测试 fixture stub skill 集合；如果不存在，先在测试夹具里 register 一个最小 2-step stub plan。

- [ ] **Step 3: 本地手动运行（CI 跳过）**

```bash
OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run pytest \
  tests/functional/test_webui_browser_chat_e2e.py::test_meta_skill_ribbon_renders_and_progresses_in_real_browser -v -s
```

Expected: 浏览器看到 ribbon 渲染、推进、最后 2/2。

- [ ] **Step 4: Commit**

```bash
git add tests/functional/test_webui_browser_chat_e2e.py
git commit -m "$(cat <<'EOF'
Verify meta-skill ribbon end-to-end in real browser

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 18: 3 个高频 meta-skill 补 label

**Files:**

- Modify: `src/opensquilla/skills/bundled/meta-document-to-decision/SKILL.md`
- Modify: `src/opensquilla/skills/bundled/meta-web-research-to-report/SKILL.md`
- Modify: `src/opensquilla/skills/bundled/meta-daily-operator-brief/SKILL.md`

- [ ] **Step 1: 写测试锚定 label 出现**

新建 `tests/test_meta_skill_label_coverage.py`：

```python
"""3 个高频 meta-skill 的 step 都声明 label。"""

from pathlib import Path

import pytest
import yaml


HIGH_FREQ = [
    "meta-document-to-decision",
    "meta-web-research-to-report",
    "meta-daily-operator-brief",
]


def _extract_frontmatter(path: Path) -> dict:
    text = path.read_text()
    assert text.startswith("---"), f"{path}: missing YAML frontmatter"
    end = text.index("\n---", 3)
    return yaml.safe_load(text[3:end])


@pytest.mark.parametrize("name", HIGH_FREQ)
def test_each_step_has_label(name):
    path = Path(f"src/opensquilla/skills/bundled/{name}/SKILL.md")
    fm = _extract_frontmatter(path)
    steps = fm["composition"]["steps"]
    missing = [s["id"] for s in steps if not s.get("label")]
    assert not missing, f"{name}: steps missing label: {missing}"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
uv run pytest tests/test_meta_skill_label_coverage.py -v
```

Expected: 3 个 skill 都缺 label。

- [ ] **Step 3: 给 3 个 SKILL.md 每个 step 加 label**

打开三份 SKILL.md，对每个 step 在 `id:` 下一行加 `label: "<中文 2-4 字>"`。建议命名：

`meta-document-to-decision`：
- intake → `意图提取`
- classify → `分类`
- evidence → `提取证据`
- recommend → `给出建议`
- audit → `审查`

`meta-web-research-to-report`：
- intake → `意图提取`
- search → `检索`
- synthesize → `综合`
- audit → `审稿`

`meta-daily-operator-brief`：
- intake → `意图提取`
- prioritize → `优先级排序`
- compose → `撰写`

具体 step id 以现有 SKILL.md 实际为准；上述只是示例。

- [ ] **Step 4: 运行测试确认通过**

```bash
uv run pytest tests/test_meta_skill_label_coverage.py -v
```

- [ ] **Step 5: Commit**

```bash
git add src/opensquilla/skills/bundled/meta-document-to-decision/SKILL.md \
        src/opensquilla/skills/bundled/meta-web-research-to-report/SKILL.md \
        src/opensquilla/skills/bundled/meta-daily-operator-brief/SKILL.md \
        tests/test_meta_skill_label_coverage.py
git commit -m "$(cat <<'EOF'
Label high-frequency meta-skill steps for ribbon display

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 19: 文档更新

**Files:**

- Modify: `docs/authoring/meta-skills.md`

- [ ] **Step 1: 在"Step Types"章节之后插入"Step Labels and Progress"小节**

定位 `docs/authoring/meta-skills.md` 中 "Step Types" 章节末尾，插入：

```markdown
## Step Labels and Progress

Two optional step-level fields drive the WebUI run progress ribbon
(see [`../features/meta-skill-user-guide.md`](../features/meta-skill-user-guide.md)
"Run progress ribbon"):

- `label`: a short, human-readable name for the step. The ribbon
  renders this as the chip text. If omitted, the WebUI humanizes the
  step `id` (e.g. `intake` → `Intake`).
- `progress_emits`: whether the step's executor may publish live
  `status_text` updates to the ribbon. Defaults:
  - `agent` / `skill_exec`: `true`
  - `tool_call`: `false`
  - `llm_chat` / `llm_classify` / `user_input`: ignored

Example:

```yaml
composition:
  steps:
    - id: intake
      kind: llm_chat
      label: 意图提取
      with: { ... }
    - id: search
      kind: agent
      skill: web-research
      label: 检索证据
      progress_emits: true
      with: { ... }
```

Set short labels (2-6 chars in CJK, 1-2 words in English). Long labels
get truncated in the ribbon header.
```

- [ ] **Step 2: 在用户指南也提一句**

修改 `docs/features/meta-skill-user-guide.md`，在 "Reading the Result" 之前加 "Run Progress Ribbon" 小节：

```markdown
## Run Progress Ribbon

While a MetaSkill runs, the WebUI shows a horizontal ribbon at the top
of the agent reply listing every step in the workflow. The currently
running chip is highlighted; succeeded steps show ✓, skipped ↷, failed
✗. Click any chip to scroll to that step's tool card. If a step fails,
the ribbon also surfaces "Retry run", "Switch meta-skill", and "Show
error detail" actions inline.
```

- [ ] **Step 3: 文档静态测试**

```bash
grep -n "Step Labels and Progress\|Run Progress Ribbon" docs/authoring/meta-skills.md docs/features/meta-skill-user-guide.md
```

Expected: 两节都存在。

- [ ] **Step 4: Commit**

```bash
git add docs/authoring/meta-skills.md docs/features/meta-skill-user-guide.md
git commit -m "$(cat <<'EOF'
Document step labels and run progress ribbon

Co-Authored-By: Claude Opus 4.7 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 20: 全量回归 + lint + mypy

- [ ] **Step 1: 全量测试**

```bash
uv run pytest tests -q
```

Expected: 全绿。

- [ ] **Step 2: lint**

```bash
uv run ruff check src tests
```

- [ ] **Step 3: 类型**

```bash
uv run mypy src/opensquilla --show-error-codes
```

- [ ] **Step 4: 静态资源验证**

```bash
uv run pytest tests/test_gateway/test_chat_static_assets.py tests/test_gateway_static_skills_view.py -v
```

- [ ] **Step 5: 公共 PR 净度检查**

```bash
git diff origin/dev..HEAD --check
git diff origin/dev..HEAD | grep -iE "personal|email|/home/|secret|token=" || echo "clean"
```

- [ ] **Step 6: 写 PR 草稿（可选，本地用）**

把 PR description 草稿写到 `docs/proposals/plans/2026-06-04-meta-skill-run-progress-pr-draft.md`（本地）：

```
Subject: Surface meta-skill run progress as a step ribbon

Summary:
- 新增 3 个 engine 事件（announced / step_state / completed），scheduler 在 6 处发布
- 新增独立模块 `chat/meta-ribbon.js` + 独立 CSS，chat.js 只做接线
- 新增可选 SKILL.md 字段 `label:` / `progress_emits:`；3 个高频 meta-skill 补全 label
- 全量回归通过；E2E browser 测试覆盖渲染+推进+失败动作行

Constraints: ToolUseStart/Result 事件不变；CLI/MCP 不受影响。

Tested: uv run pytest tests -q
Tested: uv run ruff check src tests
Tested: uv run mypy src/opensquilla
Tested: OPENSQUILLA_WEBUI_BROWSER_CHAT_E2E=1 uv run pytest tests/functional/test_webui_browser_chat_e2e.py::test_meta_skill_ribbon_renders_and_progresses_in_real_browser
```

不创建 commit；本地 reference。

---

## Self-Review 备注

按 spec §11 13 步骨架对照：

- §11-1 types/事件类 → Task 1 ✅
- §11-2 scheduler 发布点 6 位置 → Task 7, 8, 9, 10, 11 ✅
- §11-3 replay buffer 安全 → Task 3 ✅
- §11-4 节流逻辑 → Task 6 ✅
- §11-5 SKILL.md schema 扩展 → Task 4, 5 ✅
- §11-6 后端单元 + 集成测试 → 每个 Task 都自带 ✅
- §11-7 前端 meta-ribbon.js → Task 13 ✅
- §11-8 CSS → Task 12 ✅
- §11-9 chat.js 接线 → Task 14 ✅
- §11-10 前端静态测试 → Task 15, 16 ✅
- §11-11 E2E → Task 17 ✅
- §11-12 9 个 meta-skill 补 label → Task 18（先 3 个高频，剩 6 个留下一 PR） ✅
- §11-13 文档 → Task 19 ✅

未覆盖但已显式 defer：

- 节流接到 scheduler 的实际接入：Task 6 仅建 helper；scheduler 当前 status_text 默认值在 Task 8 直接用 helper 跳过节流（一次性发不会触发节流问题）；agent 子 turn 的工具名回填到 status_text 涉及 subagent_announce 联动（spec R-1），属下一轮 P0-1.1 增强，本 plan 暂不覆盖。
- 6 个剩余 meta-skill 的 label 补全：在用户指南 / 全 catalog 看不到 label 时走 humanize 回退，不阻塞功能。
- bridge_event_name 公开 API：Task 2 Step 4 描述了"如果当前未暴露则加一行 thin wrapper"，执行时按实际代码确定改法。

---

## Execution Handoff

**Plan complete and saved to** `docs/proposals/plans/2026-06-04-meta-skill-run-progress-plan.md` (local, not committed per user policy).

Two execution options:

1. **Subagent-Driven (recommended)** — 每个 Task 派一个新 subagent，做完两段 review 再进下一个。隔离度高、节奏可控、上下文不互染。
2. **Inline Execution** — 在当前 session 用 executing-plans 串起来批量跑，关键节点 checkpoint review。

**Which approach?**
