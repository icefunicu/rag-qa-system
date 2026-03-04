package auth

import (
	"crypto/rand"
	"encoding/hex"
	"errors"
	"strings"
	"sync"
	"time"

	"rag-p/go-api/internal/config"
)

const (
	RoleAdmin  = "admin"
	RoleMember = "member"
)

var ErrInvalidCredential = errors.New("invalid email or password")

type Claims struct {
	UserID string `json:"user_id"`
	Role   string `json:"role"`
	Email  string `json:"email"`
}

type session struct {
	claims    Claims
	expiresAt time.Time
}

type Manager struct {
	config config.Config
	ttl    time.Duration
	mu     sync.RWMutex
	tokens map[string]session
}

func NewManager(cfg config.Config) *Manager {
	return &Manager{
		config: cfg,
		ttl:    cfg.AuthTokenTTL,
		tokens: make(map[string]session),
	}
}

func (m *Manager) Login(email, password string) (string, Claims, error) {
	email = strings.TrimSpace(strings.ToLower(email))

	var claims Claims
	switch {
	case email == strings.ToLower(m.config.AdminEmail) && password == m.config.AdminPassword:
		claims = Claims{
			UserID: m.config.AdminUserID,
			Role:   RoleAdmin,
			Email:  m.config.AdminEmail,
		}
	case email == strings.ToLower(m.config.MemberEmail) && password == m.config.MemberPassword:
		claims = Claims{
			UserID: m.config.MemberUserID,
			Role:   RoleMember,
			Email:  m.config.MemberEmail,
		}
	default:
		return "", Claims{}, ErrInvalidCredential
	}

	token, err := newToken()
	if err != nil {
		return "", Claims{}, err
	}

	m.mu.Lock()
	defer m.mu.Unlock()
	m.tokens[token] = session{
		claims:    claims,
		expiresAt: time.Now().Add(m.ttl),
	}
	return token, claims, nil
}

func (m *Manager) Validate(token string) (Claims, bool) {
	m.mu.Lock()
	defer m.mu.Unlock()

	sess, ok := m.tokens[token]
	if !ok {
		return Claims{}, false
	}
	if time.Now().After(sess.expiresAt) {
		delete(m.tokens, token)
		return Claims{}, false
	}
	return sess.claims, true
}

func newToken() (string, error) {
	raw := make([]byte, 32)
	if _, err := rand.Read(raw); err != nil {
		return "", err
	}
	return hex.EncodeToString(raw), nil
}
