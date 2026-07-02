	if delta.DifferentAt("Spec.Tags") {
		if err := rm.syncTags(ctx, desired, latest); err != nil {
			return nil, err
		}
	}
	if !delta.DifferentExcept("Spec.Tags") {
		// Tags-only change: already synced via TagResource/UntagResource
		// above. Do NOT call UpdateMicrovmImage — it triggers a full image
		// rebuild and cuts a new image version.
		return desired, nil
	}
