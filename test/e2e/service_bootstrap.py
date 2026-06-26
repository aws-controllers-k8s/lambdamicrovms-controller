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
  - S3 bucket for code artifacts
  - IAM build role (trusted by lambda.amazonaws.com)
  - IAM execution role (trusted by lambda.amazonaws.com)
  - Test code artifact (app.js + Dockerfile) uploaded to S3
"""

import json
import logging
import os
import tempfile
import zipfile

import boto3

from acktest.bootstrapping import Resources, BootstrapFailureException
from e2e import bootstrap_directory
from e2e.bootstrap_resources import BootstrapResources

REGION = os.environ.get("AWS_REGION", "eu-west-1")
ACCOUNT_ID = os.environ.get("AWS_ACCOUNT_ID", "")

BUILD_ROLE_NAME = "ack-microvms-e2e-build-role"
EXECUTION_ROLE_NAME = "ack-microvms-e2e-execution-role"
S3_BUCKET_PREFIX = "ack-microvms-e2e-v2"
BASE_IMAGE_ARN = f"arn:aws:lambda:{REGION}:aws:microvm-image:al2023-1"

TRUST_POLICY = json.dumps({
    "Version": "2012-10-17",
    "Statement": [{
        "Effect": "Allow",
        "Principal": {"Service": "lambda.amazonaws.com"},
        "Action": ["sts:AssumeRole", "sts:TagSession"]
    }]
})

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


def _create_role(iam_client, role_name, bucket_name, account_id):
    """Create IAM role with trust policy and permissions for MicroVM builds."""
    try:
        resp = iam_client.create_role(
            RoleName=role_name,
            AssumeRolePolicyDocument=TRUST_POLICY,
            Description="ACK MicroVMs E2E test role",
        )
        role_arn = resp["Role"]["Arn"]
    except iam_client.exceptions.EntityAlreadyExistsException:
        role_arn = f"arn:aws:iam::{account_id}:role/{role_name}"

    permissions_policy = json.dumps({
        "Version": "2012-10-17",
        "Statement": [
            {
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": f"arn:aws:s3:::{bucket_name}/*"
            },
            {
                "Effect": "Allow",
                "Action": [
                    "logs:CreateLogGroup",
                    "logs:CreateLogStream",
                    "logs:PutLogEvents"
                ],
                "Resource": "arn:aws:logs:*:*:*"
            }
        ]
    })

    iam_client.put_role_policy(
        RoleName=role_name,
        PolicyName="ack-microvms-e2e-policy",
        PolicyDocument=permissions_policy,
    )

    return role_arn


def _create_bucket(s3_client, bucket_name):
    """Create S3 bucket for test artifacts."""
    try:
        if REGION == "us-east-1":
            s3_client.create_bucket(Bucket=bucket_name)
        else:
            s3_client.create_bucket(
                Bucket=bucket_name,
                CreateBucketConfiguration={"LocationConstraint": REGION},
            )
    except (
        s3_client.exceptions.BucketAlreadyOwnedByYou,
        s3_client.exceptions.BucketAlreadyExists,
    ):
        pass

    return bucket_name


def _upload_code_artifact(s3_client, bucket_name):
    """Create and upload test code artifact (app.js + Dockerfile)."""
    with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("app.js", APP_JS)
            zf.writestr("Dockerfile", DOCKERFILE)
        tmp_path = tmp.name

    key = "e2e-test-app.zip"
    s3_client.upload_file(tmp_path, bucket_name, key)
    os.unlink(tmp_path)

    return f"s3://{bucket_name}/{key}"


def service_bootstrap() -> Resources:
    logging.getLogger().setLevel(logging.INFO)

    if not ACCOUNT_ID:
        sts = boto3.client("sts", region_name=REGION)
        account_id = sts.get_caller_identity()["Account"]
    else:
        account_id = ACCOUNT_ID

    bucket_name = f"{S3_BUCKET_PREFIX}-{account_id}"

    iam_client = boto3.client("iam", region_name=REGION)
    s3_client = boto3.client("s3", region_name=REGION)

    logging.info("Creating S3 bucket: %s", bucket_name)
    _create_bucket(s3_client, bucket_name)

    logging.info("Uploading code artifact to s3://%s/e2e-test-app.zip", bucket_name)
    code_artifact_uri = _upload_code_artifact(s3_client, bucket_name)

    logging.info("Creating build role: %s", BUILD_ROLE_NAME)
    build_role_arn = _create_role(iam_client, BUILD_ROLE_NAME, bucket_name, account_id)

    logging.info("Creating execution role: %s", EXECUTION_ROLE_NAME)
    execution_role_arn = _create_role(iam_client, EXECUTION_ROLE_NAME, bucket_name, account_id)

    resources = BootstrapResources(
        BuildRoleARN=build_role_arn,
        ExecutionRoleARN=execution_role_arn,
        CodeArtifactURI=code_artifact_uri,
        BaseImageARN=BASE_IMAGE_ARN,
        S3BucketName=bucket_name,
    )

    try:
        resources.bootstrap()
    except BootstrapFailureException:
        exit(254)

    return resources


if __name__ == "__main__":
    config = service_bootstrap()
    config.serialize(bootstrap_directory)
    logging.info("Bootstrap complete. Resources serialized to %s", bootstrap_directory)
