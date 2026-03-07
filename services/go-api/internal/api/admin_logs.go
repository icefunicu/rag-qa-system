package api

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"os/exec"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"time"
)

const (
	defaultAdminLogsTail = 100
	maxAdminLogsTail     = 2000
)

type persistedLogLine struct {
	CreatedAt     time.Time
	JobID         string
	DocumentID    string
	FileName      string
	Stage         string
	Message       string
	JobStatus     string
	ErrorMessage  string
	ErrorCategory string
}

func readFrontendLogLines(repoRoot string, tail int) ([]string, error) {
	path := filepath.Join(repoRoot, "logs", "dev", "frontend.log")
	data, err := os.ReadFile(path)
	if err != nil {
		return nil, err
	}

	rawLines := strings.Split(string(data), "\n")
	lines := make([]string, 0, len(rawLines))
	for _, line := range rawLines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		lines = append(lines, "frontend | "+trimmed)
	}
	if len(lines) > tail {
		lines = lines[len(lines)-tail:]
	}
	return lines, nil
}

func parseAdminLogServices(raw string) ([]string, bool) {
	if strings.TrimSpace(raw) == "" {
		return nil, true
	}

	seen := make(map[string]struct{})
	dockerServices := make([]string, 0)
	includeFrontend := false
	for _, part := range strings.Split(raw, ",") {
		name := strings.TrimSpace(part)
		if name == "" {
			continue
		}
		if strings.EqualFold(name, "frontend") {
			includeFrontend = true
			continue
		}
		name = strings.ToLower(name)
		if _, ok := seen[name]; ok {
			continue
		}
		seen[name] = struct{}{}
		dockerServices = append(dockerServices, name)
	}
	sort.Strings(dockerServices)
	return dockerServices, includeFrontend
}

func parseAdminLogTail(raw string) int {
	if strings.TrimSpace(raw) == "" {
		return defaultAdminLogsTail
	}
	value, err := strconv.Atoi(strings.TrimSpace(raw))
	if err != nil || value <= 0 {
		return defaultAdminLogsTail
	}
	if value > maxAdminLogsTail {
		return maxAdminLogsTail
	}
	return value
}

func findRepoRoot(start string) (string, error) {
	current := strings.TrimSpace(start)
	if current == "" {
		var err error
		current, err = os.Getwd()
		if err != nil {
			return "", err
		}
	}

	current, err := filepath.Abs(current)
	if err != nil {
		return "", err
	}

	for {
		if _, err := os.Stat(filepath.Join(current, "docker-compose.yml")); err == nil {
			return current, nil
		}
		parent := filepath.Dir(current)
		if parent == current {
			return "", errors.New("repo root not found")
		}
		current = parent
	}
}

func filterLogLines(lines []string, keyword string) []string {
	needle := strings.ToLower(strings.TrimSpace(keyword))
	if needle == "" {
		return lines
	}

	filtered := make([]string, 0, len(lines))
	for _, line := range lines {
		if strings.Contains(strings.ToLower(line), needle) {
			filtered = append(filtered, line)
		}
	}
	return filtered
}

func readDockerComposeLogs(ctx context.Context, repoRoot string, services []string, tail int) ([]string, error) {
	if _, err := exec.LookPath("docker"); err != nil {
		return nil, err
	}

	args := []string{"compose", "logs", "--no-log-prefix", "--timestamps", "--tail", strconv.Itoa(tail)}
	if len(services) > 0 {
		args = append(args, services...)
	}

	cmd := exec.CommandContext(ctx, "docker", args...)
	cmd.Dir = repoRoot
	out, err := cmd.CombinedOutput()
	if err != nil {
		msg := strings.TrimSpace(string(out))
		if msg == "" {
			msg = err.Error()
		}
		return nil, fmt.Errorf("docker compose logs failed: %s", msg)
	}

	rawLines := strings.Split(string(out), "\n")
	lines := make([]string, 0, len(rawLines))
	for _, line := range rawLines {
		trimmed := strings.TrimSpace(line)
		if trimmed == "" {
			continue
		}
		lines = append(lines, trimmed)
	}
	return lines, nil
}

func formatPersistedLogLines(items []persistedLogLine) []string {
	lines := make([]string, 0, len(items))
	for _, item := range items {
		payload := map[string]any{
			"timestamp":     item.CreatedAt.UTC().Format(time.RFC3339),
			"level":         "INFO",
			"service":       "persisted-events",
			"job_id":        item.JobID,
			"document_id":   item.DocumentID,
			"file_name":     item.FileName,
			"stage":         item.Stage,
			"job_status":    item.JobStatus,
			"message":       item.Message,
			"error_message": item.ErrorMessage,
		}
		if strings.TrimSpace(item.ErrorCategory) != "" {
			payload["error_category"] = item.ErrorCategory
		}
		if strings.TrimSpace(item.ErrorMessage) == "" {
			delete(payload, "error_message")
		}

		data, err := json.Marshal(payload)
		if err != nil {
			lines = append(lines, fmt.Sprintf("persisted-events | %s %s", item.CreatedAt.UTC().Format(time.RFC3339), item.Message))
			continue
		}
		lines = append(lines, "persisted-events | "+string(data))
	}
	return lines
}

func shouldIncludePersistedLogs(serviceQuery string) bool {
	normalized := strings.TrimSpace(strings.ToLower(serviceQuery))
	if normalized == "" {
		return true
	}

	for _, item := range strings.Split(normalized, ",") {
		switch strings.TrimSpace(item) {
		case "go-api", "py-worker", "persisted-events":
			return true
		}
	}
	return false
}

func (a *API) loadPersistedLogLines(ctx context.Context, keyword string, tail int) ([]string, error) {
	items, err := a.store.ListRecentIngestEvents(ctx, keyword, tail)
	if err != nil {
		return nil, err
	}
	lines := make([]persistedLogLine, 0, len(items))
	for _, item := range items {
		lines = append(lines, persistedLogLine{
			CreatedAt:     item.CreatedAt,
			JobID:         item.JobID,
			DocumentID:    item.DocumentID,
			FileName:      item.FileName,
			Stage:         item.Stage,
			Message:       item.Message,
			JobStatus:     item.JobStatus,
			ErrorMessage:  item.ErrorMessage,
			ErrorCategory: item.ErrorCategory,
		})
	}
	return formatPersistedLogLines(lines), nil
}

func (a *API) collectAdminLogLines(ctx context.Context, serviceQuery, keyword string, tail int) ([]string, []string, error) {
	dockerServices, includeFrontend := parseAdminLogServices(serviceQuery)
	lines := make([]string, 0, tail)
	notes := make([]string, 0, 2)

	if repoRoot, err := findRepoRoot(""); err == nil {
		if strings.TrimSpace(serviceQuery) == "" || len(dockerServices) > 0 {
			dockerLines, err := readDockerComposeLogs(ctx, repoRoot, dockerServices, tail)
			if err != nil {
				notes = append(notes, err.Error())
			} else {
				lines = append(lines, filterLogLines(dockerLines, keyword)...)
			}
		}
		if includeFrontend {
			frontendLines, err := readFrontendLogLines(repoRoot, tail)
			if err != nil {
				notes = append(notes, "frontend log unavailable: "+err.Error())
			} else {
				lines = append(lines, filterLogLines(frontendLines, keyword)...)
			}
		}
	} else {
		notes = append(notes, "docker compose logs unavailable in current runtime")
	}

	if shouldIncludePersistedLogs(serviceQuery) {
		persistedLines, err := a.loadPersistedLogLines(ctx, keyword, tail)
		if err != nil {
			notes = append(notes, "persisted ingest events unavailable: "+err.Error())
		} else if len(persistedLines) > 0 {
			lines = append(lines, persistedLines...)
		}
	}

	if len(lines) > tail {
		lines = lines[:tail]
	}
	return lines, notes, nil
}

func (a *API) handleAdminLogs(w http.ResponseWriter, r *http.Request) {
	serviceQuery := strings.TrimSpace(r.URL.Query().Get("service"))
	keyword := strings.TrimSpace(r.URL.Query().Get("keyword"))
	tail := parseAdminLogTail(r.URL.Query().Get("tail"))

	lines, notes, err := a.collectAdminLogLines(r.Context(), serviceQuery, keyword, tail)
	if err != nil {
		a.logger.Printf("[admin-logs] collect failed: service=%s keyword=%s tail=%d err=%v", serviceQuery, keyword, tail, err)
		writeError(w, http.StatusInternalServerError, "collect admin logs failed")
		return
	}

	writeJSON(w, http.StatusOK, map[string]any{
		"lines": lines,
		"count": len(lines),
		"notes": notes,
	})
}
