package api

import (
	"context"
	"encoding/json"
	"strings"
	"time"

	"github.com/redis/go-redis/v9"
)

const runtimeProgressKeyPrefix = "ingest:runtime_progress:"

type RuntimeProgress struct {
	JobID           string         `json:"job_id"`
	Status          string         `json:"status"`
	OverallProgress int            `json:"overall_progress"`
	Stage           string         `json:"stage"`
	Message         string         `json:"message,omitempty"`
	UpdatedAt       time.Time      `json:"updated_at"`
	Details         map[string]any `json:"details,omitempty"`
}

func runtimeProgressKey(jobID string) string {
	return runtimeProgressKeyPrefix + strings.TrimSpace(jobID)
}

func (a *API) getRuntimeProgress(ctx context.Context, jobID string) (*RuntimeProgress, error) {
	if a.rdb == nil {
		return nil, nil
	}

	raw, err := a.rdb.Get(ctx, runtimeProgressKey(jobID)).Result()
	if err != nil {
		if err == redis.Nil {
			return nil, nil
		}
		return nil, err
	}

	var progress RuntimeProgress
	if err := json.Unmarshal([]byte(raw), &progress); err != nil {
		return nil, err
	}

	if progress.JobID == "" {
		progress.JobID = jobID
	}

	return &progress, nil
}
