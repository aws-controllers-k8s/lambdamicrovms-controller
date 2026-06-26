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

"""Pytest configuration and fixtures for Lambda MicroVMs E2E tests.

Parameters resolved in priority order:
  1. CLI args (--build-role-arn, --region, etc.)
  2. Environment variables (BUILD_ROLE_ARN, AWS_REGION, etc.)
  3. bootstrap.pkl (created by service_bootstrap.py)
"""

import os
import time

import pytest
from kubernetes.client.exceptions import ApiException

from acktest import k8s
from acktest.k8s import resource as k8s_resource
from acktest.resources import random_suffix_name

from e2e import CRD_GROUP, CRD_VERSION, load_lambdamicrovms_resource
from e2e.bootstrap_resources import get_bootstrap_resources
from e2e.replacement_values import REPLACEMENT_VALUES

IMAGE_CREATE_TIMEOUT_SECONDS = 360
IMAGE_DELETE_TIMEOUT_SECONDS = 120
POLL_INTERVAL_SECONDS = 15


def pytest_addoption(parser):
    parser.addoption("--runslow", action="store_true", default=False, help="run slow tests")
    parser.addoption("--build-role-arn", action="store", default=None)
    parser.addoption("--code-artifact-uri", action="store", default=None)
    parser.addoption("--execution-role-arn", action="store", default=None)
    parser.addoption("--base-image-arn", action="store", default=None)
    parser.addoption("--region", action="store", default=None)


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


def _resolve(cli_value, env_var, bootstrap_attr=None):
    """Resolve a parameter: CLI > env var > bootstrap.pkl."""
    if cli_value:
        return cli_value
    val = os.environ.get(env_var, "")
    if val:
        return val
    if bootstrap_attr:
        try:
            bootstrap = get_bootstrap_resources()
            return getattr(bootstrap, bootstrap_attr, "")
        except Exception:
            return ""
    return ""


@pytest.fixture(scope="session")
def region(request):
    return _resolve(request.config.getoption("--region"), "AWS_REGION") or "eu-west-1"


@pytest.fixture(scope="session")
def base_image_arn(request, region):
    val = _resolve(request.config.getoption("--base-image-arn"), "BASE_IMAGE_ARN", "BaseImageARN")
    return val or f"arn:aws:lambda:{region}:aws:microvm-image:al2023-1"


@pytest.fixture(scope="session")
def build_role_arn(request):
    val = _resolve(request.config.getoption("--build-role-arn"), "BUILD_ROLE_ARN", "BuildRoleARN")
    assert val, "Provide --build-role-arn, set BUILD_ROLE_ARN, or run service_bootstrap.py"
    return val


@pytest.fixture(scope="session")
def code_artifact_uri(request):
    val = _resolve(request.config.getoption("--code-artifact-uri"), "CODE_ARTIFACT_URI", "CodeArtifactURI")
    assert val, "Provide --code-artifact-uri, set CODE_ARTIFACT_URI, or run service_bootstrap.py"
    return val


@pytest.fixture(scope="session")
def execution_role_arn(request):
    return _resolve(request.config.getoption("--execution-role-arn"), "EXECUTION_ROLE_ARN", "ExecutionRoleARN")


@pytest.fixture(scope="session")
def microvm_image_arn(base_image_arn, build_role_arn, code_artifact_uri, region):
    """Session-scoped fixture: creates a MicrovmImage, waits for CREATED,
    yields its ARN for Microvm tests, deletes at session teardown.
    """
    resource_name = random_suffix_name("ack-fixture-img", 24)

    replacements = REPLACEMENT_VALUES.copy()
    replacements["RESOURCE_NAME"] = resource_name
    replacements["BASE_IMAGE_ARN"] = base_image_arn
    replacements["BUILD_ROLE_ARN"] = build_role_arn
    replacements["CODE_ARTIFACT_URI"] = code_artifact_uri

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
