"""Deterministic fast path for exact sandbox elevation actions."""

from __future__ import annotations

import re
import shlex
from typing import Literal

from opensquilla.engine.guardian_review import GuardianAssessment
from opensquilla.provider import Message
from opensquilla.sandbox.elevation import ElevationAction
from opensquilla.sandbox.operation_profile import OperationProfile, classify_command

LocalRiskLevel = Literal["low", "medium", "high", "critical"]

_DYNAMIC_SHELL_RE = re.compile(r"(?:`|\$\(|\$\{|\$[A-Za-z_]|[*?\[\]{}])")
_COMMAND_SPLIT_RE = re.compile(r"\s*(?:&&|;)\s*")
_LOW_RISK_CREATE_COMMANDS = frozenset({"echo", "mkdir", "printf", "touch"})
_DELETE_RE = re.compile(
    r"(?:^|[;&|]\s*)(?:sudo\s+)?(?:rm|rmdir|del|erase|remove-item)\b",
    flags=re.IGNORECASE,
)
_RECURSIVE_DELETE_RE = re.compile(
    r"\b(?:rm\s+(?:-[A-Za-z]*r[A-Za-z]*|--recursive)|"
    r"remove-item\b[^\n;&|]*\s-recurse\b|rmdir\s+/s\b)",
    flags=re.IGNORECASE,
)
_DOWNLOAD_EXEC_RE = re.compile(
    r"\b(?:curl|wget|invoke-webrequest|iwr)\b[^\n]*(?:\||&&|;)\s*"
    r"(?:sudo\s+)?(?:sh|bash|zsh|pwsh|powershell|python|node)\b",
    flags=re.IGNORECASE,
)
_OUTBOUND_TRANSFER_RE = re.compile(
    r"\b(?:curl|scp|sftp|rsync|invoke-webrequest|iwr|ftp)\b",
    flags=re.IGNORECASE,
)
_SECURITY_WEAKENING_RE = re.compile(
    r"\b(?:ufw\s+disable|setenforce\s+0|iptables\s+-F|"
    r"systemctl\s+(?:disable|mask)\b|disable-windowsoptionalfeature\b)",
    flags=re.IGNORECASE,
)
_SENSITIVE_SECRET_RE = re.compile(
    r"(?:^|[/\\])(?:\.ssh|\.aws|\.gnupg|\.kube)(?:[/\\]|$)|"
    r"(?:^|[/\\])(?:id_rsa|id_ed25519|credentials|shadow|sudoers)(?:$|[/\\])|"
    r"(?:^|[/\\])\.env(?:$|[/\\])",
    flags=re.IGNORECASE,
)
_POSIX_PATH_RE = re.compile(r"(?<![\w.])/(?:[^\s,，。；;:'\"<>|]+/?)+")
_WINDOWS_PATH_RE = re.compile(r"\b[A-Za-z]:[\\/][^\s,，。；;:'\"<>|]+")

_CREATE_WORDS = (
    "create",
    "make",
    "mkdir",
    "touch",
    "write",
    "创建",
    "新建",
    "写入",
    "生成",
)
_EDIT_WORDS = ("edit", "modify", "overwrite", "update", "编辑", "修改", "覆盖", "更新")
_DELETE_WORDS = ("delete", "remove", "unlink", "rm", "rmdir", "删除", "移除", "清理")
_INSTALL_WORDS = ("install", "add package", "安装", "装上", "添加依赖")
_NETWORK_WORDS = (
    "access",
    "fetch",
    "download",
    "request",
    "upload",
    "send",
    "访问",
    "请求",
    "下载",
    "上传",
    "发送",
    "联网",
)
_EXECUTE_WORDS = ("run", "execute", "start", "stop", "执行", "运行", "启动", "停止")


def _contains_any(text: str, words: tuple[str, ...]) -> bool:
    return any(word in text for word in words)


def _shell_command(action: ElevationAction) -> str:
    if action.action_kind != "shell.exec" or not action.argv:
        return ""
    return action.argv[-1]


def _profile(action: ElevationAction) -> OperationProfile:
    if action.action_kind != "shell.exec":
        return OperationProfile(action.action_kind)
    return classify_command(action.argv)


def _material_targets(action: ElevationAction) -> tuple[tuple[str, str], ...]:
    return tuple(item for item in action.target_paths if item[1] != "execute")


def _is_dynamic(value: str) -> bool:
    return bool(_DYNAMIC_SHELL_RE.search(value))


def _is_absolute_path(value: str) -> bool:
    return value.startswith(("/", "~/", "\\\\")) or bool(
        re.match(r"^[A-Za-z]:[\\/]", value)
    )


def _is_protected_path(value: str) -> bool:
    normalized = value.replace("\\", "/").casefold().rstrip("/") or "/"
    protected = (
        "/",
        "/bin",
        "/boot",
        "/dev",
        "/etc",
        "/lib",
        "/lib64",
        "/proc",
        "/root",
        "/sbin",
        "/sys",
        "/usr",
        "/var",
        "/system",
        "c:/windows",
        "c:/program files",
        "c:/program files (x86)",
    )
    return any(normalized == root or normalized.startswith(f"{root}/") for root in protected)


def _is_broad_recursive_delete(action: ElevationAction, command: str) -> bool:
    if not _RECURSIVE_DELETE_RE.search(command):
        return False
    for path, _access in _material_targets(action):
        normalized = path.replace("\\", "/").casefold().rstrip("/") or "/"
        if normalized in {
            "/",
            "/home",
            "/root",
            "/etc",
            "/usr",
            "/var",
            "/opt",
            "c:",
            "c:/",
            "c:/users",
            "c:/windows",
        }:
            return True
        if normalized.count("/") <= 2 and normalized.startswith("/"):
            return True
    return False


def _has_secret_exfiltration(action: ElevationAction, command: str) -> bool:
    if not action.network_targets and not _OUTBOUND_TRANSFER_RE.search(command):
        return False
    structured_secret_read = any(
        access == "read" and _SENSITIVE_SECRET_RE.search(path)
        for path, access in _material_targets(action)
    )
    return bool(structured_secret_read or _SENSITIVE_SECRET_RE.search(command))


def _is_critical(action: ElevationAction, command: str) -> bool:
    return bool(
        _has_secret_exfiltration(action, command)
        or _is_broad_recursive_delete(action, command)
        or _DOWNLOAD_EXEC_RE.search(command)
        or _SECURITY_WEAKENING_RE.search(command)
    )


def _safe_create_shell(command: str) -> bool:
    if not command or "|" in command or _is_dynamic(command):
        return False
    segments = [part.strip() for part in _COMMAND_SPLIT_RE.split(command) if part.strip()]
    if not segments:
        return False
    for segment in segments:
        try:
            tokens = shlex.split(segment, posix=True)
        except ValueError:
            return False
        if not tokens:
            return False
        command_name = tokens[0].rsplit("/", 1)[-1].casefold()
        if command_name not in _LOW_RISK_CREATE_COMMANDS:
            return False
        if command_name in {"echo", "printf"} and not re.search(r">{1,2}\s*\S+", segment):
            return False
    return True


def _is_obviously_low_risk(action: ElevationAction, profile: OperationProfile) -> bool:
    if action.network_targets or action.risk_markers or profile.needs_network:
        return False
    targets = _material_targets(action)
    if not targets or len(targets) > 8:
        return False
    if any(access != "write" for _path, access in targets):
        return False
    if any(
        not _is_absolute_path(path)
        or _is_dynamic(path)
        or _is_protected_path(path)
        or _SENSITIVE_SECRET_RE.search(path)
        for path, _access in targets
    ):
        return False
    return _safe_create_shell(_shell_command(action))


def _risk_level(
    action: ElevationAction,
    profile: OperationProfile,
    command: str,
) -> LocalRiskLevel:
    if _is_critical(action, command):
        return "critical"
    if _is_obviously_low_risk(action, profile):
        return "low"
    if (
        action.network_targets
        or action.risk_markers
        or profile.needs_network
        or profile.host_effect is not None
        or profile.name == "package_install"
        or (profile.high_impact and bool(_RECURSIVE_DELETE_RE.search(command)))
        or action.action_kind == "code.exec"
        or _RECURSIVE_DELETE_RE.search(command)
    ):
        return "high"
    if _DELETE_RE.search(command) or _material_targets(action):
        return "medium"
    return "high"


def _user_text(message: Message) -> str:
    if message.role != "user":
        return ""
    if isinstance(message.content, str):
        return message.content
    return "\n".join(
        str(getattr(block, "text", "") or getattr(block, "content", ""))
        for block in message.content
        if getattr(block, "type", "") in {"text", "compaction"}
    )


def _latest_user_text(transcript: list[Message]) -> str:
    for message in reversed(transcript):
        text = _user_text(message).strip()
        if text:
            return text.casefold()
    return ""


def _mentioned_paths(text: str) -> tuple[str, ...]:
    return tuple(
        match.group(0).rstrip("/\\).]")
        for pattern in (_POSIX_PATH_RE, _WINDOWS_PATH_RE)
        for match in pattern.finditer(text)
    )


def _target_ancestor_scopes(path: str) -> tuple[str, ...]:
    normalized = path.replace("\\", "/").casefold().rstrip("/") or "/"
    scopes: list[str] = []
    if normalized.startswith("/"):
        parts = [part for part in normalized.split("/") if part]
        scopes.extend("/" + "/".join(parts[:index]) for index in range(len(parts), 0, -1))
    elif re.match(r"^[a-z]:/", normalized):
        drive, remainder = normalized[:2], normalized[3:]
        parts = [part for part in remainder.split("/") if part]
        scopes.extend(
            drive + "/" + "/".join(parts[:index])
            for index in range(len(parts), 0, -1)
        )
    ignored = {
        "/",
        "/home",
        "/mnt",
        "/media",
        "/users",
        "c:/users",
        "c:/windows",
    }
    return tuple(scope for scope in scopes if scope not in ignored)


def _scope_is_mentioned(text: str, scope: str) -> bool:
    normalized_text = text.replace("\\", "/")
    start = 0
    while True:
        index = normalized_text.find(scope, start)
        if index < 0:
            return False
        end = index + len(scope)
        if end == len(normalized_text):
            return True
        following = normalized_text[end]
        if following in "/\t\r\n ,，。；;:'\"<>|)]}" or ord(following) > 127:
            return True
        start = index + 1


def _path_scope_matches(text: str, action: ElevationAction) -> bool:
    mentioned = tuple(path.replace("\\", "/").casefold() for path in _mentioned_paths(text))
    for target, _access in _material_targets(action):
        normalized = target.replace("\\", "/").casefold().rstrip("/") or "/"
        if _is_dynamic(normalized):
            return False
        if any(
            _scope_is_mentioned(text, scope)
            for scope in _target_ancestor_scopes(normalized)
        ):
            return True
        for scope in mentioned:
            scope = scope.rstrip("/") or "/"
            if normalized == scope or normalized.startswith(f"{scope}/"):
                return True
    return False


def _command_tokens(command: str) -> tuple[str, ...]:
    try:
        raw = shlex.split(command, posix=True)
    except ValueError:
        raw = command.split()
    ignored = {
        "python",
        "python3",
        "pip",
        "pip3",
        "install",
        "curl",
        "wget",
        "sudo",
        "sh",
        "bash",
        "-m",
    }
    return tuple(
        token.casefold()
        for token in raw
        if len(token) >= 3 and not token.startswith("-") and token.casefold() not in ignored
    )


def _has_named_subject(text: str, command: str) -> bool:
    return any(token in text for token in _command_tokens(command))


def _explicit_user_authorization(
    action: ElevationAction,
    profile: OperationProfile,
    command: str,
    transcript: list[Message],
) -> bool:
    text = _latest_user_text(transcript)
    if (
        not text
        or _is_dynamic(command)
        or any(_is_dynamic(path) for path, _ in action.target_paths)
    ):
        return False
    if action.network_targets or profile.needs_network:
        return _contains_any(text, _NETWORK_WORDS) and all(
            target.casefold() in text for target in action.network_targets
        )
    if profile.name == "package_install" or "package_install" in action.risk_markers:
        return _contains_any(text, _INSTALL_WORDS) and _has_named_subject(text, command)
    if _DELETE_RE.search(command):
        return _contains_any(text, _DELETE_WORDS) and _path_scope_matches(text, action)
    if profile.host_effect is not None or action.action_kind == "code.exec":
        return _contains_any(text, _EXECUTE_WORDS) and (
            _path_scope_matches(text, action) or _has_named_subject(text, command)
        )
    if _material_targets(action):
        words = (
            _EDIT_WORDS
            if action.action_kind in {"fs.edit", "fs.edit_source"}
            else _CREATE_WORDS
        )
        return _contains_any(text, words) and _path_scope_matches(text, action)
    return _contains_any(text, _EXECUTE_WORDS) and _has_named_subject(text, command)


def local_elevation_assessment(
    action: ElevationAction,
    transcript: list[Message],
) -> GuardianAssessment | None:
    """Return a local allow when risk is structurally obvious, else defer."""

    profile = _profile(action)
    command = _shell_command(action)
    risk_level = _risk_level(action, profile, command)
    if risk_level == "critical":
        return None
    explicitly_authorized = _explicit_user_authorization(
        action,
        profile,
        command,
        transcript,
    )
    if risk_level != "low" and not explicitly_authorized:
        return None
    return GuardianAssessment(
        risk_level=risk_level,
        user_authorization="high" if explicitly_authorized else "unknown",
        outcome="allow",
        rationale=(
            "The exact action is locally classified as low risk."
            if risk_level == "low"
            else "The current user explicitly authorized this exact non-critical action."
        ),
        attempt_count=0,
    )


__all__ = ["local_elevation_assessment"]
