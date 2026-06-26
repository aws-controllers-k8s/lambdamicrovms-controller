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

"""Cleans up the resources created by service_bootstrap.py.

Deletes: IAM roles, S3 objects, S3 bucket.
"""

import logging
import os

import boto3

from e2e import bootstrap_directory
from e2e.bootstrap_resources import BootstrapResources

REGION = os.environ.get("AWS_REGION", "eu-west-1")

BUILD_ROLE_NAME = "ack-microvms-e2e-build-role"
EXECUTION_ROLE_NAME = "ack-microvms-e2e-execution-role"


def _delete_role(iam_client, role_name):
    """Delete IAM role and its inline policies."""
    try:
        policies = iam_client.list_role_policies(RoleName=role_name)
        for policy_name in policies.get("PolicyNames", []):
            iam_client.delete_role_policy(RoleName=role_name, PolicyName=policy_name)
        iam_client.delete_role(RoleName=role_name)
        logging.info("Deleted role: %s", role_name)
    except iam_client.exceptions.NoSuchEntityException:
        logging.info("Role already gone: %s", role_name)


def _delete_bucket(s3_client, bucket_name):
    """Delete all objects in bucket, then delete the bucket."""
    try:
        objects = s3_client.list_objects_v2(Bucket=bucket_name)
        for obj in objects.get("Contents", []):
            s3_client.delete_object(Bucket=bucket_name, Key=obj["Key"])
        s3_client.delete_bucket(Bucket=bucket_name)
        logging.info("Deleted bucket: %s", bucket_name)
    except s3_client.exceptions.NoSuchBucket:
        logging.info("Bucket already gone: %s", bucket_name)


def service_cleanup():
    logging.getLogger().setLevel(logging.INFO)

    iam_client = boto3.client("iam", region_name=REGION)
    s3_client = boto3.client("s3", region_name=REGION)

    # Try to load bootstrap resources for the bucket name
    try:
        resources = BootstrapResources.deserialize(bootstrap_directory)
        bucket_name = resources.S3BucketName
    except Exception:
        # Fall back to convention
        sts = boto3.client("sts", region_name=REGION)
        account_id = sts.get_caller_identity()["Account"]
        bucket_name = f"ack-microvms-e2e-{account_id}"

    logging.info("Cleaning up bootstrap resources...")
    _delete_role(iam_client, BUILD_ROLE_NAME)
    _delete_role(iam_client, EXECUTION_ROLE_NAME)
    _delete_bucket(s3_client, bucket_name)
    logging.info("Cleanup complete.")


if __name__ == "__main__":
    service_cleanup()
