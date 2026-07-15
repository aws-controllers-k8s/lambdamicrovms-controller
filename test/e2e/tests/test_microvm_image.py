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
CREATE_TIMEOUT_SECONDS = 360
UPDATE_TIMEOUT_SECONDS = 360
POLL_INTERVAL_SECONDS = 15
DELETE_WAIT_PERIODS = 8
DELETE_PERIOD_LENGTH = 15
TAG_POLL_MAX_RETRIES = 12
TAG_POLL_INTERVAL_SECONDS = 5

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

        # baseImageVersion is populated from the create response (and kept fresh
        # on read):
        #   - status.resolvedBaseImageVersion = the full resolved value (e.g. "0.0")
        #   - spec.baseImageVersion = the sanitized value the API accepts (e.g. "0")
        resolved = cr["status"].get("resolvedBaseImageVersion")
        assert resolved is not None, "resolvedBaseImageVersion not set in status"
        spec_biv = cr.get("spec", {}).get("baseImageVersion")
        assert spec_biv is not None, \
            "spec.baseImageVersion not populated by refresh/late-init"
        # The sanitized spec value is the leading integer of the resolved value.
        assert "." not in spec_biv, \
            f"spec.baseImageVersion should be sanitized (no dot), got {spec_biv!r}"
        assert resolved.split(".")[0] == spec_biv, \
            f"spec.baseImageVersion {spec_biv!r} should be the leading component of resolved {resolved!r}"

        # AWS API dual-verification
        aws_resp = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        assert aws_resp["state"] in ("CREATED", "UPDATED"), f"AWS state: {aws_resp['state']}"

    def test_update(self, simple_microvm_image, lambdamicrovms_client):
        """Patching a build-config field (description) must actually reconcile:
        the image rebuilds into a new version carrying the new value.

        Note: description lives on the image VERSION, not the image, and
        GetMicrovmImage does not return it. An earlier version of this test
        only asserted status.state was CREATED/UPDATED and dual-verified via
        get_microvm_image — both of which stay true even when the update is
        silently dropped, so it passed without ever confirming the change
        reached AWS. This version verifies the full round-trip instead.
        """
        (ref, _) = simple_microvm_image

        # Ensure the image finished building first (order-independent), and
        # capture the active version so we can prove a new one is cut.
        cr = _wait_for_state(ref, ["CREATED", "UPDATED", "CREATE_FAILED"], CREATE_TIMEOUT_SECONDS)
        assert cr["status"]["state"] in ("CREATED", "UPDATED"), \
            f"image not built, state={cr['status']['state']}"
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        version_before = cr["status"].get("latestActiveImageVersion")

        # Unique per run so it can never accidentally match a pre-existing value.
        description = random_suffix_name("ack-e2e-desc", 40)
        k8s.patch_custom_resource(ref, {"spec": {"description": description}})

        # A real update transitions to UPDATED (not merely "still CREATED").
        cr = _wait_for_state(ref, ["UPDATED", "UPDATE_FAILED"], UPDATE_TIMEOUT_SECONDS)
        assert cr["status"]["state"] == "UPDATED", \
            f"Expected UPDATED after description change, got {cr['status']['state']}"

        # A new image version must have been cut (proves an actual rebuild).
        version_after = cr["status"].get("latestActiveImageVersion")
        assert version_after != version_before, \
            f"expected a new active version, still {version_after}"

        # The description must be present on the new version in AWS. This is the
        # assertion the old test lacked: it reads the VERSION, not the image.
        ver = lambdamicrovms_client.get_microvm_image_version(
            imageIdentifier=arn, imageVersion=version_after,
        )
        assert ver.get("description") == description, \
            f"description not applied to version {version_after}: {ver.get('description')!r}"

    def test_update_tags_no_rebuild(self, simple_microvm_image, lambdamicrovms_client):
        """Changing tags must sync via TagResource/UntagResource and must NOT
        trigger an image rebuild (UpdateMicrovmImage cuts a new image version).
        """
        (ref, _) = simple_microvm_image

        # The image build is asynchronous; wait for it to finish before tagging
        # so this test is self-sufficient regardless of execution order.
        cr = _wait_for_state(ref, ["CREATED", "UPDATED", "CREATE_FAILED"], CREATE_TIMEOUT_SECONDS)
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        before = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        version_before = before.get("latestActiveImageVersion")
        assert before["state"] in ("CREATED", "UPDATED"), f"image not built, state={before['state']}"

        updates = {"spec": {"tags": {"e2e-tag-test": "v1"}}}
        k8s.patch_custom_resource(ref, updates)

        assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=5), \
            "resource did not reach ACK.ResourceSynced=True after tag update"

        # Tag must land on the AWS side via TagResource (eventually consistent)
        aws_tags = {}
        for _ in range(TAG_POLL_MAX_RETRIES):
            aws_tags = lambdamicrovms_client.list_tags(Resource=arn).get("Tags", {})
            if aws_tags.get("e2e-tag-test") == "v1":
                break
            time.sleep(TAG_POLL_INTERVAL_SECONDS)
        assert aws_tags.get("e2e-tag-test") == "v1", f"tag not synced to AWS, got {aws_tags}"

        # ACK default tags prove EnsureTags works through the TagResource path
        assert "services.k8s.aws/controller-version" in aws_tags
        assert "services.k8s.aws/namespace" in aws_tags

        # No rebuild: same active version, never went back to UPDATING
        after = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        assert after.get("latestActiveImageVersion") == version_before, \
            f"tag change rebuilt the image: version {version_before} -> {after.get('latestActiveImageVersion')}"
        assert after["state"] in ("CREATED", "UPDATED"), f"unexpected state {after['state']}"
