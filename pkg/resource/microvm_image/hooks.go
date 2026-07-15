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
	"strings"

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

// refreshSpecFromActiveVersion overwrites the build-configuration Spec fields
// on ko with the actual state of the image's latest active version.
//
// GetMicrovmImage (the ReadOne call) does NOT return the build configuration
// (baseImageArn, buildRoleArn, codeArtifact, description, ...) — those live on
// the image version, not the image. Without this, `latest` keeps the desired
// values (sdkFind starts `latest` as a copy of `desired`), so drift on those
// fields is invisible and an adopted CR can never reconstruct its spec.
//
// The refresh is unconditional (overwrite, not fill-when-nil) so that `latest`
// reflects AWS truth: this both completes the spec for a freshly-adopted image
// AND lets delta detection see out-of-band drift, which the reconciler corrects
// by issuing UpdateMicrovmImage (a rebuild). Skipped only when the image has no
// successfully built version to read from yet.
//
// BaseImageVersion is also refreshed, sanitized: Spec gets the value the API
// accepts (drift detection + adoption) and Status the full resolved value. It
// is late-initialized (generator.yaml) so the back-fill into desired does not
// read as perpetual drift.
func (rm *resourceManager) refreshSpecFromActiveVersion(
	ctx context.Context,
	ko *svcapitypes.MicrovmImage,
) error {
	if ko.Status.LatestActiveImageVersion == nil {
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

	ko.Status.ResolvedBaseImageVersion = resp.BaseImageVersion
	ko.Spec.BaseImageVersion = sanitizeBaseImageVersion(resp.BaseImageVersion)

	// Mirror every build-config field from the active version into Spec. Nil
	// responses assign nil, which is the intended "field is unset on AWS"
	// state.
	ko.Spec.BaseImageARN = resp.BaseImageArn
	ko.Spec.BuildRoleARN = resp.BuildRoleArn
	ko.Spec.Description = resp.Description
	ko.Spec.EgressNetworkConnectors = aws.StringSlice(resp.EgressNetworkConnectors)
	ko.Spec.EnvironmentVariables = aws.StringMap(resp.EnvironmentVariables)
	ko.Spec.AdditionalOsCapabilities = capabilitiesFromSDK(resp.AdditionalOsCapabilities)
	ko.Spec.CodeArtifact = codeArtifactFromSDK(resp.CodeArtifact)
	ko.Spec.CPUConfigurations = cpuConfigurationsFromSDK(resp.CpuConfigurations)
	ko.Spec.Hooks = hooksFromSDK(resp.Hooks)
	ko.Spec.Logging = loggingFromSDK(resp.Logging)
	ko.Spec.Resources = resourcesFromSDK(resp.Resources)

	return nil
}

// sanitizeBaseImageVersion reduces a resolved version (e.g. "0.0") to the single
// leading integer the Create/Update validator accepts (e.g. "0"). Applied only
// to API-returned values in refreshSpecFromActiveVersion, never to user input.
func sanitizeBaseImageVersion(v *string) *string {
	if v == nil {
		return nil
	}
	if idx := strings.Index(*v, "."); idx >= 0 {
		minor := (*v)[:idx]
		return &minor
	}
	return v
}

// capabilitiesFromSDK maps the SDK Capability enum slice to the Spec's
// []*string representation.
func capabilitiesFromSDK(in []svcsdktypes.Capability) []*string {
	if in == nil {
		return nil
	}
	out := []*string{}
	for _, c := range in {
		out = append(out, aws.String(string(c)))
	}
	return out
}

// codeArtifactFromSDK maps the SDK CodeArtifact union to the Spec type. Only
// the Uri member is modeled.
func codeArtifactFromSDK(in svcsdktypes.CodeArtifact) *svcapitypes.CodeArtifact {
	if in == nil {
		return nil
	}
	out := &svcapitypes.CodeArtifact{}
	if uri, ok := in.(*svcsdktypes.CodeArtifactMemberUri); ok {
		out.URI = &uri.Value
	}
	return out
}

// cpuConfigurationsFromSDK maps the SDK CpuConfiguration slice to Spec.
func cpuConfigurationsFromSDK(in []svcsdktypes.CpuConfiguration) []*svcapitypes.CPUConfiguration {
	if in == nil {
		return nil
	}
	out := []*svcapitypes.CPUConfiguration{}
	for _, iter := range in {
		elem := &svcapitypes.CPUConfiguration{}
		if iter.Architecture != "" {
			elem.Architecture = aws.String(string(iter.Architecture))
		}
		out = append(out, elem)
	}
	return out
}

// resourcesFromSDK maps the SDK Resources slice to Spec, widening
// MinimumMemoryInMiB from int32 to int64.
func resourcesFromSDK(in []svcsdktypes.Resources) []*svcapitypes.Resources {
	if in == nil {
		return nil
	}
	out := []*svcapitypes.Resources{}
	for _, iter := range in {
		elem := &svcapitypes.Resources{}
		if iter.MinimumMemoryInMiB != nil {
			v := int64(*iter.MinimumMemoryInMiB)
			elem.MinimumMemoryInMiB = &v
		}
		out = append(out, elem)
	}
	return out
}

// loggingFromSDK maps the SDK Logging union (CloudWatch or Disabled) to Spec.
func loggingFromSDK(in svcsdktypes.Logging) *svcapitypes.Logging {
	if in == nil {
		return nil
	}
	out := &svcapitypes.Logging{}
	switch t := in.(type) {
	case *svcsdktypes.LoggingMemberCloudWatch:
		cw := &svcapitypes.CloudWatchLogging{}
		if t.Value.LogGroup != nil {
			cw.LogGroup = t.Value.LogGroup
		}
		if t.Value.LogStream != nil {
			cw.LogStream = t.Value.LogStream
		}
		out.CloudWatch = cw
	case *svcsdktypes.LoggingMemberDisabled:
		out.Disabled = map[string]*string{}
	}
	return out
}

// hooksFromSDK maps the SDK Hooks struct to Spec, widening the int32 timeout
// and port fields to int64.
func hooksFromSDK(in *svcsdktypes.Hooks) *svcapitypes.Hooks {
	if in == nil {
		return nil
	}
	out := &svcapitypes.Hooks{}
	if in.MicrovmHooks != nil {
		vh := &svcapitypes.MicrovmHooks{}
		if in.MicrovmHooks.Resume != "" {
			vh.Resume = aws.String(string(in.MicrovmHooks.Resume))
		}
		vh.ResumeTimeoutInSeconds = widenInt32(in.MicrovmHooks.ResumeTimeoutInSeconds)
		if in.MicrovmHooks.Run != "" {
			vh.Run = aws.String(string(in.MicrovmHooks.Run))
		}
		vh.RunTimeoutInSeconds = widenInt32(in.MicrovmHooks.RunTimeoutInSeconds)
		if in.MicrovmHooks.Suspend != "" {
			vh.Suspend = aws.String(string(in.MicrovmHooks.Suspend))
		}
		vh.SuspendTimeoutInSeconds = widenInt32(in.MicrovmHooks.SuspendTimeoutInSeconds)
		if in.MicrovmHooks.Terminate != "" {
			vh.Terminate = aws.String(string(in.MicrovmHooks.Terminate))
		}
		vh.TerminateTimeoutInSeconds = widenInt32(in.MicrovmHooks.TerminateTimeoutInSeconds)
		out.MicrovmHooks = vh
	}
	if in.MicrovmImageHooks != nil {
		ih := &svcapitypes.MicrovmImageHooks{}
		if in.MicrovmImageHooks.Ready != "" {
			ih.Ready = aws.String(string(in.MicrovmImageHooks.Ready))
		}
		ih.ReadyTimeoutInSeconds = widenInt32(in.MicrovmImageHooks.ReadyTimeoutInSeconds)
		if in.MicrovmImageHooks.Validate != "" {
			ih.Validate = aws.String(string(in.MicrovmImageHooks.Validate))
		}
		ih.ValidateTimeoutInSeconds = widenInt32(in.MicrovmImageHooks.ValidateTimeoutInSeconds)
		out.MicrovmImageHooks = ih
	}
	out.Port = widenInt32(in.Port)
	return out
}

// widenInt32 converts an optional int32 (SDK) to an optional int64 (Spec).
func widenInt32(v *int32) *int64 {
	if v == nil {
		return nil
	}
	w := int64(*v)
	return &w
}
