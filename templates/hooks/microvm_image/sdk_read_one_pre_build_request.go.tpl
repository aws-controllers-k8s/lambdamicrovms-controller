	// GetMicrovmImage requires an ARN for ImageIdentifier — plain names are rejected with
	// ValidationException. If ARN isn't set yet, the resource hasn't been created.
	if r.ko.Status.ACKResourceMetadata == nil || r.ko.Status.ACKResourceMetadata.ARN == nil {
		return nil, ackerr.NotFound
	}
