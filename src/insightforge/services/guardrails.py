import re
from dataclasses import dataclass

_INJECTION_PATTERNS = (
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"reveal\s+(the\s+)?(system|developer)\s+prompt",
    r"you\s+are\s+now\s+(dan|developer|system)",
    r"忽略.{0,8}(之前|以上).{0,8}(指令|提示词)",
    r"泄露.{0,8}(系统|开发者).{0,8}(提示词|指令)",
)


@dataclass(frozen=True)
class GuardrailResult:
    allowed: bool
    sanitized_text: str
    reason: str = ""


def validate_query(text: str, max_chars: int = 4000) -> GuardrailResult:
    """Reject common prompt-injection attempts at the trust boundary."""
    normalized = " ".join(text.split())
    if not normalized:
        return GuardrailResult(False, "", "问题不能为空")
    if len(normalized) > max_chars:
        return GuardrailResult(False, normalized[:max_chars], f"问题超过 {max_chars} 字符")
    for pattern in _INJECTION_PATTERNS:
        if re.search(pattern, normalized, flags=re.IGNORECASE):
            return GuardrailResult(False, normalized, "检测到提示词注入风险")
    return GuardrailResult(True, normalized)


def wrap_untrusted(content: str) -> str:
    """Mark retrieved content as data, never as executable instructions."""
    return f"<untrusted_evidence>\n{content[:6000]}\n</untrusted_evidence>"
