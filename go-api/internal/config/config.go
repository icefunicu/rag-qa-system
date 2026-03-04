package config

import (
	"os"
	"strconv"
	"time"
)

type Config struct {
	HTTPAddr         string
	PostgresDSN      string
	RAGServiceURL    string
	MaxUploadBytes   int64
	AuthTokenTTL     time.Duration
	AdminUserID      string
	AdminEmail       string
	AdminPassword    string
	MemberUserID     string
	MemberEmail      string
	MemberPassword   string
	AllowedFileTypes map[string]struct{}
}

func Load() Config {
	ttlMinutes := getEnvAsInt("AUTH_TOKEN_TTL_MINUTES", 120)

	return Config{
		HTTPAddr:       getEnv("HTTP_ADDR", ":8080"),
		PostgresDSN:    getEnv("POSTGRES_DSN", "postgres://rag:rag@postgres:5432/rag?sslmode=disable"),
		RAGServiceURL:  getEnv("RAG_SERVICE_URL", "http://py-rag-service:8000"),
		MaxUploadBytes: getEnvAsInt64("MAX_UPLOAD_BYTES", 524288000),
		AuthTokenTTL:   time.Duration(ttlMinutes) * time.Minute,
		AdminUserID:    getEnv("ADMIN_USER_ID", "11111111-1111-1111-1111-111111111111"),
		AdminEmail:     getEnv("ADMIN_EMAIL", "admin@local"),
		AdminPassword:  getEnv("ADMIN_PASSWORD", "ChangeMe123!"),
		MemberUserID:   getEnv("MEMBER_USER_ID", "22222222-2222-2222-2222-222222222222"),
		MemberEmail:    getEnv("MEMBER_EMAIL", "member@local"),
		MemberPassword: getEnv("MEMBER_PASSWORD", "ChangeMe123!"),
		AllowedFileTypes: map[string]struct{}{
			"txt":  {},
			"pdf":  {},
			"docx": {},
		},
	}
}

func getEnv(key, fallback string) string {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}
	return value
}

func getEnvAsInt(key string, fallback int) int {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}

	parsed, err := strconv.Atoi(value)
	if err != nil {
		return fallback
	}

	return parsed
}

func getEnvAsInt64(key string, fallback int64) int64 {
	value := os.Getenv(key)
	if value == "" {
		return fallback
	}

	parsed, err := strconv.ParseInt(value, 10, 64)
	if err != nil {
		return fallback
	}

	return parsed
}
