	// Orphan safety: ensure the server-assigned microvmID was persisted to Status.
	// Without this, a crash before status patch would leave a running VM with no way to terminate it.
	if ko.Status.MicrovmID == nil || *ko.Status.MicrovmID == "" {
		return nil, fmt.Errorf("RunMicrovm response missing microvmId — cannot persist identifier for orphan safety")
	}
