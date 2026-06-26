	// Guard: can't terminate without the server-assigned ID.
	if r.ko.Status.MicrovmID == nil || *r.ko.Status.MicrovmID == "" {
		return nil, ackerr.NewTerminalError(fmt.Errorf("microvmId not found in status — resource may be orphaned"))
	}
	// Already terminated — skip the API call, let the runtime remove the finalizer.
	if r.ko.Status.State != nil && *r.ko.Status.State == string(svcapitypes.MicrovmState_TERMINATED) {
		return r, nil
	}
	// Currently terminating — don't call TerminateMicrovm again (would get ConflictException).
	// Requeue and wait for it to finish.
	if r.ko.Status.State != nil && *r.ko.Status.State == string(svcapitypes.MicrovmState_TERMINATING) {
		return r, requeueWaitWhileTerminating
	}
