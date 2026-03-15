package github_test

import (
	"testing"

	"github.com/jack/go-cli/internal/github"
)

func TestEvaluateReviews_AllApproved(t *testing.T) {
	reviews := []github.Review{
		{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		{Author: "rev2", State: github.ReviewApproved, SubmittedAt: "2025-01-01T01:00:00Z", CommitOID: "sha1"},
	}
	required := []string{"rev1", "rev2"}

	eval := github.EvaluateReviews(reviews, required, &github.ApprovalRules{MinApprovals: 2})

	if !eval.AllRequiredApproved {
		t.Error("expected AllRequiredApproved = true")
	}
	if eval.AnyChangesRequested {
		t.Error("expected AnyChangesRequested = false")
	}
}

func TestEvaluateReviews_ChangesRequested(t *testing.T) {
	reviews := []github.Review{
		{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		{Author: "rev2", State: github.ReviewChangesRequested, SubmittedAt: "2025-01-01T01:00:00Z", CommitOID: "sha1"},
	}
	required := []string{"rev1", "rev2"}

	eval := github.EvaluateReviews(reviews, required, &github.ApprovalRules{MinApprovals: 2})

	if eval.AllRequiredApproved {
		t.Error("expected AllRequiredApproved = false")
	}
	if !eval.AnyChangesRequested {
		t.Error("expected AnyChangesRequested = true")
	}
}

func TestEvaluateReviews_LatestReviewWins(t *testing.T) {
	reviews := []github.Review{
		{Author: "rev1", State: github.ReviewChangesRequested, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-02T00:00:00Z", CommitOID: "sha2"},
	}

	eval := github.EvaluateReviews(reviews, []string{"rev1"}, &github.ApprovalRules{MinApprovals: 1})

	if !eval.AllRequiredApproved {
		t.Error("expected AllRequiredApproved = true (latest review is approval)")
	}
	if eval.AnyChangesRequested {
		t.Error("expected AnyChangesRequested = false (latest review overrides)")
	}
	if eval.ReviewSHAByReviewer["rev1"] != "sha2" {
		t.Errorf("ReviewSHAByReviewer[rev1] = %q, want sha2", eval.ReviewSHAByReviewer["rev1"])
	}
}

func TestEvaluateReviews_MinApprovals(t *testing.T) {
	reviews := []github.Review{
		{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
	}

	eval := github.EvaluateReviews(reviews, []string{}, &github.ApprovalRules{MinApprovals: 2})

	if eval.AllRequiredApproved {
		t.Error("expected AllRequiredApproved = false (only 1 of 2 approvals)")
	}
}

func TestEvaluateReviews_VetoPower(t *testing.T) {
	reviews := []github.Review{
		{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		{Author: "rev2", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		{Author: "vetoer", State: github.ReviewChangesRequested, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
	}

	eval := github.EvaluateReviews(reviews, []string{}, &github.ApprovalRules{
		MinApprovals: 2,
		VetoPowers:   []string{"vetoer"},
	})

	if !eval.AnyChangesRequested {
		t.Error("expected AnyChangesRequested = true (vetoer requested changes)")
	}
}

func TestDeterminePRAction_Merged(t *testing.T) {
	pr := github.PRDetail{State: "MERGED", HeadRefOid: "sha1"}
	status, action, _, _, _ := github.DeterminePRAction(pr, nil, nil, nil)

	if status != github.StatusMerged {
		t.Errorf("status = %q, want %q", status, github.StatusMerged)
	}
	if action != github.ActionNone {
		t.Errorf("action = %q, want %q", action, github.ActionNone)
	}
}

func TestDeterminePRAction_Conflicts(t *testing.T) {
	pr := github.PRDetail{State: "OPEN", Mergeable: "CONFLICTING", HeadRefOid: "sha1"}
	status, action, _, _, _ := github.DeterminePRAction(pr, nil, nil, nil)

	if status != github.StatusConflicting {
		t.Errorf("status = %q, want %q", status, github.StatusConflicting)
	}
	if action != github.ActionNeedsConflictResolution {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsConflictResolution)
	}
}

func TestDeterminePRAction_ChecksFailing(t *testing.T) {
	pr := github.PRDetail{
		State:      "OPEN",
		Mergeable:  "MERGEABLE",
		HeadRefOid: "sha1",
		StatusChecks: []github.StatusCheck{
			{TypeName: "CheckRun", Name: "ci", Conclusion: "FAILURE", Status: "COMPLETED"},
		},
	}
	status, action, _, _, _ := github.DeterminePRAction(pr, nil, nil, nil)

	if status != github.StatusChecksFailing {
		t.Errorf("status = %q, want %q", status, github.StatusChecksFailing)
	}
	if action != github.ActionNeedsStatusFix {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsStatusFix)
	}
}

func TestDeterminePRAction_ApprovedReadyToMerge(t *testing.T) {
	pr := github.PRDetail{
		State:      "OPEN",
		Mergeable:  "MERGEABLE",
		HeadRefOid: "sha1",
		Reviews: []github.Review{
			{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		},
	}
	required := []string{"rev1"}
	rules := &github.ApprovalRules{MinApprovals: 1}

	status, action, _, _, _ := github.DeterminePRAction(pr, nil, required, rules)

	if status != github.StatusApproved {
		t.Errorf("status = %q, want %q", status, github.StatusApproved)
	}
	if action != github.ActionReadyToMerge {
		t.Errorf("action = %q, want %q", action, github.ActionReadyToMerge)
	}
}

func TestDeterminePRAction_ApprovedButSHAMismatch(t *testing.T) {
	pr := github.PRDetail{
		State:      "OPEN",
		Mergeable:  "MERGEABLE",
		HeadRefOid: "sha2",
		Reviews: []github.Review{
			{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		},
	}

	status, action, _, _, _ := github.DeterminePRAction(pr, nil, []string{"rev1"}, &github.ApprovalRules{MinApprovals: 1})

	if status != github.StatusPendingReview {
		t.Errorf("status = %q, want %q", status, github.StatusPendingReview)
	}
	if action != github.ActionNeedsReview {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsReview)
	}
}

func TestDeterminePRAction_ChangesRequestedNeedsFix(t *testing.T) {
	pr := github.PRDetail{
		State:      "OPEN",
		Mergeable:  "MERGEABLE",
		HeadRefOid: "sha1",
		Reviews: []github.Review{
			{Author: "rev1", State: github.ReviewChangesRequested, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		},
	}

	status, action, _, _, _ := github.DeterminePRAction(pr, nil, []string{"rev1"}, &github.ApprovalRules{MinApprovals: 1})

	if status != github.StatusChangesRequested {
		t.Errorf("status = %q, want %q", status, github.StatusChangesRequested)
	}
	if action != github.ActionNeedsFix {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsFix)
	}
}

// Regression: PR miller46/jm-api#153 — CONFLICTING but fully approved with
// passing checks. Must return ActionNeedsConflictResolution, never ActionReadyToMerge.
func TestDeterminePRAction_ConflictingOverridesApproval(t *testing.T) {
	pr := github.PRDetail{
		Number:      153,
		Title:       "Add request-level timeout middleware across API routes",
		State:       "OPEN",
		Mergeable:   "CONFLICTING",
		MergeState:  "DIRTY",
		HeadRefOid:  "a4d932d5010feed041a43b8566e27db22f3fb1f5",
		HeadRefName: "feature/issue-151",
		Body:        "Closes #151",
		Reviews: []github.Review{
			{Author: "codesnob", State: github.ReviewApproved, SubmittedAt: "2026-03-14T20:18:56Z", CommitOID: "a4d932d5010feed041a43b8566e27db22f3fb1f5"},
			{Author: "architect", State: github.ReviewApproved, SubmittedAt: "2026-03-14T20:24:23Z", CommitOID: "a4d932d5010feed041a43b8566e27db22f3fb1f5"},
		},
		StatusChecks: []github.StatusCheck{
			{TypeName: "CheckRun", Name: "quality-gates", Conclusion: "SUCCESS", Status: "COMPLETED"},
			{TypeName: "CheckRun", Name: "integration-tests", Conclusion: "SUCCESS", Status: "COMPLETED"},
		},
	}
	required := []string{"codesnob", "architect"}
	rules := &github.ApprovalRules{MinApprovals: 2}

	status, action, allApproved, _, _ := github.DeterminePRAction(pr, nil, required, rules)

	if status != github.StatusConflicting {
		t.Errorf("status = %q, want %q", status, github.StatusConflicting)
	}
	if action != github.ActionNeedsConflictResolution {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsConflictResolution)
	}
	if allApproved {
		t.Error("allApproved should be false when conflicts take priority")
	}
}

func TestDeterminePRAction_UnknownMergeableNotReadyToMerge(t *testing.T) {
	pr := github.PRDetail{
		State:      "OPEN",
		Mergeable:  "UNKNOWN",
		HeadRefOid: "sha1",
		Reviews: []github.Review{
			{Author: "rev1", State: github.ReviewApproved, SubmittedAt: "2025-01-01T00:00:00Z", CommitOID: "sha1"},
		},
		StatusChecks: []github.StatusCheck{
			{TypeName: "CheckRun", Name: "ci", Conclusion: "SUCCESS", Status: "COMPLETED"},
		},
	}
	required := []string{"rev1"}
	rules := &github.ApprovalRules{MinApprovals: 1}

	_, action, _, _, _ := github.DeterminePRAction(pr, nil, required, rules)

	if action == github.ActionReadyToMerge {
		t.Errorf("action should NOT be %q when mergeable is UNKNOWN", github.ActionReadyToMerge)
	}
}

func TestDeterminePRAction_DefaultNeedsReview(t *testing.T) {
	pr := github.PRDetail{
		State:      "OPEN",
		Mergeable:  "MERGEABLE",
		HeadRefOid: "sha1",
	}

	status, action, _, _, _ := github.DeterminePRAction(pr, nil, []string{"rev1"}, &github.ApprovalRules{MinApprovals: 1})

	if status != github.StatusPendingReview {
		t.Errorf("status = %q, want %q", status, github.StatusPendingReview)
	}
	if action != github.ActionNeedsReview {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsReview)
	}
}

func TestDetermineIssueAction_Closed(t *testing.T) {
	issue := github.Issue{State: "closed", Number: 1}
	status, action := github.DetermineIssueAction(issue, nil, 0)

	if status != github.StatusClosed {
		t.Errorf("status = %q, want %q", status, github.StatusClosed)
	}
	if action != github.ActionNone {
		t.Errorf("action = %q, want %q", action, github.ActionNone)
	}
}

func TestDetermineIssueAction_HasLinkedPR(t *testing.T) {
	issue := github.Issue{State: "open", Number: 1}
	status, action := github.DetermineIssueAction(issue, nil, 42)

	if status != github.StatusPRCreated {
		t.Errorf("status = %q, want %q", status, github.StatusPRCreated)
	}
	if action != github.ActionNone {
		t.Errorf("action = %q, want %q", action, github.ActionNone)
	}
}

func TestDetermineIssueAction_NeedsDev(t *testing.T) {
	issue := github.Issue{State: "open", Number: 1}
	status, action := github.DetermineIssueAction(issue, nil, 0)

	if status != github.StatusOpen {
		t.Errorf("status = %q, want %q", status, github.StatusOpen)
	}
	if action != github.ActionNeedsDev {
		t.Errorf("action = %q, want %q", action, github.ActionNeedsDev)
	}
}

func TestApplyDispatchDedupe(t *testing.T) {
	tests := []struct {
		name     string
		action   github.Action
		headSHA  string
		lastSHA  string
		wantAction github.Action
	}{
		{"review not dispatched", github.ActionNeedsReview, "sha1", "", github.ActionNeedsReview},
		{"review already dispatched", github.ActionNeedsReview, "sha1", "sha1", github.ActionNone},
		{"review new SHA", github.ActionNeedsReview, "sha2", "sha1", github.ActionNeedsReview},
		{"fix not dispatched", github.ActionNeedsFix, "sha1", "", github.ActionNeedsFix},
		{"fix already dispatched", github.ActionNeedsFix, "sha1", "sha1", github.ActionNone},
		{"none passthrough", github.ActionNone, "sha1", "", github.ActionNone},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			dispatched := github.DispatchState{}
			switch tt.action {
			case github.ActionNeedsReview:
				dispatched.LastReviewDispatchSHA = tt.lastSHA
			case github.ActionNeedsFix:
				dispatched.LastFixDispatchSHA = tt.lastSHA
			}

			got := github.ApplyDispatchDedupe(tt.action, tt.headSHA, dispatched)
			if got != tt.wantAction {
				t.Errorf("ApplyDispatchDedupe() = %q, want %q", got, tt.wantAction)
			}
		})
	}
}

func TestUpdateIteration(t *testing.T) {
	tests := []struct {
		name          string
		action        github.Action
		iteration     int
		maxIterations int
		wantIteration int
		wantAction    github.Action
	}{
		{"fix within limit", github.ActionNeedsFix, 1, 3, 1, github.ActionNeedsFix},
		{"fix at limit", github.ActionNeedsFix, 3, 3, 3, github.ActionMaxIterationsReached},
		{"fix over limit", github.ActionNeedsFix, 5, 3, 5, github.ActionMaxIterationsReached},
		{"non-fix action", github.ActionNeedsReview, 5, 3, 5, github.ActionNeedsReview},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			iter, action := github.UpdateIteration(tt.action, tt.iteration, tt.maxIterations)
			if iter != tt.wantIteration {
				t.Errorf("iteration = %d, want %d", iter, tt.wantIteration)
			}
			if action != tt.wantAction {
				t.Errorf("action = %q, want %q", action, tt.wantAction)
			}
		})
	}
}

func TestFindLinkedIssue(t *testing.T) {
	tests := []struct {
		name string
		body string
		want int
	}{
		{"closes", "This PR closes #42", 42},
		{"fixes", "fixes #7", 7},
		{"resolves", "Resolves #100", 100},
		{"no match", "Just a regular PR body", 0},
		{"empty", "", 0},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := github.FindLinkedIssue(tt.body, "")
			if got != tt.want {
				t.Errorf("FindLinkedIssue() = %d, want %d", got, tt.want)
			}
		})
	}
}

func TestReconcileDispatchSHAs(t *testing.T) {
	tests := []struct {
		name     string
		existing string
		eval     *github.ReviewEvaluation
		headSHA  string
		want     string
	}{
		{
			name:     "clears stale dispatch (dispatched but not reviewed)",
			existing: `{"rev1":"sha1"}`,
			eval:     &github.ReviewEvaluation{ReviewSHAByReviewer: map[string]string{}},
			headSHA:  "sha1",
			want:     `{}`,
		},
		{
			name:     "preserves dispatch when reviewer actually reviewed",
			existing: `{"rev1":"sha1"}`,
			eval:     &github.ReviewEvaluation{ReviewSHAByReviewer: map[string]string{"rev1": "sha1"}},
			headSHA:  "sha1",
			want:     `{"rev1":"sha1"}`,
		},
		{
			name:     "preserves dispatch for different SHA (old commit)",
			existing: `{"rev1":"sha0"}`,
			eval:     &github.ReviewEvaluation{ReviewSHAByReviewer: map[string]string{}},
			headSHA:  "sha1",
			want:     `{"rev1":"sha0"}`,
		},
		{
			name:     "mixed: clears stale, preserves reviewed",
			existing: `{"rev1":"sha1","rev2":"sha1"}`,
			eval:     &github.ReviewEvaluation{ReviewSHAByReviewer: map[string]string{"rev2": "sha1"}},
			headSHA:  "sha1",
			want:     `{"rev2":"sha1"}`,
		},
		{
			name:     "nil eval clears all matching dispatches",
			existing: `{"rev1":"sha1"}`,
			eval:     nil,
			headSHA:  "sha1",
			want:     `{}`,
		},
		{
			name:     "corrupt JSON returns original",
			existing: `not-json`,
			eval:     nil,
			headSHA:  "sha1",
			want:     `not-json`,
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := github.ReconcileDispatchSHAs(tt.existing, tt.eval, tt.headSHA)
			if got != tt.want {
				t.Errorf("ReconcileDispatchSHAs() = %q, want %q", got, tt.want)
			}
		})
	}
}

func TestHasFailingChecks(t *testing.T) {
	tests := []struct {
		name   string
		checks []github.StatusCheck
		want   bool
	}{
		{"no checks", nil, false},
		{"all passing", []github.StatusCheck{
			{TypeName: "CheckRun", Conclusion: "SUCCESS", Status: "COMPLETED"},
		}, false},
		{"one failing", []github.StatusCheck{
			{TypeName: "CheckRun", Conclusion: "FAILURE", Status: "COMPLETED"},
		}, true},
		{"status context failure", []github.StatusCheck{
			{TypeName: "StatusContext", State: "FAILURE"},
		}, true},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			got := github.HasFailingChecks(tt.checks)
			if got != tt.want {
				t.Errorf("HasFailingChecks() = %v, want %v", got, tt.want)
			}
		})
	}
}
