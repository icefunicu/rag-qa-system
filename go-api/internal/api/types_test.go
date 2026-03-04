package api

import "testing"

func TestScopeValidate(t *testing.T) {
	tests := []struct {
		name    string
		scope   Scope
		wantErr bool
	}{
		{
			name: "single valid",
			scope: Scope{
				Mode:      "single",
				CorpusIDs: []string{"c1"},
			},
			wantErr: false,
		},
		{
			name: "single invalid corpus count",
			scope: Scope{
				Mode:      "single",
				CorpusIDs: []string{"c1", "c2"},
			},
			wantErr: true,
		},
		{
			name: "multi valid",
			scope: Scope{
				Mode:      "multi",
				CorpusIDs: []string{"c1", "c2"},
			},
			wantErr: false,
		},
		{
			name: "multi invalid corpus count",
			scope: Scope{
				Mode:      "multi",
				CorpusIDs: []string{"c1"},
			},
			wantErr: true,
		},
		{
			name: "unsupported mode",
			scope: Scope{
				Mode:      "all",
				CorpusIDs: []string{"c1"},
			},
			wantErr: true,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			err := tt.scope.Validate()
			if tt.wantErr && err == nil {
				t.Fatalf("expected error but got nil")
			}
			if !tt.wantErr && err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
		})
	}
}
