	// The codegen sets Status.ImageARN from the Create response but does NOT copy it
	// into ACKResourceMetadata.ARN. Without this, subsequent ReadOne calls return NotFound
	// (our pre_build_request hook gates on ARN), causing the reconciler to call Create again.
	if ko.Status.ImageARN != nil {
		arn := ackv1alpha1.AWSResourceName(*ko.Status.ImageARN)
		ko.Status.ACKResourceMetadata.ARN = &arn
	}
