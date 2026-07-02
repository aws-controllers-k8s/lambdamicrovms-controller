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

"""Cleans up the resources created by service_bootstrap.py."""

import logging

import boto3
import botocore.exceptions

from acktest.aws.identity import get_region

from e2e import bootstrap_directory
from e2e.bootstrap_resources import BootstrapResources


def _delete_adoption_images(resources):
    """Delete the adoption target images created directly via the AWS API.

    The adoption tests use deletion-policy: retain, so the images are still
    present after the CRs are deleted.
    """
    arns = [
        getattr(resources, "AdoptPolicyImageARN", ""),
        getattr(resources, "AdoptTagsImageARN", ""),
    ]
    client = boto3.client("lambda-microvms", region_name=get_region())
    for arn in arns:
        if not arn:
            continue
        try:
            client.delete_microvm_image(imageIdentifier=arn)
            logging.info("Deleted adoption target MicrovmImage %s", arn)
        except botocore.exceptions.ClientError as e:
            if e.response["Error"]["Code"] == "ResourceNotFoundException":
                logging.info("Adoption target MicrovmImage %s already deleted", arn)
            else:
                logging.exception("Failed to delete adoption target MicrovmImage %s", arn)


def service_cleanup():
    logging.getLogger().setLevel(logging.INFO)

    try:
        resources = BootstrapResources.deserialize(bootstrap_directory)
    except Exception:
        logging.error("Could not load bootstrap resources — nothing to clean up")
        return

    _delete_adoption_images(resources)
    resources.cleanup()
    logging.info("Cleanup complete.")


if __name__ == "__main__":
    service_cleanup()
