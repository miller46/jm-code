package scheduler

import "sync"

type Task struct {
	Name string
	Fn   func() error
}

type Scheduler struct {
	queue chan Task
	wg    sync.WaitGroup
}

func NewScheduler(size int) *Scheduler {
	return &Scheduler{
		queue: make(chan Task, size),
	}
}

func (s *Scheduler) Start(n int) {
	for i := 0; i < n; i++ {
		s.wg.Add(1)
		go s.worker()
	}
}

func (s *Scheduler) Submit(task Task) {
	s.queue <- task
}

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
