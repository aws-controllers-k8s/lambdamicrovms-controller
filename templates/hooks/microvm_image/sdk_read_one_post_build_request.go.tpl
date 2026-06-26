	// Override ImageIdentifier with the ARN. The codegen sets it from Spec.Name (via rename),
	// but the API only accepts ARN format for Get/Update/Delete — not plain names.
	if r.ko.Status.ACKResourceMetadata != nil && r.ko.Status.ACKResourceMetadata.ARN != nil {
		arn := string(*r.ko.Status.ACKResourceMetadata.ARN)
		input.ImageIdentifier = &arn
	}
