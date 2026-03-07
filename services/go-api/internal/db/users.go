package db

import (
	"context"
	"fmt"
	"strings"

	"github.com/google/uuid"
)

const configManagedPasswordHash = "!config-auth-managed!"

// ConfiguredUser describes a config-backed application user.
type ConfiguredUser struct {
	ID    string
	Email string
	Role  string
}

// EnsureConfiguredUsers upserts config-backed users into app_users.
// Input: a list of configured users with stable IDs, emails, and roles.
// Output: nil when every user exists in app_users with matching metadata.
// Failure: returns validation or database errors and leaves the transaction rolled back.
func (s *Store) EnsureConfiguredUsers(ctx context.Context, users []ConfiguredUser) error {
	if len(users) == 0 {
		return nil
	}

	seenIDs := make(map[string]struct{}, len(users))
	seenEmails := make(map[string]struct{}, len(users))

	tx, err := s.db.BeginTx(ctx, nil)
	if err != nil {
		return err
	}
	defer tx.Rollback()

	for _, user := range users {
		normalized, err := normalizeConfiguredUser(user)
		if err != nil {
			return err
		}
		if _, exists := seenIDs[normalized.ID]; exists {
			return fmt.Errorf("duplicate configured user id: %s", normalized.ID)
		}
		if _, exists := seenEmails[normalized.Email]; exists {
			return fmt.Errorf("duplicate configured user email: %s", normalized.Email)
		}
		seenIDs[normalized.ID] = struct{}{}
		seenEmails[normalized.Email] = struct{}{}

		if _, err := tx.ExecContext(
			ctx,
			`INSERT INTO app_users (id, email, password_hash, role, created_at)
			 VALUES ($1, $2, $3, $4, NOW())
			 ON CONFLICT (id) DO UPDATE
			 SET email = EXCLUDED.email,
			     password_hash = EXCLUDED.password_hash,
			     role = EXCLUDED.role`,
			normalized.ID,
			normalized.Email,
			configManagedPasswordHash,
			normalized.Role,
		); err != nil {
			return fmt.Errorf("upsert configured user %s failed: %w", normalized.Email, err)
		}
	}

	return tx.Commit()
}

func normalizeConfiguredUser(user ConfiguredUser) (ConfiguredUser, error) {
	normalized := ConfiguredUser{
		ID:    strings.TrimSpace(user.ID),
		Email: strings.ToLower(strings.TrimSpace(user.Email)),
		Role:  strings.ToLower(strings.TrimSpace(user.Role)),
	}

	if _, err := uuid.Parse(normalized.ID); err != nil {
		return ConfiguredUser{}, fmt.Errorf("invalid configured user id: %w", err)
	}
	if normalized.Email == "" {
		return ConfiguredUser{}, fmt.Errorf("configured user email is required")
	}
	if normalized.Role != "admin" && normalized.Role != "member" {
		return ConfiguredUser{}, fmt.Errorf("invalid configured user role: %s", normalized.Role)
	}

	return normalized, nil
}
