	// Keep the base image version fresh straight from the update response: the
	// sanitized value the API accepts in Spec, the full resolved value in Status.
	ko.Status.ResolvedBaseImageVersion = resp.BaseImageVersion
	ko.Spec.BaseImageVersion = sanitizeBaseImageVersion(resp.BaseImageVersion)
