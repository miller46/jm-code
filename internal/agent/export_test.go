package agent

// ResetCloneCache clears the clone-tracking state (for tests).
func ResetCloneCache() {
	cloneMu.Lock()
	defer cloneMu.Unlock()
	cloneDone = make(map[string]bool)
}

// MarkCloneDone marks a bare path as already cloned (for tests).
func MarkCloneDone(barePath string) {
	cloneMu.Lock()
	defer cloneMu.Unlock()
	cloneDone[barePath] = true
}
