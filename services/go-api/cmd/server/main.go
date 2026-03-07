package main

import (
	"context"
	"errors"
	"log"
	"net/http"
	"os"
	"os/signal"
	"syscall"
	"time"

	"rag-p/go-api/internal/api"
	"rag-p/go-api/internal/auth"
	"rag-p/go-api/internal/config"
	"rag-p/go-api/internal/db"

	"github.com/redis/go-redis/v9"
)

func main() {
	cfg := config.Load()
	logger := log.New(os.Stdout, "[go-api] ", log.LstdFlags|log.Lmicroseconds|log.LUTC)

	store, err := db.NewStore(
		cfg.PostgresDSN,
		db.WithMaxOpenConns(cfg.DBMaxOpenConns),
		db.WithMaxIdleConns(cfg.DBMaxIdleConns),
		db.WithConnMaxLifetime(cfg.DBConnMaxLifetime),
	)
	if err != nil {
		logger.Fatalf("connect postgres failed: %v", err)
	}
	defer store.Close()

	ctxUsers, cancelUsers := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancelUsers()
	if err := store.EnsureConfiguredUsers(ctxUsers, []db.ConfiguredUser{
		{ID: cfg.AdminUserID, Email: cfg.AdminEmail, Role: "admin"},
		{ID: cfg.MemberUserID, Email: cfg.MemberEmail, Role: "member"},
	}); err != nil {
		logger.Fatalf("sync configured users failed: %v", err)
	}

	rdb := redis.NewClient(&redis.Options{
		Addr: cfg.RedisURL, // Simplification for URL, actual may need ParseURL
	})
	if opt, err := redis.ParseURL(cfg.RedisURL); err == nil {
		rdb = redis.NewClient(opt)
	}

	ctxInit, cancelInit := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancelInit()
	if err := rdb.Ping(ctxInit).Err(); err != nil {
		logger.Fatalf("connect redis failed: %v", err)
	}

	authManager := auth.NewManager(cfg, rdb)
	app, err := api.New(cfg, store, authManager, rdb, logger)
	if err != nil {
		logger.Fatalf("init api components failed: %v", err)
	}
	defer app.Close()

	server := &http.Server{
		Addr:              cfg.HTTPAddr,
		Handler:           app.Router(),
		ReadHeaderTimeout: 5 * time.Second,
	}

	go func() {
		logger.Printf("server listening on %s", cfg.HTTPAddr)
		if err := server.ListenAndServe(); err != nil && !errors.Is(err, http.ErrServerClosed) {
			logger.Fatalf("server crashed: %v", err)
		}
	}()

	stop := make(chan os.Signal, 1)
	signal.Notify(stop, syscall.SIGINT, syscall.SIGTERM)
	<-stop

	ctx, cancel := context.WithTimeout(context.Background(), 10*time.Second)
	defer cancel()

	if err := server.Shutdown(ctx); err != nil {
		logger.Printf("graceful shutdown failed: %v", err)
	}
	logger.Print("server stopped")
}
