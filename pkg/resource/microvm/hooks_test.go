package microvm

import (
	"testing"
	"time"

	"github.com/aws/aws-sdk-go-v2/aws"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	svcapitypes "github.com/aws-controllers-k8s/lambdamicrovms-controller/apis/v1alpha1"
)

func TestIsDeleting_NilTimestamp(t *testing.T) {
	rm := &resourceManager{}
	r := &resource{ko: &svcapitypes.Microvm{}}
	if rm.isDeleting(r) {
		t.Error("expected isDeleting to return false when DeletionTimestamp is nil")
	}
}

func TestIsDeleting_ZeroTimestamp(t *testing.T) {
	rm := &resourceManager{}
	r := &resource{ko: &svcapitypes.Microvm{
		ObjectMeta: metav1.ObjectMeta{
			DeletionTimestamp: &metav1.Time{},
		},
	}}
	if rm.isDeleting(r) {
		t.Error("expected isDeleting to return false when DeletionTimestamp is zero")
	}
}

func TestIsDeleting_SetTimestamp(t *testing.T) {
	rm := &resourceManager{}
	now := metav1.Now()
	r := &resource{ko: &svcapitypes.Microvm{
		ObjectMeta: metav1.ObjectMeta{
			DeletionTimestamp: &now,
		},
	}}
	if !rm.isDeleting(r) {
		t.Error("expected isDeleting to return true when DeletionTimestamp is set")
	}
}

func TestRequeueWaitWhileTerminating(t *testing.T) {
	if requeueWaitWhileTerminating.Duration() != 5*time.Second {
		t.Errorf("expected 5s requeue duration, got %v", requeueWaitWhileTerminating.Duration())
	}
}

// TestIsTerminated guards the delete-unwedge fix: only a Microvm that has
// reached TERMINATED must short-circuit delete (return nil,nil so the runtime
// removes the finalizer), because AWS never returns NotFound for a retained
// terminated VM. Every other state must return false so the controller does not
// drop the finalizer prematurely: TERMINATING is transient and still progresses
// to TERMINATED, and non-terminal states like SUSPENDED may reflect a customer
// actively suspending/resuming the VM — the controller must not interfere.
func TestIsTerminated(t *testing.T) {
	cases := []struct {
		name  string
		state *string
		want  bool
	}{
		{"nil state", nil, false},
		{"running", aws.String(string(svcapitypes.MicrovmState_RUNNING)), false},
		{"suspended", aws.String(string(svcapitypes.MicrovmState_SUSPENDED)), false},
		{"suspending", aws.String(string(svcapitypes.MicrovmState_SUSPENDING)), false},
		{"pending", aws.String(string(svcapitypes.MicrovmState_PENDING)), false},
		{"terminating", aws.String(string(svcapitypes.MicrovmState_TERMINATING)), false},
		{"terminated", aws.String(string(svcapitypes.MicrovmState_TERMINATED)), true},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			r := &resource{ko: &svcapitypes.Microvm{}}
			r.ko.Status.State = tc.state
			if got := isTerminated(r); got != tc.want {
				t.Errorf("isTerminated(state=%v) = %v, want %v", tc.state, got, tc.want)
			}
		})
	}
}
