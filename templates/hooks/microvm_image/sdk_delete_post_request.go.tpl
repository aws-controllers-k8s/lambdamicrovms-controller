	// DeleteMicrovmImage is async — the image transitions DELETING -> DELETED.
	// Poll until the image is gone or in DELETED state before letting the runtime
	// remove the finalizer.
	if err == nil {
		observed, findErr := rm.sdkFind(ctx, r)
		if findErr != nil {
			if findErr == ackerr.NotFound {
				return r, nil
			}
			return nil, findErr
		}
		state := observed.ko.Status.State
		if state != nil && *state == string(svcapitypes.MicrovmImageState_DELETED) {
			return r, nil
		}
		r.SetStatus(observed)
		return r, requeueWaitWhileDeleting
	}
