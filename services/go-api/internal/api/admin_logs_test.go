package api

import (
	"os"
	"path/filepath"
	"reflect"
	"strings"
	"testing"
	"time"
)

func TestParseAdminLogServices(t *testing.T) {
	tests := []struct {
		name            string
		raw             string
		wantServices    []string
		wantHasFrontend bool
	}{
		{
			name:            "empty means all plus frontend",
			raw:             "",
			wantServices:    nil,
			wantHasFrontend: true,
		},
		{
			name:            "split comma and dedupe",
			raw:             "py-worker, frontend,go-api,py-worker",
			wantServices:    []string{"go-api", "py-worker"},
			wantHasFrontend: true,
		},
		{
			name:            "docker only",
			raw:             "py-rag-service",
			wantServices:    []string{"py-rag-service"},
			wantHasFrontend: false,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			gotServices, gotFrontend := parseAdminLogServices(tt.raw)
			if !reflect.DeepEqual(gotServices, tt.wantServices) {
				t.Fatalf("unexpected services: got=%v want=%v", gotServices, tt.wantServices)
			}
			if gotFrontend != tt.wantHasFrontend {
				t.Fatalf("unexpected frontend flag: got=%t want=%t", gotFrontend, tt.wantHasFrontend)
			}
		})
	}
}

func TestParseAdminLogTail(t *testing.T) {
	if got := parseAdminLogTail(""); got != defaultAdminLogsTail {
		t.Fatalf("expected default tail, got %d", got)
	}
	if got := parseAdminLogTail("0"); got != defaultAdminLogsTail {
		t.Fatalf("expected default tail on invalid input, got %d", got)
	}
	if got := parseAdminLogTail("999999"); got != maxAdminLogsTail {
		t.Fatalf("expected clamped tail, got %d", got)
	}
}

func TestFindRepoRoot(t *testing.T) {
	root := t.TempDir()
	nested := filepath.Join(root, "services", "go-api")
	if err := os.MkdirAll(nested, 0o755); err != nil {
		t.Fatalf("mkdir failed: %v", err)
	}
	if err := os.WriteFile(filepath.Join(root, "docker-compose.yml"), []byte("services: {}"), 0o644); err != nil {
		t.Fatalf("write docker-compose.yml failed: %v", err)
	}

	got, err := findRepoRoot(nested)
	if err != nil {
		t.Fatalf("findRepoRoot returned error: %v", err)
	}
	if got != root {
		t.Fatalf("unexpected repo root: got=%s want=%s", got, root)
	}
}

func TestFormatPersistedLogLines(t *testing.T) {
	lines := formatPersistedLogLines([]persistedLogLine{
		{
			CreatedAt:    time.Date(2026, 3, 7, 12, 0, 0, 0, time.UTC),
			JobID:        "job-1",
			DocumentID:   "doc-1",
			FileName:     "a.txt",
			Stage:        "embedding",
			Message:      "processing chunks",
			JobStatus:    "running",
			ErrorMessage: "",
		},
	})

	if len(lines) != 1 {
		t.Fatalf("unexpected line count: %d", len(lines))
	}
	if !strings.Contains(lines[0], "persisted-events |") {
		t.Fatalf("expected persisted-events prefix, got %s", lines[0])
	}
	if !strings.Contains(lines[0], "\"document_id\":\"doc-1\"") {
		t.Fatalf("expected document_id in line, got %s", lines[0])
	}
}
