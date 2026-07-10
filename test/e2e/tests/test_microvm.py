# Copyright Amazon.com Inc. or its affiliates. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"). You may
# not use this file except in compliance with the License. A copy of the
# License is located at
#
#	 http://aws.amazon.com/apache2.0/
#
# or in the "license" file accompanying this file. This file is distributed
# on an "AS IS" BASIS, WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either
# express or implied. See the License for the specific language governing
# permissions and limitations under the License.

"""Integration tests for the Microvm API.

Uses the session-scoped `microvm_image_arn` fixture from conftest.py.
Microvm has no Update operation (all Spec fields are immutable).
"""

import pytest
import time

from acktest.k8s import resource as k8s
from acktest.resources import random_suffix_name
from acktest.aws.identity import get_region

from e2e import CRD_GROUP, CRD_VERSION, load_lambdamicrovms_resource, service_marker
from e2e.bootstrap_resources import get_bootstrap_resources

RESOURCE_PLURAL = "microvms"
CREATE_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 10
DELETE_WAIT_PERIODS = 12
DELETE_PERIOD_LENGTH = 10

def _wait_for_state(ref, target_states, timeout):
    """Poll until status.state reaches one of the target values."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cr = k8s.get_resource(ref)
        state = cr.get("status", {}).get("state", "")
        if state in target_states:
            return cr
        time.sleep(POLL_INTERVAL_SECONDS)
    return k8s.get_resource(ref)


@pytest.fixture(scope="module")
def simple_microvm(microvm_image_arn):
    resource_name = random_suffix_name("ack-vm", 24)

    resources = get_bootstrap_resources()
    region = get_region()

    execution_role_arn = resources.ExecutionRole.arn if resources.ExecutionRole else ""

    replacements = {
        "RESOURCE_NAME": resource_name,
        "IMAGE_IDENTIFIER": microvm_image_arn,
        "EXECUTION_ROLE_ARN": execution_role_arn,
        "AWS_REGION": region,
    }

    resource_data = load_lambdamicrovms_resource(
        "microvm", additional_replacements=replacements
    )

    ref = k8s.CustomResourceReference(
        CRD_GROUP, CRD_VERSION, RESOURCE_PLURAL,
        resource_name, namespace="default",
    )

    k8s.create_custom_resource(ref, resource_data)
    cr = k8s.wait_resource_consumed_by_controller(ref)

    assert cr is not None
    assert k8s.get_resource_exists(ref)

    yield (ref, cr)

    try:
        _, deleted = k8s.delete_custom_resource(ref, wait_periods=DELETE_WAIT_PERIODS, period_length=DELETE_PERIOD_LENGTH)
        assert deleted
    except:
        pass


@service_marker
@pytest.mark.canary
class TestMicrovm:
    def test_create(self, simple_microvm, lambdamicrovms_client):
        (ref, _) = simple_microvm

        cr = _wait_for_state(ref, ["RUNNING", "TERMINATED"], CREATE_TIMEOUT_SECONDS)
        state = cr["status"]["state"]
        assert state == "RUNNING", f"Expected RUNNING, got {state}"

        microvm_id = cr["status"].get("microvmID")
        assert microvm_id is not None and microvm_id != "", "microvmID not set"
        assert cr["status"].get("endpoint") is not None, "endpoint not set"

        # AWS API dual-verification
        aws_resp = lambdamicrovms_client.get_microvm(microvmIdentifier=microvm_id)
        assert aws_resp["state"] in ("RUNNING", "SUSPENDING", "SUSPENDED"), f"AWS state: {aws_resp['state']}"

    def test_delete_removes_finalizer(self, microvm_image_arn, lambdamicrovms_client):
        """Deleting a Microvm must fully remove the CR (finalizer dropped), even
        though AWS retains terminated VMs.

        Regression guard: GetMicrovm never returns NotFound for a terminated VM
        (AWS keeps them queryable indefinitely), and the deletable guard rejects
        the TERMINATED state ("resource is in TERMINATED state, cannot be
        deleted"). Without the sdk_delete_pre_build_request short-circuit, the
        runtime would requeue forever waiting for a NotFound that never comes and
        the finalizer would never be removed. This exercises both a
        controller-initiated terminate and the terminal-state cleanup path.
        """
        resource_name = random_suffix_name("ack-vm-del", 24)
        resources = get_bootstrap_resources()
        execution_role_arn = resources.ExecutionRole.arn if resources.ExecutionRole else ""

        replacements = {
            "RESOURCE_NAME": resource_name,
            "IMAGE_IDENTIFIER": microvm_image_arn,
            "EXECUTION_ROLE_ARN": execution_role_arn,
            "AWS_REGION": get_region(),
        }
        resource_data = load_lambdamicrovms_resource(
            "microvm", additional_replacements=replacements
        )
        ref = k8s.CustomResourceReference(
            CRD_GROUP, CRD_VERSION, RESOURCE_PLURAL,
            resource_name, namespace="default",
        )
        k8s.create_custom_resource(ref, resource_data)
        k8s.wait_resource_consumed_by_controller(ref)

        cr = _wait_for_state(ref, ["RUNNING", "TERMINATED"], CREATE_TIMEOUT_SECONDS)
        assert cr["status"]["state"] in ("RUNNING", "TERMINATED"), \
            f"vm not ready, state={cr['status']['state']}"

        # Delete and require the CR to actually disappear. delete_custom_resource
        # blocks until the object is gone from the API server, which only happens
        # once the finalizer is removed — i.e. this fails (times out) if the
        # delete wedges on the TERMINATED state.
        _, deleted = k8s.delete_custom_resource(
            ref, wait_periods=DELETE_WAIT_PERIODS, period_length=DELETE_PERIOD_LENGTH
        )
        assert deleted, "Microvm CR was not removed — finalizer likely stuck on TERMINATED state"
        assert not k8s.get_resource_exists(ref), "Microvm CR still exists after delete"
