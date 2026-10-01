//go:build !windows

package collector

import (
	"context"
	"errors"
	"time"

	"tiai/agent/internal/models"
)

// errUnsupported is returned by the non-Windows stubs: Defender is Windows-only.
var errUnsupported = errors.New("defender collector is only supported on windows")

func ReadDefenderState(ctx context.Context) (*models.DefenderState, error) {
	return &models.DefenderState{}, nil
}

func ReadThreats(ctx context.Context) ([]models.Threat, error) { return nil, nil }

func RunQuickScan(ctx context.Context) (string, error) { return "", errUnsupported }

func RunFullScan(ctx context.Context, timeout time.Duration) (string, error) {
	return "", errUnsupported
}

func UpdateSignatures(ctx context.Context) (string, error) { return "", errUnsupported }
