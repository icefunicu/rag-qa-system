package api

import (
	"errors"
	"fmt"
	"strings"
)

type Scope struct {
	Mode                 string   `json:"mode"`
	CorpusIDs            []string `json:"corpus_ids"`
	DocumentIDs          []string `json:"document_ids,omitempty"`
	AllowCommonKnowledge bool     `json:"allow_common_knowledge"`
}

func (s Scope) Validate() error {
	mode := strings.TrimSpace(strings.ToLower(s.Mode))
	switch mode {
	case "single":
		if len(s.CorpusIDs) != 1 {
			return errors.New("scope.mode=single requires exactly one corpus_id")
		}
	case "multi":
		if len(s.CorpusIDs) < 2 {
			return errors.New("scope.mode=multi requires at least two corpus_ids")
		}
	default:
		return fmt.Errorf("unsupported scope.mode: %q", s.Mode)
	}

	for _, id := range s.CorpusIDs {
		if strings.TrimSpace(id) == "" {
			return errors.New("scope.corpus_ids contains empty value")
		}
	}

	for _, id := range s.DocumentIDs {
		if strings.TrimSpace(id) == "" {
			return errors.New("scope.document_ids contains empty value")
		}
	}
	return nil
}

type AnswerSentence struct {
	Text         string   `json:"text"`
	EvidenceType string   `json:"evidence_type"`
	CitationIDs  []string `json:"citation_ids"`
	Confidence   float64  `json:"confidence"`
}

type Citation struct {
	CitationID string `json:"citation_id"`
	FileName   string `json:"file_name"`
	PageOrLoc  string `json:"page_or_loc"`
	ChunkID    string `json:"chunk_id"`
	Snippet    string `json:"snippet"`
}
