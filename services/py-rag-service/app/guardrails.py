"""
Prompt Injection 与权限边界防护模块

防止用户输入中的 prompt injection 攻击，保护 LLM 调用安全。
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple


@dataclass
class GuardrailResult:
    """防护检查结果"""
    safe: bool
    risk_level: str  # low / medium / high / blocked
    matched_rules: List[str]
    sanitized_input: str
    reason: str = ""


# ── 高风险模式：直接拦截 ──
HIGH_RISK_PATTERNS = [
    # 角色覆盖类
    (r"(?i)ignore\s+(all\s+)?(previous|above|prior)\s+(instructions|prompts|rules)", "role_override"),
    (r"(?i)you\s+are\s+now\s+(a|an|the)\s+", "role_injection"),
    (r"(?i)forget\s+(everything|all|your)\s+(you|instructions|rules)", "role_override"),
    (r"(?i)disregard\s+(all\s+)?(any\s+)?(previous\s+)?(instructions|rules|prompts)", "role_override"),
    (r"(?i)new\s+instructions?\s*:", "role_override"),
    # 系统 prompt 泄露类
    (r"(?i)what\s+(is|are)\s+your\s+(system|initial)\s+(prompt|instructions|message)", "prompt_leak"),
    (r"(?i)repeat\s+(your|the)\s+(system|initial)\s+(prompt|instructions)", "prompt_leak"),
    (r"(?i)show\s+me\s+your\s+(prompt|instructions|system\s+message)", "prompt_leak"),
    # 编码绕过类
    (r"(?i)base64\s*:\s*[A-Za-z0-9+/=]{20,}", "encoding_bypass"),
    (r"(?i)eval\s*\(", "code_injection"),
    (r"(?i)exec\s*\(", "code_injection"),
]

# ── 中风险模式：标记但不拦截 ──
MEDIUM_RISK_PATTERNS = [
    (r"(?i)pretend\s+(to\s+be|you\s+are)", "impersonation"),
    (r"(?i)act\s+as\s+(if|a|an|the)", "impersonation"),
    (r"(?i)do\s+not\s+follow\s+(the|your)", "instruction_bypass"),
    (r"(?i)override\s+(the|your|default)", "instruction_bypass"),
    (r"(?i)jailbreak", "explicit_attack"),
    (r"(?i)DAN\s+mode", "explicit_attack"),
]


def check_input(text: str) -> GuardrailResult:
    """
    对用户输入执行 prompt injection 检查。

    Args:
        text: 用户输入文本

    Returns:
        GuardrailResult 包含安全性判断和匹配规则
    """
    matched_rules: List[str] = []
    risk_level = "low"

    # 检查高风险模式
    for pattern, rule_name in HIGH_RISK_PATTERNS:
        if re.search(pattern, text):
            matched_rules.append(f"high:{rule_name}")
            risk_level = "blocked"

    # 如果已被拦截，直接返回
    if risk_level == "blocked":
        return GuardrailResult(
            safe=False,
            risk_level="blocked",
            matched_rules=matched_rules,
            sanitized_input="",
            reason=f"检测到高风险输入模式: {', '.join(matched_rules)}",
        )

    # 检查中风险模式
    for pattern, rule_name in MEDIUM_RISK_PATTERNS:
        if re.search(pattern, text):
            matched_rules.append(f"medium:{rule_name}")
            if risk_level != "high":
                risk_level = "medium"

    # 清理输入：移除常见注入分隔符
    sanitized = text
    # 移除连续换行后的可疑指令格式
    sanitized = re.sub(r"\n{3,}", "\n\n", sanitized)

    return GuardrailResult(
        safe=True,
        risk_level=risk_level,
        matched_rules=matched_rules,
        sanitized_input=sanitized,
        reason="" if not matched_rules else f"检测到中风险模式: {', '.join(matched_rules)}",
    )


def validate_question(question: str, max_length: int = 8000) -> Tuple[bool, str, Optional[GuardrailResult]]:
    """
    验证用户问题：长度 + prompt injection 检查。

    Args:
        question: 用户问题
        max_length: 最大长度

    Returns:
        (is_valid, error_message, guardrail_result)
    """
    if not question or not question.strip():
        return False, "问题不能为空", None

    if len(question) > max_length:
        return False, f"问题长度超过限制 ({len(question)} > {max_length})", None

    result = check_input(question)

    if not result.safe:
        return False, result.reason, result

    return True, "", result
