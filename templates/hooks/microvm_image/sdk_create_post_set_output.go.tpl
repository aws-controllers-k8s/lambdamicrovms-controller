	if ko.Status.ACKResourceMetadata == nil {
		ko.Status.ACKResourceMetadata = &ackv1alpha1.ResourceMetadata{}
	}
	if resp.ImageArn != nil {
		arn := ackv1alpha1.AWSResourceName(*resp.ImageArn)
		ko.Status.ACKResourceMetadata.ARN = &arn
	}
	// Persist the sanitized base image version the API accepts into Spec (and
	// the full resolved value into Status) straight from the create response, so
	// it lands in etcd immediately and later reconciles see no spurious delta.
	ko.Status.ResolvedBaseImageVersion = resp.BaseImageVersion
	ko.Spec.BaseImageVersion = sanitizeBaseImageVersion(resp.BaseImageVersion)
