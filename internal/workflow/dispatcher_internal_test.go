package workflow

import (
	"context"
	"testing"
	"time"
)

func TestRunAll_SkipsWhenAlreadyRunning(t *testing.T) {
	d := &Dispatcher{}

	if !d.mu.TryLock() {
		t.Fatal("expected to acquire dispatch lock on fresh dispatcher")
	}
	defer d.mu.Unlock()

	done := make(chan error, 1)
	go func() {
		done <- d.RunAll(context.Background())
	}()

	select {
	case err := <-done:
		if err != nil {
			t.Fatalf("expected nil error when skipping, got %v", err)
		}
	case <-time.After(2 * time.Second):
		t.Fatal("RunAll blocked instead of skipping while dispatch already running")
	}
}
