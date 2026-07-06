package microvm_image

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"
	svcsdktypes "github.com/aws/aws-sdk-go-v2/service/lambdamicrovms/types"

	svcapitypes "github.com/aws-controllers-k8s/lambdamicrovms-controller/apis/v1alpha1"
)

// TestUpdateRequestOmitsBaseImageVersionWhenUnset guards the fix for the
// baseImageVersion round-trip bug: CreateMicrovmImage/UpdateMicrovmImage
// responses echo baseImageVersion="0.0", a value the update request validator
// rejects ("Invalid baseMicroVMImageVersion: 0.0"). The controller must not
// persist that echoed value into spec, so that when the user has not set it the
// update request omits it entirely ("use latest", the documented default).
//
// This asserts the request-side contract: an unset Spec.BaseImageVersion must
// not appear in the UpdateMicrovmImage input.
func TestUpdateRequestOmitsBaseImageVersionWhenUnset(t *testing.T) {
	rm := &resourceManager{}
	r := &resource{ko: &svcapitypes.MicrovmImage{}}
	r.ko.Spec.Name = aws.String("img")
	r.ko.Spec.BaseImageARN = aws.String("arn:aws:lambda:eu-west-1:aws:microvm-image:al2023-1")
	r.ko.Spec.BuildRoleARN = aws.String("arn:aws:iam::123456789012:role/build")
	r.ko.Spec.CodeArtifact = &svcapitypes.CodeArtifact{URI: aws.String("s3://bucket/app.zip")}
	// Spec.BaseImageVersion deliberately left nil.

	input, err := rm.newUpdateRequestPayload(context.Background(), r, nil)
	if err != nil {
		t.Fatalf("newUpdateRequestPayload returned error: %v", err)
	}
	if input.BaseImageVersion != nil {
		t.Errorf("expected BaseImageVersion to be omitted from update request, got %q", *input.BaseImageVersion)
	}
}

// TestUpdateRequestPassesBaseImageVersionWhenUserSet confirms that a value the
// user explicitly puts in spec is still forwarded to the API (pinning a base
// image version remains possible).
func TestUpdateRequestPassesBaseImageVersionWhenUserSet(t *testing.T) {
	rm := &resourceManager{}
	r := &resource{ko: &svcapitypes.MicrovmImage{}}
	r.ko.Spec.Name = aws.String("img")
	r.ko.Spec.BaseImageARN = aws.String("arn:aws:lambda:eu-west-1:aws:microvm-image:al2023-1")
	r.ko.Spec.BuildRoleARN = aws.String("arn:aws:iam::123456789012:role/build")
	r.ko.Spec.CodeArtifact = &svcapitypes.CodeArtifact{URI: aws.String("s3://bucket/app.zip")}
	r.ko.Spec.BaseImageVersion = aws.String("1")

	input, err := rm.newUpdateRequestPayload(context.Background(), r, nil)
	if err != nil {
		t.Fatalf("newUpdateRequestPayload returned error: %v", err)
	}
	if input.BaseImageVersion == nil || *input.BaseImageVersion != "1" {
		t.Errorf("expected BaseImageVersion %q to be forwarded, got %v", "1", input.BaseImageVersion)
	}
}

// The tests below cover the pure mapping helpers used by
// refreshSpecFromActiveVersion. The nil->nil contract is the load-bearing
// invariant: refreshSpecFromActiveVersion overwrites Spec from the version
// response every reconcile, so a helper that turns a nil (unset) AWS field
// into a non-nil Spec value would manufacture perpetual drift and trigger
// endless rebuilds. Each test therefore asserts nil-in/nil-out plus correct
// shape mapping for populated input.

func TestWidenInt32(t *testing.T) {
	if got := widenInt32(nil); got != nil {
		t.Errorf("widenInt32(nil) = %v, want nil", got)
	}
	got := widenInt32(aws.Int32(5))
	if got == nil || *got != int64(5) {
		t.Errorf("widenInt32(&5) = %v, want &int64(5)", got)
	}
}

func TestCapabilitiesFromSDK(t *testing.T) {
	if got := capabilitiesFromSDK(nil); got != nil {
		t.Errorf("nil input = %v, want nil", got)
	}
	got := capabilitiesFromSDK([]svcsdktypes.Capability{svcsdktypes.CapabilityAll})
	if len(got) != 1 || got[0] == nil || *got[0] != "ALL" {
		t.Errorf("got %v, want [\"ALL\"]", got)
	}
}

func TestCodeArtifactFromSDK(t *testing.T) {
	if got := codeArtifactFromSDK(nil); got != nil {
		t.Errorf("nil input = %v, want nil", got)
	}
	got := codeArtifactFromSDK(&svcsdktypes.CodeArtifactMemberUri{Value: "s3://bucket/app.zip"})
	if got == nil || got.URI == nil || *got.URI != "s3://bucket/app.zip" {
		t.Errorf("got %+v, want URI s3://bucket/app.zip", got)
	}
}

func TestCPUConfigurationsFromSDK(t *testing.T) {
	if got := cpuConfigurationsFromSDK(nil); got != nil {
		t.Errorf("nil input = %v, want nil", got)
	}
	got := cpuConfigurationsFromSDK([]svcsdktypes.CpuConfiguration{
		{Architecture: svcsdktypes.ArchitectureArm64},
	})
	if len(got) != 1 || got[0].Architecture == nil || *got[0].Architecture != "ARM_64" {
		t.Errorf("got %v, want [{ARM_64}]", got)
	}
}

func TestResourcesFromSDK(t *testing.T) {
	if got := resourcesFromSDK(nil); got != nil {
		t.Errorf("nil input = %v, want nil", got)
	}
	got := resourcesFromSDK([]svcsdktypes.Resources{{MinimumMemoryInMiB: aws.Int32(2048)}})
	if len(got) != 1 || got[0].MinimumMemoryInMiB == nil || *got[0].MinimumMemoryInMiB != int64(2048) {
		t.Errorf("got %v, want [{2048}]", got)
	}
}

func TestLoggingFromSDK(t *testing.T) {
	if got := loggingFromSDK(nil); got != nil {
		t.Errorf("nil input = %v, want nil", got)
	}

	// CloudWatch member
	cw := loggingFromSDK(&svcsdktypes.LoggingMemberCloudWatch{
		Value: svcsdktypes.CloudWatchLogging{
			LogGroup:  aws.String("lg"),
			LogStream: aws.String("ls"),
		},
	})
	if cw == nil || cw.CloudWatch == nil {
		t.Fatalf("CloudWatch mapping = %+v, want CloudWatch set", cw)
	}
	if cw.CloudWatch.LogGroup == nil || *cw.CloudWatch.LogGroup != "lg" ||
		cw.CloudWatch.LogStream == nil || *cw.CloudWatch.LogStream != "ls" {
		t.Errorf("CloudWatch fields = %+v", cw.CloudWatch)
	}
	if cw.Disabled != nil {
		t.Errorf("CloudWatch member should not set Disabled, got %v", cw.Disabled)
	}

	// Disabled member
	dis := loggingFromSDK(&svcsdktypes.LoggingMemberDisabled{})
	if dis == nil || dis.Disabled == nil {
		t.Errorf("Disabled mapping = %+v, want non-nil Disabled map", dis)
	}
	if dis != nil && dis.CloudWatch != nil {
		t.Errorf("Disabled member should not set CloudWatch, got %v", dis.CloudWatch)
	}
}

func TestHooksFromSDK(t *testing.T) {
	if got := hooksFromSDK(nil); got != nil {
		t.Errorf("nil input = %v, want nil", got)
	}

	in := &svcsdktypes.Hooks{
		Port: aws.Int32(8080),
		MicrovmHooks: &svcsdktypes.MicrovmHooks{
			Resume:                 svcsdktypes.HookStateEnabled,
			ResumeTimeoutInSeconds: aws.Int32(30),
		},
		MicrovmImageHooks: &svcsdktypes.MicrovmImageHooks{
			Ready:                 svcsdktypes.HookStateEnabled,
			ReadyTimeoutInSeconds: aws.Int32(60),
		},
	}
	got := hooksFromSDK(in)
	if got == nil {
		t.Fatal("hooksFromSDK returned nil for populated input")
	}
	if got.Port == nil || *got.Port != int64(8080) {
		t.Errorf("Port = %v, want &int64(8080)", got.Port)
	}
	if got.MicrovmHooks == nil || got.MicrovmHooks.Resume == nil || *got.MicrovmHooks.Resume != "ENABLED" {
		t.Errorf("MicrovmHooks.Resume = %+v, want ENABLED", got.MicrovmHooks)
	}
	if got.MicrovmHooks.ResumeTimeoutInSeconds == nil || *got.MicrovmHooks.ResumeTimeoutInSeconds != int64(30) {
		t.Errorf("MicrovmHooks.ResumeTimeoutInSeconds = %v, want &int64(30)", got.MicrovmHooks.ResumeTimeoutInSeconds)
	}
	if got.MicrovmImageHooks == nil || got.MicrovmImageHooks.Ready == nil || *got.MicrovmImageHooks.Ready != "ENABLED" {
		t.Errorf("MicrovmImageHooks.Ready = %+v, want ENABLED", got.MicrovmImageHooks)
	}
	if got.MicrovmImageHooks.ReadyTimeoutInSeconds == nil || *got.MicrovmImageHooks.ReadyTimeoutInSeconds != int64(60) {
		t.Errorf("MicrovmImageHooks.ReadyTimeoutInSeconds = %v, want &int64(60)", got.MicrovmImageHooks.ReadyTimeoutInSeconds)
	}
}
