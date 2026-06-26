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
"""Default replacement values for E2E test resource templates.

These are populated from environment variables or overridden by fixtures.
All $VARIABLE placeholders in resources/*.yaml must have an entry here.
"""

import os

AWS_REGION = os.environ.get("AWS_REGION", "eu-west-1")

REPLACEMENT_VALUES = {
    "AWS_REGION": AWS_REGION,
    "RESOURCE_NAME": "",
    "BASE_IMAGE_ARN": os.environ.get("BASE_IMAGE_ARN", f"arn:aws:lambda:{AWS_REGION}:aws:microvm-image:al2023-1"),
    "BUILD_ROLE_ARN": os.environ.get("BUILD_ROLE_ARN", ""),
    "CODE_ARTIFACT_URI": os.environ.get("CODE_ARTIFACT_URI", ""),
    "IMAGE_IDENTIFIER": os.environ.get("IMAGE_IDENTIFIER", ""),
    "EXECUTION_ROLE_ARN": os.environ.get("EXECUTION_ROLE_ARN", ""),
}
