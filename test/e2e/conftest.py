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

import time

import boto3
import pytest
from kubernetes.client.exceptions import ApiException

from acktest.k8s import resource as k8s_resource
from acktest.resources import random_suffix_name
from acktest.aws.identity import get_region

from e2e import CRD_GROUP, CRD_VERSION, load_lambdamicrovms_resource
from e2e.bootstrap_resources import get_bootstrap_resources

IMAGE_CREATE_TIMEOUT_SECONDS = 360
IMAGE_DELETE_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 15


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False, help="run slow tests")


def pytest_configure(config):
    config.addinivalue_line("markers", "service(arg): mark test associated with a given service")
    config.addinivalue_line("markers", "slow: mark test as slow to run")
    config.addinivalue_line("markers", "canary: mark test as canary (runs in CI)")


def pytest_collection_modifyitems(config, items):
    if config.getoption("--runslow"):
        return
    skip_slow = pytest.mark.skip(reason="need --runslow option to run")
    for item in items:
        if "slow" in item.keywords:
            item.add_marker(skip_slow)


@pytest.fixture(scope="session")
def region():
    return get_region()


@pytest.fixture(scope="session")
def bootstrap_resources():
    return get_bootstrap_resources()


@pytest.fixture(scope="session")
def lambdamicrovms_client(region):
    return boto3.client("lambda-microvms", region_name=region)


@pytest.fixture(scope="session")
def microvm_image_arn(bootstrap_resources, region):
    """Session-scoped fixture: creates a MicrovmImage, waits for CREATED,
    yields its ARN for Microvm tests, deletes at session teardown.
    """
    resources = bootstrap_resources
    resource_name = random_suffix_name("ack-fixture-img", 24)

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
    ref = k8s_resource.CustomResourceReference(
        CRD_GROUP, CRD_VERSION, "microvmimages",
        resource_name, namespace="default",
    )

    def _safe_get(r):
        try:
            return k8s_resource.get_resource(r)
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    k8s_resource.create_custom_resource(ref, resource_data)
    cr = k8s_resource.wait_resource_consumed_by_controller(ref)
    assert cr is not None, "MicrovmImage fixture was not consumed by controller"

    image_arn = None
    deadline = time.time() + IMAGE_CREATE_TIMEOUT_SECONDS
    while time.time() < deadline:
        cr = _safe_get(ref)
        if cr is None:
            break
        state = cr.get("status", {}).get("state", "")
        if state == "CREATED":
            image_arn = cr["status"]["ackResourceMetadata"]["arn"]
            break
        if state == "CREATE_FAILED":
            pytest.fail(f"MicrovmImage fixture CREATE_FAILED: {cr['status'].get('conditions')}")
        time.sleep(POLL_INTERVAL_SECONDS)

    assert image_arn is not None, "MicrovmImage fixture did not reach CREATED state"

    yield image_arn

    # Teardown
    if _safe_get(ref) is not None:
        k8s_resource.delete_custom_resource(ref, wait_periods=0)
    deadline = time.time() + IMAGE_DELETE_TIMEOUT_SECONDS
    while time.time() < deadline:
        if _safe_get(ref) is None:
            break
        time.sleep(POLL_INTERVAL_SECONDS)
