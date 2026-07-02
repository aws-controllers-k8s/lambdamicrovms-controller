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

"""Bootstraps the resources required to run the Lambda MicroVMs E2E tests.

Prerequisites created:
  - S3 bucket for code artifacts (via acktest Bucket)
  - IAM build role trusted by lambda.amazonaws.com (via acktest Role)
  - IAM execution role trusted by lambda.amazonaws.com (via acktest Role)
  - Test code artifact (app.js + Dockerfile) uploaded to S3
  - Two MicrovmImages created directly via the AWS API (adoption test targets,
    one per adoption test so they run independently under pytest-xdist)
"""

import logging
import os
import tempfile
import time
import zipfile

import boto3

from acktest.bootstrapping import Resources, BootstrapFailureException
from acktest.bootstrapping.iam import Role
from acktest.bootstrapping.s3 import Bucket
from acktest.aws.identity import get_region
from acktest.resources import random_suffix_name

from e2e import bootstrap_directory
from e2e.bootstrap_resources import BootstrapResources

REGION = get_region()
BASE_IMAGE_ARN = f"arn:aws:lambda:{REGION}:aws:microvm-image:al2023-1"

ADOPTION_IMAGE_CREATE_TIMEOUT_SECONDS = 600
ADOPTION_IMAGE_POLL_INTERVAL_SECONDS = 15

APP_JS = """\
const http = require('http');
const server = http.createServer((req, res) => {
  res.writeHead(200, { 'Content-Type': 'application/json' });
  res.end(JSON.stringify({ status: 'ok', path: req.url }));
});
server.listen(8080, () => { console.log('Listening on port 8080'); });
"""

DOCKERFILE = """\
FROM node:24-alpine
WORKDIR /app
COPY app.js .
EXPOSE 8080
CMD ["node", "app.js"]
"""


def _upload_code_artifact(bucket_name):
    """Create and upload test code artifact (app.js + Dockerfile)."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("app.js", APP_JS)
            zf.writestr("Dockerfile", DOCKERFILE)
        tmp_path = tmp.name

    key = "e2e-test-app.zip"
    s3_client = boto3.client("s3", region_name=REGION)
    s3_client.upload_file(tmp_path, bucket_name, key)
    os.unlink(tmp_path)

    return f"s3://{bucket_name}/{key}"


def _start_adoption_image(client, name_prefix, build_role_arn, code_artifact_uri):
    """Start an out-of-band MicrovmImage build (does not wait). Returns
    (name, arn); the build is asynchronous.
    """
    name = random_suffix_name(name_prefix, 32)
    logging.info("Creating adoption target MicrovmImage %s", name)
    resp = client.create_microvm_image(
        name=name,
        baseImageArn=BASE_IMAGE_ARN,
        buildRoleArn=build_role_arn,
        codeArtifact={"uri": code_artifact_uri},
    )
    return name, resp["imageArn"]


def _wait_adoption_image(client, name, arn):
    """Poll an adoption target image until it leaves CREATING, failing the
    bootstrap if it does not reach CREATED.
    """
    deadline = time.time() + ADOPTION_IMAGE_CREATE_TIMEOUT_SECONDS
    state = "CREATING"
    while time.time() < deadline:
        state = client.get_microvm_image(imageIdentifier=arn)["state"]
        if state != "CREATING":
            break
        time.sleep(ADOPTION_IMAGE_POLL_INTERVAL_SECONDS)

    if state != "CREATED":
        logging.error("Adoption target image %s ended in state %s", name, state)
        raise BootstrapFailureException()

    logging.info("Adoption target MicrovmImage %s is CREATED (%s)", name, arn)


def _create_adoption_images(build_role_arn, code_artifact_uri):
    """Create the per-test adoption target images. Both builds are started
    first, then awaited, so bootstrap pays one build window (~3 min) rather
    than one per image.
    """
    client = boto3.client("lambda-microvms", region_name=REGION)
    policy_name, policy_arn = _start_adoption_image(
        client, "ack-adopt-policy", build_role_arn, code_artifact_uri)
    tags_name, tags_arn = _start_adoption_image(
        client, "ack-adopt-tags", build_role_arn, code_artifact_uri)

    _wait_adoption_image(client, policy_name, policy_arn)
    _wait_adoption_image(client, tags_name, tags_arn)

    return policy_name, policy_arn, tags_name, tags_arn


def service_bootstrap() -> Resources:
    logging.getLogger().setLevel(logging.INFO)

    resources = BootstrapResources(
        BuildRole=Role(
            name_prefix="ack-microvms-e2e-build",
            principal_service="lambda.amazonaws.com",
            description="ACK MicroVMs E2E build role",
            managed_policies=[
                "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess",
            ],
        ),
        ExecutionRole=Role(
            name_prefix="ack-microvms-e2e-exec",
            principal_service="lambda.amazonaws.com",
            description="ACK MicroVMs E2E execution role",
        ),
        CodeArtifactBucket=Bucket(
            name_prefix="ack-microvms-e2e",
        ),
        BaseImageARN=BASE_IMAGE_ARN,
    )

    try:
        resources.bootstrap()
    except BootstrapFailureException:
        exit(254)

    logging.info("Uploading code artifact to s3://%s/e2e-test-app.zip", resources.CodeArtifactBucket.name)
    resources.CodeArtifactURI = _upload_code_artifact(resources.CodeArtifactBucket.name)

    try:
        (
            resources.AdoptPolicyImageName,
            resources.AdoptPolicyImageARN,
            resources.AdoptTagsImageName,
            resources.AdoptTagsImageARN,
        ) = _create_adoption_images(
            resources.BuildRole.arn, resources.CodeArtifactURI,
        )
    except BootstrapFailureException:
        resources.cleanup()
        exit(254)

    return resources


if __name__ == "__main__":
    config = service_bootstrap()
    config.serialize(bootstrap_directory)
    logging.info("Bootstrap complete. Resources serialized to %s", bootstrap_directory)
