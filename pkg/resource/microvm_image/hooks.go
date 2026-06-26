package microvm_image

import (
	"fmt"
	"time"

	ackrequeue "github.com/aws-controllers-k8s/runtime/pkg/requeue"
)

var requeueWaitWhileDeleting = ackrequeue.NeededAfter(
	fmt.Errorf("microvm image is deleting"),
	10*time.Second,
)
