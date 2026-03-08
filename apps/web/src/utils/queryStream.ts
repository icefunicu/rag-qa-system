export interface QueryCitation {
  unit_id: string;
  document_id: string;
  section_title: string;
  char_range: string;
  quote: string;
}

export interface QueryResult {
  strategy_used: string;
  evidence_status: string;
  grounding_score: number;
  refusal_reason: string;
  citations: QueryCitation[];
  answer: string;
}

export function createEmptyQueryResult(): QueryResult {
  return {
    strategy_used: 'pending',
    evidence_status: 'streaming',
    grounding_score: 0,
    refusal_reason: '',
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
      evidence_status: String(payload.evidence_status || current.evidence_status),
      refusal_reason: String(payload.refusal_reason || current.refusal_reason)
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
      refusal_reason: String(payload.refusal_reason || current.refusal_reason)
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
