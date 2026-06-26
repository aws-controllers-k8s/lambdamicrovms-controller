	// TerminateMicrovm returns an empty response — the VM terminates asynchronously.
	// Poll GetMicrovm until TERMINATED or NotFound, then let the runtime remove the finalizer.
	if err == nil {
		observed, findErr := rm.sdkFind(ctx, r)
		if findErr != nil {
			if findErr == ackerr.NotFound {
				return r, nil
			}
			return nil, findErr
		}
		r.SetStatus(observed)
		return r, requeueWaitWhileTerminating
	}
