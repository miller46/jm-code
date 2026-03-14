package scheduler

import "sync"

// Task is a unit of work the scheduler can run.
type Task struct {
	Name string
	Fn   func() error
}

// Scheduler distributes tasks across a pool of goroutine workers.
type Scheduler struct {
	queue chan Task
	wg    sync.WaitGroup
}

// NewScheduler creates a scheduler with the given queue capacity.
func NewScheduler(size int) *Scheduler {
	return &Scheduler{
		queue: make(chan Task, size),
	}
}

// Start launches n worker goroutines.
func (s *Scheduler) Start(n int) {
	for i := 0; i < n; i++ {
		s.wg.Add(1)
		go s.worker()
	}
}

// Submit adds a task to the queue.
func (s *Scheduler) Submit(task Task) {
	s.queue <- task
}

// Stop closes the queue and waits for all workers to finish.
func (s *Scheduler) Stop() {
	close(s.queue)
	s.wg.Wait()
}

func (s *Scheduler) worker() {
	defer s.wg.Done()
	for task := range s.queue {
		_ = task.Fn()
	}
}
