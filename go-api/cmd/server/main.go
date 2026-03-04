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
)

func main() {
	cfg := config.Load()
	logger := log.New(os.Stdout, "[go-api] ", log.LstdFlags|log.LUTC)

	store, err := db.NewStore(cfg.PostgresDSN)
	if err != nil {
		logger.Fatalf("connect postgres failed: %v", err)
	}
	defer store.Close()

	authManager := auth.NewManager(cfg)
	app := api.New(cfg, store, authManager, logger)

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
