// Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
//
// Licensed under the Apache License, Version 2.0 (the "License"). You may
// not use this file except in compliance with the License. A copy of the
// License is located at
//
//     http://aws.amazon.com/apache2.0/
//
// or in the "license" file accompanying this file. This file is distributed
// on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
// express or implied. See the License for the specific language governing
// permissions and limitations under the License.

package microvm_image

import (
	"context"

	ackrtlog "github.com/aws-controllers-k8s/runtime/pkg/runtime/log"
	"github.com/aws/aws-sdk-go-v2/aws"
	svcsdk "github.com/aws/aws-sdk-go-v2/service/lambdamicrovms"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"

	svcapitypes "github.com/aws-controllers-k8s/lambdamicrovms-controller/apis/v1alpha1"
)

// syncTags examines the Tags in the supplied MicrovmImage and calls the
// TagResource and UntagResource APIs to ensure that the set of associated
// Tags stays in sync with Spec.Tags. Tags are never sent through
// UpdateMicrovmImage: that operation triggers a rebuild and cuts a new image
// version, while the tag APIs mutate tags in place.
func (rm *resourceManager) syncTags(
	ctx context.Context,
	desired *resource,
	latest *resource,
) (err error) {
	rlog := ackrtlog.FromContext(ctx)
	exit := rlog.Trace("rm.syncTags")
	defer func() { exit(err) }()

	if latest.ko.Status.ACKResourceMetadata == nil || latest.ko.Status.ACKResourceMetadata.ARN == nil {
		return nil
	}
	arn := (*string)(latest.ko.Status.ACKResourceMetadata.ARN)

	toAdd := map[string]string{}
	toDelete := []string{}

	existingTags := latest.ko.Spec.Tags

	for k, v := range desired.ko.Spec.Tags {
		if ev, found := existingTags[k]; !found || *ev != *v {
			toAdd[k] = *v
		}
	}

	for k := range existingTags {
		if _, found := desired.ko.Spec.Tags[k]; !found {
			toDelete = append(toDelete, k)
		}
	}

	if len(toDelete) > 0 {
		_, err = rm.sdkapi.UntagResource(ctx, &svcsdk.UntagResourceInput{
			Resource: arn,
			TagKeys:  toDelete,
		})
		rm.metrics.RecordAPICall("UPDATE", "UntagResource", err)
		if err != nil {
			return err
		}
	}
	if len(toAdd) > 0 {
		_, err = rm.sdkapi.TagResource(ctx, &svcsdk.TagResourceInput{
			Resource: arn,
			Tags:     toAdd,
		})
		rm.metrics.RecordAPICall("UPDATE", "TagResource", err)
		if err != nil {
			return err
		}
	}
	return nil
}

// enrichSpecFromActiveVersion fills nil Spec fields on ko from the image's
// latest active version. GetMicrovmImage does not return the build
// configuration (baseImageArn, buildRoleArn, codeArtifact, ...) because it is
// versioned, so a CR adopted with a partial or empty spec can only be
// completed from the version-level API. The extra call is skipped when the
// build configuration is already present (the normal, non-adoption path) or
// when the image has no successfully built version to read from.
func (rm *resourceManager) enrichSpecFromActiveVersion(
	ctx context.Context,
	ko *svcapitypes.MicrovmImage,
) error {
	if ko.Status.LatestActiveImageVersion == nil {
		return nil
	}
	if ko.Spec.BaseImageARN != nil && ko.Spec.BuildRoleARN != nil && ko.Spec.CodeArtifact != nil {
		return nil
	}
	if ko.Status.ACKResourceMetadata == nil || ko.Status.ACKResourceMetadata.ARN == nil {
		return nil
	}

	input := &svcsdk.GetMicrovmImageVersionInput{
		ImageIdentifier: (*string)(ko.Status.ACKResourceMetadata.ARN),
		ImageVersion:    ko.Status.LatestActiveImageVersion,
	}
	resp, err := rm.sdkapi.GetMicrovmImageVersion(ctx, input)
	rm.metrics.RecordAPICall("READ_ONE", "GetMicrovmImageVersion", err)
	if err != nil {
		return err
	}

	if ko.Spec.BaseImageARN == nil {
		ko.Spec.BaseImageARN = resp.BaseImageArn
	}
	// BaseImageVersion is deliberately not enriched: the read API reports a
	// resolved minor version ("0.0") that UpdateMicrovmImage rejects, which
	// expects a major version ("1").
	if ko.Spec.BuildRoleARN == nil {
		ko.Spec.BuildRoleARN = resp.BuildRoleArn
	}
	if ko.Spec.CodeArtifact == nil {
		if uri, ok := resp.CodeArtifact.(*svcsdktypes.CodeArtifactMemberUri); ok {
			ko.Spec.CodeArtifact = &svcapitypes.CodeArtifact{URI: &uri.Value}
		}
	}
	if ko.Spec.Description == nil {
		ko.Spec.Description = resp.Description
	}
	if ko.Spec.EgressNetworkConnectors == nil && resp.EgressNetworkConnectors != nil {
		ko.Spec.EgressNetworkConnectors = aws.StringSlice(resp.EgressNetworkConnectors)
	}
	if ko.Spec.EnvironmentVariables == nil && resp.EnvironmentVariables != nil {
		ko.Spec.EnvironmentVariables = aws.StringMap(resp.EnvironmentVariables)
	}
	if ko.Spec.AdditionalOsCapabilities == nil && resp.AdditionalOsCapabilities != nil {
		caps := []*string{}
		for _, c := range resp.AdditionalOsCapabilities {
			caps = append(caps, aws.String(string(c)))
		}
		ko.Spec.AdditionalOsCapabilities = caps
	}

	return nil
}
