package scheduler_test

import (
	"sync/atomic"
	"testing"
	"time"

	"github.com/jack/go-cli/internal/scheduler"
)

func TestScheduler_RunsTasks(t *testing.T) {
	s := scheduler.NewScheduler(10)
	s.Start(2)

	var count atomic.Int32

	for i := 0; i < 5; i++ {
		s.Submit(scheduler.Task{
			Name: "test",
			Fn: func() error {
				count.Add(1)
				return nil
			},
		})
	}

	s.Stop()

	if count.Load() != 5 {
		t.Errorf("expected 5 tasks to run, got %d", count.Load())
	}
}

func TestScheduler_StopDrainsQueue(t *testing.T) {
	s := scheduler.NewScheduler(100)
	s.Start(1)

	done := make(chan struct{})
	s.Submit(scheduler.Task{
		Name: "slow",
		Fn: func() error {
			time.Sleep(10 * time.Millisecond)
			close(done)
			return nil
		},
	})

	s.Stop()

	select {
	case <-done:
		// task completed before stop returned — good
	default:
		t.Fatal("stop returned before task finished")
	}
}
