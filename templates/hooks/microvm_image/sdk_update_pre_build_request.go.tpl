	if delta.DifferentAt("Spec.Tags") {
		if err := rm.syncTags(ctx, desired, latest); err != nil {
			return nil, err
		}
	}
	if !delta.DifferentExcept("Spec.Tags") {
		// Tags-only change: already synced above; skip UpdateMicrovmImage
		// (it triggers a full rebuild).
		return desired, nil
	}
