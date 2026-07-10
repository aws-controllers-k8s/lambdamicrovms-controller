	// The user chooses only the MINOR component of baseImageVersion (e.g.
	// "0"); the builder owns the patch. Strip any patch the user pasted (e.g.
	// "0.0" -> "0") so the request matches what the API validator accepts.
	input.BaseImageVersion = sanitizeBaseImageVersion(input.BaseImageVersion)
