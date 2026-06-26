	// Override ImageIdentifier with the ARN for the Delete call.
	// Same reason as ReadOne — API rejects plain names.
	if r.ko.Status.ACKResourceMetadata != nil && r.ko.Status.ACKResourceMetadata.ARN != nil {
		arn := string(*r.ko.Status.ACKResourceMetadata.ARN)
		input.ImageIdentifier = &arn
	}
