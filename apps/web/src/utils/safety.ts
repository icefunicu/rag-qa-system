export interface SafetyNotice {
  level: 'warning' | 'error';
  title: string;
  message: string;
}

export interface SafetyNoticeSource {
  answerMode?: string | null;
  evidenceStatus?: string | null;
  refusalReason?: string | null;
  safety?: unknown;
}

interface BackendSafetyPayload {
  risk_level?: string;
  blocked?: boolean;
  action?: string;
  reason_codes?: unknown;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function normalizeReasonLabel(reasonCode: string): string {
  const normalized = reasonCode.trim().toLowerCase();
  const reasonMap: Record<string, string> = {
    prompt_injection_user: '用户问题包含疑似指令覆盖内容',
    prompt_injection_history: '历史消息包含疑似指令覆盖内容',
    prompt_injection_evidence: '检索证据包含疑似文档指令污染',
    prompt_leak_request: '问题试图获取隐藏提示词或内部推理',
    citation_bypass_attempt: '问题试图绕过引用或证据约束',
    unsafe_prompt: '问题触发了提示注入安全保护'
  };
  return reasonMap[normalized] || normalized;
}

function normalizeSafetyPayload(safety: unknown): BackendSafetyPayload | null {
  if (!isRecord(safety)) {
    return null;
  }
  return {
    risk_level: typeof safety.risk_level === 'string' ? safety.risk_level : undefined,
    blocked: Boolean(safety.blocked),
    action: typeof safety.action === 'string' ? safety.action : undefined,
    reason_codes: safety.reason_codes
  };
}

function buildSafetyNoticeFromPayload(safety: BackendSafetyPayload): SafetyNotice | null {
  const riskLevel = String(safety.risk_level || '').toLowerCase();
  if (!riskLevel || riskLevel === 'low') {
    return null;
  }

  const reasonCodes = Array.isArray(safety.reason_codes)
    ? safety.reason_codes
        .map((item) => String(item || '').trim())
        .filter(Boolean)
    : [];
  const reasonSummary = reasonCodes.length
    ? `命中原因：${reasonCodes.map(normalizeReasonLabel).join('；')}。`
    : '';

  if (riskLevel === 'high' || safety.blocked) {
    return {
      level: 'error',
      title: safety.action === 'fallback' ? '问题触发安全降级回答' : '问题已被安全策略拦截',
      message:
        (safety.action === 'fallback'
          ? '系统识别到高风险提示注入信号，只保留受证据约束的保守回答。'
          : '系统识别到高风险提示注入信号，已拒绝继续生成回答。') + reasonSummary
    };
  }

  return {
    level: 'warning',
    title: '问题包含可疑指令信号',
    message: `系统继续返回结果，但请优先核对引用与业务规则。${reasonSummary}`
  };
}

function normalizeSafetyReason(reason: string): string {
  const normalized = reason.trim().toLowerCase();
  if (!normalized) {
    return '当前回答命中了安全保护或缺少足够证据，请调整问题或补充知识库材料后重试。';
  }

  const reasonMap: Record<string, string> = {
    insufficient_evidence: '知识库证据不足，系统已避免给出不可靠结论。',
    unsafe_prompt: '当前问题命中了提示注入安全保护，系统未继续生成普通回答。',
    safety_blocked: '当前问题命中了安全保护，系统未继续生成普通回答。',
    policy_blocked: '当前问题命中了策略限制，系统未继续生成普通回答。',
    compliance_blocked: '当前问题命中了合规限制，系统未继续生成普通回答。'
  };

  return reasonMap[normalized] || `触发原因：${reason.trim()}`;
}

export function buildSafetyNotice(source: SafetyNoticeSource): SafetyNotice | null {
  const explicitSafety = buildSafetyNoticeFromPayload(normalizeSafetyPayload(source.safety) || {});
  if (explicitSafety) {
    return explicitSafety;
  }

  const answerMode = String(source.answerMode || '').toLowerCase();
  const evidenceStatus = String(source.evidenceStatus || '').toLowerCase();
  const refusalReason = String(source.refusalReason || '').trim();

  if (answerMode === 'refusal' || refusalReason) {
    return {
      level: 'error',
      title: '回答已触发保护策略',
      message: normalizeSafetyReason(refusalReason)
    };
  }

  if (answerMode === 'common_knowledge') {
    return {
      level: 'warning',
      title: '当前回答未命中知识库证据',
      message: '本次回答来自通用知识补全，可能与当前知识库或业务规则不完全一致，请人工复核后再使用。'
    };
  }

  if (answerMode === 'weak_grounded' || evidenceStatus === 'partial') {
    return {
      level: 'warning',
      title: '当前回答证据支撑较弱',
      message: '系统检索到了部分证据，但支撑强度不足，建议结合引用片段人工复核。'
    };
  }

  if (evidenceStatus === 'ungrounded') {
    return {
      level: 'warning',
      title: '当前回答缺少充分落地证据',
      message: '系统没有找到可直接落地到知识库的充分证据，请谨慎使用该回答。'
    };
  }

  if (evidenceStatus === 'insufficient') {
    return {
      level: 'warning',
      title: '当前问题证据不足',
      message: '知识库中没有足够证据支持直接作答，建议缩小提问范围或补充文档后重试。'
    };
  }

  return null;
}
