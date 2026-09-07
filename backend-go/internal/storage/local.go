package storage

import (
	"context"
	"crypto/sha256"
	"encoding/hex"
	"errors"
	"io"
	"os"
	"path/filepath"
	"strings"
)

var ErrObjectTooLarge = errors.New("object too large")

type ObjectInfo struct {
	SizeBytes int64

	SHA256 string
}

type ObjectStore interface {
	Put(
		context.Context,
		string,
		io.Reader,
		int64,
	) (ObjectInfo, error)

	Delete(
		context.Context,
		string,
	) error
}

type LocalObjectStore struct {
	root string
}

func NewLocalObjectStore(
	root string,
) (*LocalObjectStore, error) {
	root = strings.TrimSpace(root)

	if root == "" {
		root = "./data/knowledge"
	}

	absolute, err := filepath.Abs(root)

	if err != nil {
		return nil, err
	}

	if err = os.MkdirAll(
		absolute,
		0o750,
	); err != nil {
		return nil, err
	}

	return &LocalObjectStore{
		root: absolute,
	}, nil
}

func (s *LocalObjectStore) objectPath(
	key string,
) (string, error) {
	key = strings.ReplaceAll(
		key,
		"\\",
		"/",
	)

	cleaned := filepath.Clean(
		filepath.FromSlash(key),
	)

	if cleaned == "." ||
		filepath.IsAbs(cleaned) ||
		strings.HasPrefix(cleaned, "..") {
		return "", errors.New("invalid object key")
	}

	full := filepath.Join(
		s.root,
		cleaned,
	)

	relative, err := filepath.Rel(
		s.root,
		full,
	)

	if err != nil ||
		relative == ".." ||
		strings.HasPrefix(
			relative,
			".."+string(filepath.Separator),
		) {
		return "", errors.New("object path escapes storage root")
	}

	return full, nil
}

func (s *LocalObjectStore) Put(
	ctx context.Context,
	key string,
	source io.Reader,
	maxBytes int64,
) (ObjectInfo, error) {
	if maxBytes <= 0 {
		return ObjectInfo{}, errors.New("max bytes must be positive")
	}

	select {
	case <-ctx.Done():
		return ObjectInfo{}, ctx.Err()
	default:
	}

	target, err := s.objectPath(key)
	if err != nil {
		return ObjectInfo{}, err
	}

	if err = os.MkdirAll(
		filepath.Dir(target),
		0o750,
	); err != nil {
		return ObjectInfo{}, err
	}

	temporary := target + ".uploading"
	file, err := os.OpenFile(
		temporary,
		os.O_CREATE|os.O_TRUNC|os.O_WRONLY,
		0o640,
	)
	if err != nil {
		return ObjectInfo{}, err
	}

	success := false
	defer func() {
		_ = file.Close()
		if !success {
			_ = os.Remove(temporary)
		}
	}()

	hasher := sha256.New()
	written, err := io.Copy(
		io.MultiWriter(file, hasher),
		io.LimitReader(source, maxBytes+1),
	)
	if err != nil {
		return ObjectInfo{}, err
	}

	if written > maxBytes {
		return ObjectInfo{}, ErrObjectTooLarge
	}

	if err = file.Sync(); err != nil {
		return ObjectInfo{}, err
	}

	if err = file.Close(); err != nil {
		return ObjectInfo{}, err
	}

	if err = os.Rename(
		temporary,
		target,
	); err != nil {
		return ObjectInfo{}, err
	}

	success = true

	return ObjectInfo{
		SizeBytes: written,
		SHA256:    hex.EncodeToString(hasher.Sum(nil)),
	}, nil
}

func (s *LocalObjectStore) Open(
	ctx context.Context,
	key string,
) (io.ReadCloser, error) {
	select {
	case <-ctx.Done():
		return nil, ctx.Err()
	default:
	}

	target, err := s.objectPath(key)
	if err != nil {
		return nil, err
	}

	file, err := os.Open(target)
	if errors.Is(err, os.ErrNotExist) {
		return nil, os.ErrNotExist
	}

	return file, err
}

func (s *LocalObjectStore) Delete(
	ctx context.Context,
	key string,
) error {
	select {
	case <-ctx.Done():
		return ctx.Err()
	default:
	}

	target, err := s.objectPath(key)
	if err != nil {
		return err
	}

	err = os.Remove(target)
	if errors.Is(err, os.ErrNotExist) {
		return nil
	}

	return err
}
