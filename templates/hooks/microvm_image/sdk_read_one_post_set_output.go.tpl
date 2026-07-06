	if ko.Status.ACKResourceMetadata == nil {
		ko.Status.ACKResourceMetadata = &ackv1alpha1.ResourceMetadata{}
	}
	if resp.ImageArn != nil {
		arn := ackv1alpha1.AWSResourceName(*resp.ImageArn)
		ko.Status.ACKResourceMetadata.ARN = &arn
	}
	if err := rm.refreshSpecFromActiveVersion(ctx, ko); err != nil {
		return nil, err
	}
