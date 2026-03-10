export interface QueryCitation {
  unit_id: string;
  document_id: string;
  section_title: string;
  char_range: string;
  quote: string;
  evidence_kind?: 'text' | 'visual_ocr';
  source_kind?: string;
  page_number?: number | null;
  asset_id?: string;
  thumbnail_url?: string;
  document_title?: string;
}

export interface QueryResult {
  strategy_used: string;
  answer_mode: string;
  evidence_status: string;
  grounding_score: number;
  refusal_reason: string;
  safety?: unknown;
  citations: QueryCitation[];
  answer: string;
}

export function createEmptyQueryResult(): QueryResult {
  return {
    strategy_used: 'pending',
    answer_mode: '',
    evidence_status: 'streaming',
    grounding_score: 0,
    refusal_reason: '',
    safety: null,
    citations: [],
    answer: ''
  };
}

export function applyQueryStreamEvent(
  current: QueryResult,
  eventName: string,
  payload: Record<string, unknown> | null
): QueryResult {
  if (!payload) {
    return current;
  }

  if (eventName === 'metadata') {
    return {
      ...current,
      strategy_used: String(payload.strategy_used || current.strategy_used),
      answer_mode: String(payload.answer_mode || current.answer_mode),
      evidence_status: String(payload.evidence_status || current.evidence_status),
      refusal_reason: String(payload.refusal_reason || current.refusal_reason),
      safety: payload.safety ?? current.safety ?? null
    };
  }

  if (eventName === 'citation') {
    const unitId = String(payload.unit_id || '');
    if (!unitId || current.citations.some((citation) => citation.unit_id === unitId)) {
      return current;
    }
    return {
      ...current,
      citations: [...current.citations, payload as unknown as QueryCitation]
    };
  }

  if (eventName === 'answer') {
    return {
      ...current,
      answer: String(payload.answer || current.answer),
      grounding_score: Number(payload.grounding_score ?? current.grounding_score),
      refusal_reason: String(payload.refusal_reason || current.refusal_reason),
      safety: payload.safety ?? current.safety ?? null
    };
  }

  return current;
}

export function resolveQueryStreamPayload(data: unknown): Record<string, unknown> | null {
  if (!data || typeof data !== 'object') {
    return null;
  }
  return data as Record<string, unknown>;
}
