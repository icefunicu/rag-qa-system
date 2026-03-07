package storage

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"net"
	"net/http"
	"net/url"
	"path/filepath"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/minio/minio-go/v7"
	"github.com/minio/minio-go/v7/pkg/credentials"
)

var ErrObjectTooLarge = errors.New("object exceeds limit")

type PresignedUpload struct {
	StorageKey string            `json:"storage_key"`
	UploadURL  string            `json:"upload_url"`
	Method     string            `json:"method"`
	Headers    map[string]string `json:"headers"`
	ExpiresIn  int               `json:"expires_in_seconds"`
}

type S3Client struct {
	internal      *minio.Client
	public        *minio.Client
	bucket        string
	expiryMinutes int
}

func NewS3Client(internalEndpoint, publicEndpoint, accessKey, secretKey, bucket string, useSSL bool, expiryMinutes int) (*S3Client, error) {
	internalClient, err := minio.New(internalEndpoint, &minio.Options{
		Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
		Secure: useSSL,
	})
	if err != nil {
		return nil, fmt.Errorf("create internal minio client failed: %w", err)
	}

	publicClient := internalClient
	if strings.TrimSpace(publicEndpoint) != "" && publicEndpoint != internalEndpoint {
		publicOptions := &minio.Options{
			Creds:  credentials.NewStaticV4(accessKey, secretKey, ""),
			Secure: useSSL,
		}

		overrideTransport, err := newEndpointOverrideTransport(internalEndpoint)
		if err != nil {
			return nil, fmt.Errorf("build public client transport failed: %w", err)
		}
		publicOptions.Transport = overrideTransport

		publicClient, err = minio.New(publicEndpoint, publicOptions)
		if err != nil {
			return nil, fmt.Errorf("create public minio client failed: %w", err)
		}
	}

	return &S3Client{internal: internalClient, public: publicClient, bucket: bucket, expiryMinutes: expiryMinutes}, nil
}

func (s *S3Client) EnsureBucket(ctx context.Context) error {
	exists, err := s.internal.BucketExists(ctx, s.bucket)
	if err != nil {
		return fmt.Errorf("check bucket exists failed: %w", err)
	}
	if exists {
		return nil
	}
	if err := s.internal.MakeBucket(ctx, s.bucket, minio.MakeBucketOptions{}); err != nil {
		return fmt.Errorf("create bucket failed: %w", err)
	}
	return nil
}

func (s *S3Client) NewUploadURL(ctx context.Context, userID, corpusID, fileName, fileType string) (PresignedUpload, error) {
	if err := s.EnsureBucket(ctx); err != nil {
		return PresignedUpload{}, err
	}

	ext := strings.ToLower(strings.TrimPrefix(filepath.Ext(fileName), "."))
	if ext == "" {
		ext = strings.TrimSpace(strings.ToLower(fileType))
	}
	if ext == "" {
		ext = "bin"
	}
	storageKey := fmt.Sprintf("raw/%s/%s/%s.%s", userID, corpusID, uuid.NewString(), ext)

	headers := map[string]string{}
	url, err := s.public.PresignedPutObject(
		ctx,
		s.bucket,
		storageKey,
		time.Duration(s.expiryMinutes)*time.Minute,
	)
	if err != nil {
		return PresignedUpload{}, fmt.Errorf("create presigned put object failed: %w", err)
	}

	return PresignedUpload{
		StorageKey: storageKey,
		UploadURL:  url.String(),
		Method:     "PUT",
		Headers:    headers,
		ExpiresIn:  s.expiryMinutes * 60,
	}, nil
}

func (s *S3Client) ObjectExists(ctx context.Context, storageKey string) (bool, error) {
	_, err := s.internal.StatObject(ctx, s.bucket, storageKey, minio.StatObjectOptions{})
	if err == nil {
		return true, nil
	}

	resp := minio.ToErrorResponse(err)
	if isNoSuchObjectError(resp.Code) {
		return false, nil
	}
	return false, err
}

func (s *S3Client) NewDownloadURL(ctx context.Context, storageKey string) (string, error) {
	if strings.TrimSpace(storageKey) == "" {
		return "", errors.New("storage_key is required")
	}

	url, err := s.public.PresignedGetObject(
		ctx,
		s.bucket,
		storageKey,
		time.Duration(s.expiryMinutes)*time.Minute,
		nil,
	)
	if err != nil {
		return "", fmt.Errorf("create presigned get object failed: %w", err)
	}
	return url.String(), nil
}

func (s *S3Client) ReadObjectText(ctx context.Context, storageKey string, maxBytes int64, allowTruncated bool) (TextReadResult, error) {
	if strings.TrimSpace(storageKey) == "" {
		return TextReadResult{}, errors.New("storage_key is required")
	}
	if maxBytes <= 0 {
		return TextReadResult{}, errors.New("maxBytes must be positive")
	}

	object, err := s.internal.GetObject(ctx, s.bucket, storageKey, minio.GetObjectOptions{})
	if err != nil {
		return TextReadResult{}, fmt.Errorf("get object failed: %w", err)
	}
	defer object.Close()

	payload, err := io.ReadAll(io.LimitReader(object, maxBytes+1))
	if err != nil {
		return TextReadResult{}, fmt.Errorf("read object failed: %w", err)
	}

	truncated := int64(len(payload)) > maxBytes
	if truncated {
		if !allowTruncated {
			return TextReadResult{}, ErrObjectTooLarge
		}
		payload = payload[:int(maxBytes)]
	}

	text, detectedEncoding := decodeTextPayload(payload)
	return TextReadResult{
		Text:      text,
		Encoding:  detectedEncoding,
		Truncated: truncated,
	}, nil
}

func (s *S3Client) PutObjectText(ctx context.Context, storageKey, content string) (int64, error) {
	if strings.TrimSpace(storageKey) == "" {
		return 0, errors.New("storage_key is required")
	}

	payload := []byte(content)
	_, err := s.internal.PutObject(
		ctx,
		s.bucket,
		storageKey,
		bytes.NewReader(payload),
		int64(len(payload)),
		minio.PutObjectOptions{ContentType: "text/plain; charset=utf-8"},
	)
	if err != nil {
		return 0, fmt.Errorf("put object failed: %w", err)
	}
	return int64(len(payload)), nil
}

func (s *S3Client) RemoveObject(ctx context.Context, storageKey string) error {
	if strings.TrimSpace(storageKey) == "" {
		return nil
	}

	err := s.internal.RemoveObject(ctx, s.bucket, storageKey, minio.RemoveObjectOptions{})
	if err == nil {
		return nil
	}

	resp := minio.ToErrorResponse(err)
	if isNoSuchObjectError(resp.Code) {
		return nil
	}
	return err
}

func (s *S3Client) RemoveObjects(ctx context.Context, storageKeys []string) error {
	for _, storageKey := range storageKeys {
		if err := s.RemoveObject(ctx, storageKey); err != nil {
			return fmt.Errorf("remove object %s failed: %w", storageKey, err)
		}
	}
	return nil
}

func isNoSuchObjectError(code string) bool {
	return code == "NoSuchKey" || code == "NoSuchObject"
}

func newEndpointOverrideTransport(internalEndpoint string) (*http.Transport, error) {
	dialAddress, err := normalizeDialAddress(internalEndpoint)
	if err != nil {
		return nil, err
	}

	dialer := &net.Dialer{
		Timeout:   5 * time.Second,
		KeepAlive: 30 * time.Second,
	}

	return &http.Transport{
		Proxy: http.ProxyFromEnvironment,
		DialContext: func(ctx context.Context, network, _ string) (net.Conn, error) {
			return dialer.DialContext(ctx, network, dialAddress)
		},
		ForceAttemptHTTP2:     false,
		MaxIdleConns:          100,
		IdleConnTimeout:       90 * time.Second,
		TLSHandshakeTimeout:   10 * time.Second,
		ExpectContinueTimeout: 1 * time.Second,
	}, nil
}

func normalizeDialAddress(endpoint string) (string, error) {
	trimmed := strings.TrimSpace(endpoint)
	if trimmed == "" {
		return "", fmt.Errorf("empty endpoint")
	}

	if strings.Contains(trimmed, "://") {
		parsed, err := url.Parse(trimmed)
		if err != nil {
			return "", fmt.Errorf("parse endpoint failed: %w", err)
		}
		if parsed.Host == "" {
			return "", fmt.Errorf("endpoint host is empty")
		}
		trimmed = parsed.Host
	}

	if !strings.Contains(trimmed, ":") {
		trimmed += ":80"
	}

	if _, _, err := net.SplitHostPort(trimmed); err != nil {
		return "", fmt.Errorf("invalid endpoint %q: %w", endpoint, err)
	}
	return trimmed, nil
}
