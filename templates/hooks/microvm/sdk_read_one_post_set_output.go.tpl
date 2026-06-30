	if ko.Status.State != nil && *ko.Status.State == string(svcapitypes.MicrovmState_TERMINATED) {
		if !rm.isDeleting(r) {
			msg := "MicroVM terminated unexpectedly (idle policy or max duration exceeded)"
			if ko.Status.StateReason != nil && *ko.Status.StateReason != "" {
				msg = *ko.Status.StateReason
			}
			return &resource{ko}, ackerr.NewTerminalError(errors.New(msg))
		}
	}
