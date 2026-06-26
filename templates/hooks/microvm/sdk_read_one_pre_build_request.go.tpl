	// GetMicrovm requires the server-assigned microvmID. If it's not in Status yet,
	// the resource hasn't been created — return NotFound so the reconciler triggers Create.
	if r.ko.Status.MicrovmID == nil || *r.ko.Status.MicrovmID == "" {
		return nil, ackerr.NotFound
	}
