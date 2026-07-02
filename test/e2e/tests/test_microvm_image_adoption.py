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

"""Integration tests for adopting a pre-existing MicrovmImage."""

import pytest
import time
from datetime import datetime, timezone

from acktest.k8s import resource as k8s
from acktest.resources import random_suffix_name

from e2e import CRD_GROUP, CRD_VERSION, load_lambdamicrovms_resource, service_marker
from e2e.bootstrap_resources import get_bootstrap_resources

RESOURCE_PLURAL = "microvmimages"
DELETE_WAIT_PERIODS = 8
DELETE_PERIOD_LENGTH = 15
TAG_POLL_MAX_RETRIES = 12
TAG_POLL_INTERVAL_SECONDS = 5

ADOPTED_ANNOTATION = "services.k8s.aws/adopted"
ACK_FINALIZER = "finalizers.lambdamicrovms.services.k8s.aws/MicrovmImage"


def _adopt_image(image_arn):
    """Create a spec-less MicrovmImage CR that adopts the given pre-existing
    AWS image, and yield (ref, cr). Teardown deletes only the CR — the AWS
    image is owned by bootstrap (deletion-policy: retain) and removed in
    service_cleanup.py.
    """
    assert image_arn, "Bootstrap did not create the adoption target image"
    resource_name = random_suffix_name("ack-adopt", 24)

    replacements = {
        "RESOURCE_NAME": resource_name,
        "ADOPTION_POLICY": "adopt",
        "ADOPTION_FIELDS": f'{{\\"arn\\": \\"{image_arn}\\"}}',
    }

    resource_data = load_lambdamicrovms_resource(
        "microvm_image_adopt", additional_replacements=replacements
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


@pytest.fixture
def adopt_policy_image():
    """Dedicated adoption target for the read-only adopt-policy test."""
    yield from _adopt_image(get_bootstrap_resources().AdoptPolicyImageARN)


@pytest.fixture
def adopt_tags_image():
    """Dedicated adoption target for the tag-mutating test, so it never races
    the adopt-policy test on a shared image under pytest-xdist."""
    yield from _adopt_image(get_bootstrap_resources().AdoptTagsImageARN)


@service_marker
@pytest.mark.canary
class TestMicrovmImageAdoption:
    def test_adopt_policy(self, adopt_policy_image, lambdamicrovms_client):
        (ref, _) = adopt_policy_image
        resources = get_bootstrap_resources()

        assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=5)
        cr = k8s.get_resource(ref)

        # Controller marked the resource as adopted and managed
        annotations = cr["metadata"].get("annotations", {})
        assert annotations.get(ADOPTED_ANNOTATION) == "true"
        assert ACK_FINALIZER in cr["metadata"].get("finalizers", [])

        # The CR was created without a spec; the controller populated it from
        # the pre-existing AWS image (GetMicrovmImage + the version-level
        # GetMicrovmImageVersion enrichment)
        assert cr["spec"]["name"] == resources.AdoptPolicyImageName
        assert cr["spec"]["baseImageARN"] == resources.BaseImageARN
        assert cr["spec"]["buildRoleARN"] == resources.BuildRole.arn
        assert cr["spec"]["codeArtifact"]["uri"] == resources.CodeArtifactURI

        # Status binds to the pre-existing image, not a newly created one
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        assert arn == resources.AdoptPolicyImageARN
        # UPDATED is possible when the image was modified on a previous run
        assert cr["status"]["state"] in ("CREATED", "UPDATED")
        assert cr["status"].get("latestActiveImageVersion") is not None

        # AWS API dual-verification: same creation timestamp proves the
        # controller adopted rather than built a second image
        aws_resp = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        assert aws_resp["state"] in ("CREATED", "UPDATED")
        aws_created_at = aws_resp["createdAt"].astimezone(timezone.utc)
        cr_created_at = datetime.strptime(cr["status"]["createdAt"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        assert cr_created_at == aws_created_at.replace(microsecond=0)

    def test_adopted_image_tag_update(self, adopt_tags_image, lambdamicrovms_client):
        """Tagging an adopted image must sync via TagResource/UntagResource
        without triggering an image rebuild (a new version). This is the
        real-world reconcile path for an adopted image: ReadOne only refreshes
        Name and Tags, so tags are the field that actually drives updates.
        """
        (ref, _) = adopt_tags_image

        # Ensure the image is settled (synced.when requires State CREATED/UPDATED)
        # before snapshotting the version, so this test is order-independent.
        assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=5), \
            "adopted resource not synced before tag update"
        cr = k8s.get_resource(ref)
        arn = cr["status"]["ackResourceMetadata"]["arn"]
        before = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        version_before = before.get("latestActiveImageVersion")

        updates = {"spec": {"tags": {"adopt-tag-test": "v1"}}}
        k8s.patch_custom_resource(ref, updates)

        assert k8s.wait_on_condition(ref, "ACK.ResourceSynced", "True", wait_periods=5), \
            "adopted resource did not reach ACK.ResourceSynced=True after tag update"

        # Tag must land on the AWS side via TagResource (eventually consistent)
        aws_tags = {}
        for _ in range(TAG_POLL_MAX_RETRIES):
            aws_tags = lambdamicrovms_client.list_tags(Resource=arn).get("Tags", {})
            if aws_tags.get("adopt-tag-test") == "v1":
                break
            time.sleep(TAG_POLL_INTERVAL_SECONDS)
        assert aws_tags.get("adopt-tag-test") == "v1", f"tag not synced to AWS, got {aws_tags}"

        # ACK default tags prove EnsureTags runs through the TagResource path
        assert "services.k8s.aws/controller-version" in aws_tags
        assert "services.k8s.aws/namespace" in aws_tags

        # No rebuild: same active version, image never went back to UPDATING
        after = lambdamicrovms_client.get_microvm_image(imageIdentifier=arn)
        assert after.get("latestActiveImageVersion") == version_before, \
            f"tag change rebuilt the adopted image: version {version_before} -> {after.get('latestActiveImageVersion')}"
        assert after["state"] in ("CREATED", "UPDATED"), f"unexpected state {after['state']}"
