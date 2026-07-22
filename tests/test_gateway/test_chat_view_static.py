"""Focused Vue chat wiring contracts retained after the vanilla UI removal."""

from pathlib import Path

CHAT_VIEW = Path("opensquilla-webui/src/views/ChatView.vue")
CHAT_SEND = Path("opensquilla-webui/src/composables/chat/useChatSend.ts")
CHAT_MESSAGE_ACTIONS = Path("opensquilla-webui/src/composables/chat/useChatMessageActions.ts")
ROUTER_FX = Path("opensquilla-webui/src/components/chat/RouterFxStrip.vue")


def test_router_fx_cells_expose_only_model_names() -> None:
    source = ROUTER_FX.read_text(encoding="utf-8")

    assert '<span class="nm-base">{{ cell.displayName }}</span>' in source
    assert '<span class="nm-win" aria-hidden="true">{{ cell.displayName }}</span>' in source
    assert ":data-kind" not in source
    assert ":data-tiers" not in source


def test_chat_view_wires_middle_edit_branch_fork_id() -> None:
    view = CHAT_VIEW.read_text(encoding="utf-8")
    send = CHAT_SEND.read_text(encoding="utf-8")
    actions = CHAT_MESSAGE_ACTIONS.read_text(encoding="utf-8")

    assert "const pendingForkBeforeMessageId = ref<string | null>(null)" in view

    actions_start = view.index("const chatMessageActions = useChatMessageActions({")
    actions_end = view.index("})\nconst {", actions_start)
    assert "pendingForkBeforeMessageId," in view[actions_start:actions_end]

    send_start = view.index("const chatSend = useChatSend({")
    send_end = view.index("})\nconst { onSend", send_start)
    assert "pendingForkBeforeMessageId," in view[send_start:send_end]

    session_watch_start = view.index("watch(sessionKey, () => {")
    session_watch_end = view.index("})", session_watch_start)
    assert "pendingForkBeforeMessageId.value = null" in view[session_watch_start:session_watch_end]

    assert "pendingForkBeforeMessageId: Ref<string | null>" in send
    assert "params.forkBeforeMessageId = forkBeforeMessageId" in send
    assert "options.pendingForkBeforeMessageId.value = null" in send
    assert (
        "options.pendingForkBeforeMessageId.value = "
        "options.messages.value[userMsgIndex]?.messageId || null"
    ) in actions
    assert (
        "options.pendingForkBeforeMessageId.value = "
        "options.messages.value[msgIndex]?.messageId || null"
    ) in actions
