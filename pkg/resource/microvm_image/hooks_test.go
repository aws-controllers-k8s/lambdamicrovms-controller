package microvm_image

import (
	"context"
	"testing"

	"github.com/aws/aws-sdk-go-v2/aws"

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
