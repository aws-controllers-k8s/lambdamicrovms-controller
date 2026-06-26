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

"""E2E tests for MicrovmImage resource.

Tests run in order within the class:
  1. test_create — Create image, wait for CREATED, verify synced
  2. test_update — Update description, verify synced
  3. test_delete — Delete image, wait for removal
"""

import time
import pytest
from kubernetes.client.exceptions import ApiException

from acktest.resources import random_suffix_name
from acktest.k8s import resource as k8s
from acktest.k8s import condition

import boto3

from e2e import CRD_GROUP, CRD_VERSION, load_lambdamicrovms_resource, service_marker
from e2e.replacement_values import REPLACEMENT_VALUES

RESOURCE_PLURAL = "microvmimages"
CREATE_TIMEOUT_SECONDS = 360
UPDATE_TIMEOUT_SECONDS = 360
DELETE_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 15


def _safe_get(ref):
    """Get resource, return None if not found (instead of raising)."""
    try:
        return k8s.get_resource(ref)
    except ApiException as e:
        if e.status == 404:
            return None
        raise


def _wait_for_state(ref, target_states, timeout):
    """Poll until status.state reaches one of the target values."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        cr = _safe_get(ref)
        if cr is None:
            return None
        state = cr.get("status", {}).get("state", "")
        if state in target_states:
            return cr
        time.sleep(POLL_INTERVAL_SECONDS)
    return _safe_get(ref)


@service_marker
@pytest.mark.canary
class TestMicrovmImage:
    """Ordered lifecycle tests for MicrovmImage. Tests share state via class attributes."""

    resource_name = None
    ref = None
    aws_client = None
    image_arn = None

    @pytest.fixture(autouse=True, scope="class")
    @classmethod
    def setup_resource(cls, base_image_arn, build_role_arn, code_artifact_uri, region):
        """Create the resource name and reference once for the whole class."""
        cls.aws_client = boto3.client('lambda-microvms', region_name=region)
        cls.resource_name = random_suffix_name("ack-img", 24)
        cls.ref = k8s.CustomResourceReference(
            CRD_GROUP, CRD_VERSION, RESOURCE_PLURAL,
            cls.resource_name, namespace="default",
        )

        replacements = REPLACEMENT_VALUES.copy()
        replacements["RESOURCE_NAME"] = cls.resource_name
        replacements["BASE_IMAGE_ARN"] = base_image_arn
        replacements["BUILD_ROLE_ARN"] = build_role_arn
        replacements["CODE_ARTIFACT_URI"] = code_artifact_uri

        cls.resource_data = load_lambdamicrovms_resource(
            "microvm_image", additional_replacements=replacements
        )

    def test_create(self):
        """Create MicrovmImage and wait for CREATED state."""
        ref = self.ref

        k8s.create_custom_resource(ref, self.resource_data)
        cr = k8s.wait_resource_consumed_by_controller(ref)
        assert cr is not None, "CR was not consumed by controller"

        cr = _wait_for_state(ref, ["CREATED", "CREATE_FAILED"], CREATE_TIMEOUT_SECONDS)
        assert cr is not None, "Timed out waiting for MicrovmImage"
        state = cr["status"]["state"]
        assert state == "CREATED", f"Expected CREATED, got {state}: {cr['status'].get('conditions')}"

        assert k8s.wait_on_condition(
            ref, condition.CONDITION_TYPE_RESOURCE_SYNCED, "True", wait_periods=5
        ), "ACK.ResourceSynced did not become True"

        arn = cr["status"].get("ackResourceMetadata", {}).get("arn")
        assert arn is not None, "ARN not set in ackResourceMetadata"
        assert cr["status"].get("imageVersion") is not None, "imageVersion not set"
        TestMicrovmImage.image_arn = arn

        # AWS API dual-verification
        aws_resp = self.aws_client.get_microvm_image(imageIdentifier=arn)
        assert aws_resp["state"] in ("CREATED", "UPDATED"), f"AWS state: {aws_resp['state']}"
        assert aws_resp["name"] == self.resource_name

    def test_update(self):
        """Update description and verify synced."""
        ref = self.ref

        updates = {"spec": {"description": "updated by ack e2e test"}}
        k8s.patch_custom_resource(ref, updates)

        cr = _wait_for_state(ref, ["CREATED", "UPDATED", "UPDATE_FAILED"], UPDATE_TIMEOUT_SECONDS)
        assert cr is not None, "Timed out waiting after update"
        state = cr["status"]["state"]
        assert state in ("CREATED", "UPDATED"), f"Expected CREATED/UPDATED, got {state}"

        assert k8s.wait_on_condition(
            ref, condition.CONDITION_TYPE_RESOURCE_SYNCED, "True", wait_periods=5
        ), "ACK.ResourceSynced did not become True after update"

        # AWS API dual-verification
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        aws_resp = self.aws_client.get_microvm_image(imageIdentifier=arn)
        assert aws_resp["state"] in ("CREATED", "UPDATED"), f"AWS state after update: {aws_resp['state']}"

    def test_delete(self):
        """Delete MicrovmImage and wait for removal."""
        ref = self.ref

        if _safe_get(ref) is None:
            pytest.skip("Resource already gone")

        k8s.delete_custom_resource(ref, wait_periods=0)

        deadline = time.time() + DELETE_TIMEOUT_SECONDS
        while time.time() < deadline:
            if _safe_get(ref) is None:
                break
            time.sleep(POLL_INTERVAL_SECONDS)

        assert _safe_get(ref) is None, "MicrovmImage CR not removed after delete"

        # AWS API verification — resource should be DELETED or gone
        try:
            aws_resp = self.aws_client.get_microvm_image(imageIdentifier=self.image_arn)
            assert aws_resp["state"] in ("DELETING", "DELETED"), f"AWS state after delete: {aws_resp['state']}"
        except self.aws_client.exceptions.ResourceNotFoundException:
            pass
