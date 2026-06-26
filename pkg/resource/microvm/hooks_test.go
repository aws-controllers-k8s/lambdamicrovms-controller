package microvm

import (
	"testing"
	"time"

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
