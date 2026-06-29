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
"""

import logging
import os
import tempfile
import zipfile

import boto3

from acktest.bootstrapping import Resources, BootstrapFailureException
from acktest.bootstrapping.iam import Role
from acktest.bootstrapping.s3 import Bucket
from acktest.aws.identity import get_region

from e2e import bootstrap_directory
from e2e.bootstrap_resources import BootstrapResources

REGION = get_region()
BASE_IMAGE_ARN = f"arn:aws:lambda:{REGION}:aws:microvm-image:al2023-1"

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

    return resources


if __name__ == "__main__":
    config = service_bootstrap()
    config.serialize(bootstrap_directory)
    logging.info("Bootstrap complete. Resources serialized to %s", bootstrap_directory)
