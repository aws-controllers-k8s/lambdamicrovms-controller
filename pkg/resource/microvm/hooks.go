package microvm

import (
	"fmt"
	"time"

	ackrequeue "github.com/aws-controllers-k8s/runtime/pkg/requeue"
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
