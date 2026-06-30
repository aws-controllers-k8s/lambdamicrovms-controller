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

"""Integration tests for the MicrovmImage API."""

import pytest
import time

from acktest.k8s import resource as k8s
from acktest.resources import random_suffix_name
from acktest.aws.identity import get_region

from e2e import CRD_GROUP, CRD_VERSION, load_lambdamicrovms_resource, service_marker
from e2e.bootstrap_resources import get_bootstrap_resources

RESOURCE_PLURAL = "microvmimages"
CREATE_TIMEOUT_SECONDS = 600
UPDATE_TIMEOUT_SECONDS = 360
POLL_INTERVAL_SECONDS = 15
DELETE_WAIT_PERIODS = 8
DELETE_PERIOD_LENGTH = 15

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
def simple_microvm_image():
    resource_name = random_suffix_name("ack-img", 24)

    resources = get_bootstrap_resources()
    region = get_region()

    replacements = {
        "RESOURCE_NAME": resource_name,
        "BASE_IMAGE_ARN": resources.BaseImageARN,
        "BUILD_ROLE_ARN": resources.BuildRole.arn,
        "CODE_ARTIFACT_URI": resources.CodeArtifactURI,
        "AWS_REGION": region,
    }

    resource_data = load_lambdamicrovms_resource(
        "microvm_image", additional_replacements=replacements
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
class TestMicrovmImage:
    def test_create(self, simple_microvm_image, lambdamicrovms_client):
        (ref, _) = simple_microvm_image

        cr = _wait_for_state(ref, ["CREATED", "CREATE_FAILED"], CREATE_TIMEOUT_SECONDS)
        state = cr["status"]["state"]
        assert state == "CREATED", f"Expected CREATED, got {state}"

        arn = cr["status"].get("ackResourceMetadata", {}).get("arn")
        assert arn is not None, "ARN not set in ackResourceMetadata"
        assert cr["status"].get("imageVersion") is not None, "imageVersion not set"

        # AWS API dual-verification
        aws_resp = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        assert aws_resp["state"] in ("CREATED", "UPDATED"), f"AWS state: {aws_resp['state']}"

    def test_update(self, simple_microvm_image, lambdamicrovms_client):
        (ref, _) = simple_microvm_image

        updates = {"spec": {"description": "updated by ack e2e test"}}
        k8s.patch_custom_resource(ref, updates)

        cr = _wait_for_state(ref, ["CREATED", "UPDATED", "UPDATE_FAILED"], UPDATE_TIMEOUT_SECONDS)
        state = cr["status"]["state"]
        assert state in ("CREATED", "UPDATED"), f"Expected CREATED/UPDATED, got {state}"

        # AWS API dual-verification
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        aws_resp = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        assert aws_resp["state"] in ("CREATED", "UPDATED"), f"AWS state after update: {aws_resp['state']}"
