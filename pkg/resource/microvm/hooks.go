package microvm

import (
	"fmt"
	"time"

	ackrequeue "github.com/aws-controllers-k8s/runtime/pkg/requeue"

	svcapitypes "github.com/aws-controllers-k8s/lambdamicrovms-controller/apis/v1alpha1"
)

var requeueWaitWhileTerminating = ackrequeue.NeededAfter(
	fmt.Errorf("microvm is terminating"),
	5*time.Second,
)

func (rm *resourceManager) isDeleting(r *resource) bool {
	if r.ko.DeletionTimestamp != nil && !r.ko.DeletionTimestamp.IsZero() {
		return true
	}
	return false
}

// isTerminated reports whether the Microvm has reached the TERMINATED terminal
// state — the only state in which the VM is truly gone.
//
// It exists to unwedge deletion. The generated delete flow assumes
// TerminateMicrovm eventually drives GetMicrovm to NotFound, at which point the
// runtime removes the finalizer. But AWS RETAINS terminated VMs: GetMicrovm
// keeps returning TERMINATED indefinitely (verified live hours after
// termination), so that NotFound never arrives. Combined with the deletable
// guard rejecting TERMINATED ("resource is in TERMINATED state, cannot be
// deleted"), any Microvm that reaches TERMINATED — whether by user delete or by
// self-termination (idle policy / maximumDurationInSeconds) — leaves its CR
// stuck with a finalizer forever.
//
// The sdk_delete_pre_build_request hook uses this to short-circuit: once the VM
// is TERMINATED there is nothing left to terminate, so delete is treated as
// complete and sdkDelete returns (nil, nil), letting the runtime remove the
// finalizer.
//
// Only TERMINATED counts, deliberately NOT TERMINATING: TERMINATING is a
// transient state that still progresses to TERMINATED, so we wait for full
// termination (the deletable guard requeues in the meantime) rather than drop
// the finalizer while the VM is still winding down. Non-terminal states such as
// SUSPENDED must never short-circuit here — a customer may be actively
// suspending/resuming the VM, and the controller must not interfere with that.
func isTerminated(r *resource) bool {
	if r.ko.Status.State == nil {
		return false
	}
	return *r.ko.Status.State == string(svcapitypes.MicrovmState_TERMINATED)
}
