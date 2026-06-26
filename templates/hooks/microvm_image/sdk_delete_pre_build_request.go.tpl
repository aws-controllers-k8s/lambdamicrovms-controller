	// Already deleted — skip the API call, let the runtime remove the finalizer.
	if r.ko.Status.State != nil && *r.ko.Status.State == string(svcapitypes.MicrovmImageState_DELETED) {
		return r, nil
	}
	// Currently deleting — don't call DeleteMicrovmImage again. Requeue and wait.
	if r.ko.Status.State != nil && *r.ko.Status.State == string(svcapitypes.MicrovmImageState_DELETING) {
		return r, requeueWaitWhileDeleting
	}
