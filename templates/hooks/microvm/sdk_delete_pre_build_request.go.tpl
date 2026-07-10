	// If the VM has already reached TERMINATED there is nothing left to
	// terminate. AWS retains terminated VMs, so GetMicrovm never returns
	// NotFound and the generated delete flow would otherwise requeue forever
	// (the deletable guard also rejects TERMINATED). Treat delete as complete by
	// returning (nil, nil) so the runtime removes the finalizer. TERMINATING and
	// other non-terminal states (e.g. SUSPENDED) deliberately fall through so we
	// never drop the finalizer while the VM might still be alive. See
	// isTerminated in hooks.go for the full rationale.
	if isTerminated(r) {
		return nil, nil
	}
