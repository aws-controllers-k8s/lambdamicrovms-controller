	// Detect unexpected termination (idle policy timeout or max duration exceeded).
	// If the controller didn't initiate deletion, mark the resource as terminal so the
	// user knows the VM is gone and won't be restarted.
	if ko.Status.State != nil && *ko.Status.State == string(svcapitypes.MicrovmState_TERMINATED) {
		if !rm.isDeleting(r) {
			msg := "MicroVM terminated unexpectedly (idle policy or max duration exceeded)"
			if ko.Status.StateReason != nil && *ko.Status.StateReason != "" {
				msg = *ko.Status.StateReason
			}
			terminalCondition := &ackv1alpha1.Condition{
				Type:    ackv1alpha1.ConditionTypeTerminal,
				Status:  corev1.ConditionTrue,
				Message: &msg,
			}
			ko.Status.Conditions = append(ko.Status.Conditions, terminalCondition)
		}
	}
