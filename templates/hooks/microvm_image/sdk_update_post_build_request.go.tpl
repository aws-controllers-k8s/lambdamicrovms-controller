	// Override ImageIdentifier with the ARN for the Update call.
	// Same reason as ReadOne — API rejects plain names.
	if desired.ko.Status.ACKResourceMetadata != nil && desired.ko.Status.ACKResourceMetadata.ARN != nil {
		arn := string(*desired.ko.Status.ACKResourceMetadata.ARN)
		input.ImageIdentifier = &arn
	}
